"""The Data room's browser flows' delivery (plan 2026-11-21 v2 §5): software test data, the made-up Exampleamide
(`modeler_project.dataroom.synthetic`), never client data; the flows run with no LLM provider.

    uv run python dataroom.py zip <out dir>                        # writes the delivery's zip, prints its path
    uv run python dataroom.py seed <read root> <project id>        # after the read stage ran: what A6-A8 would answer
    uv run python dataroom.py pause <read root> <project id> <why> # after a run: the run paused at extraction

`seed` writes the question card (a draft, to confirm on the page), each file's triage and each used file's extraction
straight into the project's Data room store, exactly the forms the agents submit; code reads and checks every value
from the cells when the page asks for the room, as always. Prints, as JSON, the files the room holds.

`pause` turns the finished run's record into one paused at extraction, 3 of 8 files done, as a run on a model leaves it
(plan 2026-11-24 §4): `provider_unavailable` (it resumes by itself in 10 minutes) or `budget_cap` (it waits for the cap).
No model is called: the flows run with none, so the run resumed from it skips its agent stages and finishes.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from modeler_project import FileProjectStore, Workspace
from modeler_project.dataroom import DataRoomStore
from modeler_project.dataroom.synthetic import delivery_zip, seed

SAID = {"provider_unavailable": "Nemotron Ultra could not answer (too many requests: its rate limit was reached).",
        "budget_cap": "The run reached its $10 limit for paid models (Admin → Limits)."}


def _store(root: Path, project_id: str) -> DataRoomStore:
    tenant = next(t.name for t in root.iterdir() if (t / "projects" / project_id).is_dir())
    return DataRoomStore(Workspace(FileProjectStore(root), tenant, project_id))


def _pause(store: DataRoomStore, reason: str) -> dict:
    doc = store.run()
    if doc.get("state") not in ("done", "paused"):
        raise SystemExit("run the delivery first: the paused run is made from a finished one")
    stages = {s["id"]: s for s in doc["stages"]}
    for sid in ("question", "triage"):
        stages[sid].update(state="done", note="as the agents left it")
    stages["extract"].update(state="paused", done=3, total=8, note="")
    for sid in ("check", "write"):
        stages[sid].update(state="waiting", note="")
    now = datetime.now(UTC)
    rests = reason == "provider_unavailable"
    doc.update(state="paused", finished_at=None, error="", auto_resumes=0,
               params={"stages": list(stages), "redo": [], "files": [], "focus_chars": None, "use_ocr": False},
               pause={"reason": reason, "said": SAID[reason],
                      "detail": "nvidia unavailable: HTTP 429: Too Many Requests" if rests else "",
                      "stage": "extract", "where": "extraction", "per_file": True, "done": 3, "total": 8,
                      "at": now.isoformat(timespec="seconds"),
                      "resume_at": (now + timedelta(minutes=10)).isoformat(timespec="seconds") if rests else None})
    store.set_run(doc)
    return {"state": "paused", "reason": reason}


if sys.argv[1] == "zip":
    out = Path(sys.argv[2]) / "Exampleamide delivery.zip"
    out.write_bytes(delivery_zip())
    print(json.dumps({"zip": str(out)}))
elif sys.argv[1] == "pause":
    print(json.dumps(_pause(_store(Path(sys.argv[2]), sys.argv[3]), sys.argv[4])))
else:
    store = _store(Path(sys.argv[2]), sys.argv[3])
    if not store.files():
        raise SystemExit("the delivery is not read yet: run the read stage first")
    seed(store, by="e2e-fixture")
    print(json.dumps({"files": [f.path for f in store.files()]}))
