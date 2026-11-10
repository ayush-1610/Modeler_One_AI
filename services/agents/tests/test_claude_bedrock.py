"""Claude on Amazon Bedrock as an agent's model (`modeler_agents.claude`): the real SDK client against a stand-in HTTP
transport, so what is checked is the request Bedrock would receive. Made-up answers; no network."""

from __future__ import annotations

import json

import httpx2
import pytest
from anthropic import AnthropicBedrockMantle

from modeler_agents.claude import ClaudeBedrockChat, _kept, to_messages
from modeler_agents.llm import LLMConfigError, Tool, chat_model_from_env, run_tool_loop

pytestmark = pytest.mark.req("T-20")

MODEL = "anthropic.claude-opus-5-5"
FALLBACK = "anthropic.claude-sonnet-5-5"
TEST_CREDENTIAL = "t" * 12                # a made-up credential


def _message(content: list[dict], stop: str, *, model: str = MODEL, usage: dict | None = None, **more) -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop, "stop_sequence": None, **more,
            "usage": usage or {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0,
                               "cache_read_input_tokens": 0}}


class Bedrock:
    """A stand-in for Bedrock: answers each request with the next answer, and keeps the requests."""

    def __init__(self, answers: list[tuple[int, dict]]):
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        status, body = self.answers.pop(0)
        return httpx2.Response(status, json=body)

    def body(self, i: int) -> dict:
        return json.loads(self.requests[i].content)

    def chat(self, **kw) -> ClaudeBedrockChat:
        client = AnthropicBedrockMantle(aws_region="ap-south-1", api_key=TEST_CREDENTIAL, max_retries=0,
                                        http_client=httpx2.Client(transport=httpx2.MockTransport(self)))
        return ClaudeBedrockChat(model=MODEL, region="ap-south-1", client=client, **kw)


def _note_tool(seen: list) -> Tool:
    return Tool("note", "Record a value.", {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]},
                lambda x: seen.append(x) or f"noted {x}")


def test_a_tool_loop_sends_its_turns_back_unchanged_with_caching_and_effort_and_counts_the_cache():
    turn1 = [{"type": "thinking", "thinking": "", "signature": "sig-1"},
             {"type": "tool_use", "id": "toolu_1", "name": "note", "input": {"x": 3}}]
    bedrock = Bedrock([
        (200, _message(turn1, "tool_use", usage={"input_tokens": 40, "output_tokens": 20, "cache_creation_input_tokens": 900,
                                                 "cache_read_input_tokens": 0})),
        (200, _message([{"type": "text", "text": "done"}], "end_turn",
                       usage={"input_tokens": 30, "output_tokens": 8, "cache_creation_input_tokens": 60,
                              "cache_read_input_tokens": 900})),
    ])
    seen: list = []
    outcome = run_tool_loop(bedrock.chat(effort="high"), system="You are A1.", user="Read the proposal.",
                            tools=[_note_tool(seen)], max_turns=4)
    assert (outcome.status, outcome.final_text, seen) == ("COMPLETED", "done", [3])
    # every token the provider reported, the cache's reads and writes included
    assert outcome.usage == {"input_tokens": 70, "output_tokens": 28, "cache_creation_input_tokens": 960,
                             "cache_read_input_tokens": 900}
    first, second = bedrock.body(0), bedrock.body(1)
    assert str(bedrock.requests[0].url).startswith("https://bedrock-mantle.ap-south-1.api.aws/anthropic")
    assert first["model"] == MODEL and first["output_config"] == {"effort": "high"}
    assert first["cache_control"] == {"type": "ephemeral"}                      # the conversation so far, each turn
    assert first["system"] == [{"type": "text", "text": "You are A1.", "cache_control": {"type": "ephemeral"}}]
    assert first["tools"][0]["name"] == "note" and first["tools"][0]["input_schema"]["required"] == ["x"]
    assert "thinking" not in first                                                # always on; effort is the control
    # turn 2 carries turn 1 exactly as the model wrote it (thinking and its signature), then the tool's answer
    assert second["messages"][1] == {"role": "assistant", "content": turn1}
    assert second["messages"][2] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                                                  "content": "noted 3"}]}
    assert second["messages"][0] == first["messages"][0] == {"role": "user", "content": "Read the proposal."}


