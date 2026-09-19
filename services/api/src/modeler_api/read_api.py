"""Read APIs for the web app: projects, questions and the Compound Parameter Framework (task T-26 backing).

These serve the operator UI's read models. The CPF is the system of record: a GET returns the parsed CPF
projected for display (parameters with value/unit/provenance/status/fittable stages) plus the S0 completeness
computed from it. Data is fetched through a ``ReadStore`` protocol so the authorization and projection are
tested without a datastore; ``FileReadStore`` (in ``modeler_api.filestore``) reads per-tenant JSON from a
configured root, the seam the Postgres §5 read tables will replace.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from modeler_api.auth import Principal, require_project, require_role
from modeler_api.config import get_settings
from modeler_api.filestore import FileReadStore, ReadStore
from modeler_api.responses import envelope
from pbpk_domain.cpf import CPF
from pbpk_domain.cpf.completeness import check_completeness

# re-exported so existing imports (`from modeler_api.read_api import FileReadStore`) keep working
__all__ = ["FileReadStore", "ReadStore", "get_read_store", "project_cpf_view", "router"]

router = APIRouter(prefix="/api/v1", tags=["read"])

# any authenticated member of the tenant may read; writes have their own stricter roles
_READ_ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer")

# The S0 completeness rule checks six requirement groups; completeness is the fraction satisfied.
_COMPLETENESS_TOTAL = 6


def project_cpf_view(cpf: CPF) -> dict[str, Any]:
    """Project a CPF for the compound screen: parameter rows plus the S0 completeness fraction."""
    report = check_completeness(cpf)
    completeness = round((_COMPLETENESS_TOTAL - len(report.missing_ids)) / _COMPLETENESS_TOTAL, 3)
    parameters = [
        {
            "id": p.id,
            "value": None if p.value is None else str(p.value),
            "unit": p.unit,
            "status": p.status.value.lower(),
            "source": (p.provenance.source_type if p.provenance else "unknown"),
            "reference": (p.provenance.reference if p.provenance and p.provenance.reference else ""),
            "fittableStages": list(p.fit_policy.stage) if p.fit_policy else [],
        }
        for p in cpf.parameters
    ]
    return {
        "compound": cpf.compound,
        "version": cpf.version,
        "completeness": completeness,
        "ready": report.ready,
        "missing": list(report.missing),
        "parameters": parameters,
    }


def get_read_store() -> ReadStore:
    settings = get_settings()
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Read models are not configured. Set MODELER_READ_ROOT.")
    return FileReadStore(settings.read_root)


PrincipalDep = Annotated[Principal, Depends(require_role(*_READ_ROLES))]
StoreDep = Annotated[ReadStore, Depends(get_read_store)]


@router.get("/projects")
def list_projects(principal: PrincipalDep, store: StoreDep):
    return envelope({"projects": store.list_projects(principal.tenant_id)})


@router.get("/projects/{project_id}")
def get_project(project_id: str, principal: PrincipalDep, store: StoreDep):
    require_project(project_id, principal)
    project = store.get_project(principal.tenant_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return envelope(project)


@router.get("/projects/{project_id}/compounds/{compound}/cpf")
def get_compound_cpf(project_id: str, compound: str, principal: PrincipalDep, store: StoreDep):
    require_project(project_id, principal)
    cpf = store.get_cpf(principal.tenant_id, project_id, compound)
    if cpf is None:
        raise HTTPException(status_code=404, detail=f"no CPF for {compound} in project {project_id}")
    return envelope(project_cpf_view(cpf))


@router.get("/campaigns")
def list_campaigns(principal: PrincipalDep, store: StoreDep):
    """List the tenant's campaigns (summary + stage/round detail) for the campaign monitor."""
    return envelope({"campaigns": store.list_campaigns(principal.tenant_id)})


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, principal: PrincipalDep, store: StoreDep):
    """One campaign's monitor view. 404 when it is not in the tenant; 403 when the caller is not a member of
    the campaign's project (checked after the lookup, since the project is a property of the campaign, not the URL)."""
    campaign = store.get_campaign(principal.tenant_id, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"campaign {campaign_id} not found")
    project_id = campaign.get("project")
    if project_id:
        require_project(project_id, principal)
    return envelope(campaign)


@router.get("/escalations")
def list_escalations(principal: PrincipalDep, store: StoreDep):
    """Open campaign escalations awaiting a signed decision (review inbox)."""
    return envelope({"escalations": store.list_escalations(principal.tenant_id)})


@router.get("/proposals")
def list_proposals(principal: PrincipalDep, store: StoreDep):
    """Pending agent parameter proposals awaiting curator acceptance (review inbox)."""
    return envelope({"proposals": store.list_proposals(principal.tenant_id)})
