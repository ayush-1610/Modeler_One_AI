"""A figure the reading agent suggests for digitizing, in the browser flows, which run with no LLM provider (plan
2026-11-10, R5): software test data.

    uv run python figure_suggestion.py <read root> <project> <sid> <page> <study> <caption>

Runs the real reading job (`run_document_job`: the agent's tools, code's checks, the record on the file) with a scripted
model that suggests one figure, a study's concentration-time profile, its caption quoted.
"""

from __future__ import annotations

import sys
from pathlib import Path

from modeler_agents.llm import ChatResult, ToolCall
from modeler_api.client_api import run_document_job
from modeler_project import FileProjectStore


class Scripted:
    provider, model = "e2e", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        calls = self.turns.pop(0) if self.turns else []
        return ChatResult(content="Only a figure shows the profile.", finish_reason="", model="scripted",
                          usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)))


root, project_id, sid, page, study, caption = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5], sys.argv[6]
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
suggest = ("suggest_digitization", {"kind": "concentration_time", "page": page, "study_id": study, "quote": caption})
result = run_document_job(FileProjectStore(root), tenant, project_id, sid, model=Scripted([[suggest]]))
assert result["refused"] == 0, result
