"""The project's reading queue (plan 2026-11-10, R1): every client file the reading agent is to read, in the order it
arrived, until it is read.

Before it, a file that arrived while a reading ran was dropped: the one `reading` job was busy and nothing kept the file
for later. Now each arrival, and each "Read" a person asks for, is an item here; one background job (the API's
`intake_jobs.drain`) takes the items one after the other, and a file is never lost because another was being read. The
queue is the project's operational record beside its artifacts (`reading-queue.json`, next to the library's
`library.json`); what the agent read is recorded on each file and in its agent run, as before.

An item is `queued`, then `reading` while the agent works on it, then `done` or `failed` (with why). An item left
`reading` by a worker that stopped is put back once by the next drain (`recover`), then failed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from modeler_project.workspace import Workspace
from pbpk_domain.atomic_io import atomic_write_text, file_lock

QueueState = Literal["queued", "reading", "done", "failed"]
# "arrival": what code could not do with a file that has just arrived; "read": a person's "Read" (a document read for
# its data, or a workbook's sheets, all not read yet or the ones named); "map": a file code read whole, queued only to be
# looked at by the delivery pass with the others (plan 2026-11-10, R4)
QueueTask = Literal["arrival", "read", "map"]
MAX_ATTEMPTS = 2
KEEP_FINISHED = 500   # finished items kept beyond each file's latest one; older ones are dropped from the file


class QueueItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    sid: str
    file: str
    task: QueueTask
    sheets: tuple[str, ...] = ()
    state: QueueState = "queued"
    added_by: str
    added_at: str
    started_at: str | None = None
    finished_at: str | None = None
    attempts: int = 0
    note: str = ""                                   # what came of it, or why it failed
    run_ids: tuple[str, ...] = ()
    found: dict[str, int] = Field(default_factory=dict)   # counts of what the reading proposed (datasets, facts, …)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ReadingQueue:
    def __init__(self, ws: Workspace):
        self.ws = ws
        root = getattr(ws.store, "root", None)
        self._path = Path(root) / ws.tenant_id / "projects" / ws.project_id / "reading-queue.json" if root else None

    @property
    def available(self) -> bool:
        """Whether this store keeps the queue (a file store); without it the caller reads at once, as before."""
        return self._path is not None

    def items(self) -> list[QueueItem]:
        if self._path is None or not self._path.exists():
            return []
        return [QueueItem.model_validate(row) for row in json.loads(self._path.read_text(encoding="utf-8"))["items"]]

    def pending(self) -> bool:
        """Whether anything is waiting or being read."""
        return any(i.state in ("queued", "reading") for i in self.items())

    def _write(self, items: list[QueueItem]) -> None:
        assert self._path is not None
        # each file's latest item is always kept (the tray shows it, and `sweep` knows the file was queued); older,
        # finished items of a file read again are dropped first, oldest first
        latest = {i.sid: i.id for i in items}
        old = [i for i in items if i.state in ("done", "failed") and latest[i.sid] != i.id]
        finished = sum(1 for i in items if i.state in ("done", "failed"))
        drop = {i.id for i in old[:max(0, finished - KEEP_FINISHED)]}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path, json.dumps({"items": [i.model_dump(mode="json") for i in items if i.id not in drop]},
                                                 indent=1, ensure_ascii=False))

    def _change(self, edit) -> Any:
        if self._path is None:
            raise RuntimeError("this project store keeps no reading queue")
        with file_lock(self._path):
            items = self.items()
            items, answer = edit(items)
            self._write(items)
            return answer

    def add(self, files: list[tuple[str, str]], *, task: QueueTask, by: str, sheets: tuple[str, ...] = (),
            supersede_arrival: bool = False) -> list[QueueItem]:
        """Queue each `(sid, file name)`; a file already waiting for the same task and sheets is not queued twice (nor
        an arrival being read). `supersede_arrival`: this Read does all an arrival would (a document read for its data),
        so the file's waiting arrival is dropped. Returns the items added."""
        def edit(items: list[QueueItem]):
            # an arrival waiting or being read covers another arrival of the same file; a person's Read is covered
            # only by one still waiting (one being read fixed its sheets when it started)
            waiting = {(i.sid, i.task, i.sheets) for i in items
                       if i.state == "queued" or (i.state == "reading" and i.task == "arrival")}
            if task == "read" and supersede_arrival:   # a document's Read covers its waiting arrival: read it once
                items = [i for i in items if not (i.task == "arrival" and i.state == "queued"
                                                  and i.sid in {sid for sid, _name in files})]
            number = max((int(i.id[2:]) for i in items), default=0)
            added = []
            for sid, name in dict.fromkeys(files):
                if (sid, task, tuple(sheets)) in waiting:
                    continue
                number += 1
                added.append(QueueItem(id=f"q-{number}", sid=sid, file=name, task=task, sheets=tuple(sheets), added_by=by,
                                       added_at=_now()))
                waiting.add((sid, task, tuple(sheets)))
            return items + added, added
        return self._change(edit)

    def take(self) -> QueueItem | None:
        """The next waiting item, now `reading`; None when nothing waits. Only the holder of the reading job takes."""
        def edit(items: list[QueueItem]):
            for n, item in enumerate(items):
                if item.state == "queued":
                    taken = item.model_copy(update={"state": "reading", "started_at": _now(), "attempts": item.attempts + 1})
                    items[n] = taken
                    return items, taken
            return items, None
        return self._change(edit)

    def finish(self, item_id: str, state: Literal["done", "failed"], *, note: str = "", run_ids: tuple[str, ...] = (),
               found: dict[str, int] | None = None) -> None:
        def edit(items: list[QueueItem]):
            return [i.model_copy(update={"state": state, "finished_at": _now(), "note": note[:500], "run_ids": run_ids,
                                         "found": found or {}}) if i.id == item_id else i for i in items], None
        self._change(edit)

    def recover(self) -> int:
        """Items left `reading` by a worker that stopped (only the job's holder calls this, so none is being read):
        queued again, or failed after `MAX_ATTEMPTS`. Returns how many were put back."""
        def edit(items: list[QueueItem]):
            out, back = [], 0
            for i in items:
                if i.state != "reading":
                    out.append(i)
                elif i.attempts < MAX_ATTEMPTS:
                    out.append(i.model_copy(update={"state": "queued"}))
                    back += 1
                else:
                    out.append(i.model_copy(update={"state": "failed", "finished_at": _now(),
                                                    "note": "the reading stopped twice (the server restarted); read it again"}))
            return out, back
        return self._change(edit) if self._path is not None else 0
