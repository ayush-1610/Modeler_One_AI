"""Repositories for the campaign tables. Every write records an audit event in the same transaction.

A repository is bound to one already-tenant-scoped session plus the acting actor. Reads and writes are
therefore isolated to that tenant by row-level security, and no change is committed without its audit row.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modeler_api.compliance.audit import append_audit_event
from modeler_api.db.models import Campaign, CampaignRound, CampaignStage, Deviation, Escalation


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class CampaignRepository:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, actor: str):
        self.session = session
        self.tenant_id = tenant_id
        self.actor = actor

    async def _audit(self, action: str, resource_type: str, resource_id: uuid.UUID,
                     before: Any, after: Any) -> None:
        await append_audit_event(
            self.session, tenant_id=self.tenant_id, actor=self.actor, action=action,
            resource_type=resource_type, resource_id=str(resource_id), before=before, after=after,
        )

    # --- campaigns -------------------------------------------------------------------------------

    async def create_campaign(self, *, campaign_ref: str, compound_name: str, cpf_start_sha256: str,
                              budget_seconds: int = 3600, seed: int = 1, map_id: str | None = None,
                              current_stage: str | None = "S0", engine_image_id: uuid.UUID | None = None,
                              question_id: uuid.UUID | None = None) -> Campaign:
        campaign = Campaign(
            tenant_id=self.tenant_id, campaign_ref=campaign_ref, compound_name=compound_name,
            cpf_start_sha256=cpf_start_sha256, budget_seconds=budget_seconds, seed=seed, map_id=map_id,
            current_stage=current_stage, engine_image_id=engine_image_id, question_id=question_id, status="RUNNING",
        )
        self.session.add(campaign)
        await self.session.flush()
        await self._audit("campaign.created", "campaign", campaign.id, None,
                          {"campaign_ref": campaign_ref, "compound": compound_name, "cpf": cpf_start_sha256})
        return campaign

    async def get_campaign(self, campaign_ref: str) -> Campaign | None:
        result = await self.session.execute(
            select(Campaign).where(Campaign.tenant_id == self.tenant_id, Campaign.campaign_ref == campaign_ref)
        )
        return result.scalar_one_or_none()

    async def set_campaign_status(self, campaign: Campaign, status: str, *, current_stage: str | None = None,
                                  final_cpf_sha256: str | None = None, finished: bool = False) -> None:
        before = {"status": campaign.status, "current_stage": campaign.current_stage}
        campaign.status = status
        if current_stage is not None:
            campaign.current_stage = current_stage
        if final_cpf_sha256 is not None:
            campaign.final_cpf_sha256 = final_cpf_sha256
        if finished:
            campaign.finished_at = _utcnow()
        await self.session.flush()
        await self._audit("campaign.status", "campaign", campaign.id, before,
                          {"status": status, "current_stage": campaign.current_stage})

    # --- stages ----------------------------------------------------------------------------------

    async def get_stage(self, campaign: Campaign, stage: str) -> CampaignStage | None:
        result = await self.session.execute(
            select(CampaignStage).where(
                CampaignStage.tenant_id == self.tenant_id,
                CampaignStage.campaign_id == campaign.id,
                CampaignStage.stage == stage,
            )
        )
        return result.scalar_one_or_none()

    async def completed_stages(self, campaign: Campaign) -> list[str]:
        result = await self.session.execute(
            select(CampaignStage.stage).where(
                CampaignStage.tenant_id == self.tenant_id,
                CampaignStage.campaign_id == campaign.id,
                CampaignStage.status.in_(("PASSED", "ACCEPTED")),
            )
        )
        return [row[0] for row in result.all()]

    async def create_stage(self, campaign: Campaign, *, stage: str, budget_seconds: int, max_rounds: int) -> CampaignStage:
        row = CampaignStage(
            tenant_id=self.tenant_id, campaign_id=campaign.id, stage=stage, status="RUNNING",
            budget_seconds=budget_seconds, max_rounds=max_rounds,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit("stage.created", "campaign_stage", row.id, None, {"stage": stage})
        return row

    async def set_stage_status(self, stage: CampaignStage, status: str, *, summary: dict[str, Any] | None = None,
                               finished: bool = False) -> None:
        before = {"status": stage.status}
        stage.status = status
        if summary is not None:
            stage.summary = summary
        if finished:
            stage.finished_at = _utcnow()
        await self.session.flush()
        await self._audit("stage.status", "campaign_stage", stage.id, before, {"status": status})

    # --- rounds (append-only) --------------------------------------------------------------------

    async def append_round(self, stage: CampaignStage, *, round_index: int, cpf_before_sha256: str,
                           cpf_after_sha256: str, verdict: str, action: dict[str, Any] | None = None,
                           diagnostics: dict[str, Any] | None = None, metrics: dict[str, Any] | None = None,
                           model_version_id: uuid.UUID | None = None) -> CampaignRound:
        row = CampaignRound(
            tenant_id=self.tenant_id, stage_id=stage.id, round=round_index,
            cpf_before_sha256=cpf_before_sha256, cpf_after_sha256=cpf_after_sha256, verdict=verdict,
            action=action, diagnostics=diagnostics, metrics=metrics or {}, model_version_id=model_version_id,
            finished_at=_utcnow(),
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit("round.recorded", "campaign_round", row.id, None,
                          {"stage_id": str(stage.id), "round": round_index, "verdict": verdict})
        return row

    async def rounds_for_stage(self, stage: CampaignStage) -> list[CampaignRound]:
        result = await self.session.execute(
            select(CampaignRound).where(CampaignRound.tenant_id == self.tenant_id, CampaignRound.stage_id == stage.id)
            .order_by(CampaignRound.round)
        )
        return list(result.scalars())

    # --- escalations -----------------------------------------------------------------------------

    async def open_escalation(self, campaign: Campaign, *, reason_code: str, stage_id: uuid.UUID | None = None,
                              round_id: uuid.UUID | None = None, evidence: dict[str, Any] | None = None,
                              options: dict[str, Any] | None = None) -> Escalation:
        row = Escalation(
            tenant_id=self.tenant_id, campaign_id=campaign.id, stage_id=stage_id, round_id=round_id,
            reason_code=reason_code, evidence=evidence, options=options,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit("escalation.opened", "escalation", row.id, None, {"reason_code": reason_code})
        return row

    async def decide_escalation(self, escalation: Escalation, *, decision: dict[str, Any],
                                decided_by: uuid.UUID | None = None) -> None:
        before = {"decision": escalation.decision}
        escalation.decision = decision
        escalation.decided_by = decided_by
        escalation.decided_at = _utcnow()
        await self.session.flush()
        await self._audit("escalation.decided", "escalation", escalation.id, before, {"decision": decision})

    # --- deviations (append-only) ----------------------------------------------------------------

    async def append_deviation(self, campaign: Campaign, *, kind: str, rationale: str, map_id: str | None = None,
                               decided_by: uuid.UUID | None = None, signature_id: uuid.UUID | None = None) -> Deviation:
        row = Deviation(
            tenant_id=self.tenant_id, campaign_id=campaign.id, kind=kind, rationale=rationale, map_id=map_id,
            decided_by=decided_by, signature_id=signature_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit("deviation.recorded", "deviation", row.id, None, {"kind": kind})
        return row
