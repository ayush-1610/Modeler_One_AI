"""Chat with tool use for the start-up pipeline's agents (plan §14, decision D-16).

The owner's model runs in-house: Ollama serves `qwen3-coder:30b` on the server, and a LiteLLM proxy in front of it
exposes the OpenAI-compatible Chat Completions protocol under one alias, `qwen-coder`. `OpenAICompatChat` posts
messages and tool schemas and returns the model's text and tool calls; `run_tool_loop` runs the agent loop: the model
calls tools, deterministic handlers check and record what it proposes, and the handlers' answers (including
rejections) go back to the model until it stops calling tools or the turn limit is reached.

Configuration comes only from the host environment, never from the repository:

    MODELER_LLM_PROVIDER=litellm      unset or "disabled" = agents off, every step on its manual path
    LITELLM_BASE=http://<host>:4000/v1  the proxy (default http://127.0.0.1:4000/v1, the API on the same server)
    LITELLM_KEY=...                   the proxy's bearer key
    MODELER_LLM_MODEL=qwen-coder      the proxy's model alias (default)
    MODELER_LLM_TIMEOUT_S=600         a local 30B model reading a long document can take minutes per turn

or Claude on Amazon Bedrock (`modeler_agents.claude`; the admin console sets the same names from its store):

    MODELER_LLM_PROVIDER=bedrock
    MODELER_LLM_MODEL=anthropic.claude-opus-5-5
    BEDROCK_REGION=...                the AWS region
    BEDROCK_API_KEY=...               a Bedrock API key, or AWS_ACCESS_KEY_ID with AWS_SECRET_ACCESS_KEY (or neither:
                                      the AWS credentials the server already has)
    MODELER_LLM_EFFORT=medium         low, medium, high, xhigh or max (unset: the model's own default)
    MODELER_LLM_FALLBACK=...          the model asked when the first declines or stays overloaded (optional)

or any other OpenAI-compatible service (Cerebras, NVIDIA's API catalog, OpenRouter …), its address, key and model given:

    MODELER_LLM_PROVIDER=openai_compat
    OPENAI_COMPAT_BASE=https://…/v1
    OPENAI_COMPAT_KEY=...
    MODELER_LLM_MODEL=...

or a model of NVIDIA's API catalog (its address is fixed; Nemotron Ultra by default):

    MODELER_LLM_PROVIDER=nvidia
    NVIDIA_API_KEY=...                the key from build.nvidia.com
    MODELER_LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b   (default)

or gpt-oss-120b on GroqCloud (plan 2026-11-21 v2 §9: a third model, chosen per agent in the admin console), through
Groq's OpenAI-compatible endpoint `https://api.groq.com/openai/v1` with the same client as the proxy:

    MODELER_LLM_PROVIDER=groq
    GROQ_API_KEY=...                  the GroqCloud API key
    MODELER_LLM_MODEL=openai/gpt-oss-120b   (default)
    MODELER_LLM_EFFORT=medium         low, medium or high, sent as `reasoning_effort` (unset: the model's own default)

`gemini` stays refused: the hosted Gemini provider was removed on 2026-10-06 and has not come back.

Web search (Ollama's cloud API, its own key) is a tool the agents may call: `modeler_agents.web_search`.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from modeler_agents.run import LLMUnavailableError


@dataclass(frozen=True)
class ProviderDefaults:
    base_url: str
    key_env: str
    model: str


# Defaults only: LITELLM_BASE / MODELER_LLM_MODEL override them per deployment. The owner replaced the hosted providers
# (Gemini, Groq) with the in-house model on 2026-10-06, and brought GroqCloud back as a third model, chosen per agent, on
# 2026-11-21 (plan 2026-11-21 v2 §9); Gemini stays out.
PROVIDERS: dict[str, ProviderDefaults] = {
    "litellm": ProviderDefaults("http://127.0.0.1:4000/v1", "LITELLM_KEY", "qwen-coder"),
    "groq": ProviderDefaults("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    # any other service with an OpenAI-compatible Chat Completions endpoint (Cerebras, NVIDIA's API catalog,
    # OpenRouter, Together …): its address, key and model are the console's
    "openai_compat": ProviderDefaults("", "OPENAI_COMPAT_KEY", ""),
    # NVIDIA's API catalog (build.nvidia.com): free trial credits, OpenAI-compatible; Nemotron Ultra by default
    "nvidia": ProviderDefaults("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", "nvidia/nemotron-3-ultra-550b-a55b"),
}
BASE_ENV = {"litellm": "LITELLM_BASE", "openai_compat": "OPENAI_COMPAT_BASE"}       # GroqCloud's address is fixed
GROQ_EFFORTS = ("low", "medium", "high")      # gpt-oss's `reasoning_effort` on GroqCloud
DEFAULT_TIMEOUT_S = 600.0

_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    # The call exactly as the provider sent it. Echoed back unchanged on the next turn: Gemini attaches a thought
    # signature (`extra_content.google.thought_signature`) that must come back with the call or the turn is refused.
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str
    usage: dict[str, int]
    model: str
    # the assistant turn exactly as the provider returned it (Claude's content blocks, thinking included), sent back
    # unchanged on the next turn; None where the loop's own shape is enough (the Chat Completions proxy)
    native: tuple[Any, ...] | None = None


class ChatModel(Protocol):
    provider: str
    model: str

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResult: ...


class ToolCallRejected(RuntimeError):
    """The provider refused the model's own tool call (GroqCloud checks the arguments against the tool's schema and
    answers HTTP 400): the loop tells the model why, and it calls again."""


class ContextExceeded(LLMUnavailableError):
    """The request is longer than the model takes: a provider's 413 or "maximum context length", or the in-house model
    reporting that it read a cut prompt. `window`: the most it took, in tokens, when the answer says. The tool loop
    leaves its oldest turns out and asks again (`run_tool_loop`); a request that cannot be made short enough fails."""

    def __init__(self, message: str, window: int | None = None):
        super().__init__(message)
        self.window = window


class LLMConfigError(RuntimeError):
    """A provider is selected but not usable (unknown name or missing key)."""


class OpenAICompatChat:
    """Chat Completions on an OpenAI-compatible endpoint (the LiteLLM proxy in front of Ollama, or GroqCloud).
    `reasoning_effort` is sent only when given (gpt-oss on GroqCloud); without it the request is the proxy's as before."""

    def __init__(self, *, provider: str, base_url: str, api_key: str, model: str, timeout_s: float = DEFAULT_TIMEOUT_S,
                 max_retries: int = 4, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, reasoning_effort: str | None = None):
        self.provider = provider
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.base_url = base_url.rstrip("/")
        self._url = self.base_url + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep
        # the context window asked of the in-house model (Ollama's `num_ctx`, which LiteLLM passes into its options)
        # once it has cut a prompt; -1 once a larger window was refused. Kept for this client's later requests.
        self.num_ctx = 0
        self._cut: ContextExceeded | None = None

    def list_models(self) -> list[str]:
        """The model names the endpoint serves (GET /models); [] when it cannot say."""
        try:
            with httpx.Client(timeout=30, transport=self._transport) as client:
                response = client.get(self.base_url + "/models", headers=self._headers)
            return sorted(str(m.get("id")) for m in response.json().get("data", [])) if response.status_code == 200 else []
        except (httpx.HTTPError, ValueError, AttributeError):
            return []

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResult:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0, "stream": False}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if self.num_ctx > 0:
            body["num_ctx"] = self.num_ctx
        last_error = ""
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = client.post(self._url, headers=self._headers, json=body)
                except httpx.TimeoutException:
                    last_error = f"no answer within {self._timeout:g} s (raise MODELER_LLM_TIMEOUT_S for long documents)"
                except httpx.ConnectError as exc:
                    last_error = f"cannot reach {self.base_url} ({exc}); " + (
                        "is the LiteLLM proxy running and LITELLM_BASE right?" if self.provider == "litellm"
                        else "may the server reach it (its network's allowed hosts)?")
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code == 200:
                        try:
                            result = _parse(response.json(), self.model, inline_tools=bool(tools))
                        except ValueError as exc:
                            raise LLMUnavailableError(f"{self.provider} answered with something that is not JSON: {exc}") from exc
                        try:
                            _check_context(self, body, result)
                        except ContextExceeded as cut:
                            if self.provider != "litellm" or self.num_ctx:
                                raise
                            # the in-house model cut the prompt: ask Ollama for a larger window and send it again
                            self.num_ctx, self._cut, body["num_ctx"] = LARGER_CONTEXT, cut, LARGER_CONTEXT
                            continue
                        self._cut = None
                        return result
                    if self._cut is not None and "num_ctx" in body:
                        # the larger window was refused (too little memory for it, say): the server's own window stays,
                        # and the tool loop fits the conversation into it
                        cut, self._cut, self.num_ctx = self._cut, None, -1
                        raise cut
                    raise_refusal(self, response)
                    last_error = f"HTTP {response.status_code}: {_error_message(response)}"
                    wait = _retry_after(response)
                    if wait is not None and attempt < self._max_retries:
                        self._sleep(wait)   # a rate limit says when to come back (GroqCloud's per-minute token budget)
                        continue
                if attempt < self._max_retries:
                    self._sleep(min(2.0 ** (attempt + 1), 30.0))
        raise LLMUnavailableError(f"{self.provider} unavailable after {self._max_retries + 1} attempts: {last_error}")


