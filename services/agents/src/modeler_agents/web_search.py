"""Web search for the agents: Ollama's cloud search API as a tool the model may call (decision D-16, plan D-09).

    OLLAMA_API_KEY=...                       the search API's own key (not the LiteLLM key)
    OLLAMA_WEB_SEARCH_URL=https://ollama.com/api/web_search   (default)

`web_search(query)` returns the results (title, url, content). `ask(question)` is the plain loop the owner's
reference script runs: the model gets the `web_search` tool, its calls are answered with the results, and the final
answer is returned. Inside the pipeline the agents use `search_tool`: every result page is stored as a document first,
so a value the agent proposes is quoted from a stored page and checked verbatim, like any other source (D-09: the web
finds primary sources; it is never itself the citation for a number without the page it came from).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping

import httpx

from modeler_agents.llm import ChatModel, LLMConfigError, LoopOutcome, Tool, chat_model_from_env, run_tool_loop

DEFAULT_URL = "https://ollama.com/api/web_search"
TOOL_NAME = "web_search"
TOOL_SCHEMA_PARAMETERS = {"type": "object", "properties": {"query": {"type": "string"},
                                                           "max_results": {"type": "integer"}}, "required": ["query"]}


class WebSearchError(RuntimeError):
    """The search could not run (no key, key rejected, unreachable, unexpected answer)."""


def search_key(env: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if env is None else env
    return (env.get("OLLAMA_API_KEY") or "").strip() or None


def web_search(query: str, max_results: int = 5, *, env: Mapping[str, str] | None = None, timeout_s: float = 30.0,
               transport: httpx.BaseTransport | None = None) -> list[dict[str, str]]:
    """[{title, url, content}] for `query` from Ollama's web search."""
    env = os.environ if env is None else env
    key = search_key(env)
    if not key:
        raise WebSearchError("web search needs OLLAMA_API_KEY in the environment")
    if not str(query).strip():
        raise WebSearchError("an empty query")
    url = env.get("OLLAMA_WEB_SEARCH_URL") or DEFAULT_URL
    try:
        with httpx.Client(timeout=timeout_s, transport=transport) as client:
            response = client.post(url, headers={"Authorization": f"Bearer {key}"},
                                   json={"query": str(query), "max_results": max(1, min(int(max_results), 10))})
    except httpx.TimeoutException as exc:
        raise WebSearchError(f"web search gave no answer within {timeout_s:g} s") from exc
    except httpx.HTTPError as exc:
        raise WebSearchError(f"web search unreachable: {type(exc).__name__}: {exc}") from exc
    if response.status_code in (401, 403):
        raise WebSearchError(f"web search rejected the key (HTTP {response.status_code}); check OLLAMA_API_KEY")
    if response.status_code != 200:
        raise WebSearchError(f"web search failed: HTTP {response.status_code}: {response.text[:200]}")
    try:
        results = response.json().get("results") or []
    except (ValueError, AttributeError) as exc:
        raise WebSearchError("web search answered with something that is not the expected JSON") from exc
    return [{"title": str(r.get("title") or ""), "url": str(r.get("url") or ""), "content": str(r.get("content") or "")}
            for r in results if isinstance(r, dict)]


def plain_tool(*, env: Mapping[str, str] | None = None, transport: httpx.BaseTransport | None = None) -> Tool:
    """The `web_search` tool of the owner's contract: the results go back to the model as JSON."""
    def handler(query: str, max_results: int = 5) -> str:
        try:
            return json.dumps(web_search(query, max_results, env=env, transport=transport), ensure_ascii=False)
        except WebSearchError as exc:
            return f"ERROR: {exc}"

    return Tool(TOOL_NAME, "Search the web for current information", TOOL_SCHEMA_PARAMETERS, handler)


def search_tool(store_page: Callable[[dict[str, str]], str], *, env: Mapping[str, str] | None = None,
                transport: httpx.BaseTransport | None = None) -> Tool | None:
    """The pipeline's variant: each result page is stored first (`store_page` returns its document sha256), so what
    the agent quotes is on a stored page. None when no search key is configured (the tool is then not offered)."""
    if not search_key(env):
        return None

    def handler(query: str, max_results: int = 5) -> str:
        try:
            results = web_search(query, max_results, env=env, transport=transport)
        except WebSearchError as exc:
            return f"ERROR: {exc}"
        if not results:
            return "no results"
        rows = []
        for r in results:
            sha = store_page(r) if r["content"].strip() else ""
            rows.append(f"{r['title']} | {r['url']}" + (f" | stored as doc_sha256 {sha} page 1 (read it with read_page, "
                                                         "quote from it)" if sha else " | no text"))
        return "\n".join(rows)

    return Tool(TOOL_NAME, "Search the web to find primary sources (papers, regulatory reviews, labels). Each result "
                           "page is stored as a document; read it and quote from it. A search result alone is never a "
                           "citation.", TOOL_SCHEMA_PARAMETERS, handler)


def ask(question: str, *, model: ChatModel | None = None, env: Mapping[str, str] | None = None, max_turns: int = 6,
        transport: httpx.BaseTransport | None = None) -> str:
    """Answer `question` with the configured model, letting it search the web (the owner's reference loop)."""
    model = model or chat_model_from_env(env)
    if model is None:
        raise LLMConfigError("agents are off: set MODELER_LLM_PROVIDER=litellm (with LITELLM_BASE and LITELLM_KEY)")
    tools = [plain_tool(env=env, transport=transport)] if search_key(env) else []
    outcome: LoopOutcome = run_tool_loop(model, system="Answer accurately. Search the web when the question needs current "
                                                       "information, and say which sources you used.",
                                         user=question, tools=tools, max_turns=max_turns)
    if outcome.status != "COMPLETED":
        raise RuntimeError(f"no answer: {outcome.status} {outcome.error}".strip())
    return outcome.final_text
