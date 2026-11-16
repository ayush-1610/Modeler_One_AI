"""Leave a literature value in a project as the literature agent would (the paper stored, the value proposed through
`evidence_register.propose` with its quote): software test data for the browser flows, which run with no LLM provider.

    uv run python literature_value.py <read root> <project id> [<values as JSON>]

With no values given, reusamide's logP from its stored paper. Values given (a list of {target, value, unit, quote,
doi, title}) are proposed as the literature agent's, each citing its publication by DOI (another project of the same
drug offers them until this one holds the same value, from the same source and quote: `value_reuse.offered`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from modeler_project import FileProjectStore, Workspace
from modeler_project.documents import DocumentLibrary, document_record
from modeler_project.evidence import EvidenceItem, SourceRef, SourceType, new_id
from modeler_project.evidence_register import propose

root, project_id = Path(sys.argv[1]), sys.argv[2]
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
ws = Workspace(FileProjectStore(root), tenant, project_id)
if len(sys.argv) > 3:
    for given in json.loads(sys.argv[3]):
        propose(ws, EvidenceItem(id=new_id(), target=given["target"], value=given["value"], unit=given.get("unit"),
                                 source_type=SourceType.PUBLICATION, quote=given["quote"],
                                 source=SourceRef(title=given["title"], doi=given["doi"], year=2015)), actor="agent:e2e-fixture")
    raise SystemExit(0)
paper = b"# Pharmacokinetics of reusamide\n\nThe logP of reusamide was 2.4 by shake flask at pH 7.4.\n"
doc = document_record(DocumentLibrary(ws).add(paper, "fulltext-PMC7.md", role="paper", by="agent:e2e-fixture"))
propose(ws, EvidenceItem(id=new_id(), target="phys.logp", value=2.4, source_type=SourceType.PUBLICATION,
                         quote="The logP of reusamide was 2.4", conditions={"method": "shake flask", "pH": "7.4"},
                         source=SourceRef(doc_sha256=doc.sha256, page=1, title="Pharmacokinetics of reusamide",
                                          doi="10.1/reuse", year=2020)), actor="agent:e2e-fixture")