RETRY_AFTER_MAX_S = 90.0
# a request of this many characters or more is at least this many tokens (JSON and English run 3–4.5 characters a
# token); a model that reports reading under half of that saw a cut prompt
CHARS_PER_TOKEN_MAX = 4.5
CUT_PROMPT_SHARE = 0.5


#: the window asked of the in-house model once it cuts a prompt (LiteLLM passes `num_ctx` into Ollama's options; checked
#: 2026-11-22 against LiteLLM's `ollama_chat/` and `ollama/` routes, and an `openai/` route ignores it)
LARGER_CONTEXT = 32768
#: what the in-house model's context window is raised to, and how (said when even a fitted request does not fit)
RAISE_CONTEXT = ("raise it on the server (Ollama: start it with OLLAMA_CONTEXT_LENGTH=32768, or a model with PARAMETER "
                 "num_ctx 32768) and run again")


def _check_context(chat: OpenAICompatChat, body: dict[str, Any], result: ChatResult) -> None:
    """The in-house model (Ollama behind the proxy) cuts a prompt longer than its context window without saying so, and
    answers from what is left. A reported prompt much shorter than the request is refused as too long for the window
    (`ContextExceeded`, the window being what it read): the tool loop then leaves the oldest turns out itself, keeping
    the instructions and the task, and asks again."""
    seen = result.usage.get("input_tokens", 0)
    least = len(json.dumps(body, ensure_ascii=False)) / CHARS_PER_TOKEN_MAX
    if chat.provider == "litellm" and seen and least > 2000 and seen < CUT_PROMPT_SHARE * least:
        raise ContextExceeded(
            f"the model read {seen} tokens of a request of at least {least:.0f}: its context window is too small and "
            f"the prompt was cut; {RAISE_CONTEXT}", window=int(seen))


