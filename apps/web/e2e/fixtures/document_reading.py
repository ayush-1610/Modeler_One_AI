"""The reading agent's part in the browser flows, which run with no LLM provider (I4): software test data.

    uv run python document_reading.py write <dir>                       the delivery's files (a PK workbook, a Word synopsis)
    uv run python document_reading.py read <read root> <project> <sid>  read the synopsis as the agent would

`read` runs the real reading job (`modeler_api.client_api.run_document_job`: the agent's tools, code's checks, the
record on the file and the agent run's log) with a scripted model making the evaluation set's perfect reading
(`modeler_project.delivery_eval`), so what the page shows is what a reading that code accepted produces.
"""

from __future__ import annotations

import sys
from pathlib import Path

from modeler_agents.llm import ChatResult, ToolCall
from modeler_api.client_api import run_document_job
from modeler_project import FileProjectStore
from modeler_project.delivery_eval import DELIVERIES

DELIVERY = next(d for d in DELIVERIES if d.name == "a Word protocol giving another dose than the PK sheet")
SYNOPSIS = next(f for f in DELIVERY.files if f.document)


class Scripted:
    provider, model = "e2e", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        calls = self.turns.pop(0) if self.turns else []
        return ChatResult(content="The synopsis states EX-301's dose, route, design, dosage form, food state and n.",
                          finish_reason="", model="scripted", usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)))


if sys.argv[1] == "write":
    out = Path(sys.argv[2])
    for f in DELIVERY.files:
        (out / f.name).write_bytes(f.build())
else:
    root, project_id, sid = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
    result = run_document_job(FileProjectStore(root), tenant, project_id, sid, model=Scripted([list(SYNOPSIS.reading)]))
    assert result["refused"] == 0 and result["facts"] == 6, result
