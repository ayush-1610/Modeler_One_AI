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
# (Gemini, Groq) with the in-house model on 2026-10-06: client documents then never leave the company's server.
PROVIDERS: dict[str, ProviderDefaults] = {
    "litellm": ProviderDefaults("http://127.0.0.1:4000/v1", "LITELLM_KEY", "qwen-coder"),
}
BASE_ENV = {"litellm": "LITELLM_BASE"}
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


class ChatModel(Protocol):
    provider: str
    model: str

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResult: ...


class LLMConfigError(RuntimeError):
    """A provider is selected but not usable (unknown name or missing key)."""


class OpenAICompatChat:
    """Chat Completions on an OpenAI-compatible endpoint (the LiteLLM proxy in front of Ollama)."""

    def __init__(self, *, provider: str, base_url: str, api_key: str, model: str, timeout_s: float = DEFAULT_TIMEOUT_S,
                 max_retries: int = 4, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._url = self.base_url + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

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
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last_error = ""
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = client.post(self._url, headers=self._headers, json=body)
                except httpx.TimeoutException:
                    last_error = f"no answer within {self._timeout:g} s (raise MODELER_LLM_TIMEOUT_S for long documents)"
                except httpx.ConnectError as exc:
                    last_error = f"cannot reach {self.base_url} ({exc}); is the LiteLLM proxy running and LITELLM_BASE right?"
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code == 200:
                        try:
                            return _parse(response.json(), self.model, inline_tools=bool(tools))
                        except ValueError as exc:
                            raise LLMUnavailableError(f"{self.provider} answered with something that is not JSON: {exc}") from exc
                    raise_refusal(self, response)
                    last_error = f"HTTP {response.status_code}: {_error_message(response)}"
                if attempt < self._max_retries:
                    self._sleep(min(2.0 ** (attempt + 1), 30.0))
        raise LLMUnavailableError(f"{self.provider} unavailable after {self._max_retries + 1} attempts: {last_error}")


def raise_refusal(chat: OpenAICompatChat, response: httpx.Response) -> None:
    """A non-retryable answer becomes an error that says what to fix (the key, the model name); retryable ones return."""
    status, message = response.status_code, _error_message(response)
    if status in _RETRY_STATUS:
        return
    if status in (401, 403):
        raise LLMUnavailableError(f"{chat.provider} rejected the key (HTTP {status}: {message}); check LITELLM_KEY")
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
    defaults = PROVIDERS.get(provider)
    if defaults is None:
        raise LLMConfigError(f"unknown MODELER_LLM_PROVIDER {provider!r}; use one of: {', '.join(PROVIDERS)} or disabled")
    key = (env.get(defaults.key_env) or "").strip()
    if not key:
        raise LLMConfigError(f"MODELER_LLM_PROVIDER={provider} needs {defaults.key_env} in the environment")
    try:
        timeout = float(env.get("MODELER_LLM_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    except ValueError as exc:
        raise LLMConfigError(f"MODELER_LLM_TIMEOUT_S must be a number of seconds, not {env.get('MODELER_LLM_TIMEOUT_S')!r}") from exc
    return OpenAICompatChat(
        provider=provider, base_url=(env.get(BASE_ENV[provider]) or defaults.base_url).strip(), api_key=key,
        model=(env.get("MODELER_LLM_MODEL") or defaults.model).strip(), timeout_s=timeout,
    )


def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
         model: ChatModel | None = None) -> ChatResult:
    """One chat completion on the configured model (raises LLMConfigError when agents are off)."""
    model = model or chat_model_from_env()
    if model is None:
        raise LLMConfigError("agents are off: set MODELER_LLM_PROVIDER=litellm (with LITELLM_BASE and LITELLM_KEY)")
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
    usage = {"input_tokens": 0, "output_tokens": 0}
    for turn in range(1, max_turns + 1):
        try:
            result = model.complete(messages, schemas)
        except LLMUnavailableError as exc:
            log_step({"type": "llm_unavailable", "turn": turn, "error": str(exc)})
            return LoopOutcome("LLM_UNAVAILABLE", "", turn - 1, usage, error=str(exc))
        usage["input_tokens"] += result.usage.get("input_tokens", 0)
        usage["output_tokens"] += result.usage.get("output_tokens", 0)
        log_step({"type": "model_turn", "turn": turn, "model": result.model, "content": result.content,
                  "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in result.tool_calls],
                  "usage": result.usage})
        if not result.tool_calls:
            return LoopOutcome("COMPLETED", result.content, turn, usage)
        messages.append({"role": "assistant", "content": result.content or None, "tool_calls": [
            c.raw or {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(c.arguments)}}
            for c in result.tool_calls]})
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
            log_step({"type": "tool_result", "turn": turn, "tool": call.name, "id": call.id, "result": answer})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": answer})
    return LoopOutcome("INCOMPLETE", "", max_turns, usage, error=f"stopped after {max_turns} turns")
