"""Read APIs for the web app: projects, questions and the Compound Parameter Framework (task T-26 backing).

These serve the operator UI's read models. The CPF is the system of record: a GET returns the parsed CPF
projected for display (parameters with value/unit/provenance/status/fittable stages) plus the S0 completeness
computed from it. Data is fetched through a ``ReadStore`` protocol so the authorization and projection are
tested without a datastore; ``FileReadStore`` (in ``modeler_storage.filestore``) reads per-tenant JSON from a
configured root, the seam the Postgres §5 read tables will replace.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from modeler_api.auth import Principal, require_project, require_role
from modeler_api.config import SettingsDep
from modeler_api.cpf_view import project_cpf_view
from modeler_api.deps import get_project_store
from modeler_api.memberships import archive_for, memberships_for
from modeler_api.ownership import may_change
from modeler_api.responses import answers, envelope
from modeler_api.views.campaigns import CampaignPackage, Campaigns, Escalations
from modeler_api.views.read import CpfView, Projects, ProjectSystem, Proposals, Studies, StudyRow
from modeler_project import ProjectStore, Workspace
from modeler_project.steps import project_steps
from modeler_storage.filestore import FileReadStore, ReadStore
from modeler_storage.records import CampaignRecord, ProjectRecord
from pbpk_domain.cpf.models import ParameterStatus

# re-exported so existing imports (`from modeler_api.read_api import FileReadStore`) keep working
__all__ = ["FileReadStore", "ReadStore", "get_read_store", "project_cpf_view", "router"]

router = APIRouter(prefix="/api/v1", tags=["read"])

# any authenticated member of the tenant may read; writes have their own stricter roles
_READ_ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer")

def get_read_store(settings: SettingsDep) -> ReadStore:
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Read models are not configured. Set MODELER_READ_ROOT.")
    return FileReadStore(settings.read_root)


PrincipalDep = Annotated[Principal, Depends(require_role(*_READ_ROLES))]
StoreDep = Annotated[ReadStore, Depends(get_read_store)]


ProjectsDep = Annotated[ProjectStore, Depends(get_project_store)]


@router.get("/projects", **answers(Projects))
def list_projects(principal: PrincipalDep, store: StoreDep, settings: SettingsDep, projects_store: ProjectsDep,
                  with_: Annotated[str | None, Query(alias="with", description="Comma list of extra parts: steps, owner")] = None):
    # only the projects this person may open (their token's and their platform memberships, P3); each says whether it is
    # archived (page review 1), and the Projects page hides those until asked
    parts = {w.strip() for w in (with_ or "").split(",") if w.strip()}
    unknown = parts - LIST_PARTS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown part(s) {', '.join(sorted(unknown))}: ask for steps, owner or both.")
    projects = store.list_projects(principal.tenant_id)
    if "*" not in principal.projects:
        projects = [p for p in projects if p.get("id") in principal.projects]
    archived = archive_for(settings, principal.tenant_id).archived() if settings.read_root else {}
    items = [{**p, "archived": dataclasses.asdict(archived[p["id"]]) if p.get("id") in archived else None} for p in projects]
    # the redesign's R-N03: each project's steps (as `GET /projects/{id}/steps` answers them) and its owner's name (as
    # `GET /projects/{id}/members` does, with its id), in this one read; only when asked, so other callers keep today's cost
    if "steps" in parts:
        statuses: dict[str, list[str]] = {}
        for c in store.list_campaigns(principal.tenant_id):
            statuses.setdefault(str(c.get("project")), []).append(str(c.get("status", "")))
        for item in items:
            ws = Workspace(projects_store, principal.tenant_id, item["id"])
            item["steps"] = [s.model_dump(mode="json") for s in project_steps(ws, statuses.get(item["id"], []))]
    if "owner" in parts:
        memberships = memberships_for(settings, principal.tenant_id) if settings.read_root else None
        for item in items:
            owner = memberships.owner(item["id"]) if memberships else None
            names = {m.subject: m.name for m in memberships.members(item["id"])} if memberships and owner else {}
            item["owner"] = owner
            item["owner_name"] = names.get(owner, owner) if owner else None
    return envelope({"projects": items})


LIST_PARTS = {"steps", "owner"}


@router.get("/projects/{project_id}", **answers(ProjectRecord))
def get_project(project_id: str, principal: PrincipalDep, store: StoreDep):
    require_project(project_id, principal)
    project = store.get_project(principal.tenant_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    return envelope(project)


@router.get("/projects/{project_id}/compounds/{compound}/cpf", **answers(CpfView))
def get_compound_cpf(project_id: str, compound: str, principal: PrincipalDep, store: StoreDep, projects: ProjectsDep):
    """The compound's CPF: the one Inputs assembles for the project (the system of record every simulation of a pipeline
    project is regenerated from; final review OWN-13) once it holds a value, else the one stored for the campaign path,
    else 404 (the page then says the values are filled in on Inputs). An assembled CPF that holds no value yet is not
    answered in place of the stored one, nor as an empty table (round 3: a project whose inputs had assembled nothing
    answered 200 with no parameter where it answered 404)."""
    require_project(project_id, principal)
    from modeler_project.inputs import current_cpf

    assembled = current_cpf(Workspace(projects, principal.tenant_id, project_id))
    held = assembled is not None and assembled.compound == compound and any(
        p.value is not None and p.status is not ParameterStatus.MISSING for p in assembled.parameters)
    cpf = assembled if held else store.get_cpf(principal.tenant_id, project_id, compound)
    if cpf is None:
        raise HTTPException(status_code=404, detail=f"no CPF for {compound} in project {project_id}")
    return envelope(project_cpf_view(cpf))


def _member_of(principal: Principal, project: str | None) -> bool:
    """Whether a tenant-wide list may show an item of `project` to this person: the same rule as the detail routes'
    `require_project` (a campaign with no project stays visible, as its own page is), so a list never shows what its
    detail route refuses (redesign review R-S01: the lists showed every project's campaigns and escalations)."""
    return not project or "*" in principal.projects or project in principal.projects


@router.get("/campaigns", **answers(Campaigns))
def list_campaigns(principal: PrincipalDep, store: StoreDep, project: str | None = None):
    """List the tenant's campaigns (summary + stage/round detail); ``?project=`` narrows to one project."""
    campaigns = [c for c in store.list_campaigns(principal.tenant_id) if _member_of(principal, c.get("project"))]
    if project:
        campaigns = [c for c in campaigns if c.get("project") == project]
    return envelope({"campaigns": campaigns})


@router.get("/campaigns/{campaign_id}", **answers(CampaignRecord))
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


def get_artifact_root(settings: SettingsDep) -> Path | None:
    """The object store's local root (file://), under which every campaign artifact must lie."""
    uri = settings.object_store_uri
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


@router.get("/campaigns/{campaign_id}/package", **answers(CampaignPackage))
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
                               root: ArtifactRootDep) -> FileResponse:
    """Download the package zip or the rendered MAR. The zip is refused while reproduction has not passed (D13);
    only files inside the object store are ever served."""
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


