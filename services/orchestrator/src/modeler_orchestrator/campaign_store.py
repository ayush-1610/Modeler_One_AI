"""Durable campaign state for the campaign activities (wires T-13 to T-05 persistence).

`resume_campaign` and `record_round` use this to read and write the campaign's progress through the
`CampaignRepository`, so a campaign survives a worker restart (Temporal replays the workflow; the DB
holds which stages and rounds already ran) and every round is an append-only, audited record. When no
database is configured (``MODELER_DATABASE_URL`` unset) the activities keep their in-memory fallback, so
unit tests and local runs work without Postgres.
"""

from __future__ import annotations

import dataclasses
import os
import uuid

from modeler_api.db.repositories import CampaignRepository
from modeler_api.db.session import Database
from modeler_contracts.runs import CAMPAIGN_STAGES, CampaignRequest, ResumeState, RoundRecord


class CampaignStore:
    def __init__(self, database_url: str):
        self._db = Database(database_url)

    @classmethod
    def from_env(cls) -> CampaignStore | None:
        url = os.environ.get("MODELER_DATABASE_URL")
        return cls(url) if url else None

    async def dispose(self) -> None:
        await self._db.dispose()

    async def resume(self, request: CampaignRequest) -> ResumeState:
        tenant = uuid.UUID(request.tenant_id)
        async with self._db.tenant_session(tenant) as session:
            repo = CampaignRepository(session, tenant, actor=f"campaign:{request.campaign_id}")
            campaign = await repo.get_campaign(request.campaign_id)
            if campaign is None:
                await repo.create_campaign(
                    campaign_ref=request.campaign_id, compound_name=request.compound,
                    cpf_start_sha256=request.cpf_sha256, budget_seconds=_total_budget(request),
                    seed=request.seed, map_id=request.map_id,
                )
                return ResumeState(last_completed_stage=None, cpf_uri=request.cpf_uri, cpf_sha256=request.cpf_sha256)
            completed = set(await repo.completed_stages(campaign))
            last = None
            for stage in CAMPAIGN_STAGES:
                if stage in completed and stage in request.stages:
                    last = stage
            return ResumeState(
                last_completed_stage=last, cpf_uri=request.cpf_uri,
                cpf_sha256=campaign.final_cpf_sha256 or request.cpf_sha256,
            )

    async def record_round(self, record: RoundRecord) -> None:
        ctx = record.context
        tenant = uuid.UUID(ctx.tenant_id)
        async with self._db.tenant_session(tenant) as session:
            repo = CampaignRepository(session, tenant, actor=f"campaign:{ctx.campaign_id}")
            campaign = await repo.get_campaign(ctx.campaign_id)
            if campaign is None:
                campaign = await repo.create_campaign(
                    campaign_ref=ctx.campaign_id, compound_name=ctx.campaign_id, cpf_start_sha256=ctx.cpf_sha256,
                )
            stage = await repo.get_stage(campaign, ctx.stage)
            if stage is None:
                stage = await repo.create_stage(campaign, stage=ctx.stage, budget_seconds=0, max_rounds=0)
            action = dataclasses.asdict(record.choice) if record.choice is not None else None
            await repo.append_round(
                stage, round_index=ctx.round_index, cpf_before_sha256=ctx.cpf_sha256,
                cpf_after_sha256=record.run_result.cpf_sha256,
                verdict="PASS" if record.evaluation.gate_passed else "FAIL",
                action=action, metrics=record.evaluation.metrics,
            )
            if record.evaluation.gate_passed:
                await repo.set_stage_status(stage, "PASSED", finished=True)


def _total_budget(request: CampaignRequest) -> int:
    return sum(request.stage_budgets_seconds.values()) or 3600
