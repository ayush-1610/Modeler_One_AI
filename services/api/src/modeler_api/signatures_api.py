"""Electronic-signature endpoint over the OIDC step-up (task T-06).

A signature is accepted only from an authenticated principal who is a member of the project and whose token
proves a recent step-up (acr=loa2, auth_time within 300 s). The signature binds to the record's SHA-256.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from modeler_api.auth import CurrentPrincipal, ensure_step_up, require_project
from modeler_api.compliance.signatures import SignatureMeaning, Signer, sign_after_step_up

router = APIRouter(prefix="/api/v1", tags=["signatures"])


class SignatureRequest(BaseModel):
    meaning: SignatureMeaning
    record_type: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/projects/{project_id}/signatures", status_code=201)
def create_signature(project_id: str, request: SignatureRequest, principal: CurrentPrincipal) -> dict:
    require_project(project_id, principal)   # 403 for a project the principal is not a member of
    ensure_step_up(principal)                # 403 STEP_UP_REQUIRED / STEP_UP_STALE
    signature = sign_after_step_up(
        signer=Signer(user_id=principal.user_id, printed_name=principal.printed_name),
        meaning=request.meaning, record_type=request.record_type, record_id=request.record_id,
        record_sha256=request.record_sha256, acr=principal.acr or "",
    )
    return {
        "signature_id": signature.signature_id,
        "manifestation": signature.manifestation(),
        "record_sha256": signature.record_sha256,
        "auth_method": signature.auth_method,
        "signed_by": principal.user_id,
    }
