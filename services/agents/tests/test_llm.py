"""D-16: the in-house model (LiteLLM proxy in front of Ollama) through the OpenAI-compatible client, and the tool loop."""

from __future__ import annotations

import json

import httpx
import pytest

from modeler_agents.llm import (
    ChatResult,
    ContextExceeded,
    LLMConfigError,
    OpenAICompatChat,
    Tool,
    ToolCall,
    chat_model_from_env,
    run_tool_loop,
)

pytestmark = pytest.mark.req("T-41")


@pytest.fixture(autouse=True)
def _rested_models_forgotten():
    # the models a chain rests are shared by the process: each test starts with none resting
    from modeler_agents.llm import HEALTH

    HEALTH.reset()
    yield
    HEALTH.reset()


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


def test_a_rate_limit_is_waited_out_as_long_as_the_provider_asks():
    answers = [httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "rate limit: tokens per minute"}}),
               httpx.Response(200, json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 1}, "model": "m"})]
    waits = []
    chat = OpenAICompatChat(provider="groq", base_url="https://x", api_key="k", model="m", max_retries=2,
                            transport=httpx.MockTransport(lambda request: answers.pop(0)), sleep=waits.append)
    assert chat.complete([], []).content == "OK" and waits == [7.0]


def test_a_tool_call_the_provider_refuses_is_sent_back_to_the_model_to_correct():
    from modeler_agents.llm import Tool, run_tool_loop

    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, json={"error": {"message": "Tool call validation failed: parameters for tool submit "
                                                                  "did not match schema: missing properties: 'role'"}})
        if len(bodies) == 2:
            return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                                  "function": {"name": "submit", "arguments": json.dumps({"role": "test"})}}]},
                                  "finish_reason": "tool_calls"}], "usage": {}, "model": "m"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "DONE"}, "finish_reason": "stop"}], "usage": {},
                                         "model": "m"})

    got = []
    chat = OpenAICompatChat(provider="groq", base_url="https://x", api_key="k", model="m",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    tool = Tool("submit", "submit", {"type": "object", "properties": {"role": {"type": "string"}}}, lambda **a: got.append(a) or "saved")
    outcome = run_tool_loop(chat, system="s", user="u", tools=[tool])
    assert outcome.status == "COMPLETED" and got == [{"role": "test"}]
    assert "Your last tool call was refused" in bodies[1]["messages"][-1]["content"]


def test_a_spent_daily_limit_is_said_at_once_not_waited_on():
    calls, waits = [], []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1580"}, json={"error": {
            "message": "Rate limit reached for model on tokens per day (TPD): Limit 200000, Used 199093"}})

    chat = OpenAICompatChat(provider="groq", base_url="https://x", api_key="k", model="m", max_retries=4,
                            transport=httpx.MockTransport(handler), sleep=waits.append)
    with pytest.raises(Exception, match="daily limit is reached"):
        chat.complete([], [])
    assert (len(calls), waits) == (1, [])


