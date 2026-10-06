"""Check the agents' model and web search from a terminal, with the environment the API will run with.

    source ~/.modeler-secrets.env
    uv run python -m modeler_agents.llm_check                      # model list, a reply, a tool call
    uv run python -m modeler_agents.llm_check --search             # + one web search and a question answered with it
    uv run python -m modeler_agents.llm_check --ask "What is the half-life of dapagliflozin?"

Prints what it checked and why anything failed; never prints a key. Exit code 0 only when every check passed.
"""

from __future__ import annotations

import argparse
import sys

from modeler_agents.llm import LLMConfigError, chat_model_from_env
from modeler_agents.run import LLMUnavailableError
from modeler_agents.web_search import WebSearchError, ask, search_key, web_search

_TOOL = {"type": "function", "function": {
    "name": "record_dose", "description": "Record the dose stated in the text.",
    "parameters": {"type": "object", "properties": {"value": {"type": "number"}, "unit": {"type": "string"}},
                   "required": ["value", "unit"]}}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--search", action="store_true", help="also check the web search and the search loop")
    parser.add_argument("--ask", help="a question to answer with the model and web search")
    args = parser.parse_args(argv)
    ok = True
    try:
        model = chat_model_from_env()
    except LLMConfigError as exc:
        print(f"FAIL configuration: {exc}")
        return 1
    if model is None:
        print("FAIL agents are off: set MODELER_LLM_PROVIDER=litellm, LITELLM_BASE and LITELLM_KEY")
        return 1
    print(f"model    {model.provider} {model.model} at {model.base_url}")
    served = model.list_models()
    print(f"served   {', '.join(served) or 'unknown (GET /models gave nothing)'}")
    if served and model.model not in served:
        print(f"FAIL     {model.model!r} is not among them: set MODELER_LLM_MODEL")
        ok = False
    try:
        reply = model.complete([{"role": "user", "content": "Reply with the single word: ready"}], [])
        print(f"reply    {reply.content.strip()[:60]!r} ({reply.usage.get('output_tokens', 0)} tokens)")
        called = model.complete([{"role": "user", "content": "The protocol says: 'a single oral dose of 10 mg'. "
                                                               "Record the dose with the tool."}], [_TOOL])
        calls = [(c.name, c.arguments) for c in called.tool_calls]
        print(f"tools    {calls or 'no tool call (the agents need tool calls)'}")
        ok = ok and bool(calls)
    except LLMUnavailableError as exc:
        print(f"FAIL     {exc}")
        return 1
    if args.search or args.ask:
        if not search_key():
            print("FAIL     web search needs OLLAMA_API_KEY")
            return 1
        try:
            results = web_search("dapagliflozin pharmacokinetics half-life", 3)
            print(f"search   {len(results)} results: {'; '.join(r['url'] for r in results)[:200]}")
        except WebSearchError as exc:
            print(f"FAIL     {exc}")
            return 1
        question = args.ask or "What is the terminal half-life of dapagliflozin in healthy adults? Cite the source."
        try:
            print(f"ask      {question}\n{ask(question, model=model)}")
        except (RuntimeError, LLMUnavailableError) as exc:
            print(f"FAIL     {exc}")
            ok = False
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
