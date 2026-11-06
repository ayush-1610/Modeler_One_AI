"""Write what the intake agent proposes from what a proposal implies (build D) into a project's brief, as agent A1's
`propose_implied` would (DRAFTED, each with the quote from the uploaded proposal and why, through `brief_ops.agent_set`
and `save_brief`, so the version and its audit event are the real ones): software test data for the browser flows,
which run with no LLM provider.

    uv run python agent_implied.py <read root> <project id> <quote>
"""

from __future__ import annotations

import sys
from pathlib import Path

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import Citation, FieldStatus, ProjectBrief
from modeler_project.brief_ops import BRIEF_ID, agent_set, save_brief
from modeler_project.documents import DocumentLibrary, document_record

root, project_id, quote = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
ws = Workspace(FileProjectStore(root), tenant, project_id)
doc = document_record(DocumentLibrary(ws).documents()[0])
cite = Citation(doc_sha256=doc.sha256, page=1, quote=quote, source=doc.name)
brief = ProjectBrief.from_content(ws.latest(ArtifactKind.BRIEF, BRIEF_ID).content)
for path, value, why in (
    ("qoi.context_of_use", "support a biowaiver of the 25 mg strength", "a biowaiver is what the proposal is for"),
    ("scope.formulation_types", ["ir_tablet"], "an immediate-release tablet is the only product the proposal names"),
    ("scenarios[0].route", "oral", "the tablet is taken by mouth"),
):
    brief = agent_set(brief, path, value=value, unit=None, citations=(cite,), status=FieldStatus.DRAFTED, confidence=None,
                      by="agent:e2e-fixture", note=f"proposed by the intake agent from what the document implies: {why}")
save_brief(ws, brief, actor="agent:e2e-fixture", reason="test fixture: what the intake agent drafted from the proposal")
