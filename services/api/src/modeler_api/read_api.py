"""Read APIs for the web app: projects, questions and the Compound Parameter Framework (task T-26 backing).

These serve the operator UI's read models. The CPF is the system of record: a GET returns the parsed CPF
projected for display (parameters with value/unit/provenance/status/fittable stages) plus the S0 completeness
computed from it. Data is fetched through a ``ReadStore`` protocol so the authorization and projection are
tested without a datastore; ``FileReadStore`` (in ``modeler_api.filestore``) reads per-tenant JSON from a
configured root, the seam the Postgres §5 read tables will replace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import unquote, urlparse

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
def list_campaigns(principal: PrincipalDep, store: StoreDep, project: str | None = None):
    """List the tenant's campaigns (summary + stage/round detail); ``?project=`` narrows to one project."""
    campaigns = store.list_campaigns(principal.tenant_id)
    if project:
        campaigns = [c for c in campaigns if c.get("project") == project]
    return envelope({"campaigns": campaigns})


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


# --- the S7 package: summary and downloads ------------------------------------------------------------------

_ARTIFACTS = {
    "package.zip": "application/zip",
    "mar.md": "text/markdown; charset=utf-8",
    "mar.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "mar.pdf": "application/pdf",
}


def get_artifact_root() -> Path | None:
    """The object store's local root (file://), under which every campaign artifact must lie."""
    uri = get_settings().object_store_uri
    parsed = urlparse(uri)
    return Path(unquote(parsed.path)).resolve() if parsed.scheme == "file" else None


ArtifactRootDep = Annotated[Path | None, Depends(get_artifact_root)]


def _package_record(campaign_id: str, principal: Principal, store: ReadStore) -> dict[str, Any]:
    campaign = store.get_campaign(principal.tenant_id, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"campaign {campaign_id} not found")
    if campaign.get("project"):
        require_project(campaign["project"], principal)
    record = campaign.get("package")
    if not record:
        raise HTTPException(status_code=404, detail=f"campaign {campaign_id} has no package yet (S7 has not run)")
    return record


def _available(record: dict[str, Any]) -> list[str]:
    names = [f"mar.{fmt}" for fmt in (record.get("report") or {}) if f"mar.{fmt}" in _ARTIFACTS]
    return (["package.zip"] if record.get("exportable") else []) + sorted(names)


@router.get("/campaigns/{campaign_id}/package")
def get_campaign_package(campaign_id: str, principal: PrincipalDep, store: StoreDep):
    """The S7 package: reproduction verdict, whether it may be exported (D13), hashes, and the downloadable
    artifacts. Server paths are never returned."""
    record = _package_record(campaign_id, principal, store)
    return envelope({
        "exportable": bool(record.get("exportable")),
        "reproduction": record.get("reproduction"),
        "data_bundle_sha256": record.get("data_bundle_sha256"),
        "package_sha256": record.get("package_sha256"),
        "files": record.get("files"),
        "report_notes": record.get("report_notes", []),
        "report_issues": record.get("report_issues", []),
        "artifacts": _available(record),
        # the PK-Sim projects inside the package (pksim/<stem>.pksim5), and why one is missing
        "pksim_projects": record.get("pksim_projects", []),
        "project_notes": record.get("project_notes", []),
    })


@router.get("/campaigns/{campaign_id}/package/{artifact}")
def download_campaign_artifact(campaign_id: str, artifact: str, principal: PrincipalDep, store: StoreDep,
                               root: ArtifactRootDep):
    """Download the package zip or the rendered MAR. The zip is refused while reproduction has not passed (D13);
    only files inside the object store are ever served."""
    from fastapi.responses import FileResponse

    record = _package_record(campaign_id, principal, store)
    if artifact not in _ARTIFACTS:
        raise HTTPException(status_code=404, detail=f"unknown artifact {artifact!r}")
    if artifact == "package.zip":
        if not record.get("exportable"):
            raise HTTPException(status_code=409, detail="the package is withheld: its reproduction did not pass (D13)")
        location = record.get("package")
    else:
        location = (record.get("report") or {}).get(artifact.split(".", 1)[1])
    if not location or root is None:
        raise HTTPException(status_code=404, detail=f"{artifact} is not available for campaign {campaign_id}")
    path = Path(location).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{artifact} is not available for campaign {campaign_id}")
    return FileResponse(path, media_type=_ARTIFACTS[artifact], filename=f"{campaign_id}-{artifact}")


@router.get("/projects/{project_id}/studies")
def list_studies(project_id: str, principal: PrincipalDep, store: StoreDep):
    """The observed clinical studies uploaded for this project (what the campaign fits and validates against)."""
    require_project(project_id, principal)
    return envelope({"studies": store.list_studies(principal.tenant_id, project_id)})


@router.get("/escalations")
def list_escalations(principal: PrincipalDep, store: StoreDep):
    """Open campaign escalations awaiting a signed decision (review inbox)."""
    return envelope({"escalations": store.list_escalations(principal.tenant_id)})


@router.get("/proposals")
def list_proposals(principal: PrincipalDep, store: StoreDep):
    """Pending agent parameter proposals awaiting curator acceptance (review inbox)."""
    return envelope({"proposals": store.list_proposals(principal.tenant_id)})