def test_a_prompt_the_in_house_model_cut_is_refused_as_too_long_for_its_window():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 2048, "completion_tokens": 3}, "model": "m"})

    chat = OpenAICompatChat(provider="litellm", base_url="https://x", api_key="k", model="m",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(ContextExceeded, match="OLLAMA_CONTEXT_LENGTH") as caught:
        chat.complete([{"role": "user", "content": "word " * 8000}], [])
    assert caught.value.window == 2048
    assert chat.complete([{"role": "user", "content": "short"}], []).content == "ok"   # a short prompt read whole


def test_the_in_house_model_is_asked_for_a_larger_window_once_it_cuts_a_prompt():
    # LiteLLM passes `num_ctx` into Ollama's options (checked 2026-11-22 on its ollama_chat/ and ollama/ routes): the
    # cut request is sent again asking for 32k, and every later request asks for it too
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        read = 9000 if body.get("num_ctx") == 32768 else 2048
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": read, "completion_tokens": 3}, "model": "m"})

    chat = OpenAICompatChat(provider="litellm", base_url="https://x", api_key="k", model="m",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert chat.complete([{"role": "user", "content": "word " * 8000}], []).content == "ok"
    assert [b.get("num_ctx") for b in bodies] == [None, 32768]
    chat.complete([{"role": "user", "content": "next"}], [])
    assert bodies[-1]["num_ctx"] == 32768


def test_a_larger_window_the_server_refuses_leaves_the_conversation_to_be_fitted():
    def handler(request):
        if json.loads(request.content).get("num_ctx"):
            return httpx.Response(500, json={"error": {"message": "model requires more system memory than is available"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 2048, "completion_tokens": 3}, "model": "m"})

    chat = OpenAICompatChat(provider="litellm", base_url="https://x", api_key="k", model="m",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(ContextExceeded) as caught:
        chat.complete([{"role": "user", "content": "word " * 8000}], [])
    assert caught.value.window == 2048 and chat.num_ctx == -1          # not asked again
    assert chat.complete([{"role": "user", "content": "short"}], []).content == "ok"


def test_the_same_call_with_the_same_answer_says_so_and_a_changed_answer_does_not():
    answers = iter(["no matches", "no matches", "REFUSED: record the dose first", "ACCEPTED"])
    calls = [("search", {"q": "mw"}), ("search", {"q": "mw"}), ("save", {"v": 1}), ("save", {"v": 1})]

    class Repeats:
        provider, model = "test", "r"

        def __init__(self):
            self.n = 0

        def complete(self, messages, tools):
            self.n += 1
            if self.n > len(calls):
                return ChatResult("done", (), "stop", {}, "r")
            name, args = calls[self.n - 1]
            return ChatResult("", (ToolCall(id=str(self.n), name=name, arguments=args),), "tool_calls", {}, "r")

    tools = [Tool(n, n, {"type": "object", "properties": {}}, lambda **kw: next(answers)) for n in ("search", "save")]
    steps = []
    run_tool_loop(Repeats(), system="s", user="u", tools=tools, log_step=steps.append)
    results = [s["result"] for s in steps if s["type"] == "tool_result"]
    assert results[1].startswith("NOTE: you made this same call before (turn 1)") and "NOTE" not in results[0]
    assert results[3] == "ACCEPTED"                                     # its answer changed: it moved on


@pytest.mark.parametrize(("status", "message", "window"), [
    (413, ("Request too large for model `openai/gpt-oss-120b` on tokens per minute (TPM): Limit 8000, Requested 9512, "
           "please reduce your message size and try again."), 8000),
    (400, "This model's maximum context length is 32768 tokens. However, you requested 40100 tokens.", 32768),
    (413, "payload too large", None),
])
def test_a_provider_saying_the_request_is_too_long_names_its_window(status, message, window):
    chat = OpenAICompatChat(provider="groq", base_url="https://x", api_key="k", model="m", sleep=lambda s: None,
                            transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"error": {"message": message}})))
    with pytest.raises(ContextExceeded) as caught:
        chat.complete([{"role": "user", "content": "hi"}], [])
    assert caught.value.window == window


class _SmallWindow:
    """A model whose context window holds `window` tokens (4 characters each here): a longer request is refused as the
    in-house model's is; otherwise it reads a page per turn, then stops."""

    provider, model = "litellm", "small"

    def __init__(self, window: int, pages: int):
        self.window, self.pages, self.sent = window, pages, []

    def complete(self, messages, tools):
        from modeler_agents.llm import _size

        self.sent.append(messages)
        if _size(messages, tools) / 4 > self.window:
            raise ContextExceeded("cut", window=self.window)
        read = len(self.sent)                       # a new page each turn (what it read is not counted back)
        done = len(self.sent) > self.pages + 6
        if done:
            return ChatResult("finished", (), "stop", {"input_tokens": 1, "output_tokens": 1}, "small")
        call = ToolCall(id=f"c{len(self.sent)}", name="read_page", arguments={"page": read + 1})
        return ChatResult("", (call,), "tool_calls", {"input_tokens": 1, "output_tokens": 1}, "small")


