"""Hash-chained, append-only audit trail (21 CFR 11.10(e); feature F-404).

Each tenant has its own chain: row_hash = SHA-256(prev_hash | canonical JSON of the event).
Editing or deleting any stored event breaks every later link, which ``verify_chain`` reports.
The database additionally rejects UPDATE/DELETE/TRUNCATE on ``audit_events``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditEvent:
    tenant_id: str
    seq: int
    occurred_at: str  # ISO 8601 UTC, taken from the NTP-synchronized application clock
    actor: str
    action: str
    resource_type: str
    resource_id: str
    before: Any = None
    after: Any = None
    reason: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class ChainedEvent:
    event: AuditEvent
    prev_hash: str
    row_hash: str = field(default="")


def canonical_event_bytes(event: AuditEvent | Mapping[str, Any]) -> bytes:
    payload = asdict(event) if isinstance(event, AuditEvent) else dict(event)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def compute_row_hash(prev_hash: str, event: AuditEvent) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + b"|" + canonical_event_bytes(event)).hexdigest()


def chain(prev_hash: str, event: AuditEvent) -> ChainedEvent:
    return ChainedEvent(event=event, prev_hash=prev_hash, row_hash=compute_row_hash(prev_hash, event))


def verify_chain(events: Sequence[ChainedEvent]) -> int | None:
    """Return the index of the first invalid link, or None if the whole chain verifies."""
    expected_prev = GENESIS_HASH
    for index, item in enumerate(events):
        if item.prev_hash != expected_prev or item.row_hash != compute_row_hash(item.prev_hash, item.event):
            return index
        expected_prev = item.row_hash
    return None


_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))")
_HEAD_SQL = text("SELECT seq, row_hash FROM audit_events WHERE tenant_id = :tenant_id ORDER BY seq DESC LIMIT 1")
_INSERT_SQL = text(
    """
    INSERT INTO audit_events
      (tenant_id, seq, occurred_at, actor, action, resource_type, resource_id,
       before, after, reason, request_id, prev_hash, row_hash)
    VALUES
      (:tenant_id, :seq, :occurred_at, :actor, :action, :resource_type, :resource_id,
       CAST(:before AS jsonb), CAST(:after AS jsonb), :reason, :request_id, :prev_hash, :row_hash)
    """
)


async def append_audit_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    before: Any = None,
    after: Any = None,
    reason: str | None = None,
    request_id: str | None = None,
) -> ChainedEvent:
    """Append one event inside the caller's transaction so it commits atomically with the change it records."""
    params = {"tenant_id": str(tenant_id)}
    await session.execute(_LOCK_SQL, params)
    head = (await session.execute(_HEAD_SQL, params)).first()
    seq, prev_hash = (head.seq + 1, head.row_hash) if head else (1, GENESIS_HASH)

    event = AuditEvent(
        tenant_id=str(tenant_id),
        seq=seq,
        occurred_at=datetime.now(UTC).isoformat(),
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=before,
        after=after,
        reason=reason,
        request_id=request_id,
    )
    chained = chain(prev_hash, event)
    await session.execute(
        _INSERT_SQL,
        {
            **asdict(event),
            "before": json.dumps(before, default=str),
            "after": json.dumps(after, default=str),
            "prev_hash": chained.prev_hash,
            "row_hash": chained.row_hash,
        },
    )
    return chained