_CONTEXT_WORDS = ("context length", "context_length", "context window", "maximum context", "too many tokens",
                  "prompt is too long", "request too large", "reduce the length", "reduce your message size")
_WINDOW_NUMBER = re.compile(r"(?:maximum context length is|context length of|context window of|limit)\D{0,12}(\d{3,7})",
                            re.IGNORECASE)


def _context_refusal(status: int, message: str) -> ContextExceeded | None:
    """A provider's "the request is too long" (HTTP 413, or a 400 naming the context length), with the window it names
    (GroqCloud: "Limit 8000, Requested 9512"; vLLM and NIM: "maximum context length is 8192 tokens")."""
    lowered = message.lower()
    if status != 413 and not (status == 400 and any(w in lowered for w in _CONTEXT_WORDS)):
        return None
    number = _WINDOW_NUMBER.search(message)
    return ContextExceeded(f"the request is longer than the model takes (HTTP {status}: {message})",
                           window=int(number.group(1)) if number else None)


def _retry_after(response: httpx.Response) -> float | None:
    """How long a 429 asks the client to wait (the Retry-After header, in seconds), at most RETRY_AFTER_MAX_S."""
    if response.status_code != 429:
        return None
    if "per day" in _error_message(response).lower():
        # a daily budget is spent: waiting minutes does not help; say so at once
        raise LLMUnavailableError(f"the provider's daily limit is reached: {_error_message(response)}")
    try:
        return min(max(float(response.headers.get("retry-after", "")), 0.5), RETRY_AFTER_MAX_S)
    except ValueError:
        return None


