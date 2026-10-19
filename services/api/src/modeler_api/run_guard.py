"""What a campaign start checks before anything runs (run integrity, 2026-10-18).

The MAP is the signed contract the campaign follows (MS-01; ICH M15). A pilot or production deployment starts a
campaign only on a MAP a person signed: the MAP document itself (Approve and Sign in the model plan, P5), or an
approval signature recorded on its exact bytes (`campaign:prepare` followed by a `map_approval` signature; every
signature is an audit event, `modeler_api.part11.record_signature`). A development deployment (tests, the reference
runs in CI) may start an unsigned one: its DEV verifier signs nothing that counts.

The signed MAP also fixes each stage's time: MS-01's share of the campaign budget the person set in the plan. Outside
development a start cannot override it stage by stage (the owner's decision, 2026-10-18); a campaign that needs more
time gets a larger budget in the plan, signed again.

And the campaign runs on the parameters its MAP signed (D-36, 2026-10-19): the CPF handed to the run has the values,
units, fit stages, bounds and plausibility ranges the MAP's parameter table records. Outside development a CPF that
departs from it is refused; a development run records the differences at S0.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from modeler_contracts.runtime import runtime_env

if TYPE_CHECKING:
    from modeler_api.config import Settings


def _map_bytes(map_uri: str) -> bytes | None:
    return _file_bytes(map_uri)


def _file_bytes(uri: str) -> bytes | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = Path(unquote(parsed.path))
    return path.read_bytes() if path.is_file() else None


def map_signed(settings: Settings, tenant_id: str, map_uri: str) -> bool:
    """Whether a person signed the MAP at `map_uri`: its document carries the signature, or the audit trail holds a
    `map_approval` signature on its SHA-256."""
    data = _map_bytes(map_uri) if map_uri else None
    if data is None:
        return False
    try:
        doc = json.loads(data)
    except ValueError:
        return False
    if doc.get("status") == "SIGNED" and doc.get("signature"):
        return True
    if not settings.read_root:
        return False
    from modeler_project import FileProjectStore

    sha = hashlib.sha256(data).hexdigest()
    return any(r.event.action == "signature.create" and r.event.resource_type == "map_approval"
               and (r.event.after or {}).get("record_sha256") == sha
               for r in FileProjectStore(settings.read_root).audit(tenant_id).records())


def require_signed_map(settings: Settings, tenant_id: str, map_uri: str) -> None:
    """409 unless the MAP is signed, on a pilot or production deployment."""
    if runtime_env().deployment_kind == "development":
        return
    if not map_signed(settings, tenant_id, map_uri):
        raise HTTPException(status_code=409, detail="This campaign's MAP is not signed. Approve and sign it in the model "
                                                    "plan before the campaign can start.")


def require_signed_limits(stage_budgets_seconds: dict[str, int]) -> None:
    """422 when a pilot or production start overrides the signed MAP's stage budgets."""
    if stage_budgets_seconds and runtime_env().deployment_kind != "development":
        raise HTTPException(status_code=422, detail="Each stage's time is its MS-01 share of the budget in the signed MAP, "
                                                    "and a start cannot change it. To give the campaign more time, raise "
                                                    "its budget in the model plan and sign again.")


def require_cpf_matches_map(cpf_uri: str, map_uri: str) -> None:
    """409 when a pilot or production campaign's CPF departs from its signed MAP's parameter table (D-36), or cannot be
    read to check it."""
    if runtime_env().deployment_kind == "development":
        return
    from pbpk_domain.campaign.map import MapDocument, cpf_differences
    from pbpk_domain.cpf import CPF

    cpf_bytes, map_bytes = _file_bytes(cpf_uri), _file_bytes(map_uri) if map_uri else None
    if cpf_bytes is None or map_bytes is None:
        raise HTTPException(status_code=409, detail="The campaign's CPF or MAP could not be read to check that the run uses "
                                                    "the parameters the MAP signed.")
    try:
        differences = cpf_differences(MapDocument.model_validate_json(map_bytes), CPF.model_validate_json(cpf_bytes))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"The campaign's CPF or MAP does not read: {exc}") from exc
    if differences:
        shown = "; ".join(differences[:5]) + (f"; and {len(differences) - 5} more" if len(differences) > 5 else "")
        raise HTTPException(status_code=409, detail="The campaign's CPF is not the one its MAP signed: " + shown + ". Bring "
                                                    "the plan up to date and sign it again, or start the campaign from the "
                                                    "signed MAP's own CPF.")
