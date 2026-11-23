"""The Delivery flow's files and the layouts a person signed off earlier (contracts 2026-11-12 §8.10): software test
data for the browser flow, which runs with no LLM provider.

    uv run python delivery.py <read root> <project id> <out dir>

Writes the synthetic workbook and report of the made-up Exampleamide (`modeler_intake.synthetic`) to <out dir>, and
puts every `TruthTable.spec` of both into the project's mapping cache as a person's version: each approved, except the
one of the workbook's urine table, which stays proposed, so its table is read with a mapping that waits for a person.
Prints, as JSON, the two file names and the mapping that waits.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from modeler_intake import synthetic
from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.source import parse_document, region_grid
from modeler_project import FileProjectStore, Workspace
from modeler_project.mapping_cache import MappingCache

WAITING = "urine-excretion"                           # the id of the truth table whose mapping no person approved yet

root, project_id, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
cache = MappingCache(Workspace(FileProjectStore(root), tenant, project_id))
# the report without its unruled table: that page is a table no code grids, counted as silent loss
files = (synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False))
waiting: dict[str, object] = {}
for file in files:
    (out / file.name).write_bytes(file.data)
    doc = parse_document(file.data, file.name)
    regions = {r.where: r for r in doc.regions}
    for table in file.tables:
        region = regions[table.where]
        entry = cache.propose(layout_fingerprint(region_grid(doc, region.id)), table.spec, origin="person",
                              origin_detail="e2e-fixture", first_seen=(doc.file_sha256, region.id), by="e2e-fixture")
        if table.id == WAITING:
            waiting = {"mapping_id": entry.mapping_id, "version": entry.version, "table": table.id, "where": table.where}
        else:
            cache.approve(entry.mapping_id, entry.version, by="e2e-fixture", note="signed off earlier")
if not waiting:
    raise SystemExit(f"no truth table is named {WAITING!r}")
print(json.dumps({"files": [f.name for f in files], "waiting": waiting}))
