"""Integration tests for the persistence layer against a real Postgres 16 (task T-05).

Requires Docker; skipped if it is unavailable. A superuser applies the migrations and grants a
non-superuser `modeler` role (RLS does not apply to superusers), and the repositories run as that role so
row-level security, the append-only triggers and the audit chain are all exercised as in production.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

try:
    import asyncpg
    from testcontainers.postgres import PostgresContainer

    _HAVE_DEPS = True
except ImportError:  # pragma: no cover - environment without docker/testcontainers
    _HAVE_DEPS = False

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modeler_api.compliance.audit import GENESIS_HASH
from modeler_api.db.models import Campaign
from modeler_api.db.repositories import CampaignRepository
from modeler_api.db.session import Database

MIGRATIONS = Path(__file__).parents[1] / "migrations"


async def _setup(host: str, port: str) -> None:
    admin = await asyncpg.connect(host=host, port=int(port), user="test", password="test", database="test")
    try:
        for name in ("0001_core.sql", "0002_campaigns.sql", "0003_agents.sql"):
            await admin.execute((MIGRATIONS / name).read_text())
        await admin.execute("DROP ROLE IF EXISTS modeler")
        await admin.execute("CREATE ROLE modeler LOGIN PASSWORD 'modeler' NOSUPERUSER")
        await admin.execute("GRANT USAGE ON SCHEMA public TO modeler")
        await admin.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO modeler")
        await admin.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO modeler")
    finally:
        await admin.close()


async def _seed_tenants(db: Database) -> tuple[uuid.UUID, uuid.UUID]:
    # tenants has no RLS; create two with unique slugs (the container persists across tests).
    suffix = uuid.uuid4().hex[:8]
    ids = []
    for name in ("a", "b"):
        async with db.tenant_session(uuid.uuid4()) as session:
            result = await session.execute(
                text("INSERT INTO tenants (slug, tenancy_mode) VALUES (:s, 'saas-pooled') RETURNING id"),
                {"s": f"tenant-{name}-{suffix}"},
            )
            ids.append(result.scalar_one())
    return ids[0], ids[1]


@pytest.fixture(scope="module")
def pg():
    if not _HAVE_DEPS:
        pytest.skip("docker/testcontainers not available")
    try:
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:  # noqa: BLE001 - docker may be missing/unhealthy; skip rather than fail
        pytest.skip(f"cannot start Postgres container: {exc}")
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    try:
        asyncio.run(_setup(host, port))
        yield f"postgresql+asyncpg://modeler:modeler@{host}:{port}/test"
    finally:
        container.stop()


def run(coro):
    return asyncio.run(coro)


def test_migrations_apply_and_tables_exist(pg):
    async def scenario():
        db = Database(pg)
        try:
            async with db.tenant_session(uuid.uuid4()) as session:
                rows = await session.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
                ))
                names = {r[0] for r in rows}
            assert {"campaigns", "campaign_stages", "campaign_rounds", "escalations", "deviations", "audit_events"} <= names
            assert {"agent_runs", "agent_steps", "proposals"} <= names  # T-20
        finally:
            await db.dispose()
    run(scenario())


def test_rls_isolates_two_tenants(pg):
    async def scenario():
        db = Database(pg)
        try:
            tenant_a, tenant_b = await _seed_tenants(db)
            async with db.tenant_session(tenant_a) as session:
                repo = CampaignRepository(session, tenant_a, actor="user:a")
                await repo.create_campaign(campaign_ref="camp-a", compound_name="A", cpf_start_sha256="a" * 64)
            # tenant B cannot see tenant A's campaign
            async with db.tenant_session(tenant_b) as session:
                repo = CampaignRepository(session, tenant_b, actor="user:b")
                assert await repo.get_campaign("camp-a") is None
            # tenant A sees its own
            async with db.tenant_session(tenant_a) as session:
                repo = CampaignRepository(session, tenant_a, actor="user:a")
                assert (await repo.get_campaign("camp-a")) is not None
        finally:
            await db.dispose()
    run(scenario())


def test_rls_check_blocks_cross_tenant_write(pg):
    async def scenario():
        db = Database(pg)
        try:
            tenant_a, tenant_b = await _seed_tenants(db)
            # bound to tenant B, try to insert a row owned by tenant A -> RLS WITH CHECK rejects
            with pytest.raises(DBAPIError):
                async with db.tenant_session(tenant_b) as session:
                    session.add(Campaign(
                        tenant_id=tenant_a, campaign_ref="x", compound_name="X", cpf_start_sha256="a" * 64,
                        budget_seconds=3600, seed=1, status="RUNNING",
                    ))
                    await session.flush()
        finally:
            await db.dispose()
    run(scenario())


def test_campaign_round_trip_and_audit(pg):
    async def scenario():
        db = Database(pg)
        try:
            tenant_a, _ = await _seed_tenants(db)
            async with db.tenant_session(tenant_a) as session:
                repo = CampaignRepository(session, tenant_a, actor="user:a")
                campaign = await repo.create_campaign(campaign_ref="camp-rt", compound_name="Ex", cpf_start_sha256="a" * 64)
                stage = await repo.create_stage(campaign, stage="S1", budget_seconds=1800, max_rounds=4)
                await repo.append_round(stage, round_index=1, cpf_before_sha256="a" * 64, cpf_after_sha256="b" * 64, verdict="FAIL")
                await repo.append_round(stage, round_index=2, cpf_before_sha256="b" * 64, cpf_after_sha256="c" * 64, verdict="PASS")
                await repo.set_stage_status(stage, "PASSED", finished=True)
                await repo.set_campaign_status(campaign, "COMPLETED", current_stage="S1", final_cpf_sha256="c" * 64, finished=True)
                esc = await repo.open_escalation(campaign, reason_code="rounds_exhausted")
                await repo.decide_escalation(esc, decision={"action": "accept_best"})
                await repo.append_deviation(campaign, kind="fed_prediction", rationale="no fed study; predicted")
            # everything committed; verify rows and that the audit chain is linked correctly
            async with db.tenant_session(tenant_a) as session:
                rounds = (await session.execute(text("SELECT count(*) FROM campaign_rounds"))).scalar_one()
                assert rounds == 2
                events = (await session.execute(text(
                    "SELECT seq, prev_hash, row_hash, action FROM audit_events ORDER BY seq"
                ))).all()
            # campaign+stage+2 rounds+stage status+campaign status+escalation open/decide+deviation
            assert len(events) >= 8
            assert {e.action for e in events} >= {"campaign.created", "stage.created", "round.recorded",
                                                  "escalation.decided", "deviation.recorded"}
            expected_prev = GENESIS_HASH
            for e in events:
                assert e.prev_hash == expected_prev
                expected_prev = e.row_hash
        finally:
            await db.dispose()
    run(scenario())


def test_campaign_rounds_are_append_only(pg):
    async def scenario():
        db = Database(pg)
        try:
            tenant_a, _ = await _seed_tenants(db)
            async with db.tenant_session(tenant_a) as session:
                repo = CampaignRepository(session, tenant_a, actor="user:a")
                campaign = await repo.create_campaign(campaign_ref="camp-ao", compound_name="Ex", cpf_start_sha256="a" * 64)
                stage = await repo.create_stage(campaign, stage="S1", budget_seconds=1800, max_rounds=4)
                await repo.append_round(stage, round_index=1, cpf_before_sha256="a" * 64, cpf_after_sha256="b" * 64, verdict="FAIL")
            with pytest.raises(DBAPIError, match="append-only"):
                async with db.tenant_session(tenant_a) as session:
                    await session.execute(text("UPDATE campaign_rounds SET verdict='PASS'"))
        finally:
            await db.dispose()
    run(scenario())
