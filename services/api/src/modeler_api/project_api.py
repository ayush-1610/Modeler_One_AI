"""The project start-up pipeline's shared API: phases, artifacts, version history, impact preview, audit (T-40).

Every phase of `docs/plans/2026-09-25-project-startup-pipeline.md` stores its output as versioned artifacts in a
`modeler_project.Workspace`; these endpoints let the web app show the phase rail, any artifact and its history, what
an edit would make stale before it is saved (plan §13.2), and the project's audit trail. The phase-specific routers
(brief, requirements, evidence, client data, inputs, plan) build on `workspace_for`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modeler_api.auth import Principal, require_project, require_role
from modeler_api.config import get_settings
from modeler_api.responses import envelope
from modeler_project import ArtifactKind, ArtifactRef, ArtifactVersion, FileProjectStore, ProjectStore, Workspace
from modeler_project import blinding as blind
from modeler_project.workspace import PHASE_LABELS

router = APIRouter(prefix="/api/v1", tags=["project-pipeline"])

READ_ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer")
WRITE_ROLES = ("modeler-curator", "modeler-reviewer")
Reader = Annotated[Principal, Depends(require_role(*READ_ROLES))]
Writer = Annotated[Principal, Depends(require_role(*WRITE_ROLES))]
MiddLead = Annotated[Principal, Depends(require_role("modeler-reviewer"))]


def get_project_store() -> ProjectStore:
    settings = get_settings()
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Project storage is not configured. Set MODELER_READ_ROOT.")
    return FileProjectStore(settings.read_root)


StoreDep = Annotated[ProjectStore, Depends(get_project_store)]


def workspace_for(project_id: str, principal: Principal, store: ProjectStore) -> Workspace:
    require_project(project_id, principal)
    return Workspace(store, principal.tenant_id, project_id)


def parse_kind(kind: str) -> ArtifactKind:
    try:
        return ArtifactKind(kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"unknown artifact kind {kind!r}") from exc


def version_view(ws: Workspace, version: ArtifactVersion, *, with_content: bool = True) -> dict[str, Any]:
    """An artifact version as the web app reads it: identity, status, provenance of the version, approvals."""
    view: dict[str, Any] = {
        "kind": version.kind.value, "id": version.id, "version": version.version, "sha256": version.sha256,
        "status": ws.status(version).value, "stale_reasons": ws.stale_reasons(version),
        "created_at": version.created_at.isoformat(), "created_by": version.created_by, "reason": version.reason,
        "derived_from": [r.model_dump(mode="json") for r in version.derived_from],
        "approvals": [a.model_dump(mode="json") for a in ws.approvals_of(version.ref)],
    }
    if with_content:
        view["content"] = version.content
    return view


@router.get("/projects/{project_id}/phases")
def get_phases(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    phases = ws.phases()
    return envelope({
        "phases": [{"phase": p, "label": PHASE_LABELS[p], "status": s.value} for p, s in phases.items()],
        "stale": [{"ref": item.ref.model_dump(mode="json"), "reasons": list(item.reasons)} for item in ws.stale()],
    })


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(project_id: str, principal: Reader, store: StoreDep, kind: str | None = None) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    versions = ws.list(parse_kind(kind) if kind else None)
    return envelope({"artifacts": [version_view(ws, v, with_content=False) for v in versions]})


@router.get("/projects/{project_id}/artifacts/{kind}/{artifact_id}")
def get_artifact(project_id: str, kind: str, artifact_id: str, principal: Reader, store: StoreDep,
                 version: int | None = None) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    k = parse_kind(kind)
    found = ws.get(ArtifactRef(kind=k, id=artifact_id, version=version)) if version else ws.latest(k, artifact_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no {kind}/{artifact_id}" + (f"@v{version}" if version else ""))
    view = version_view(ws, found)
    view["content"] = redact(ws, found.kind, found.content)
    return envelope(view)


@router.get("/projects/{project_id}/artifacts/{kind}/{artifact_id}/history")
def get_history(project_id: str, kind: str, artifact_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    k = parse_kind(kind)
    rows = ws.history(k, artifact_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no {kind}/{artifact_id}")
    hidden = _hidden_paths(ws, k, ws.latest(k, artifact_id).content)
    return envelope({"versions": [
        {**{k: v for k, v in row.items() if k not in ("ref", "approvals", "changes", "status", "created_at")},
         "version": row["ref"].version, "status": row["status"].value, "created_at": row["created_at"].isoformat(),
         "approvals": [a.model_dump(mode="json") for a in row["approvals"]],
         "changes": [{"path": c.path, "before": c.before, "after": c.after, "kind": c.kind} for c in row["changes"]
                     if not c.path.startswith(hidden)]}
        for row in rows
    ]})


class ImpactRequest(BaseModel):
    kind: ArtifactKind
    id: str = Field(min_length=1)
    content: dict[str, Any]


def impact_view(report) -> dict[str, Any]:
    return {
        "target": report.target.model_dump(mode="json") if report.target else None,
        "unchanged": report.unchanged,
        "changes": [{"path": c.path, "before": c.before, "after": c.after, "kind": c.kind} for c in report.changes],
        "affected": [{"ref": i.ref.model_dump(mode="json"), "status": i.status.value, "effect": i.effect,
                      "needs_signature": i.needs_signature} for i in report.affected],
        "notes": list(report.notes),
    }


@router.post("/projects/{project_id}/impact")
def preview_impact(project_id: str, body: ImpactRequest, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """What saving `content` as the next version of `kind/id` would change and make stale. Saves nothing."""
    ws = workspace_for(project_id, principal, store)
    return envelope(impact_view(ws.impact(body.kind, body.id, body.content)))


@router.get("/projects/{project_id}/audit")
def get_audit(project_id: str, principal: Reader, store: StoreDep, limit: int = 200) -> dict[str, Any]:
    """This project's audit events (newest first) and whether the tenant's chain verifies."""
    ws = workspace_for(project_id, principal, store)
    log = store.audit(ws.tenant_id)
    prefix = f"{project_id}/"
    events = [r for r in log.records() if r.event.resource_id.startswith(prefix)]
    broken = log.verify()
    return envelope({
        "chain_verifies": broken is None, "first_broken_index": broken,
        "events": [{"seq": r.event.seq, "occurred_at": r.event.occurred_at, "actor": r.event.actor,
                    "action": r.event.action, "resource_type": r.event.resource_type, "resource_id": r.event.resource_id,
                    "before": r.event.before, "after": r.event.after, "reason": r.event.reason, "row_hash": r.row_hash}
                   for r in reversed(events[-max(1, min(limit, 2000)):])],
    })


# --- blinding (D-15) ------------------------------------------------------------------------------------------------


def _project_record(ws: Workspace) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.read_root:
        return None
    from modeler_api.filestore import FileReadStore

    return FileReadStore(settings.read_root).get_project(ws.tenant_id, ws.project_id)


def _model_risk(ws: Workspace) -> str | None:
    """The human-confirmed model risk: the plan's (P5) once it exists, else the brief's acceptance tier."""
    plan = ws.latest(ArtifactKind.MODEL_PLAN, "main")
    if plan is not None:
        return (plan.content.get("structure") or {}).get("model_risk")
    brief = ws.latest(ArtifactKind.BRIEF, "main")
    if brief is None:
        return None
    from modeler_project.brief import ProjectBrief

    return ProjectBrief.from_content(brief.content).value("acceptance.tier")


def blinded_studies(ws: Workspace) -> set[str]:
    return blind.blinded_studies(ws, _project_record(ws), _model_risk(ws))


def redact(ws: Workspace, kind: ArtifactKind, content: dict[str, Any], hidden: set[str] | None = None) -> dict[str, Any]:
    """An artifact's content as the viewer may see it: blinded external values left out (D-15)."""
    if kind not in (ArtifactKind.DATASET, ArtifactKind.STUDY_CATALOG):
        return content
    hidden = blinded_studies(ws) if hidden is None else hidden
    if not hidden:
        return content
    if kind is ArtifactKind.DATASET:
        return blind.redact_dataset(content) if str((content.get("study") or {}).get("study_id")) in hidden else content
    return {**content, "studies": [blind.redact_row(r) if str(r.get("study_id")) in hidden else r
                                   for r in content.get("studies", [])]}


