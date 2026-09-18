"""Escalations, deviations and signed decisions (task T-17).

A stage escalates when the automated loop cannot proceed (rounds or budget exhausted, a parameter at a bound,
no permitted action). It resumes only through a human decision, and — per 21 CFR 11 — only when that decision
carries a valid electronic signature of the required meaning (`sign_record`). The endpoint verifies the
signature first; without it no workflow signal is sent, so an escalated campaign cannot be resumed unsigned.

The identity provider, the workflow signaler and the persistence store are injected (FastAPI dependencies), so
the decision flow is testable without Keycloak, Temporal or a database; the real providers are wired at
startup. Decision options come from MS-01 §4.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from modeler_api.compliance.signatures import (
    SignatureAuthenticationError,
    SignatureMeaning,
    Signer,
    StepUpVerifier,
    sign_record,
)
from modeler_contracts.runs import DeviationRecord, EscalationDecision

router = APIRouter(prefix="/api/v1", tags=["escalations"])

# MS-01 §4: an escalated stage resumes only through one of these decisions.
ESCALATION_ACTIONS: dict[str, str] = {
    "retry": "Retry the stage without a new action (e.g. after adding data or relaxing a bound).",
    "accept_best": "Accept the best CPF found so far and continue to the next stage.",
    "abort": "Abort the stage; the campaign escalates for human re-planning.",
}
# A continuation decision is an approval; a deviation from the signed MAP is likewise approved.
DECISION_MEANING = SignatureMeaning.APPROVED


def decision_options() -> list[dict[str, str]]:
    return [{"action": a, "description": d, "required_signature": DECISION_MEANING.value} for a, d in ESCALATION_ACTIONS.items()]


class Signaler(Protocol):
    """Delivers a signal to the running campaign/stage workflow (Temporal at runtime)."""

    async def signal_escalation(self, *, campaign_id: str, stage: str, decision: EscalationDecision) -> None: ...

    async def signal_deviation(self, *, campaign_id: str, stage: str, deviation: DeviationRecord) -> None: ...


class EscalationStore(Protocol):
    """Records the signed decision as an audited row (CampaignRepository at runtime)."""

    async def record_escalation_decision(self, *, campaign_id: str, stage: str, decision: EscalationDecision, signature_id: str) -> None: ...

    async def record_deviation(self, *, campaign_id: str, deviation: DeviationRecord, signature_id: str) -> None: ...


class TemporalSignaler:
    """Signals the running stage workflow (id ``{campaign_id}-{stage}``) over a Temporal client."""

    def __init__(self, client: Any):
        self._client = client

    async def signal_escalation(self, *, campaign_id: str, stage: str, decision: EscalationDecision) -> None:
        await self._client.get_workflow_handle(f"{campaign_id}-{stage}").signal("escalation_decided", decision)

    async def signal_deviation(self, *, campaign_id: str, stage: str, deviation: DeviationRecord) -> None:
        await self._client.get_workflow_handle(f"{campaign_id}-{stage}").signal("deviation_recorded", deviation)


def get_verifier() -> StepUpVerifier:
    raise HTTPException(status_code=503, detail="Signature verification is not configured (Keycloak step-up).")


async def get_signaler() -> Signaler:
    from modeler_api.config import get_settings

    settings = get_settings()
    if not settings.temporal_address:
        raise HTTPException(status_code=503, detail="Workflow signalling is not configured. Set MODELER_TEMPORAL_ADDRESS.")
    from temporalio.client import Client

    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    return TemporalSignaler(client)


def get_store() -> EscalationStore | None:
    return None  # persistence is optional; the decision still signals the workflow when no store is configured


class SignedDecisionRequest(BaseModel):
    action: Literal["retry", "accept_best", "abort"]
    note: str = ""
    escalation_id: str = Field(min_length=1)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")  # the escalation state the reviewer is signing
    signer_id: str = Field(min_length=1)
    printed_name: str = Field(min_length=1)
    password: str = Field(min_length=1)
    second_factor: str = Field(min_length=1)


class DeviationRequest(BaseModel):
    stage: str = Field(min_length=1)
    description: str = Field(min_length=1)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signer_id: str = Field(min_length=1)
    printed_name: str = Field(min_length=1)
    password: str = Field(min_length=1)
    second_factor: str = Field(min_length=1)


def _sign(req: SignedDecisionRequest | DeviationRequest, *, record_type: str, record_id: str, verifier: StepUpVerifier):
    try:
        return sign_record(
            signer=Signer(user_id=req.signer_id, printed_name=req.printed_name), meaning=DECISION_MEANING,
            record_type=record_type, record_id=record_id, record_sha256=req.record_sha256,
            password=req.password, second_factor=req.second_factor, verifier=verifier,
        )
    except SignatureAuthenticationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/escalations/decision-options")
def escalation_decision_options() -> dict[str, Any]:
    return {"options": decision_options()}


@router.post("/campaigns/{campaign_id}/stages/{stage}/escalation:decide")
async def decide_escalation(
    campaign_id: str,
    stage: str,
    request: SignedDecisionRequest,
    x_tenant_id: Annotated[str, Header()],
    verifier: Annotated[StepUpVerifier, Depends(get_verifier)],
    signaler: Annotated[Signaler, Depends(get_signaler)],
    store: Annotated[EscalationStore | None, Depends(get_store)],
) -> dict[str, Any]:
    """Resume an escalated stage with a signed decision. The signature is verified before any signal is sent."""
    signature = _sign(request, record_type="escalation", record_id=request.escalation_id, verifier=verifier)
    decision = EscalationDecision(action=request.action, note=request.note, signature_id=signature.signature_id)
    await signaler.signal_escalation(campaign_id=campaign_id, stage=stage, decision=decision)
    if store is not None:
        await store.record_escalation_decision(campaign_id=campaign_id, stage=stage, decision=decision, signature_id=signature.signature_id)
    return {
        "campaign_id": campaign_id, "stage": stage, "action": decision.action,
        "signature": {"signature_id": signature.signature_id, "manifestation": signature.manifestation()},
    }


@router.post("/campaigns/{campaign_id}/deviations", status_code=201)
async def record_deviation(
    campaign_id: str,
    request: DeviationRequest,
    x_tenant_id: Annotated[str, Header()],
    verifier: Annotated[StepUpVerifier, Depends(get_verifier)],
    signaler: Annotated[Signaler, Depends(get_signaler)],
    store: Annotated[EscalationStore | None, Depends(get_store)],
) -> dict[str, Any]:
    """Record a signed deviation from the MAP and inform the running stage workflow."""
    signature = _sign(request, record_type="deviation", record_id=f"{campaign_id}:{request.stage}", verifier=verifier)
    deviation = DeviationRecord(stage=request.stage, description=request.description, signature_id=signature.signature_id)
    await signaler.signal_deviation(campaign_id=campaign_id, stage=request.stage, deviation=deviation)
    if store is not None:
        await store.record_deviation(campaign_id=campaign_id, deviation=deviation, signature_id=signature.signature_id)
    return {
        "campaign_id": campaign_id, "stage": request.stage,
        "signature": {"signature_id": signature.signature_id, "manifestation": signature.manifestation()},
    }
