"""Leave a literature value in a project as the literature agent would (the paper stored, the value proposed through
`evidence_register.propose` with its quote): software test data for the browser flows, which run with no LLM provider.

    uv run python literature_value.py <read root> <project id>
"""

from __future__ import annotations

import sys
from pathlib import Path

from modeler_project import FileProjectStore, Workspace
from modeler_project.documents import DocumentLibrary, document_record
from modeler_project.evidence import EvidenceItem, SourceRef, SourceType, new_id
from modeler_project.evidence_register import propose

root, project_id = Path(sys.argv[1]), sys.argv[2]
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
ws = Workspace(FileProjectStore(root), tenant, project_id)
paper = b"# Pharmacokinetics of reusamide\n\nThe logP of reusamide was 2.4 by shake flask at pH 7.4.\n"
doc = document_record(DocumentLibrary(ws).add(paper, "fulltext-PMC7.md", role="paper", by="agent:e2e-fixture"))
propose(ws, EvidenceItem(id=new_id(), target="phys.logp", value=2.4, source_type=SourceType.PUBLICATION,
                         quote="The logP of reusamide was 2.4", conditions={"method": "shake flask", "pH": "7.4"},
                         source=SourceRef(doc_sha256=doc.sha256, page=1, title="Pharmacokinetics of reusamide",
                                          doi="10.1/reuse", year=2020)), actor="agent:e2e-fixture")