def test_a_conversation_longer_than_the_window_leaves_its_oldest_turns_out_and_goes_on():
    # the owner, 2026-11-22: "read the proposal" on Start stopped once its conversation outgrew the in-house model's
    # window; the loop now keeps the instructions and the task and leaves the oldest pages out, saying so
    model = _SmallWindow(window=4000, pages=20)
    tool = Tool("read_page", "a page", {"type": "object", "properties": {"page": {"type": "integer"}}},
                lambda page: f"page {page}: " + "text " * 600)
    steps = []
    outcome = run_tool_loop(model, system="SYSTEM", user="TASK", tools=[tool], max_turns=40, log_step=steps.append)
    assert outcome.status == "COMPLETED", outcome.error
    fitted = [s for s in steps if s["type"] == "context_fitted"]
    assert len(fitted) == 1 and fitted[0]["window"] == 4000          # refused once, then fitted before every turn
    last = model.sent[-1]
    assert last[0]["content"] == "SYSTEM" and last[1]["content"].startswith("TASK") and "left out" in last[1]["content"]
    tool_answers = [m["content"] for m in last if m["role"] == "tool"]
    assert all(a.endswith("(shortened to fit the model's context window)") for a in tool_answers[:-1])  # earlier: a trace
    assert len(tool_answers[-1]) > 2000                                                                    # latest: whole
    assert all(m["role"] != "tool" or m["tool_call_id"] in {c["id"] for a in last if a["role"] == "assistant"
                                                             for c in a["tool_calls"]} for m in last)   # pairs kept


def test_a_request_that_cannot_fit_the_window_fails_with_what_to_change():
    model = _SmallWindow(window=100, pages=3)
    outcome = run_tool_loop(model, system="SYSTEM " * 200, user="TASK", tools=[], max_turns=5)
    assert outcome.status == "LLM_UNAVAILABLE" and "do not fit the model's context window" in outcome.error
    assert "OLLAMA_CONTEXT_LENGTH" in outcome.error

