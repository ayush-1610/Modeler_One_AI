"""Part 11 records in PostgreSQL (production readiness P2; docs/plans/2026-10-15-part11-records-postgres.md).

A production deployment keeps a copy of every audit event and every signature in the database of
deploy/server/postgres.sh, where the API's login cannot change or remove a row (the `reject_mutation` triggers, and
no UPDATE/DELETE/TRUNCATE grant):

- `Part11Store.mirror_audit` is called by the file audit chain (`modeler_project.audit.AuditLog`) inside its lock,
  before a line is written: the record goes in with the file chain's own hashes, after any records the database is
  missing (the history from before the switch, a past outage), so the copy is complete and in order. A database that
  refuses, or that disagrees with the file chain, stops the append, and so the action.
- `Part11Store.record_signature` writes a signature, with its signer upserted into `users` by token subject.
- `verify_all` (``python -m modeler_api.part11 verify``, nightly from postgres.sh) checks every tenant: each file record is in the database
  with the same hashes, and the database chain recomputes. A file chain rewritten after the fact no longer matches.

Records are plain dicts in the file chain's line shape (``{"event": {...}, "prev_hash", "row_hash"}``), so this
module needs nothing above it. Tenants are named in the chain (``"dev"``) and keyed by UUID in the schema; the name
maps through ``tenants.slug`` and the hashes cover the name, exactly as the file chain computed them.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Callable, Coroutine, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from modeler_storage.audit import GENESIS_HASH, AuditEvent, compute_row_hash

AuditLine = dict[str, Any]
"""One record of the file chain: {"event": {...}, "prev_hash": str, "row_hash": str}."""


class Part11Error(RuntimeError):
    """The database refused a Part 11 record, or disagrees with the file chain."""


def asyncpg_dsn(database_url: str) -> str:
    """The asyncpg form of a SQLAlchemy URL (postgresql+asyncpg://… → postgresql://…)."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class _Loop:
    """A private event loop on its own thread, so synchronous callers (the audit chain, sync routes) can use asyncpg
    whether or not a loop is already running in theirs."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="part11-db", daemon=True).start()

    def run(self, coro: Coroutine[Any, Any, Any], timeout: float = 30) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


_INSERT_AUDIT = """
    INSERT INTO audit_events (tenant_id, seq, occurred_at, actor, action, resource_type, resource_id,
                              before, after, reason, request_id, prev_hash, row_hash)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12, $13)
