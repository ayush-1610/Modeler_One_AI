"""Provider-agnostic chat with tool use, for the start-up pipeline's agents (plan §14, decision D-16).

The owner chose Gemini or Groq. Both serve the OpenAI-compatible Chat Completions protocol, so one client covers them:
`OpenAICompatChat` posts messages and tool schemas and returns the model's text and tool calls. `run_tool_loop` runs
the agent loop: the model calls tools, deterministic handlers check and record what it proposes, and the handlers'
answers (including rejections) go back to the model until it stops calling tools or the turn limit is reached.

Keys come only from the host environment (`GEMINI_API_KEY`, `GROQ_API_KEY`), never from the repository. With no
provider configured, `chat_model_from_env` returns None and every agent step falls back to its manual path.
"""

from __future__ import annotations

import json
import os
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


# Defaults only: MODELER_LLM_MODEL / MODELER_LLM_BASE_URL override them per deployment. The Gemini default is the
# provider's "latest flash" alias, which served tool calls on the owner's key on 2026-10-05 (the pro models were over
# its quota); Groq is reachable from the deployment host only (this build's container blocks it).
PROVIDERS: dict[str, ProviderDefaults] = {
    "gemini": ProviderDefaults("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-flash-latest"),
    "groq": ProviderDefaults("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
}

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
    """Chat Completions over HTTPS (Gemini's and Groq's OpenAI-compatible endpoints)."""

    def __init__(self, *, provider: str, base_url: str, api_key: str, model: str, timeout_s: float = 120.0,
                 max_retries: int = 4, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.provider = provider
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatResult:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last_error = ""
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = client.post(self._url, headers=self._headers, json=body)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code == 200:
                        return _parse(response.json(), self.model)
                    last_error = f"HTTP {response.status_code}: {_error_message(response)}"
                    if response.status_code not in _RETRY_STATUS:
                        raise LLMUnavailableError(f"{self.provider} refused the request: {last_error}")
                if attempt < self._max_retries:
                    self._sleep(min(2.0 ** (attempt + 1), 30.0))
        raise LLMUnavailableError(f"{self.provider} unavailable after {self._max_retries + 1} attempts: {last_error}")


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


def _parse(data: dict[str, Any], model: str) -> ChatResult:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    calls = []
    for index, call in enumerate(message.get("tool_calls") or []):
        function = call.get("function") or {}
        raw = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            arguments = {"__unparsed__": raw}
        calls.append(ToolCall(id=str(call.get("id") or f"call_{index}"), name=str(function.get("name", "")),
                              arguments=arguments if isinstance(arguments, dict) else {"__unparsed__": raw},
                              raw_arguments=raw if isinstance(raw, str) else json.dumps(raw), raw=dict(call)))
    usage = data.get("usage") or {}
    return ChatResult(
        content=str(message.get("content") or ""), tool_calls=tuple(calls),
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
    return OpenAICompatChat(
        provider=provider, base_url=env.get("MODELER_LLM_BASE_URL") or defaults.base_url, api_key=key,
        model=env.get("MODELER_LLM_MODEL") or defaults.model,
    )


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
