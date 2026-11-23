"""The Data room's browser flows' delivery (plan 2026-11-21 v2 §5): software test data, the made-up Exampleamide
(`modeler_project.dataroom.synthetic`), never client data; the flows run with no LLM provider.

    uv run python dataroom.py zip <out dir>                        # writes the delivery's zip, prints its path
    uv run python dataroom.py seed <read root> <project id>        # after the read stage ran: what A6-A8 would answer

`seed` writes the question card (a draft, to confirm on the page), each file's triage and each used file's extraction
straight into the project's Data room store, exactly the forms the agents submit; code reads and checks every value
from the cells when the page asks for the room, as always. Prints, as JSON, the files the room holds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from modeler_project import FileProjectStore, Workspace
from modeler_project.dataroom import DataRoomStore
from modeler_project.dataroom.synthetic import delivery_zip, seed

if sys.argv[1] == "zip":
    out = Path(sys.argv[2]) / "Exampleamide delivery.zip"
    out.write_bytes(delivery_zip())
    print(json.dumps({"zip": str(out)}))
else:
    root, project_id = Path(sys.argv[2]), sys.argv[3]
    tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
    store = DataRoomStore(Workspace(FileProjectStore(root), tenant, project_id))
    if not store.files():
        raise SystemExit("the delivery is not read yet: run the read stage first")
    seed(store, by="e2e-fixture")
    print(json.dumps({"files": [f.path for f in store.files()]}))
