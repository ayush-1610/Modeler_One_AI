"""The single-node campaign runner the API uses (`modeler_contracts.ports.CampaignRunner`).

A thin adapter: every call goes to the existing local-runner and feedback functions, unchanged.
"""

from __future__ import annotations

from typing import Any

from modeler_contracts.runs import CampaignRequest
from modeler_orchestrator import feedback, local_runner


class LocalCampaignRunner:
    def start(self, request: CampaignRequest, *, read_root: str, project: str, question: str, model_risk: str) -> None:
        local_runner.start_campaign(request, read_root=read_root, project=project, question=question,
                                    model_risk=model_risk)

    def gate_refusal(self, campaign: dict[str, Any], project: dict[str, Any] | None) -> str | None:
        return local_runner.gate_refusal(campaign, project)

    def check_feedback(self, campaign: dict[str, Any], stage: str, action: str, payload: dict[str, Any] | None) -> None:
        local_runner.check_feedback(campaign, stage, action, payload)

    def decision_digest(self, campaign_id: str, stage: str, action: str, payload: dict[str, Any] | None) -> str:
        return feedback.decision_digest(campaign_id, stage, action, payload)

    def resolve(self, *, read_root: str, tenant_id: str, campaign_id: str, stage: str, action: str,
                payload: dict[str, Any] | None, signature_id: str, printed_name: str, note: str) -> dict[str, Any]:
        return local_runner.resolve_escalation(
            read_root=read_root, tenant_id=tenant_id, campaign_id=campaign_id, stage=stage, action=action,
            payload=payload, signature_id=signature_id, printed_name=printed_name, note=note,
        )