def test_a_refusal_ends_the_run_saying_why_and_an_overloaded_model_falls_back_once():
    refused = Bedrock([(200, _message([], "refusal", stop_details={"type": "refusal", "category": "bio",
                                                                   "explanation": "declined"}))])
    outcome = run_tool_loop(refused.chat(), system="s", user="u", tools=[], max_turns=2)
    assert outcome.status == "LLM_UNAVAILABLE" and "declined the request (bio)" in outcome.error
    overloaded = Bedrock([(529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
                          (200, _message([{"type": "text", "text": "ok"}], "end_turn", model=FALLBACK))])
    result = overloaded.chat(fallback=FALLBACK).complete([{"role": "user", "content": "u"}], [])
    assert (result.content, result.model) == ("ok", FALLBACK)
    assert [overloaded.body(i)["model"] for i in range(2)] == [MODEL, FALLBACK]
    unauthorised = Bedrock([(403, {"type": "error", "error": {"type": "permission_error", "message": "no access"}})])
    failed = run_tool_loop(unauthorised.chat(), system="s", user="u", tools=[], max_turns=2)
    assert failed.status == "LLM_UNAVAILABLE" and "check the key in the admin console" in failed.error


def test_after_a_refusal_fallback_the_thinking_and_calls_before_the_boundary_are_left_out():
    class B:
        def __init__(self, type_, **kw):
            self.type = type_
            self.__dict__.update(kw)

    blocks = [B("thinking"), B("tool_use", id="a"), B("text", text="partial"), B("fallback"), B("thinking"),
              B("tool_use", id="b")]
    assert [(b.type, getattr(b, "id", None)) for b in _kept(blocks)] == [("text", None), ("fallback", None),
                                                                         ("thinking", None), ("tool_use", "b")]


def test_the_loop_shape_becomes_claudes_with_tool_results_together_and_errors_marked():
    system, messages = to_messages([
        {"role": "system", "content": "S"}, {"role": "user", "content": "U"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{\"a\": 1}"}},
            {"id": "c2", "type": "function", "function": {"name": "g", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "fine"},
        {"role": "tool", "tool_call_id": "c2", "content": "ERROR: wrong arguments"}])
    assert system == "S"
    assert messages[1]["content"] == [{"type": "tool_use", "id": "c1", "name": "f", "input": {"a": 1}},
                                      {"type": "tool_use", "id": "c2", "name": "g", "input": {}}]
    assert messages[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1", "content": "fine"},
        {"type": "tool_result", "tool_use_id": "c2", "content": "ERROR: wrong arguments", "is_error": True}]}


def test_bedrock_is_configured_by_name_and_says_what_is_missing():
    env = {"MODELER_LLM_PROVIDER": "bedrock", "MODELER_LLM_MODEL": MODEL, "BEDROCK_REGION": "ap-south-1",
           "BEDROCK_API_KEY": TEST_CREDENTIAL, "MODELER_LLM_EFFORT": "medium", "MODELER_LLM_FALLBACK": FALLBACK}
    model = chat_model_from_env(env)
    assert (model.provider, model.model, model.effort, model.fallback) == ("bedrock", MODEL, "medium", FALLBACK)
    with pytest.raises(LLMConfigError, match="needs MODELER_LLM_MODEL"):
        chat_model_from_env({k: v for k, v in env.items() if k != "MODELER_LLM_MODEL"})
    with pytest.raises(LLMConfigError, match="needs BEDROCK_REGION"):
        chat_model_from_env({k: v for k, v in env.items() if k != "BEDROCK_REGION"})
    with pytest.raises(LLMConfigError, match="MODELER_LLM_EFFORT must be one of"):
        chat_model_from_env(env | {"MODELER_LLM_EFFORT": "extreme"})
