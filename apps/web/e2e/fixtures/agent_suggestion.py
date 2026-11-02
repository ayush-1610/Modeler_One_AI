"""Write the intake agent's suggested M15 ratings into a project's brief, as agent A1 would (DRAFTED, through
`brief_ops.agent_set` and `save_brief`, so the version and its audit event are the real ones): software test data for
the browser flows, which run with no LLM provider.

    uv run python agent_suggestion.py <read root> <project id> <influence> <consequence>
"""

from __future__ import annotations

import sys
from pathlib import Path

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import FieldStatus, ProjectBrief
from modeler_project.brief_ops import BRIEF_ID, agent_set, save_brief

root, project_id, influence, consequence = Path(sys.argv[1]), *sys.argv[2:5]
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
ws = Workspace(FileProjectStore(root), tenant, project_id)
brief = ProjectBrief.from_content(ws.latest(ArtifactKind.BRIEF, BRIEF_ID).content)
for path, value in (("m15.influence_suggested", influence), ("m15.consequence_suggested", consequence)):
    brief = agent_set(brief, path, value=value, unit=None, citations=(), status=FieldStatus.DRAFTED, confidence=None,
                      by="agent:e2e-fixture")
save_brief(ws, brief, actor="agent:e2e-fixture", reason="test fixture: the intake agent's suggested ratings")
