"""D-16: web search for the agents through Ollama's cloud API (mocked HTTP; the owner's server runs it live)."""

from __future__ import annotations

import json

import httpx
import pytest

from modeler_agents.llm import ChatResult, ToolCall
from modeler_agents.web_search import WebSearchError, ask, search_tool, web_search

pytestmark = pytest.mark.req("T-41")
ENV = {"OLLAMA_API_KEY": "search-key", "MODELER_LLM_PROVIDER": "litellm", "LITELLM_KEY": "llm-key"}
RESULTS = {"results": [{"title": "Farxiga label", "url": "https://example.org/label",
                        "content": "The mean plasma terminal half-life (t1/2) for dapagliflozin is approximately 12.9 hours."}]}


def _search(handler):
    return httpx.MockTransport(handler)


def test_web_search_sends_the_key_and_reads_the_results():
    seen = {}

    def handler(request):
        seen["auth"], seen["body"] = request.headers["Authorization"], json.loads(request.content)
        return httpx.Response(200, json=RESULTS)

    out = web_search("dapagliflozin half-life", 3, env=ENV, transport=_search(handler))
    assert seen == {"auth": "Bearer search-key", "body": {"query": "dapagliflozin half-life", "max_results": 3}}
    assert out[0]["url"] == "https://example.org/label" and "12.9 hours" in out[0]["content"]


def test_web_search_errors_say_what_to_fix():
    with pytest.raises(WebSearchError, match="OLLAMA_API_KEY"):
        web_search("q", env={})
    with pytest.raises(WebSearchError, match="rejected the key"):
        web_search("q", env=ENV, transport=_search(lambda r: httpx.Response(401, json={"error": "unauthorized"})))

    def slow(request):
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(WebSearchError, match="no answer within"):
        web_search("q", env=ENV, transport=_search(slow))


class Scripted:
    """The model of the owner's loop: first asks for a search, then answers from the tool result."""

    provider, model = "litellm", "qwen-coder"

    def __init__(self):
        self.seen = []

    def complete(self, messages, tools):
        self.seen.append([dict(m) for m in messages])
        if len(self.seen) == 1:
            assert [t["function"]["name"] for t in tools] == ["web_search"]
            return ChatResult("", (ToolCall(id="c1", name="web_search", arguments={"query": "dapagliflozin half-life"}),),
                              "tool_calls", {"input_tokens": 1, "output_tokens": 1}, "qwen-coder")
        tool_answer = messages[-1]
        assert tool_answer["role"] == "tool" and tool_answer["tool_call_id"] == "c1" and "12.9 hours" in tool_answer["content"]
        return ChatResult("About 12.9 hours (Farxiga label).", (), "stop", {"input_tokens": 1, "output_tokens": 1}, "qwen-coder")


def test_ask_runs_the_search_loop_and_returns_the_final_answer():
    model = Scripted()
    answer = ask("What is the half-life of dapagliflozin?", model=model, env=ENV,
                 transport=_search(lambda r: httpx.Response(200, json=RESULTS)))
    assert answer == "About 12.9 hours (Farxiga label)."
    assistant = model.seen[1][2]
    assert assistant["role"] == "assistant" and assistant["tool_calls"][0]["function"]["name"] == "web_search"


def test_the_agents_search_tool_stores_every_page_before_it_can_be_quoted():
    stored = []

    def store(result):
        stored.append(result)
        return "a" * 64

    tool = search_tool(store, env=ENV, transport=_search(lambda r: httpx.Response(200, json=RESULTS)))
    answer = tool.handler(query="dapagliflozin half-life")
    assert stored[0]["url"] == "https://example.org/label" and f"doc_sha256 {'a' * 64} page 1" in answer
    assert search_tool(store, env={}) is None                                 # no key: the tool is not offered