def raise_refusal(chat: OpenAICompatChat, response: httpx.Response) -> None:
    """A non-retryable answer becomes an error that says what to fix (the key, the model name); retryable ones return."""
    status, message = response.status_code, _error_message(response)
    if status in _RETRY_STATUS:
        return
    if status == 400 and any(w in message.lower() for w in ("tool call validation failed", "failed to parse tool call",
                                                             "tool_use_failed")):
        raise ToolCallRejected(message)
    if (too_long := _context_refusal(status, message)) is not None:
        raise too_long
    if status in (401, 403):
        key_env = PROVIDERS[chat.provider].key_env if chat.provider in PROVIDERS else "the provider's key"
        raise LLMUnavailableError(f"{chat.provider} rejected the key (HTTP {status}: {message}); check {key_env}")
    lowered = message.lower()
    if status in (400, 404) and ("model" in lowered and any(w in lowered for w in ("not found", "invalid", "no such", "does not exist"))):
        served = chat.list_models()
        raise LLMUnavailableError(f"{chat.provider} does not serve the model {chat.model!r} (HTTP {status}: {message}); "
                                  f"it serves: {', '.join(served) or 'unknown'} — set MODELER_LLM_MODEL")
    raise LLMUnavailableError(f"{chat.provider} refused the request: HTTP {status}: {message}")


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message", ""))[:300]
    return str(data)[:300]


_INLINE_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def _inline_calls(content: str) -> list[dict[str, Any]]:
    """Tool calls a model wrote into its text (`<tool_call>{"name": …, "arguments": …}</tool_call>`, Qwen's own format)
    when the server did not turn them into `tool_calls`."""
    out = []
    for index, block in enumerate(_INLINE_CALL.findall(content or "")):
        try:
            call = json.loads(block)
        except json.JSONDecodeError:
            call = {"name": "", "arguments": block}
        out.append({"id": f"inline_{index}", "type": "function",
                    "function": {"name": call.get("name", ""), "arguments": call.get("arguments", {})}})
    return out


def _parse(data: dict[str, Any], model: str, *, inline_tools: bool = False) -> ChatResult:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    raw_calls = message.get("tool_calls") or []
    content = str(message.get("content") or "")
    if not raw_calls and inline_tools and "<tool_call>" in content:
        raw_calls = _inline_calls(content)
        content = _INLINE_CALL.sub("", content).strip()
    calls = []
    for index, call in enumerate(raw_calls):
        function = call.get("function") or {}
        raw = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            arguments = {"__unparsed__": raw}
        inline = str(call.get("id", "")).startswith("inline_")
        calls.append(ToolCall(id=str(call.get("id") or f"call_{index}"), name=str(function.get("name", "")),
                              arguments=arguments if isinstance(arguments, dict) else {"__unparsed__": raw},
                              raw_arguments=raw if isinstance(raw, str) else json.dumps(raw),
                              raw={} if inline else dict(call)))
    usage = data.get("usage") or {}
    return ChatResult(
        content=content, tool_calls=tuple(calls),
        finish_reason=str(choice.get("finish_reason") or ""),
        usage={"input_tokens": int(usage.get("prompt_tokens") or 0), "output_tokens": int(usage.get("completion_tokens") or 0)},
        model=str(data.get("model") or model),
    )


