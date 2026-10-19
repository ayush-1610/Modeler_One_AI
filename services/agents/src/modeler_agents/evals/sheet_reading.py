"""Score the reading agent on the evaluation set for client sheets (`modeler_intake.reading_eval`, R3c).

    uv run python -m modeler_agents.evals.sheet_reading                  # code's first filling (suggest)
    uv run python -m modeler_agents.evals.sheet_reading --reader agent   # the reading agent (MODELER_LLM_*, the server)

The agent is scored here exactly as the API runs it: from code's first filling, each proposal checked by code. The
owner's real files are scored only on the server, never committed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from modeler_intake.grid import WorkbookGrid
from modeler_intake.reading_eval import Case, Reader, answer_reader, evaluate, report, suggest_reader
from modeler_intake.sheet_form import SheetForm


def agent_reader(model: Any, *, max_turns: int = 8) -> Reader:
    """The reading agent on `model`, starting from code's first filling, as the API runs it."""
    from modeler_agents.sheet_reader import read_sheet

    def read(case: Case, grid: WorkbookGrid) -> SheetForm | None:
        return read_sheet(model, workbook=grid, sheet=case.sheet, drug=case.drug, actor="agent:eval",
                          max_turns=max_turns).form

    return read


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reader", choices=("suggest", "agent", "answer"), default="suggest")
    parser.add_argument("--json", help="also write the scores here, as JSON")
    args = parser.parse_args(argv)
    if args.reader == "agent":
        from modeler_agents.llm import chat_model_from_env

        model = chat_model_from_env()
        if model is None:
            print("no model configured: set MODELER_LLM_PROVIDER (and its key) and run this on the server", file=sys.stderr)
            return 2
        reader: Reader = agent_reader(model)
    else:
        reader = suggest_reader if args.reader == "suggest" else answer_reader
    scores = evaluate(reader)
    print(f"reader: {args.reader}\n{report(scores)}")
    for s in scores:
        for problem in s.problems[:3]:
            print(f"  {s.case}: {problem}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump([{"case": s.case, "fields": s.fields, "exact": s.exact, "problems": s.problems} for s in scores],
                      handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