def test_another_openai_compatible_service_needs_its_address_and_model():
    from modeler_agents.llm import chat_model_from_env

    env = {"MODELER_LLM_PROVIDER": "openai_compat", "OPENAI_COMPAT_KEY": "k"}
    with pytest.raises(LLMConfigError, match="OPENAI_COMPAT_BASE"):
        chat_model_from_env(env)
    model = chat_model_from_env(env | {"OPENAI_COMPAT_BASE": "https://api.example.ai/v1", "MODELER_LLM_MODEL": "gpt-oss-120b"})
    assert (model.provider, model.base_url, model.model) == ("openai_compat", "https://api.example.ai/v1", "gpt-oss-120b")


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
    with pytest.raises(LLMConfigError, match="no longer supported.*MODELER_LLM_PROVIDER=litellm"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "k"})   # the hosted providers are gone
    with pytest.raises(LLMConfigError, match="unknown"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "other"})
    with pytest.raises(LLMConfigError, match="seconds"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k", "MODELER_LLM_TIMEOUT_S": "soon"})
    model = chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k"})
    assert (model.provider, model.model, model.base_url) == ("litellm", "qwen-coder", "http://127.0.0.1:4000/v1")
    model = chat_model_from_env({"MODELER_LLM_PROVIDER": "LiteLLM", "LITELLM_KEY": "k", "LITELLM_BASE": "http://srv:4000/v1/",
                                 "MODELER_LLM_MODEL": "other"})
    assert (model.model, model.base_url) == ("other", "http://srv:4000/v1")


def test_groq_is_the_third_provider_gpt_oss_120b_with_its_reasoning_effort_in_the_body():
    """Plan 2026-11-21 v2 §9: gpt-oss-120b on GroqCloud through the same OpenAI-compatible client. `reasoning_effort`
    goes in the request body for it only; the proxy's request is unchanged. A mock transport answers: no test calls
    GroqCloud."""
    with pytest.raises(LLMConfigError, match="needs GROQ_API_KEY"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "groq", "LITELLM_KEY": "k"})          # never the proxy's key
    with pytest.raises(LLMConfigError, match="low, medium, high, not 'max'"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "groq", "GROQ_API_KEY": "gk", "MODELER_LLM_EFFORT": "max"})
    model = chat_model_from_env({"MODELER_LLM_PROVIDER": "Groq", "GROQ_API_KEY": "gk", "MODELER_LLM_EFFORT": "medium",
                                 "LITELLM_BASE": "http://srv:4000/v1"})              # the proxy's address is not GroqCloud's
    assert (model.provider, model.model, model.base_url, model.reasoning_effort) == (
        "groq", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1", "medium")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), auth=request.headers["Authorization"], body=json.loads(request.content))
        return httpx.Response(200, json=_completion([("record_dose", {"value": 10, "unit": "mg"})]))

    model._transport = httpx.MockTransport(handler)
    result = model.complete([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "record_dose"}}])
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions" and seen["auth"] == "Bearer gk"
    assert (seen["body"]["model"], seen["body"]["reasoning_effort"], seen["body"]["tool_choice"]) == (
        "openai/gpt-oss-120b", "medium", "auto")
    assert [(c.name, c.arguments) for c in result.tool_calls] == [("record_dose", {"value": 10, "unit": "mg"})]
    # no effort set: the model's own default (nothing sent); another model from MODELER_LLM_MODEL
    other = chat_model_from_env({"MODELER_LLM_PROVIDER": "groq", "GROQ_API_KEY": "gk", "MODELER_LLM_MODEL": "openai/gpt-oss-20b"})
    other._transport = httpx.MockTransport(handler)
    other.complete([], [])
    assert other.model == "openai/gpt-oss-20b" and "reasoning_effort" not in seen["body"]
    # the proxy's request is unchanged, even with MODELER_LLM_EFFORT set (Claude's setting)
    proxy = chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k", "MODELER_LLM_EFFORT": "high"})
    proxy._transport = httpx.MockTransport(handler)
    proxy.complete([], [])
    assert set(seen["body"]) == {"model", "messages", "temperature", "stream", "stream_options"} and seen["auth"] == "Bearer k"
    assert seen["body"]["stream"] is True                 # the in-house model streams (a slow CPU model is not cut off)


