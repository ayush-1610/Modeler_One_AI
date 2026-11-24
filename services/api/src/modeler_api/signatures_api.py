"""Electronic-signature endpoint over the OIDC step-up (task T-06).

A signature is accepted only from an authenticated principal who is a member of the project and whose token
proves a recent step-up (acr=loa2, auth_time within 300 s). The signature binds to the record's SHA-256.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from modeler_api.auth import CurrentPrincipal, ensure_step_up, require_project
from modeler_api.compliance.signatures import SignatureMeaning, Signer, sign_after_step_up
from modeler_api.config import SettingsDep
from modeler_api.deps import Reader, StoreDep, project_campaigns, workspace_for
from modeler_api.part11 import record_signature
from modeler_api.responses import answers, answers_without_envelope, envelope
from modeler_api.views.campaigns import SignatureCreated, SignatureRegister

router = APIRouter(prefix="/api/v1", tags=["signatures"])


class SignatureRequest(BaseModel):
    meaning: SignatureMeaning
    record_type: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/projects/{project_id}/signatures", status_code=201, **answers_without_envelope(SignatureCreated))
def create_signature(project_id: str, request: SignatureRequest, principal: CurrentPrincipal, settings: SettingsDep) -> dict:
    require_project(project_id, principal)   # 403 for a project the principal is not a member of
    ensure_step_up(principal)                # 403 STEP_UP_REQUIRED / STEP_UP_STALE
    signature = sign_after_step_up(
        signer=Signer(user_id=principal.user_id, printed_name=principal.printed_name),
        meaning=request.meaning, record_type=request.record_type, record_id=request.record_id,
        record_sha256=request.record_sha256, acr=principal.acr or "",
    )
    record_signature(settings, principal.tenant_id, signature)
    return {
        "signature_id": signature.signature_id,
        "manifestation": signature.manifestation(),
        "record_sha256": signature.record_sha256,
        "auth_method": signature.auth_method,
        "signed_by": principal.user_id,
    }


# an escalation decision signs "{campaign_id}-{stage}" (`escalations.resolve_escalation`)
_DECISION = re.compile(r"^(?P<campaign>.+)-(?P<stage>S\d+|SJ)$")


@router.get("/projects/{project_id}/signatures", **answers(SignatureRegister))
def get_signatures(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """The signatures given on this project's records (R-N09), newest first: every `signature.create` event of the
    company's audit chain whose record is the project's (its id starts with the project's: an intake confirmation, the
    MAP and its deviations, the Data room's publication) or a decision on one of its campaigns' escalations (signed as
    "{campaign_id}-{stage}"), which the project's audit trail, filtered by the project's prefix, does not list."""
    ws = workspace_for(project_id, principal, store)
    log = store.audit(ws.tenant_id)
    prefix = f"{project_id}/"
    campaigns = {c["id"] for c in project_campaigns(ws)}

    def mine(record_type: str, record_id: str) -> bool:
        if record_id == project_id or record_id.startswith(prefix):
            return True
        decision = _DECISION.match(record_id) if record_type == "escalation" else None
        return decision is not None and decision["campaign"] in campaigns

    rows = []
    for r in log.records():
        event = r.event
        if event.action != "signature.create" or not mine(event.resource_type, event.resource_id):
            continue
        after = event.after or {}
        manifestation = event.reason or ""
        rows.append({"signature_id": str(after.get("signature_id", "")), "signer_id": event.actor,
                     "printed_name": manifestation.split(" | ", 1)[0] or None if " | " in manifestation else None,
                     "meaning": str(after.get("meaning", "")), "record_type": event.resource_type,
                     "record_id": event.resource_id, "record_sha256": str(after.get("record_sha256", "")),
                     "signed_at": str(event.occurred_at), "manifestation": manifestation, "seq": event.seq})
    return envelope({"chain_verifies": log.verify() is None, "signatures": list(reversed(rows))})
