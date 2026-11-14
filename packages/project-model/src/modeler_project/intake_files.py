"""Every client file that arrives, and the delivery it arrives in (contracts §5, §6.5; build W; plan G2, decision F).

One hash-chained log, `intake/files.jsonl` (`IntakeStore.files`), three kinds of line:
- `delivery` (`{"id": "dl-<seq>", "by", "at"}`): one per arrival request (an upload, the project's start, a library
  document read for data, a sweep of the files stored before the pipeline ran);
- `file` (`FileRecord`): one per file of a delivery, written AFTER its bytes are in the project store (`put_blob`), so a
  line never names bytes the store does not hold. The same bytes arriving in a later delivery get a line of their own
  marked `repeat`; the same bytes twice in one delivery (and the same container) are one line;
- `legacy` (`{"file_id", "sid", "refusal"}`): what today's reader (`client_data.ingest`) did with the file: the client
  file it became, or why it refused it. `files()` folds it into the file's latest record before it.

A file is recorded whatever today's reader makes of it: an unsupported or unreadable file is stored and recorded before
it is refused (decision F), so the pipeline's run states why it read nothing. Nothing here parses a file.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from modeler_intake.anchors import check_id
from modeler_intake.source_model import ContainerRef
from modeler_project.intake_records import FileRecord
from modeler_project.intake_store import ChainEntry, IntakeStore
from modeler_project.workspace import Workspace


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def file_id_of(sha256: str) -> str:
    """A file's id: "fl-" + the first 12 characters of its sha256 (the same bytes are one file, however often they
    arrive)."""
    return check_id("file", "fl-" + check_id("sha256", sha256)[:12])


def _store(ws: Workspace) -> IntakeStore:
    store = IntakeStore(ws)
    if not store.available:
        raise RuntimeError("the project store has no file root: the intake pipeline is off")
    return store


def _delivery_line(by: str) -> Any:
    def body(seq: int) -> dict[str, Any]:
        return {"id": f"dl-{seq}", "by": by, "at": _now()}
    return body


def open_delivery(ws: Workspace, *, by: str) -> str:
    """A new delivery (one per arrival request): its id, "dl-<seq>"."""
    entry = _store(ws).files.append("delivery", _delivery_line(by))
    return str(entry.body["id"])


def record_arrival(ws: Workspace, data: bytes, filename: str, *, delivery: str, by: str,
                   container: ContainerRef | None = None) -> FileRecord:
    """Store the bytes (`put_blob`), then write the file's line in `delivery` (decided under the log's lock). The same
    bytes arrived before, in another delivery: a `repeat` line; already recorded in this delivery from the same
    container: that record, nothing written. KeyError for a delivery that was never opened."""
    store = _store(ws)
    check_id("line", delivery)
    sha = hashlib.sha256(data).hexdigest()
    stored = ws.store.put_blob(ws.tenant_id, ws.project_id, data)
    if stored != sha or ws.store.blob_path(ws.tenant_id, ws.project_id, sha) is None:
        raise RuntimeError(f"{filename}: the project store did not keep the file's bytes")
    record = FileRecord(file_id=file_id_of(sha), sha256=sha, name=filename, size_bytes=len(data), delivery=delivery,
                        container=container, by=by, at=_now())
    found: list[FileRecord] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        if not any(e.kind == "delivery" and e.body.get("id") == delivery for e in entries):
            raise KeyError(f"no delivery {delivery} in the project's files log")
        seen = [FileRecord.model_validate(e.body) for e in entries if e.kind == "file" and e.body.get("sha256") == sha]
        same = next((r for r in seen if r.delivery == delivery and r.container == container), None)
        if same is not None:
            found.append(same)
            return []
        new = record.model_copy(update={"repeat": bool(seen)})
        found.append(new)
        return [("file", new.model_dump(mode="json"))]

    store.files.append_if(decide)
    return found[0]


def record_stored(ws: Workspace, items: Sequence[tuple[str, str]], *, by: str) -> list[FileRecord]:
    """Files already in the project store (sha256, name) that `files.jsonl` does not name yet, recorded under one new
    delivery in one decision (a sweep: the files stored before the pipeline ran). Returns the record of each item
    whose bytes the store holds: the new one, or the one another writer recorded first. Nothing (no delivery either)
    when every item is recorded already or none has its bytes."""
    store = _store(ws)
    sizes: dict[str, tuple[str, int]] = {}
    for sha, name in items:
        path = ws.store.blob_path(ws.tenant_id, ws.project_id, check_id("sha256", sha))
        if path is not None and sha not in sizes:
            sizes[sha] = (name, path.stat().st_size)
    found: dict[str, FileRecord] = {}

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        for e in entries:
            if e.kind == "file" and e.body.get("sha256") in sizes:
                found[str(e.body["sha256"])] = FileRecord.model_validate(e.body)
        todo = [sha for sha in sizes if sha not in found]
        if not todo:
            return []
        delivery = f"dl-{(entries[-1].seq if entries else 0) + 1}"
        rows: list[tuple[str, Any]] = [("delivery", {"id": delivery, "by": by, "at": _now()})]
        for sha in todo:
            name, size = sizes[sha]
            record = FileRecord(file_id=file_id_of(sha), sha256=sha, name=name, size_bytes=size, delivery=delivery, by=by,
                                at=_now())
            found[sha] = record
            rows.append(("file", record.model_dump(mode="json")))
        return rows

    store.files.append_if(decide)
    return [found[sha] for sha in sizes if sha in found]


def note_legacy(ws: Workspace, file_id: str, *, sid: str | None, refusal: str | None) -> None:
    """What today's reader did with a recorded file: the client file it became (`sid`), or why it refused it."""
    check_id("file", file_id)
    _store(ws).files.append("legacy", {"file_id": file_id, "sid": sid, "refusal": refusal})


def files(ws: Workspace) -> list[FileRecord]:
    """Every file line, in arrival order, each with what today's reader did with it (the latest `legacy` line that
    follows it). [] when the store has no file root."""
    store = IntakeStore(ws)
    out: list[FileRecord] = []
    latest: dict[str, int] = {}
    for entry in store.files.entries():
        if entry.kind == "file":
            record = FileRecord.model_validate(entry.body)
            latest[record.file_id] = len(out)
            out.append(record)
        elif entry.kind == "legacy" and (i := latest.get(str(entry.body.get("file_id")))) is not None:
            out[i] = out[i].model_copy(update={"legacy_sid": entry.body.get("sid"), "legacy_refusal": entry.body.get("refusal")})
    return out


def deliveries(ws: Workspace) -> list[dict[str, Any]]:
    """Every delivery line's body ({"id", "by", "at"}), in order."""
    return [dict(e.body) for e in IntakeStore(ws).files.entries("delivery")]


def file_record(ws: Workspace, sha256: str, *, delivery: str | None = None) -> FileRecord | None:
    """The record of a file (by its sha256) in a delivery, else its latest record; None when it was never recorded."""
    mine = [r for r in files(ws) if r.sha256 == sha256]
    return next((r for r in reversed(mine) if r.delivery == delivery), None) or (mine[-1] if mine else None)