def test_a_rejected_or_unreachable_groqcloud_names_its_own_key_not_the_proxys():
    groq = {"provider": "groq", "base_url": "https://api.groq.com/openai/v1", "api_key": "gk", "model": "openai/gpt-oss-120b",
            "sleep": lambda s: None}
    rejected = OpenAICompatChat(**groq, transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"error": {"message": "Invalid API Key", "code": "invalid_api_key"}})))
    with pytest.raises(Exception, match="groq rejected the key .*check GROQ_API_KEY") as caught:
        rejected.complete([], [])
    assert "LITELLM" not in str(caught.value)

    def refuse(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(Exception, match="cannot reach https://api.groq.com/openai/v1") as caught:
        OpenAICompatChat(**groq, max_retries=0, transport=httpx.MockTransport(refuse)).complete([], [])
    assert "LITELLM" not in str(caught.value)


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


def test_a_loop_going_round_in_circles_stops_so_shorter_steps_can_run():
    # in an 8k window Nemotron searched one phrase 50 times (2026-11-22): five turns in a row of nothing but calls made
    # before with the same answers end the loop
    class Circles:
        provider, model = "test", "c"

        def complete(self, messages, tools):
            return ChatResult("", (ToolCall(id=str(len(messages)), name="search", arguments={"q": "mw"}),), "tool_calls", {}, "c")

    tool = Tool("search", "search", {"type": "object", "properties": {"q": {"type": "string"}}}, lambda q: "no matches")
    outcome = run_tool_loop(Circles(), system="s", user="u", tools=[tool], max_turns=80)
    assert outcome.status == "INCOMPLETE" and outcome.turns == 6 and "repeated the same calls" in outcome.error


def test_an_agent_that_keeps_reading_is_told_to_submit_two_turns_before_its_last():
    # A6 on Nemotron read files for all ten of its turns and saved no question card (2026-11-22)
    seen = []

    class Reader:
        provider, model = "test", "r"

        def complete(self, messages, tools):
            seen.append(messages[-1])
            if messages[-1]["role"] == "user" and messages[-1]["content"].startswith("Two turns are left"):
                return ChatResult("", (ToolCall(id="s", name="submit_card", arguments={}),), "tool_calls", {}, "r")
            return ChatResult("", (ToolCall(id=str(len(messages)), name="read", arguments={"n": len(messages)}),),
                              "tool_calls", {}, "r")

    saved = []
    tools = [Tool("read", "read", {"type": "object", "properties": {}}, lambda n: f"line {n}"),
             Tool("submit_card", "submit", {"type": "object", "properties": {}}, lambda: saved.append(1) or "saved")]
    run_tool_loop(Reader(), system="s", user="u", tools=tools, max_turns=10)
    assert saved == [1]
    assert sum(1 for m in seen if m["role"] == "user" and "Two turns are left. Call submit_card now" in m["content"]) == 1


def _client(provider, handler, **kw):
    return OpenAICompatChat(provider=provider, base_url=f"https://{provider}", api_key="k", model=f"{provider}-m",
                            transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw)


def test_a_chain_hands_a_request_the_first_model_cannot_answer_to_the_next_at_once():
    # the owner, 2026-11-22: the question stage waited five times 600 s on the in-house model and produced nothing;
    # "if any model is unavailable, switch at that moment to another, so the task continues"
    from modeler_agents.llm import FallbackChat

    slow_calls, fast_calls = [], []

    def slow(request):
        slow_calls.append(1)
        raise httpx.ReadTimeout("no answer", request=request)

    def fast(request):
        fast_calls.append(json.loads(request.content))
        return httpx.Response(200, json=_completion(content="the question card"))

    chain = FallbackChat([_client("litellm", slow), _client("nvidia", fast)], labels=["Qwen Coder", "Nemotron Ultra"])
    steps = []
    outcome = run_tool_loop(chain, system="s", user="u", tools=[], log_step=steps.append)
    assert outcome.status == "COMPLETED" and outcome.final_text == "the question card"
    assert len(slow_calls) == 1                                   # handed over at once, not five waits
    assert outcome.answered_by == "Nemotron Ultra"                # the conversation ended there
    again = chain.conversation()                                  # the next conversation does not wait on it again
    assert again.label == "Nemotron Ultra" and "resting" in again.switches[0]["why"]
    (switch,) = [s for s in steps if s["type"] == "model_switch"]
    assert (switch["from"], switch["to"]) == ("Qwen Coder", "Nemotron Ultra") and "no answer within" in switch["why"]


@pytest.mark.parametrize(("status", "body"), [
    (429, {"error": {"message": "Rate limit reached on tokens per day (TPD): Limit 200000, Used 199999"}}),
    (502, {"error": {"message": "upstream request failed"}}),
    (401, {"error": {"message": "invalid api key"}}),
])
def test_a_spent_daily_limit_an_outage_or_a_refused_key_hands_over_too(status, body):
    from modeler_agents.llm import FallbackChat

    first = _client("groq", lambda r: httpx.Response(status, json=body))
    chain = FallbackChat([first, _client("nvidia", lambda r: httpx.Response(200, json=_completion(content="ok")))])
    talk = chain.conversation()
    assert talk.complete([{"role": "user", "content": "hi"}], []).content == "ok"
    assert talk.provider == "nvidia" and len(talk.switches) == 1


def test_a_models_own_refused_tool_call_stays_with_it_and_the_last_models_failure_is_said():
    from modeler_agents.llm import FallbackChat, LLMUnavailableError, ToolCallRejected

    refused = _client("groq", lambda r: httpx.Response(400, json={"error": {"message": "tool call validation failed"}}))
    talk = FallbackChat([refused, _client("nvidia", lambda r: httpx.Response(200, json=_completion(content="ok")))]).conversation()
    with pytest.raises(ToolCallRejected):
        talk.complete([{"role": "user", "content": "hi"}], [])
    assert talk.provider == "groq"
    down = FallbackChat([_client("groq", lambda r: httpx.Response(503, json={})),
                         _client("nvidia", lambda r: httpx.Response(503, json={}))]).conversation()
    with pytest.raises(LLMUnavailableError, match="nvidia unavailable"):
        down.complete([{"role": "user", "content": "hi"}], [])
    assert [s["from"] for s in down.switches] == ["groq/groq-m"]


def test_a_conversation_goes_on_with_another_provider_without_claudes_own_blocks():
    seen = []
    chat = _client("nvidia", lambda r: seen.append(json.loads(r.content)) or httpx.Response(200, json=_completion(content="ok")))
    chat.complete([{"role": "user", "content": "u"},
                   {"role": "assistant", "content": None, "tool_calls": [], "native": ("thinking block",)}], [])
    assert all(set(m) <= {"role", "content", "tool_calls", "tool_call_id", "name"} for m in seen[0]["messages"])


def test_without_a_chain_a_timeout_is_tried_twice_not_five_times():
    calls = []

    def slow(request):
        calls.append(1)
        raise httpx.ReadTimeout("no answer", request=request)

    with pytest.raises(Exception, match="no answer within"):
        _client("litellm", slow, max_retries=4).complete([{"role": "user", "content": "hi"}], [])
    assert len(calls) == 2


def test_a_conversation_under_way_starts_again_on_the_next_model_never_goes_on_there():
    # the governance review, 2026-11-22: one model answers a whole conversation (one author per file), and the next
    # provider is sent only what a fresh start sends
    from modeler_agents.llm import FallbackChat

    first_seen, second_seen = [], []

    def first(request):
        body = json.loads(request.content)
        first_seen.append(len(body["messages"]))
        if len(body["messages"]) > 2:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json=_completion([("read", {"page": 1})]))

    def second(request):
        second_seen.append(len(json.loads(request.content)["messages"]))
        return httpx.Response(200, json=_completion(content="done"))

    chain = FallbackChat([_client("litellm", first), _client("nvidia", second)], labels=["Qwen Coder", "Nemotron Ultra"])
    tool = Tool("read", "a page", {"type": "object", "properties": {"page": {"type": "integer"}}}, lambda page: "page text")
    steps = []
    outcome = run_tool_loop(chain, system="s", user="u", tools=[tool], log_step=steps.append)
    assert outcome.status == "COMPLETED" and outcome.final_text == "done"
    assert second_seen == [2]                                   # a fresh start: the instructions and the task only
    assert [s["type"] for s in steps if s["type"] in ("model_switch", "conversation_restarted")] == [
        "model_switch", "conversation_restarted"]


