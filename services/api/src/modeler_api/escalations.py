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

import hashlib
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from modeler_api.auth import CurrentPrincipal, ensure_step_up, require_project
from modeler_api.compliance.signatures import (
    SignatureAuthenticationError,
    SignatureMeaning,
    Signer,
    StepUpVerifier,
    sign_after_step_up,
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


# --- single-node (local execution backend) ---------------------------------------------------------
#
# The endpoint above signals a running Temporal workflow and authenticates the signature with a password-based
# step-up verifier. Under the `local` backend there is no workflow to signal, and signatures are taken from the
# OIDC token's step-up (`acr=loa2`), the same way the MAP is signed — so no password crosses the wire. This
# endpoint applies the decision to the persisted campaign instead: retry / accept_best / abort (MS-01 §4).


class FeedbackEvidence(BaseModel):
    """New evidence after an S5 failure (plan §12.3 N4 c): one parameter's measured value, in the CPF's own unit."""

    parameter: str = Field(min_length=1)
    value: float
    unit: str | None = None
    reference: str = Field(min_length=1)


class ResolveRequest(BaseModel):
    # "approve" signs a gate (the S4/S5 evaluation before S6, MS-01 §4) and continues the campaign; "learn" and
    # "new_evidence" answer a failed external validation (S5) with a new cycle (plan §12.3 N4).
    action: Literal["retry", "accept_best", "abort", "approve", "learn", "new_evidence"]
    note: str = ""
    studies: list[str] = Field(default_factory=list)  # learn: the failing studies to move (default: every learnable one)
    beyond_cap: str = ""                              # learn beyond the cycle cap (D-05): the signed deviation reason
    evidence: FeedbackEvidence | None = None          # new_evidence


class FeedbackRequest(ResolveRequest):
    action: Literal["accept_best", "learn", "new_evidence", "abort"]


@router.post("/campaigns/{campaign_id}/feedback:decide")
def decide_feedback(campaign_id: str, request: FeedbackRequest, principal: CurrentPrincipal) -> dict[str, Any]:
    """The signed decision on a failed external validation (plan §12.4 FEEDBACK_PENDING): limitation (accept_best),
    learn, new evidence, or stop (abort)."""
    return resolve_escalation_decision(campaign_id, "S5", request, principal)


def _payload(request: ResolveRequest) -> dict[str, Any] | None:
    if request.action == "learn":
        return {"studies": request.studies, "beyond_cap": request.beyond_cap}
    if request.action == "new_evidence":
        if request.evidence is None:
            raise HTTPException(status_code=422, detail="new evidence needs the parameter, its value, unit and source")
        return request.evidence.model_dump()
    return None


@router.post("/campaigns/{campaign_id}/stages/{stage}/escalation:resolve")
def resolve_escalation_decision(
    campaign_id: str, stage: str, request: ResolveRequest, principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Resume, accept or abort an escalated stage of a single-node campaign, with a Part 11 signature."""
    from modeler_api.config import get_settings
    from modeler_api.filestore import FileReadStore

    settings = get_settings()
    if settings.execution_backend != "local":
        raise HTTPException(status_code=409,
                            detail="This deployment runs campaigns on Temporal; use escalation:decide instead.")
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Campaign state is not configured. Set MODELER_READ_ROOT.")

    campaign = FileReadStore(settings.read_root).get_campaign(principal.tenant_id, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"campaign {campaign_id} not found")
    project_id = campaign.get("project")
    if project_id:
        require_project(project_id, principal)

    from modeler_orchestrator.feedback import decision_digest
    from modeler_orchestrator.local_runner import (  # lazy: orchestrator depends on this package
        check_feedback,
        gate_refusal,
        resolve_escalation,
    )

    # Nothing judged on data that is not real is signed outside an exploratory project (plan §9.4, D-19); refused
    # before the signature is taken, so no signature exists for a decision that was not applied.
    if request.action == "approve" and (refusal := gate_refusal(campaign, FileReadStore(settings.read_root).get_project(
            principal.tenant_id, project_id or ""))):
        raise HTTPException(status_code=409, detail=refusal)
    # A feedback decision's guardrails (plan §12.3 N4: spent studies, the cycle cap, the evidence's unit and source)
    # are checked before the signature too.
    payload = _payload(request)
    try:
        check_feedback(campaign, stage, request.action, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Every decision that resumes or ends a stage is an approval (MS-01 §4 / 21 CFR 11), so it is signed
    # before anything is applied — an unsigned decision must not be able to move the campaign.
    ensure_step_up(principal)
    signature = sign_after_step_up(
        signer=Signer(user_id=principal.user_id, printed_name=principal.printed_name),
        meaning=DECISION_MEANING, record_type="escalation", record_id=f"{campaign_id}-{stage}",
        # the signature binds the decision and, for a feedback cycle, its content (studies learned, evidence given)
        record_sha256=decision_digest(campaign_id, stage, request.action, payload) if payload is not None
        else hashlib.sha256(f"{campaign_id}:{stage}:{request.action}".encode()).hexdigest(),
        acr=principal.acr or "",
    )

    try:
        result = resolve_escalation(
            read_root=settings.read_root, tenant_id=principal.tenant_id,
            campaign_id=campaign_id, stage=stage, action=request.action, payload=payload,
            signature_id=signature.signature_id, printed_name=principal.printed_name, note=request.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {**result, "note": request.note,
            "signature": {"signature_id": signature.signature_id, "manifestation": signature.manifestation()}}
