"""The single-node audit trail: hash-chained, append-only JSON lines per tenant (plan §13.4, 21 CFR 11.10(e)).

Same event shape and row hash as the Postgres trail (`modeler_api.compliance.audit`):
row_hash = SHA-256(prev_hash | canonical JSON of the event). Editing or deleting a stored line breaks every later
link, which `verify` reports. Kept here (not imported from the API package) so the project model has no dependency on
the API; a test in the API package pins that both produce identical hashes.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64
_LOCK = threading.Lock()


@dataclass(frozen=True)
class AuditEvent:
    tenant_id: str
    seq: int
    occurred_at: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    before: Any = None
    after: Any = None
    reason: str | None = None
    request_id: str | None = None


def _canonical(event: AuditEvent) -> bytes:
    return json.dumps(asdict(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def row_hash(prev_hash: str, event: AuditEvent) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + b"|" + _canonical(event)).hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    event: AuditEvent
    prev_hash: str
    row_hash: str


class AuditLog:
    """Append-only chain in `<root>/<tenant>/audit.jsonl`."""

    def __init__(self, root: Path, tenant_id: str):
        self.tenant_id = tenant_id
        self.path = root / tenant_id / "audit.jsonl"

    def records(self) -> list[AuditRecord]:
        if not self.path.exists():
            return []
        out: list[AuditRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            out.append(AuditRecord(event=AuditEvent(**row["event"]), prev_hash=row["prev_hash"], row_hash=row["row_hash"]))
        return out

    def append(self, *, actor: str, action: str, resource_type: str, resource_id: str, before: Any = None,
               after: Any = None, reason: str | None = None, request_id: str | None = None) -> AuditRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.seek(0)
                lines = [ln for ln in handle.read().splitlines() if ln.strip()]
                last = json.loads(lines[-1]) if lines else None
                prev = last["row_hash"] if last else GENESIS_HASH
                seq = (last["event"]["seq"] + 1) if last else 1
                event = AuditEvent(
                    tenant_id=self.tenant_id, seq=seq, occurred_at=datetime.now(UTC).isoformat(), actor=actor,
                    action=action, resource_type=resource_type, resource_id=resource_id, before=before, after=after,
                    reason=reason, request_id=request_id,
                )
                record = AuditRecord(event=event, prev_hash=prev, row_hash=row_hash(prev, event))
                handle.seek(0, 2)
                handle.write(json.dumps({"event": asdict(event), "prev_hash": prev, "row_hash": record.row_hash},
                                        ensure_ascii=False, default=str) + "\n")
                handle.flush()
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        return record

    def verify(self) -> int | None:
        """Index of the first broken link, or None when the whole chain verifies."""
        expected = GENESIS_HASH
        for index, record in enumerate(self.records()):
            if record.prev_hash != expected or record.row_hash != row_hash(record.prev_hash, record.event):
                return index
            expected = record.row_hash
        return None