"""


class Part11Store:
    """The production database's Part 11 tables, used by the API's own login (no superuser, no owner)."""

    def __init__(self, database_url: str) -> None:
        self._dsn = asyncpg_dsn(database_url)
        self._loop = _Loop()
        self._pool: Any = None

    # --- connection ------------------------------------------------------------------------------------------

    async def _connection_pool(self) -> Any:
        import asyncpg

        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=0, max_size=4)
        return self._pool

    async def _tenant(self, conn: Any, slug: str) -> uuid.UUID:
        """The tenant's UUID, created on first use; and the transaction scoped to it (row-level security)."""
        await conn.execute("INSERT INTO tenants (slug, tenancy_mode) VALUES ($1, 'onprem-single') ON CONFLICT (slug) DO NOTHING",
                           slug)
        tenant = await conn.fetchval("SELECT id FROM tenants WHERE slug = $1", slug)
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
        return tenant

    def ping(self) -> None:
        """Fails unless the database answers with the Part 11 tables in place (checked when the API starts)."""
        async def go() -> None:
            async with (await self._connection_pool()).acquire() as conn:
                missing = [t for t in ("tenants", "users", "signatures", "audit_events")
                           if await conn.fetchval("SELECT to_regclass($1)", t) is None]
                if missing:
                    raise Part11Error(f"the Part 11 database lacks {', '.join(missing)}: run 'postgres.sh migrate'")
        self._loop.run(go())

    # --- audit ------------------------------------------------------------------------------------------------

    def mirror_audit(self, tenant: str, record: AuditLine, earlier: Callable[[int], list[AuditLine]]) -> None:
        """Copy `record` (and first any earlier records the database lacks, from `earlier(from_seq)`) into
        `audit_events`, in one transaction. Raises Part11Error when the database is ahead of the file chain or its
        last row does not link to `record`: the chain was changed outside the platform."""
        self._loop.run(self._mirror(tenant, record, earlier))

    async def _mirror(self, tenant: str, record: AuditLine, earlier: Callable[[int], list[AuditLine]]) -> None:
        seq = int(record["event"]["seq"])
        async with (await self._connection_pool()).acquire() as conn, conn.transaction():
            tenant_id = await self._tenant(conn, tenant)
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", str(tenant_id))
            head = await conn.fetchrow("SELECT seq, row_hash FROM audit_events WHERE tenant_id = $1 ORDER BY seq DESC LIMIT 1",
                                       tenant_id)
            head_seq, head_hash = (head["seq"], head["row_hash"]) if head else (0, GENESIS_HASH)
            if head_seq >= seq:
                raise Part11Error(f"the database already holds {tenant} audit event {head_seq}, the file chain is at {seq}: "
                                  "the file chain was changed outside the platform")
            missing = earlier(head_seq + 1) if head_seq < seq - 1 else []
            expected = head_hash
            for line in [*missing, record]:
                if line["prev_hash"] != expected:
                    raise Part11Error(f"{tenant} audit event {line['event']['seq']} does not link to the database's "
                                      f"chain (prev {line['prev_hash'][:12]}…, expected {expected[:12]}…)")
                await conn.execute(_INSERT_AUDIT, *_audit_row(tenant_id, line))
                expected = line["row_hash"]

    # --- signatures -------------------------------------------------------------------------------------------

    def record_signature(self, tenant: str, *, signature_id: str, signer_subject: str, printed_name: str, meaning: str,
                         signed_at: datetime, record_type: str, record_id: str, record_sha256: str, auth_method: str) -> None:
        """One signature row (its signer upserted into `users` by token subject); a signature is recorded once."""
        async def go() -> None:
            async with (await self._connection_pool()).acquire() as conn, conn.transaction():
                tenant_id = await self._tenant(conn, tenant)
                signer = await conn.fetchval(
                    """INSERT INTO users (tenant_id, oidc_subject, printed_name) VALUES ($1, $2, $3)
                       ON CONFLICT (tenant_id, oidc_subject) DO UPDATE SET printed_name = EXCLUDED.printed_name
                       RETURNING id""", tenant_id, signer_subject, printed_name)
                await conn.execute(
                    """INSERT INTO signatures (id, tenant_id, signer_id, printed_name, meaning, signed_at, record_type,
                                               record_id, record_sha256, auth_method)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                    uuid.UUID(signature_id), tenant_id, signer, printed_name, meaning, signed_at, record_type, record_id,
                    record_sha256, auth_method)
        self._loop.run(go())

    # --- verification -----------------------------------------------------------------------------------------

    def audit_rows(self, tenant: str) -> list[AuditLine]:
        """The tenant's chain as the database holds it, in the file chain's line shape."""
        async def go() -> list[AuditLine]:
            async with (await self._connection_pool()).acquire() as conn, conn.transaction():
                tenant_id = await self._tenant(conn, tenant)
                rows = await conn.fetch("SELECT * FROM audit_events WHERE tenant_id = $1 ORDER BY seq", tenant_id)
            return [_line(tenant, row) for row in rows]
        return self._loop.run(go())

    def verify(self, tenant: str, file_lines: Iterable[AuditLine]) -> list[str]:
        """Problems with the tenant's Part 11 copy: none when the database chain recomputes and holds every file
        record with the same hashes."""
        rows, problems, expected = self.audit_rows(tenant), [], GENESIS_HASH
        for row in rows:
            event = AuditEvent(**row["event"])
            if row["prev_hash"] != expected or row["row_hash"] != compute_row_hash(row["prev_hash"], event):
                problems.append(f"{tenant}: database audit event {event.seq} does not recompute")
                break
            expected = row["row_hash"]
        by_seq = {row["event"]["seq"]: row for row in rows}
        for line in file_lines:
            seq = line["event"]["seq"]
            held = by_seq.get(seq)
            if held is None:
                problems.append(f"{tenant}: file audit event {seq} is not in the database")
            elif held["row_hash"] != line["row_hash"] or held["event"] != _normal(line["event"]):
                problems.append(f"{tenant}: file audit event {seq} differs from the database's copy")
        return problems


def _audit_row(tenant_id: uuid.UUID, line: AuditLine) -> tuple[Any, ...]:
    event = line["event"]
    return (tenant_id, int(event["seq"]), datetime.fromisoformat(event["occurred_at"]), event["actor"], event["action"],
            event["resource_type"], event["resource_id"], _json(event.get("before")), _json(event.get("after")),
            event.get("reason"), event.get("request_id"), line["prev_hash"], line["row_hash"])


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def _normal(event: dict[str, Any]) -> dict[str, Any]:
    """An event as JSON round-trips it (what the database's jsonb gives back)."""
    return json.loads(json.dumps(event, ensure_ascii=False, default=str))


def _line(tenant: str, row: Any) -> AuditLine:
    event = {"tenant_id": tenant, "seq": row["seq"], "occurred_at": row["occurred_at"].isoformat(), "actor": row["actor"],
             "action": row["action"], "resource_type": row["resource_type"], "resource_id": row["resource_id"],
             "before": json.loads(row["before"]) if row["before"] is not None else None,
             "after": json.loads(row["after"]) if row["after"] is not None else None,
             "reason": row["reason"], "request_id": row["request_id"]}
    return {"event": event, "prev_hash": row["prev_hash"].strip(), "row_hash": row["row_hash"].strip()}


def read_file_chain(path: Path) -> list[AuditLine]:
    """A tenant's file chain (`<read_root>/<tenant>/audit.jsonl`), line by line."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_all(read_root: Path, database_url: str) -> tuple[int, list[str]]:
    """Every tenant's Part 11 copy against its file chain: (tenants checked, problems)."""
    store = Part11Store(database_url)
    tenants = sorted(p.parent.name for p in read_root.glob("*/audit.jsonl"))
    problems = [problem for tenant in tenants for problem in store.verify(tenant, read_file_chain(read_root / tenant / "audit.jsonl"))]
    return len(tenants), problems
