"""Claude as an agent's model, on Amazon Bedrock (the owner, 2026-11-10; docs/plans/2026-11-10-admin-console.md) or on
Anthropic's own Claude API with a Console key (the owner, 2026-11-24: decision D1 of
docs/plans/2026-11-24-data-story-next-phase.md).

`ClaudeBedrockChat` and `ClaudeAPIChat` are `llm.ChatModel`s: `run_tool_loop` hands one the conversation in the loop's
own shape (a system message, the task, assistant turns with tool calls, tool results) and gets back the text, the tool
calls and the usage. Both call Claude through Anthropic's SDK (`anthropic.AnthropicBedrockMantle` on Bedrock,
`anthropic.Anthropic` on the Claude API), so that they have:

- **prompt caching:** the system prompt and tools are a cache breakpoint (a run's conversations share them), and the
  conversation so far is cached at every turn (`cache_control` on the request), so each turn pays the cache-read price
  for what the previous turn sent;
- **effort** (`output_config.effort`): how much the model thinks, set per agent in the admin console; thinking is always
  on for Claude Opus 5.5, and effort is its control;
- **the model's own turns sent back unchanged:** each assistant turn's content blocks (thinking included) go back as
  the model wrote them (`ChatResult.native`), as the API requires of a tool loop; the loop only ever appends;
- **a fallback model on a refusal:** on the Claude API the server re-runs a declined request on the fallback model
  inside the same call (`fallbacks`: the model the admin console names, else Anthropic's default by refusal category);
  Bedrock has no server-side fallback, so there the SDK's client-side middleware (`BetaRefusalFallbackMiddleware`)
  re-asks the fallback model, pinned per conversation (`BetaFallbackState`); on both, an overloaded or failing model is
  retried by the SDK and then, once, by the fallback model;
- **exact usage:** the tokens read from and written to the cache, besides the uncached input and the output.

Configuration comes from `llm.chat_model_from_env` (the server's environment, or the admin console's setting).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import anthropic
from anthropic import AnthropicBedrockMantle, BetaFallbackState, BetaRefusalFallbackMiddleware

from modeler_agents.run import LLMUnavailableError

DEFAULT_MAX_TOKENS = 16_000            # the reply and the thinking (thinking counts toward it)
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Claude on Bedrock: the first-party ids with Bedrock's `anthropic.` prefix
MODELS = ("anthropic.claude-opus-5-5", "anthropic.claude-sonnet-5-5", "anthropic.claude-haiku-5-5")
# Claude on Anthropic's own API: the first-party ids, as they are
API_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"   # the Claude API's server-side refusal fallback
_INTERNAL = ("thinking", "redacted_thinking", "tool_use")


def _tool(schema: dict[str, Any]) -> dict[str, Any]:
    """A loop tool (`llm.Tool.schema`, the Chat Completions shape) as Claude reads it."""
    function = schema.get("function", schema)
    return {"name": function["name"], "description": function.get("description", ""),
            "input_schema": function.get("parameters") or {"type": "object", "properties": {}}}


def to_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """The loop's conversation as Claude's system prompt and messages. An assistant turn the model wrote is sent back as
    its own content blocks (`native`); the tool results that follow it go back together in one user message."""
    system = "\n\n".join(str(m["content"]) for m in messages if m["role"] == "system")
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "system":
            continue
        if role == "assistant":
            if m.get("native") is not None:
                content: Any = list(m["native"])
            else:
                content = ([{"type": "text", "text": m["content"]}] if m.get("content") else []) + [
                    {"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                     "input": _arguments(c["function"].get("arguments"))} for c in m.get("tool_calls") or []]
            out.append({"role": "assistant", "content": content})
        elif role == "tool":
            text = str(m.get("content", ""))
            result = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": text,
                      **({"is_error": True} if text.startswith("ERROR") else {})}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) and out[-1].get("_results"):
                out[-1]["content"].append(result)
            else:
                out.append({"role": "user", "content": [result], "_results": True})
        else:
            out.append({"role": "user", "content": str(m.get("content", ""))})
    for m in out:
        m.pop("_results", None)
    return system, out


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _kept(blocks: list[Any]) -> list[Any]:
    """The blocks to send back and act on: after a refusal fallback, the thinking and tool calls before the last
    `fallback` block are left out (the fallback block itself stays where it was), as the API requires."""
    last = max((i for i, b in enumerate(blocks) if getattr(b, "type", "") == "fallback"), default=-1)
    return [b for i, b in enumerate(blocks) if i > last or getattr(b, "type", "") not in _INTERNAL]


class _ClaudeChat:
    """What Claude on Bedrock and on the Claude API share: the request, its caching and effort, the fallback on an
    overloaded model, and the answer in the loop's shape. A subclass makes the client and says where it runs."""

    provider = ""
    where = ""                       # the service's name in a message ("Amazon Bedrock", "The Claude API")

    def _init(self, *, model: str, effort: str | None, fallback: str | None, max_tokens: int) -> None:
        self.model = model
        self.effort = effort if effort in EFFORTS else None
        self.fallback = fallback or None
        self.max_tokens = max_tokens
        # in a chain of models (`llm.FallbackChat`), Claude hands over after one retry instead of the SDK's four
        self.fail_fast = False

    def _params(self, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        params: dict[str, Any] = {"model": model, "max_tokens": self.max_tokens, "messages": messages,
                                  "cache_control": {"type": "ephemeral"}}
        if system:
            params["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if tools:
            params["tools"] = [_tool(t) for t in tools]
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        return params

    def _client_for_call(self) -> Any:
        return self._client.with_options(max_retries=1) if self.fail_fast and hasattr(self._client, "with_options") \
            else self._client

    def _create(self, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        raise NotImplementedError

    def _refused_credentials(self, exc: anthropic.APIStatusError) -> str:
        return f"{self.where} refused the credentials ({exc.status_code}): check the key in the admin console (Keys)"

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        from modeler_agents.llm import ChatResult, ToolCall

        system, converted = to_messages(messages)
        try:
            try:
                response = self._create(self.model, system, converted, tools)
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                busy = isinstance(exc, anthropic.APIConnectionError) or exc.status_code == 429 or exc.status_code >= 500
                if not (self.fallback and busy):
                    raise
                # overloaded, rate-limited or failing after the SDK's own retries (529 overloaded included)
                response = self._create(self.fallback, system, converted, tools)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LLMUnavailableError(self._refused_credentials(exc)) from exc
        except anthropic.NotFoundError as exc:
            raise LLMUnavailableError(f"{self.where} does not serve {self.model!r}: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailableError(f"{self.where} answered HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError(f"{self.where} could not be reached: {exc}") from exc
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMUnavailableError(f"Claude declined the request ({getattr(details, 'category', None) or 'policy'}): "
                                      f"{getattr(details, 'explanation', None) or 'no explanation given'}")
        blocks = _kept(list(response.content))
        text = "\n".join(b.text for b in blocks if b.type == "text").strip()
        calls = tuple(ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}), raw_arguments=json.dumps(b.input or {}))
                      for b in blocks if b.type == "tool_use")
        u = response.usage
        usage = {"input_tokens": int(u.input_tokens or 0), "output_tokens": int(u.output_tokens or 0),
                 "cache_creation_input_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
                 "cache_read_input_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0)}
        return ChatResult(content=text, tool_calls=calls, finish_reason=str(response.stop_reason or ""), usage=usage,
                          model=str(response.model or self.model), native=tuple(blocks))


class ClaudeBedrockChat(_ClaudeChat):
    provider = "bedrock"
    where = "Amazon Bedrock"

    def __init__(self, *, model: str, region: str, api_key: str | None = None, aws_access_key: str | None = None,
                 aws_secret_key: str | None = None, effort: str | None = None, fallback: str | None = None,
                 max_tokens: int = DEFAULT_MAX_TOKENS, timeout_s: float = 600.0, client: Any = None):
        self._init(model=model, effort=effort, fallback=fallback, max_tokens=max_tokens)
        self.region = region
        middleware = [BetaRefusalFallbackMiddleware([{"model": self.fallback}])] if self.fallback else None
        self._client = client or AnthropicBedrockMantle(
            aws_region=region, api_key=api_key or None, aws_access_key=aws_access_key or None,
            aws_secret_key=aws_secret_key or None, timeout=timeout_s, max_retries=4, middleware=middleware)
        self._states: dict[str, BetaFallbackState] = {}

    def _state(self, system: str, first: Any) -> BetaFallbackState:
        """One fallback state per conversation (its system prompt and task), so a fallback pins only that conversation."""
        key = hashlib.sha256((system + "\x00" + json.dumps(first, sort_keys=True, default=str)).encode()).hexdigest()
        return self._states.setdefault(key, BetaFallbackState())

    def _create(self, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        params = self._params(model, system, messages, tools)
        client = self._client_for_call()
        if self.fallback:
            with self._state(system, messages[0]["content"] if messages else ""):
                return client.beta.messages.create(**params)
        return client.beta.messages.create(**params)

    def _refused_credentials(self, exc: anthropic.APIStatusError) -> str:
        return (f"Amazon Bedrock refused the credentials ({exc.status_code}): check the key in the admin console (Keys) "
                "and that the model is enabled in the AWS account")


class ClaudeAPIChat(_ClaudeChat):
    """Claude on Anthropic's own API with a Console key (`anthropic.Anthropic`). A refusal is re-run on the fallback model
    by the server inside the same call: the model the admin console names, else Anthropic's default (`fallbacks`)."""

    provider = "anthropic"
    where = "The Claude API"

    def __init__(self, *, model: str, api_key: str, effort: str | None = None, fallback: str | None = None,
                 max_tokens: int = DEFAULT_MAX_TOKENS, timeout_s: float = 600.0, client: Any = None):
        self._init(model=model, effort=effort, fallback=fallback, max_tokens=max_tokens)
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=4)

    def _create(self, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        params = self._params(model, system, messages, tools)
        params["betas"] = [SERVER_FALLBACK_BETA]
        params["fallbacks"] = [{"model": self.fallback}] if self.fallback and self.fallback != model else "default"
        return self._client_for_call().beta.messages.create(**params)

    def _refused_credentials(self, exc: anthropic.APIStatusError) -> str:
        return (f"The Claude API refused the key ({exc.status_code}): check the key in the admin console (Keys), and that "
                "its Console workspace has credit left")


def check_api_key(api_key: str, *, client: Any = None) -> tuple[bool, str]:
    """Whether a Claude API key works, at no cost: the list of models it may use (no message is sent, no token spent)."""
    client = client or anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=0)
    try:
        served = [m.id for m in client.models.list(limit=100)]
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        return False, f"the Claude API refused the key ({exc.status_code}): check that it was copied whole"
    except anthropic.APIStatusError as exc:
        return False, f"the Claude API answered HTTP {exc.status_code}: {exc.message}"
    except anthropic.APIConnectionError as exc:
        return False, f"the Claude API could not be reached from the server: {exc}"
    known = [m for m in API_MODELS if m in served]
    return (True, f"answers; the key may use {', '.join(known)}") if known else (
        True, f"answers, but none of {', '.join(API_MODELS)} is among its {len(served)} models")