def _hidden_paths(ws: Workspace, kind: ArtifactKind, content: dict[str, Any]) -> tuple[str, ...]:
    """History paths that would show blinded values (a dataset's series and reported PK, a catalog's studies)."""
    if kind is ArtifactKind.DATASET and str((content.get("study") or {}).get("study_id")) in blinded_studies(ws):
        return ("series", "reported")
    if kind is ArtifactKind.STUDY_CATALOG and blinded_studies(ws):
        return ("studies",)
    return ()


def blinding_view(ws: Workspace) -> dict[str, Any]:
    state = blind.setting(_project_record(ws), _model_risk(ws))
    return {**state, "map_signed": blind.map_signed(ws), "blinded": sorted(blinded_studies(ws)),
            "external": sorted(blind.external_studies(ws))}


@router.get("/projects/{project_id}/blinding")
def get_blinding(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope(blinding_view(workspace_for(project_id, principal, store)))


class BlindingRequest(BaseModel):
    on: bool
    reason: str = Field(min_length=1)


@router.put("/projects/{project_id}/blinding")
def set_blinding(project_id: str, body: BlindingRequest, principal: MiddLead, store: StoreDep) -> dict[str, Any]:
    """The MIDD lead's choice for this project (D-15), with its reason, on the audit chain."""
    from modeler_api.filestore import FileWriteStore

    ws = workspace_for(project_id, principal, store)
    project = _project_record(ws)
    if project is None:
        raise HTTPException(status_code=404, detail="the project record is not in the read store")
    before = blind.setting(project, _model_risk(ws))
    choice = {"on": body.on, "reason": body.reason, "by": principal.user_id, "at": datetime.now(UTC).isoformat()}
    FileWriteStore(get_settings().read_root).put_project(ws.tenant_id, {**project, "blinding": choice})
    store.audit(ws.tenant_id).append(actor=principal.user_id, action="blinding.set", resource_type="project",
                                     resource_id=f"{project_id}/blinding", before=before["on"], after=body.on,
                                     reason=body.reason)
    return envelope(blinding_view(ws))


class RevealRequest(BaseModel):
    reason: str = Field(min_length=1)


@router.post("/projects/{project_id}/datasets/{dataset_id}:reveal")
def reveal_dataset(project_id: str, dataset_id: str, body: RevealRequest, principal: Writer,
                   store: StoreDep) -> dict[str, Any]:
    """A blinded dataset's values for one check (digitization, acceptance), with the reason on the audit chain."""
    ws = workspace_for(project_id, principal, store)
    version = ws.latest(ArtifactKind.DATASET, dataset_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"no dataset {dataset_id}")
    sid = str((version.content.get("study") or {}).get("study_id"))
    if sid in blinded_studies(ws):
        store.audit(ws.tenant_id).append(actor=principal.user_id, action="dataset.reveal", resource_type="dataset",
                                         resource_id=f"{project_id}/{dataset_id}@v{version.version}",
                                         after=version.sha256, reason=body.reason)
    return envelope(version.content)
