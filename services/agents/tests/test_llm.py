"""D-16: the in-house model (LiteLLM proxy in front of Ollama) through the OpenAI-compatible client, and the tool loop."""

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

    chat = OpenAICompatChat(provider="litellm", base_url="http://llm:4000/v1", api_key="k", model="m",
                            transport=httpx.MockTransport(handler))
    result = chat.complete([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "f"}}])
    assert seen["auth"] == "Bearer k" and seen["body"]["temperature"] == 0 and seen["body"]["tools"]
    assert seen["body"]["stream"] is False
    assert result.tool_calls[0].name == "propose_field" and result.tool_calls[0].arguments == {"field": "dose", "value": "50"}
    assert result.usage == {"input_tokens": 10, "output_tokens": 5}


def test_client_retries_overload_then_gives_up_with_the_providers_message():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json=[{"error": {"message": "This model is currently experiencing high demand."}}])

    chat = OpenAICompatChat(provider="litellm", base_url="https://x", api_key="k", model="m", max_retries=2,
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(Exception, match="high demand"):
        chat.complete([], [])
    assert len(calls) == 3


def test_client_does_not_retry_a_refusal():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    chat = OpenAICompatChat(provider="litellm", base_url="https://x", api_key="k", model="m",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(Exception, match="refused"):
        chat.complete([], [])
    assert len(calls) == 1


def test_provider_selection_from_env_never_reads_keys_from_elsewhere():
    assert chat_model_from_env({}) is None
    assert chat_model_from_env({"MODELER_LLM_PROVIDER": "disabled"}) is None
    with pytest.raises(LLMConfigError, match="LITELLM_KEY"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm"})
    with pytest.raises(LLMConfigError, match="unknown"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "k"})   # the hosted providers are gone
    with pytest.raises(LLMConfigError, match="seconds"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k", "MODELER_LLM_TIMEOUT_S": "soon"})
    model = chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k"})
    assert (model.provider, model.model, model.base_url) == ("litellm", "qwen-coder", "http://127.0.0.1:4000/v1")
    model = chat_model_from_env({"MODELER_LLM_PROVIDER": "LiteLLM", "LITELLM_KEY": "k", "LITELLM_BASE": "http://srv:4000/v1/",
                                 "MODELER_LLM_MODEL": "other"})
    assert (model.model, model.base_url) == ("other", "http://srv:4000/v1")


def _chat(handler, **kw):
    return OpenAICompatChat(provider="litellm", base_url="http://llm:4000/v1", api_key="k", model="qwen-coder",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw)


def test_a_rejected_key_is_named_and_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"message": "Authentication Error, Invalid proxy server token passed"}})

    with pytest.raises(Exception, match="rejected the key .*LITELLM_KEY"):
        _chat(handler).complete([], [])
    assert len(calls) == 1


def test_an_unknown_model_names_the_models_the_proxy_serves():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen-coder"}]})
        return httpx.Response(400, json={"error": {"message": "Invalid model name passed in model=qwen3-coder:30b"}})

    chat = OpenAICompatChat(provider="litellm", base_url="http://llm:4000/v1", api_key="k", model="qwen3-coder:30b",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(Exception, match="does not serve the model 'qwen3-coder:30b'.*it serves: qwen-coder"):
        chat.complete([], [])


def test_an_unreachable_proxy_and_a_timeout_say_what_to_check():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(Exception, match="cannot reach http://llm:4000/v1.*LITELLM_BASE"):
        _chat(refuse, max_retries=1).complete([], [])

    def slow(request):
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(Exception, match="no answer within 5 s .*MODELER_LLM_TIMEOUT_S"):
        _chat(slow, max_retries=1, timeout_s=5).complete([], [])


def test_tool_calls_written_into_the_text_are_read_and_bad_arguments_go_back_to_the_model():
    content = ('Let me record it.\n<tool_call>\n{"name": "record_dose", "arguments": {"value": 10, "unit": "mg"}}\n'
               '</tool_call>')
    result = _chat(lambda r: httpx.Response(200, json=_completion(content=content))).complete(
        [], [{"type": "function", "function": {"name": "record_dose"}}])
    assert [(c.name, c.arguments) for c in result.tool_calls] == [("record_dose", {"value": 10, "unit": "mg"})]
    assert result.content == "Let me record it."
    broken = {"model": "m", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c0", "type": "function", "function": {"name": "f", "arguments": "{not json"}}]}}]}
    call = _chat(lambda r: httpx.Response(200, json=broken)).complete([], [{"type": "function", "function": {"name": "f"}}]).tool_calls[0]
    assert "__unparsed__" in call.arguments           # run_tool_loop answers the model: "not valid JSON, call again"


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
