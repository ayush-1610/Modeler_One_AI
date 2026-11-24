"""Claude on Anthropic's own API with a Console key (`modeler_agents.claude.ClaudeAPIChat`, decision D1 of
docs/plans/2026-11-24-data-story-next-phase.md): the real SDK client against a stand-in HTTP transport, so what is
checked is the request the Claude API would receive. Made-up answers; no network, no spend."""

from __future__ import annotations

import json

import httpx2
import pytest
from anthropic import Anthropic

from modeler_agents.claude import SERVER_FALLBACK_BETA, ClaudeAPIChat, check_api_key
from modeler_agents.llm import LLMConfigError, chat_model_from_env
from modeler_agents.run import LLMUnavailableError

pytestmark = pytest.mark.req("T-20")

TEST_CREDENTIAL = "t" * 12                # a made-up credential


def _message(model: str = "claude-opus-5-5") -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": "ready"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 3,
                      "cache_read_input_tokens": 7}}


class ClaudeAPI:
    """A stand-in for the Claude API: answers each request with the next answer, and keeps the requests."""

    def __init__(self, answers: list[tuple[int, dict]]):
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        status, body = self.answers.pop(0)
        return httpx2.Response(status, json=body)

    def client(self) -> Anthropic:
        return Anthropic(api_key=TEST_CREDENTIAL, max_retries=0,
                         http_client=httpx2.Client(transport=httpx2.MockTransport(self)))

    def body(self, i: int) -> dict:
        return json.loads(self.requests[i].content)


def test_a_request_is_cached_with_its_effort_and_a_server_side_fallback_on_a_refusal():
    api = ClaudeAPI([(200, _message()), (200, _message())])
    chat = ClaudeAPIChat(model="claude-opus-5-5", api_key=TEST_CREDENTIAL, effort="medium", client=api.client())
    result = chat.complete([{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Say ready."}], [])
    body = api.body(0)
    assert body["model"] == "claude-opus-5-5" and body["output_config"] == {"effort": "medium"}
    assert body["cache_control"] == {"type": "ephemeral"} and body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["fallbacks"] == "default"                                     # Anthropic's own, by refusal category
    assert SERVER_FALLBACK_BETA in api.requests[0].headers["anthropic-beta"]
    assert result.content == "ready" and result.usage["cache_read_input_tokens"] == 7
    # the admin console's fallback model is named to the server instead
    named = ClaudeAPIChat(model="claude-opus-5-5", api_key=TEST_CREDENTIAL, fallback="claude-sonnet-5-5", client=api.client())
    named.complete([{"role": "user", "content": "Say ready."}], [])
    assert api.body(1)["fallbacks"] == [{"model": "claude-sonnet-5-5"}]


def test_a_refused_key_says_where_to_look_and_an_overloaded_model_hands_over_to_the_fallback_once():
    api = ClaudeAPI([(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})])
    with pytest.raises(LLMUnavailableError, match="refused the key.*admin console"):
        ClaudeAPIChat(model="claude-opus-5-5", api_key=TEST_CREDENTIAL, client=api.client()).complete(
            [{"role": "user", "content": "x"}], [])
    busy = ClaudeAPI([(529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
                      (200, _message("claude-sonnet-5-5"))])
    chat = ClaudeAPIChat(model="claude-opus-5-5", api_key=TEST_CREDENTIAL, fallback="claude-sonnet-5-5", client=busy.client())
    assert chat.complete([{"role": "user", "content": "x"}], []).model == "claude-sonnet-5-5"
    assert [busy.body(i)["model"] for i in range(2)] == ["claude-opus-5-5", "claude-sonnet-5-5"]


def test_the_claude_api_is_configured_by_name_and_says_what_is_missing():
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "anthropic", "MODELER_LLM_MODEL": "claude-opus-5-5"})
    with pytest.raises(LLMConfigError, match="MODELER_LLM_MODEL"):
        chat_model_from_env({"MODELER_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": TEST_CREDENTIAL})
    chat = chat_model_from_env({"MODELER_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": TEST_CREDENTIAL,
                                "MODELER_LLM_MODEL": "claude-sonnet-5-5", "MODELER_LLM_EFFORT": "low",
                                "MODELER_LLM_FALLBACK": "claude-haiku-5-5"})
    assert isinstance(chat, ClaudeAPIChat) and chat.provider == "anthropic"
    assert (chat.model, chat.effort, chat.fallback) == ("claude-sonnet-5-5", "low", "claude-haiku-5-5")


def test_a_key_is_checked_for_free_by_the_list_of_models_it_may_use():
    listing = {"data": [{"type": "model", "id": m, "display_name": m, "created_at": "2026-10-01T00:00:00Z"}
                        for m in ("claude-opus-5-5", "claude-sonnet-5-5")], "has_more": False,
               "first_id": "claude-opus-5-5", "last_id": "claude-sonnet-5-5"}
    ok, said = check_api_key(TEST_CREDENTIAL, client=ClaudeAPI([(200, listing)]).client())
    assert ok and "claude-opus-5-5" in said
    refused = ClaudeAPI([(401, {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}})])
    ok, said = check_api_key(TEST_CREDENTIAL, client=refused.client())
    assert not ok and "refused the key" in said