def test_parallel_conversations_keep_their_own_place_and_a_one_off_server_error_rests_nothing():
    # the reliability review, 2026-11-22: one NVIDIA 502 on one document moved every later file off NVIDIA
    from modeler_agents.llm import FallbackChat, ModelHealth

    def nvidia(request):
        text = json.loads(request.content)["messages"][-1]["content"]
        return httpx.Response(502, json={"error": {"message": "upstream request failed"}}) if "dissolution" in text else \
            httpx.Response(200, json=_completion(content="nvidia"))

    chain = FallbackChat([_client("nvidia", nvidia), _client("groq", lambda r: httpx.Response(200, json=_completion(content="groq")))],
                         labels=["Nemotron Ultra", "gpt-oss-120b"], health=ModelHealth())
    a, b = chain.conversation(), chain.conversation()
    assert a.complete([{"role": "user", "content": "the dissolution report"}], []).content == "groq"
    assert b.complete([{"role": "user", "content": "the synopsis"}], []).content == "nvidia"   # b stayed on its model
    assert chain.conversation().label == "Nemotron Ultra"                                     # nothing rests


def test_a_request_too_long_for_one_window_goes_only_to_a_larger_one():
    from modeler_agents.llm import ContextExceeded, FallbackChat, ModelHealth

    def small(request):     # a window of 9,500 tokens: GroqCloud's 8,000 is smaller still
        return httpx.Response(413, json={"error": {"message": "Request too large: Limit 9500, Requested 12000"}})

    chain = FallbackChat([_client("litellm", small), _client("groq", small),
                          _client("nvidia", lambda r: httpx.Response(200, json=_completion(content="large")))],
                         health=ModelHealth())
    talk = chain.conversation()
    assert talk.complete([{"role": "user", "content": "x"}], []).content == "large"
    assert [s["to"] for s in talk.switches] == ["nvidia/nvidia-m"]           # GroqCloud's 8k was skipped
    only_small = FallbackChat([_client("litellm", small), _client("groq", small)], health=ModelHealth()).conversation()
    with pytest.raises(ContextExceeded):                                       # none larger: the loop fits it
        only_small.complete([{"role": "user", "content": "x"}], [])


