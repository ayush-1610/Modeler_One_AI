"""The campaign store persists and resumes campaign progress via CampaignRepository (T-13 <-> T-05 wiring).

Requires Docker; skipped otherwise. Applies the real migrations and runs as a non-superuser so RLS,
append-only triggers and the audit chain all apply, then checks a campaign's rounds are recorded and that
a re-started campaign resumes past the stage it already finished.
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
except ImportError:  # pragma: no cover
    _HAVE_DEPS = False

from modeler_contracts.runs import (
    ActionChoice,
    CampaignRequest,
    RoundContext,
    RoundEvaluation,
    RoundRecord,
    RoundRunResult,
)

MIGRATIONS = Path(__file__).parents[2] / "api" / "migrations"
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64


async def _setup(host: str, port: str) -> None:
    admin = await asyncpg.connect(host=host, port=int(port), user="test", password="test", database="test")
    try:
        for name in ("0001_core.sql", "0002_campaigns.sql"):
            await admin.execute((MIGRATIONS / name).read_text())
        await admin.execute("DROP ROLE IF EXISTS modeler")
        await admin.execute("CREATE ROLE modeler LOGIN PASSWORD 'modeler' NOSUPERUSER")
        await admin.execute("GRANT USAGE ON SCHEMA public TO modeler")
        await admin.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO modeler")
        await admin.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO modeler")
        row = await admin.fetchrow("INSERT INTO tenants (slug, tenancy_mode) VALUES ('t', 'saas-pooled') RETURNING id")
    finally:
        await admin.close()
    return str(row["id"])


@pytest.fixture(scope="module")
def pg():
    if not _HAVE_DEPS:
        pytest.skip("docker/testcontainers not available")
    try:
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cannot start Postgres container: {exc}")
    host, port = container.get_container_host_ip(), container.get_exposed_port(5432)
    try:
        tenant_id = asyncio.run(_setup(host, port))
        yield f"postgresql+asyncpg://modeler:modeler@{host}:{port}/test", tenant_id
    finally:
        container.stop()


def _request(url_tenant, campaign_id="camp1") -> CampaignRequest:
    _, tenant_id = url_tenant
    return CampaignRequest(
        campaign_id=campaign_id, tenant_id=tenant_id, compound="Example-A", map_id="map1",
        cpf_uri="file:///tmp/cpf.json", cpf_sha256=SHA_A, stages=["S0", "S1", "S2"],
        stage_budgets_seconds={"S1": 1800, "S2": 1800}, seed=1,
    )


def _round_record(tenant_id, campaign_id, stage, round_index, *, before, after, passed) -> RoundRecord:
    ctx = RoundContext(
        campaign_id=campaign_id, tenant_id=tenant_id, stage=stage, round_index=round_index,
        cpf_uri="file:///tmp/cpf.json", cpf_sha256=before, pending_action=None,
    )
    return RoundRecord(
        context=ctx,
        run_result=RoundRunResult(results_uri="r", cpf_uri="file:///tmp/cpf.json", cpf_sha256=after),
        evaluation=RoundEvaluation(gate_passed=passed, acceptable=passed, metrics={"gmfe": 1.2}, findings=[]),
        choice=ActionChoice(action_id="fit_clspec", rationale="x"),
    )


def run(coro):
    return asyncio.run(coro)


def test_campaign_progress_is_recorded_and_resumable(pg):
    from modeler_orchestrator.campaign_store import CampaignStore

    url, tenant_id = pg

    async def scenario():
        store = CampaignStore(url)
        try:
            request = _request(pg, "camp-resume")
            # first resume creates the campaign; nothing completed yet
            first = await store.resume(request)
            assert first.last_completed_stage is None

            # two S1 rounds: fail then pass -> stage PASSED
            await store.record_round(_round_record(tenant_id, "camp-resume", "S1", 1, before=SHA_A, after=SHA_B, passed=False))
            await store.record_round(_round_record(tenant_id, "camp-resume", "S1", 2, before=SHA_B, after=SHA_C, passed=True))

            # a re-started campaign resumes past S1
            second = await store.resume(request)
            assert second.last_completed_stage == "S1"
        finally:
            await store.dispose()

    run(scenario())


def test_rounds_and_audit_rows_written(pg):
    from sqlalchemy import text

    from modeler_orchestrator.campaign_store import CampaignStore

    url, tenant_id = pg

    async def scenario():
        store = CampaignStore(url)
        try:
            await store.resume(_request(pg, "camp-rows"))
            await store.record_round(_round_record(tenant_id, "camp-rows", "S1", 1, before=SHA_A, after=SHA_B, passed=True))
            async with store._db.tenant_session(uuid.UUID(tenant_id)) as session:
                rounds = (await session.execute(text(
                    "SELECT count(*) FROM campaign_rounds cr JOIN campaigns c ON c.id = (SELECT campaign_id FROM campaign_stages WHERE id = cr.stage_id) "
                    "WHERE c.campaign_ref = 'camp-rows'"
                ))).scalar_one()
                audits = (await session.execute(text(
                    "SELECT count(*) FROM audit_events WHERE action IN ('campaign.created','stage.created','round.recorded')"
                ))).scalar_one()
            assert rounds == 1
            assert audits >= 3
        finally:
            await store.dispose()

    run(scenario())
