"""The project start-up pipeline's shared API: phases, artifacts, version history, impact preview, audit (T-40).

Every phase of `docs/plans/2026-09-25-project-startup-pipeline.md` stores its output as versioned artifacts in a
`modeler_project.Workspace`; these endpoints let the web app show the phase rail, any artifact and its history, what
an edit would make stale before it is saved (plan §13.2), and the project's audit trail. The phase-specific routers
(brief, requirements, evidence, client data, inputs, plan) build on `workspace_for`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modeler_api.auth import Principal, require_project, require_role
from modeler_api.config import get_settings
from modeler_api.responses import envelope
from modeler_project import ArtifactKind, ArtifactRef, ArtifactVersion, FileProjectStore, ProjectStore, Workspace
from modeler_project.workspace import PHASE_LABELS

router = APIRouter(prefix="/api/v1", tags=["project-pipeline"])

READ_ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer")
WRITE_ROLES = ("modeler-curator", "modeler-reviewer")
Reader = Annotated[Principal, Depends(require_role(*READ_ROLES))]
Writer = Annotated[Principal, Depends(require_role(*WRITE_ROLES))]


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
    return envelope(version_view(ws, found))


@router.get("/projects/{project_id}/artifacts/{kind}/{artifact_id}/history")
def get_history(project_id: str, kind: str, artifact_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    rows = ws.history(parse_kind(kind), artifact_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no {kind}/{artifact_id}")
    return envelope({"versions": [
        {**{k: v for k, v in row.items() if k not in ("ref", "approvals", "changes", "status", "created_at")},
         "version": row["ref"].version, "status": row["status"].value, "created_at": row["created_at"].isoformat(),
         "approvals": [a.model_dump(mode="json") for a in row["approvals"]],
         "changes": [{"path": c.path, "before": c.before, "after": c.after, "kind": c.kind} for c in row["changes"]]}
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