def test_a_model_without_tool_call_ids_gets_unique_ones_and_its_reasoning_is_dropped():
    from modeler_agents.llm import _parse

    data = {"choices": [{"message": {"content": "<think>the dose is 2 x 30</think>Here.", "tool_calls": [
        {"type": "function", "function": {"name": "read", "arguments": "{}"}},
        {"type": "function", "function": {"name": "read", "arguments": "{}"}}]}}]}
    first, second = _parse(data, "m"), _parse(data, "m")
    ids = [c.id for r in (first, second) for c in r.tool_calls]
    assert len(set(ids)) == 4 and all(len(i) == 9 and i.isalnum() for i in ids)
    assert first.content == "Here." and all(c.raw == {} for c in first.tool_calls)



def _sse(*chunks) -> bytes:
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks).encode() + b"data: [DONE]\n\n"


def test_a_streamed_answer_is_put_back_together_with_its_tool_calls_and_usage():
    # the in-house model streams so that a slow but working CPU model is not cut off by the wait for the whole answer
    stream = _sse(
        {"model": "qwen", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Reading "}}]},
        {"choices": [{"index": 0, "delta": {"content": "the page."}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                                            "function": {"name": "read_page", "arguments": "{\"pa"}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "ge\": 3}"}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 9}})
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=stream, headers={"content-type": "text/event-stream"})

    chat = chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k"})
    chat._transport = httpx.MockTransport(handler)
    result = chat.complete([{"role": "user", "content": "go"}], [{"type": "function", "function": {"name": "read_page"}}])
    assert result.content == "Reading the page." and result.finish_reason == "tool_calls"
    (call,) = result.tool_calls
    assert (call.id, call.name, call.arguments) == ("c1", "read_page", {"page": 3})
    assert result.usage == {"input_tokens": 120, "output_tokens": 9}       # the cut-prompt check still has its count
    assert seen[0]["stream_options"] == {"include_usage": True}


def test_an_error_inside_a_stream_is_raised_and_a_server_that_cannot_stream_is_asked_again_whole():
    broken = _sse({"choices": [{"index": 0, "delta": {"content": "half"}}]}, {"error": {"message": "model crashed"}})
    chat = chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k"})
    chat._transport = httpx.MockTransport(lambda r: httpx.Response(200, content=broken))
    with pytest.raises(Exception, match="the answer broke off: model crashed"):
        chat.complete([{"role": "user", "content": "go"}], [])

    def no_stream(request):
        if json.loads(request.content).get("stream"):
            return httpx.Response(400, json={"error": {"message": "stream is not supported with tools"}})
        return httpx.Response(200, json=_completion(content="whole"))

    plain = chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k"})
    plain._transport = httpx.MockTransport(no_stream)
    assert plain.complete([{"role": "user", "content": "go"}], []).content == "whole" and plain.stream is False
    off = chat_model_from_env({"MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "k", "MODELER_LLM_STREAM": "0"})
    assert off.stream is False