def chat_model_from_env(env: Mapping[str, str] | None = None) -> ChatModel | None:
    """The configured provider, or None when agents are off (`MODELER_LLM_PROVIDER` unset or "disabled")."""
    env = os.environ if env is None else env
    provider = (env.get("MODELER_LLM_PROVIDER") or "").strip().lower()
    if provider in ("", "disabled", "none"):
        return None
    if provider == "gemini":
        raise LLMConfigError("MODELER_LLM_PROVIDER=gemini is no longer supported: since 2026-10-06 the agents use the "
                             "in-house model, Claude on Bedrock or gpt-oss-120b on GroqCloud. Set MODELER_LLM_PROVIDER=litellm "
                             "with LITELLM_BASE and LITELLM_KEY in ~/.modeler-secrets.env (template: "
                             "deploy/server/modeler-secrets.env.example), or choose each agent's model in the admin console")
    if provider == "bedrock":
        return _bedrock(env)
    defaults = PROVIDERS.get(provider)
    if defaults is None:
        raise LLMConfigError(f"unknown MODELER_LLM_PROVIDER {provider!r}; use one of: {', '.join(PROVIDERS)}, bedrock or "
                             "disabled")
    key = (env.get(defaults.key_env) or "").strip()
    if not key:
        raise LLMConfigError(f"MODELER_LLM_PROVIDER={provider} needs {defaults.key_env} in the environment")
    try:
        timeout = float(env.get("MODELER_LLM_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    except ValueError as exc:
        raise LLMConfigError(f"MODELER_LLM_TIMEOUT_S must be a number of seconds, not {env.get('MODELER_LLM_TIMEOUT_S')!r}") from exc
    effort = None
    if provider == "groq":           # the proxy's request stays as it was: no effort for it
        effort = (env.get("MODELER_LLM_EFFORT") or "").strip().lower() or None
        if effort and effort not in GROQ_EFFORTS:
            raise LLMConfigError(f"MODELER_LLM_EFFORT for groq must be one of {', '.join(GROQ_EFFORTS)}, not {effort!r}")
    base_env = BASE_ENV.get(provider)
    if provider == "openai_compat" and not ((env.get("OPENAI_COMPAT_BASE") or "").strip() and (env.get("MODELER_LLM_MODEL") or "").strip()):
        raise LLMConfigError("MODELER_LLM_PROVIDER=openai_compat needs OPENAI_COMPAT_BASE (the service's …/v1 address) and "
                             "MODELER_LLM_MODEL")
    return OpenAICompatChat(
        provider=provider, base_url=((env.get(base_env) if base_env else None) or defaults.base_url).strip(), api_key=key,
        model=(env.get("MODELER_LLM_MODEL") or defaults.model).strip(), timeout_s=timeout, reasoning_effort=effort,
    )


def _bedrock(env: Mapping[str, str]) -> ChatModel:
    from modeler_agents.claude import EFFORTS, ClaudeBedrockChat

    def get(name: str) -> str:
        return (env.get(name) or "").strip()

    model, region = get("MODELER_LLM_MODEL"), get("BEDROCK_REGION") or get("AWS_REGION")
    if not model:
        raise LLMConfigError("MODELER_LLM_PROVIDER=bedrock needs MODELER_LLM_MODEL (e.g. anthropic.claude-opus-5-5)")
    if not region:
        raise LLMConfigError("MODELER_LLM_PROVIDER=bedrock needs BEDROCK_REGION, the AWS region")
    effort = get("MODELER_LLM_EFFORT") or None
    if effort and effort not in EFFORTS:
        raise LLMConfigError(f"MODELER_LLM_EFFORT must be one of {', '.join(EFFORTS)}, not {effort!r}")
    try:
        timeout = float(get("MODELER_LLM_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    except ValueError as exc:
        raise LLMConfigError("MODELER_LLM_TIMEOUT_S must be a number of seconds") from exc
    return ClaudeBedrockChat(model=model, region=region, api_key=get("BEDROCK_API_KEY") or None,
                             aws_access_key=get("AWS_ACCESS_KEY_ID") or None, aws_secret_key=get("AWS_SECRET_ACCESS_KEY") or None,
                             effort=effort, fallback=get("MODELER_LLM_FALLBACK") or None, timeout_s=timeout)


def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
         model: ChatModel | None = None) -> ChatResult:
    """One chat completion on the configured model (raises LLMConfigError when agents are off)."""
    model = model or chat_model_from_env()
    if model is None:
        raise LLMConfigError("agents are off: set MODELER_LLM_PROVIDER=litellm (with LITELLM_BASE and LITELLM_KEY), bedrock "
                             "or groq (with GROQ_API_KEY)")
    return model.complete(messages, tools or [])


# --- the agent loop -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    """A tool the model may call. `handler` receives the parsed arguments and returns the text the model sees."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., str]

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


@dataclass
class LoopOutcome:
    status: Literal["COMPLETED", "INCOMPLETE", "LLM_UNAVAILABLE"]
    final_text: str
    turns: int
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    error: str = ""


def run_tool_loop(model: ChatModel, *, system: str, user: str, tools: list[Tool], max_turns: int = 30,
                  log_step: Callable[[dict[str, Any]], None] = lambda step: None) -> LoopOutcome:
    """Let the model work through `tools` until it answers without calling one, or `max_turns` is reached.

    Every model turn and every tool call (arguments and the handler's answer) is passed to `log_step`, the agent run's
    append-only step log. A handler that raises answers the model with the error instead of ending the run."""
    by_name = {t.name: t for t in tools}
    schemas = [t.schema() for t in tools]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    window: int | None = None          # the model's context window, in tokens, once a refusal has said it
    share = FIT_SHARE
    made: dict[str, tuple[list[int], str]] = {}   # each call (name and arguments) -> its turns and its last answer
    repeating = 0                      # turns in a row whose every call was made before with the same answer
    for turn in range(1, max_turns + 1):
        if window is not None:
            messages = _fitted(messages, schemas, window, share)
        try:
            result = model.complete(messages, schemas)
        except ContextExceeded as exc:
            # too long for the model: the oldest turns are left out (what their tool calls recorded is kept) and the
            # model is asked again; each further refusal fits tighter, and a request that cannot shrink fails
            sent = _size(messages, schemas) / CHARS_PER_TOKEN_FIT
            if window is not None:
                share *= 0.75
            window = min(window or exc.window or int(sent * 0.6), exc.window or int(sent * 0.6))
            fitted = _fitted(messages, schemas, window, share)
            log_step({"type": "context_fitted", "turn": turn, "window": window, "error": str(exc),
                      "messages": [len(messages), len(fitted)]})
            if (_size(fitted, schemas) >= _size(messages, schemas)
                    or _size(fitted, schemas) > window * share * CHARS_PER_TOKEN_FIT):
                tail = RAISE_CONTEXT if model.provider == "litellm" else "choose a model with a longer context for this agent"
                return LoopOutcome("LLM_UNAVAILABLE", "", turn - 1, usage, error=(
                    f"the agent's instructions and material do not fit the model's context window ({window} tokens) "
                    f"even with its earlier turns left out; {tail} ({exc})"))
            messages = fitted
            continue
        except ToolCallRejected as exc:
            log_step({"type": "tool_call_rejected", "turn": turn, "error": str(exc)})
            messages.append({"role": "user", "content": f"Your last tool call was refused: {exc}. Call the tool again with "
                                                        "arguments that match its schema exactly."})
            continue
        except LLMUnavailableError as exc:
            log_step({"type": "llm_unavailable", "turn": turn, "error": str(exc)})
            return LoopOutcome("LLM_UNAVAILABLE", "", turn - 1, usage, error=str(exc))
        for name, tokens in result.usage.items():     # the cache's reads and writes too, where the provider reports them
            usage[name] = usage.get(name, 0) + int(tokens or 0)
        log_step({"type": "model_turn", "turn": turn, "model": result.model, "content": result.content,
                  "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in result.tool_calls],
                  "usage": result.usage})
        if not result.tool_calls:
            return LoopOutcome("COMPLETED", result.content, turn, usage)
        turn_message: dict[str, Any] = {"role": "assistant", "content": result.content or None, "tool_calls": [
            c.raw or {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(c.arguments)}}
            for c in result.tool_calls]}
        if result.native is not None:     # the provider's own turn, sent back unchanged (Claude's thinking blocks)
            turn_message["native"] = result.native
        messages.append(turn_message)
        repeated = 0
        for call in result.tool_calls:
            tool = by_name.get(call.name)
            if tool is None:
                answer = f"ERROR: unknown tool {call.name!r}; available: {', '.join(by_name)}"
            elif "__unparsed__" in call.arguments:
                answer = "ERROR: the arguments were not valid JSON; call the tool again with a JSON object"
            else:
                try:
                    answer = tool.handler(**call.arguments)
                except TypeError as exc:
                    answer = f"ERROR: wrong arguments for {call.name}: {exc}"
                except Exception as exc:  # noqa: BLE001 - the model must hear what went wrong, the run must go on
                    answer = f"ERROR: {type(exc).__name__}: {exc}"
            # the same call with the same answer again (a model that has lost its earlier turns searches the same words
            # over and over): the answer comes back, and says so; a call whose answer changed is a call that moved on
            signature = call.name + json.dumps(call.arguments, sort_keys=True, default=str)
            turns_before, last = made.get(signature, ([], None))
            made[signature] = ([*turns_before, turn], str(answer))
            if turns_before and str(answer) == last:
                repeated += 1
                answer = (f"NOTE: you made this same call before (turn {', '.join(map(str, turns_before[-3:]))}) and its "
                          "answer is unchanged. Do not repeat it: use what it says, mark the field missing, or finish.\n"
                          + str(answer))
            log_step({"type": "tool_result", "turn": turn, "tool": call.name, "id": call.id, "result": answer})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": answer})
        repeating = repeating + 1 if repeated == len(result.tool_calls) else 0
        if repeating >= REPEAT_LIMIT:
            # going round in circles (on a small context window, it forgets what it found): stopped, so the caller's
            # shorter steps can run instead of spending the remaining turns
            return LoopOutcome("INCOMPLETE", "", turn, usage, error=(
                f"stopped: it repeated the same calls with the same answers {REPEAT_LIMIT} turns in a row"))
    return LoopOutcome("INCOMPLETE", "", max_turns, usage, error=f"stopped after {max_turns} turns")


REPEAT_LIMIT = 5      # turns in a row of nothing but calls already made, with the same answers, before the loop stops


# fitting a conversation into a known context window: characters a token is taken to be (JSON, hashes and English run
# 2.5–4.5; the low end, so a fitted request is not refused again) and the window's share the request may fill (the rest
# is the answer's and the chat template's)
CHARS_PER_TOKEN_FIT = 3.0
FIT_SHARE = 0.8
LEFT_OUT = ("(Earlier turns of this conversation were shortened or left out to fit the model's context window. Everything "
            "your tool calls recorded is kept; call a tool again for anything you need from them.)")
STUB_CHARS = 240      # an earlier tool answer, shortened to fit: its first characters stay, so the model sees what it did
STUB_TAIL = " … (shortened to fit the model's context window)"


def _size(messages: list[dict[str, Any]], schemas: list[dict[str, Any]]) -> int:
    return len(json.dumps([{k: v for k, v in m.items() if k != "native"} for m in messages], ensure_ascii=False,
                          default=str)) + len(json.dumps(schemas, ensure_ascii=False))


def _fitted(messages: list[dict[str, Any]], schemas: list[dict[str, Any]], window: int, share: float) -> list[dict[str, Any]]:
    """The conversation within `share` of the `window`: the instructions and the task kept, the earlier turns' tool
    answers shortened to their first lines (so the model still sees what it did and does not do it again), then the
    oldest turns (each model turn with its tool answers, never split) left out until it fits, the latest turn always
    kept. Unchanged when it fits; as short as it can be made when it does not."""
    budget = window * share * CHARS_PER_TOKEN_FIT
    if _size(messages, schemas) <= budget:
        return messages
    head, rest = messages[:2], messages[2:]
    turns: list[list[dict[str, Any]]] = []
    for message in rest:
        if message["role"] == "tool" and turns:
            turns[-1].append(message)
        else:
            turns.append([message])
    task = head[1]
    if LEFT_OUT not in str(task.get("content", "")):
        head = [head[0], {**task, "content": f"{task.get('content', '')}\n\n{LEFT_OUT}"}]
    for turn in turns[:-1]:
        for i, m in enumerate(turn):
            text = m.get("content")
            if m["role"] == "tool" and isinstance(text, str) and len(text) > STUB_CHARS + len(STUB_TAIL):
                turn[i] = {**m, "content": text[:STUB_CHARS] + STUB_TAIL}
    while len(turns) > 1 and _size(head + [m for t in turns for m in t], schemas) > budget:
        turns.pop(0)
    return head + [m for t in turns for m in t]
