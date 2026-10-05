"""D-16: Gemini / Groq through the OpenAI-compatible client, and the provider-agnostic tool loop."""

from __future__ import annotations

import json

import httpx
import pytest

from modeler_agents.llm import (
    ChatResult,
    LLMConfigError,
    OpenAICompatChat,
    Tool,
    ToolCall,
    chat_model_from_env,
    run_tool_loop,
)

pytestmark = pytest.mark.req("T-41")


def _completion(tool_calls=None, content=""):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [{"id": f"c{i}", "type": "function",
                                  "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(tool_calls)]
    return {"model": "m", "choices": [{"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def test_client_sends_bearer_and_tools_and_parses_calls():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion([("propose_field", {"field": "dose", "value": "50"})]))

    chat = OpenAICompatChat(provider="gemini", base_url="https://x/v1beta/openai", api_key="k", model="m",
                            transport=httpx.MockTransport(handler))
    result = chat.complete([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "f"}}])
    assert seen["auth"] == "Bearer k" and seen["body"]["temperature"] == 0 and seen["body"]["tools"]
    assert result.tool_calls[0].name == "propose_field" and result.tool_calls[0].arguments == {"field": "dose", "value": "50"}
    assert result.usage == {"input_tokens": 10, "output_tokens": 5}


def test_client_retries_overload_then_gives_up_with_the_providers_message():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json=[{"error": {"message": "This model is currently experiencing high demand."}}])

    chat = OpenAICompatChat(provider="gemini", base_url="https://x", api_key="k", model="m", max_retries=2,
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(Exception, match="high demand"):
        chat.complete([], [])
    assert len(calls) == 3


def test_client_does_not_retry_a_refusal():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    chat = OpenAICompatChat(provider="groq", base_url="https://x", api_key="k", model="m",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(Exception, match="refused"):
        chat.complete([], [])
    assert len(calls) == 1


def test_provider_selection_from_env_never_reads_keys_from_elsewhere():
    assert chat_model_from_env({}) is None
    assert chat_model_from_env({"MODELER_LLM_PROVIDER": "disabled"}) is None
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "gemini"})
    with pytest.raises(LLMConfigError, match="unknown"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "other", "GEMINI_API_KEY": "k"})
    model = chat_model_from_env({"MODELER_LLM_PROVIDER": "groq", "GROQ_API_KEY": "k", "MODELER_LLM_MODEL": "x"})
    assert (model.provider, model.model) == ("groq", "x")


class ScriptedModel:
    provider = "test"
    model = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.messages = []

    def complete(self, messages, tools):
        self.messages.append(list(messages))
        calls = self.turns.pop(0)
        return ChatResult(content="" if calls else "done", tool_calls=tuple(
            ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)),
            finish_reason="", usage={"input_tokens": 1, "output_tokens": 1}, model="scripted")


def test_tool_loop_feeds_handler_answers_back_and_logs_every_step():
    recorded = []
    steps = []
    tool = Tool("record", "record a value", {"type": "object", "properties": {"v": {"type": "string"}}},
                handler=lambda v: (recorded.append(v), "RECORDED")[1] if v != "bad" else "REJECTED: not in the quote")
    model = ScriptedModel([[("record", {"v": "bad"})], [("record", {"v": "good"}), ("nope", {})], []])
    outcome = run_tool_loop(model, system="s", user="u", tools=[tool], log_step=steps.append)
    assert outcome.status == "COMPLETED" and outcome.final_text == "done" and recorded == ["good"]
    tool_messages = [m for m in model.messages[1] if m["role"] == "tool"]
    assert tool_messages[0]["content"].startswith("REJECTED")
    assert "unknown tool" in [s for s in steps if s["type"] == "tool_result"][-1]["result"]
    assert outcome.usage == {"input_tokens": 3, "output_tokens": 3}


def test_tool_loop_stops_at_the_turn_limit():
    tool = Tool("t", "", {"type": "object", "properties": {}}, handler=lambda: "ok")
    outcome = run_tool_loop(ScriptedModel([[("t", {})]] * 5), system="s", user="u", tools=[tool], max_turns=3)
    assert outcome.status == "INCOMPLETE" and outcome.turns == 3


def test_gemini_thought_signature_is_echoed_back_with_the_call():
    """Gemini refuses a follow-up turn whose function call lost its thought signature (seen live, 2026-10-05)."""
    sent = []
    replies = [
        {"model": "m", "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c0", "type": "function", "function": {"name": "t", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "SIG"}}}]}}]},
        _completion(),
    ]

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))

    chat = OpenAICompatChat(provider="gemini", base_url="https://x", api_key="k", model="m", transport=httpx.MockTransport(handler))
    tool = Tool("t", "", {"type": "object", "properties": {}}, handler=lambda: "ok")
    assert run_tool_loop(chat, system="s", user="u", tools=[tool]).status == "COMPLETED"
    echoed = next(m for m in sent[1]["messages"] if m["role"] == "assistant")["tool_calls"][0]
    assert echoed["extra_content"]["google"]["thought_signature"] == "SIG"