def _from_inputs(row: dict[str, Any], project_id: str) -> dict[str, Any]:
    """A study of the catalog Inputs assembles, as the study list shows it: the fields a study upload has (the profile
    without its BLQ note), marked as the inputs' (`source`)."""
    from modeler_api.studies import ObservedProfile, StudyUpload

    out = {k: v for k, v in row.items() if k in StudyUpload.model_fields and k != "profile"}
    profile = row.get("profile")
    out["profile"] = {k: v for k, v in profile.items() if k in ObservedProfile.model_fields} if profile else None
    # typed as the list types an upload (numbers as the study list gives them), so both read alike
    return StudyRow.model_validate({**out, "project": project_id, "blinded": bool(row.get("blinded")),
                                    "source": "inputs"}).model_dump(mode="json")


@router.get("/projects/{project_id}/studies", **answers(Studies))
def list_studies(project_id: str, principal: PrincipalDep, store: StoreDep, projects: ProjectsDep):
    """The observed clinical studies of this project (what a campaign fits and validates against): those uploaded for the
    campaign path, then the studies of the catalog Inputs assembles (what a signed plan stages; final review OWN-13: the
    Run page listed none while Inputs had a study in the model), each once, an upload first."""
    require_project(project_id, principal)
    studies = store.list_studies(principal.tenant_id, project_id)
    from modeler_api.deps import blinded_sources
    from modeler_project.inputs import catalog_rows

    ws = Workspace(projects, principal.tenant_id, project_id)
    hidden = blinded_sources(ws)          # one rule for a study's values: the list's and the delivery's (round 6)
    uploaded = {str(s.get("study_id")) for s in studies}
    studies += [_from_inputs(r, project_id) for r in catalog_rows(ws) if str(r.get("study_id")) not in uploaded]
    if hidden:  # D-15: a pipeline project's external studies, published at P4, keep their values out until the MAP is signed
        from modeler_project.blinding import redact_row

        studies = [redact_row(s) if hidden.withholds(s.get("study_id")) else s for s in studies]
    return envelope({"studies": studies})



@router.get("/projects/{project_id}/system", **answers(ProjectSystem))
def get_system(project_id: str, principal: PrincipalDep, store: StoreDep):
    """The project's model system (compounds and roles, formation, products with their dose fractions, analytes and
    the stages that judge each, MS-01 v1.3 §6.5), or none for a single-compound project."""
    require_project(project_id, principal)
    links = store.get_system(principal.tenant_id, project_id)
    if links is None:
        return envelope({"system": None, "links": None})
    from modeler_api.system_view import system_detail

    cpfs = {c: cpf for c in links.get("compounds", []) if (cpf := store.get_cpf(principal.tenant_id, project_id, c)) is not None}
    return envelope({"system": system_detail(links, cpfs), "links": links})


@router.get("/escalations", **answers(Escalations))
def list_escalations(principal: PrincipalDep, store: StoreDep, settings: SettingsDep):
    """Open campaign escalations awaiting a signed decision, of the projects this person is a member of. An escalation
    names its campaign, not its project, so its project is its campaign's; one whose campaign is not (yet) recorded has
    no project to check and stays listed, as a campaign with no project does (the decision pop-up reads this list alone,
    so a decision is asked even before its campaign's record can be read)."""
    projects = {c.get("id"): c.get("project") for c in store.list_campaigns(principal.tenant_id)}
    listed = [e for e in store.list_escalations(principal.tenant_id) if _member_of(principal, projects.get(e.get("campaignId")))]
    # whether this person may decide each one: the rule `escalation:resolve` applies (its owner, or a reviewer it is shared
    # with; a campaign with no project recorded has no owner to check, as the route has none) (R-S02)
    return envelope({"escalations": [{**e, "can_decide": (not (p := projects.get(e.get("campaignId"))))
                                      or may_change(p, principal, settings, signing=True)} for e in listed]})


@router.get("/proposals", **answers(Proposals))
def list_proposals(principal: PrincipalDep, store: StoreDep):
    """Pending agent parameter proposals awaiting curator acceptance (review inbox)."""
    return envelope({"proposals": store.list_proposals(principal.tenant_id)})
