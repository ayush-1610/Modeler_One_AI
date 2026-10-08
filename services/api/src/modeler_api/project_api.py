"""The project start-up pipeline's shared API: phases, artifacts, version history, impact preview, audit (T-40).

Every phase of `docs/plans/2026-09-25-project-startup-pipeline.md` stores its output as versioned artifacts in a
`modeler_project.Workspace`; these endpoints let the web app show the phase rail, any artifact and its history, what
an edit would make stale before it is saved (plan §13.2), and the project's audit trail. The phase-specific routers
(brief, requirements, evidence, client data, inputs, plan) build on `workspace_for`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modeler_api.config import get_settings
from modeler_api.deps import (  # noqa: F401 - re-exported: tests override project_api.get_project_store
    MiddLead,
    Reader,
    StoreDep,
    Writer,
    blinded_studies,
    blinding_view,
    get_project_store,
    hidden_paths,
    impact_view,
    model_risk,
    parse_kind,
    project_record,
    redact,
    version_view,
    workspace_for,
)
from modeler_api.responses import answers, envelope
from modeler_api.views.common import ImpactView, StoredContent, VersionView
from modeler_api.views.project import Artifacts, AuditTrail, BlindingView, History, Phases
from modeler_project import ArtifactKind, ArtifactRef
from modeler_project import blinding as blind
from modeler_project.datasets import ObservedDataset
from modeler_project.workspace import PHASE_LABELS

router = APIRouter(prefix="/api/v1", tags=["project-pipeline"])



@router.get("/projects/{project_id}/phases", **answers(Phases))
def get_phases(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    phases = ws.phases()
    return envelope({
        "phases": [{"phase": p, "label": PHASE_LABELS[p], "status": s.value} for p, s in phases.items()],
        "stale": [{"ref": item.ref.model_dump(mode="json"), "reasons": list(item.reasons)} for item in ws.stale()],
    })


@router.get("/projects/{project_id}/artifacts", **answers(Artifacts))
def list_artifacts(project_id: str, principal: Reader, store: StoreDep, kind: str | None = None) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    versions = ws.list(parse_kind(kind) if kind else None)
    return envelope({"artifacts": [version_view(ws, v, with_content=False) for v in versions]})


@router.get("/projects/{project_id}/artifacts/{kind}/{artifact_id}", **answers(VersionView))
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


@router.get("/projects/{project_id}/artifacts/{kind}/{artifact_id}/history", **answers(History))
def get_history(project_id: str, kind: str, artifact_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    k = parse_kind(kind)
    rows = ws.history(k, artifact_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no {kind}/{artifact_id}")
    hidden = hidden_paths(ws, k, ws.latest(k, artifact_id).content)
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


@router.post("/projects/{project_id}/impact", **answers(ImpactView))
def preview_impact(project_id: str, body: ImpactRequest, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """What saving `content` as the next version of `kind/id` would change and make stale. Saves nothing."""
    ws = workspace_for(project_id, principal, store)
    return envelope(impact_view(ws.impact(body.kind, body.id, body.content)))


@router.get("/projects/{project_id}/audit", **answers(AuditTrail))
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


# --- blinding (D-15): the views live in modeler_api.deps ------------------------------------------------------------


@router.get("/projects/{project_id}/blinding", **answers(BlindingView))
def get_blinding(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope(blinding_view(workspace_for(project_id, principal, store)))


class BlindingRequest(BaseModel):
    on: bool
    reason: str = Field(min_length=1)


@router.put("/projects/{project_id}/blinding", **answers(BlindingView))
def set_blinding(project_id: str, body: BlindingRequest, principal: MiddLead, store: StoreDep) -> dict[str, Any]:
    """The MIDD lead's choice for this project (D-15), with its reason, on the audit chain."""
    from modeler_storage.filestore import FileWriteStore

    ws = workspace_for(project_id, principal, store)
    project = project_record(ws)
    if project is None:
        raise HTTPException(status_code=404, detail="the project record is not in the read store")
    before = blind.setting(project, model_risk(ws))
    choice = {"on": body.on, "reason": body.reason, "by": principal.user_id, "at": datetime.now(UTC).isoformat()}
    FileWriteStore(get_settings().read_root).put_project(ws.tenant_id, {**project, "blinding": choice})
    store.audit(ws.tenant_id).append(actor=principal.user_id, action="blinding.set", resource_type="project",
                                     resource_id=f"{project_id}/blinding", before=before["on"], after=body.on,
                                     reason=body.reason)
    return envelope(blinding_view(ws))


class RevealRequest(BaseModel):
    reason: str = Field(min_length=1)


@router.post("/projects/{project_id}/datasets/{dataset_id}:reveal", **answers(StoredContent))
def reveal_dataset(project_id: str, dataset_id: str, body: RevealRequest, principal: Writer,
                   store: StoreDep) -> dict[str, Any]:
    """A blinded dataset's values for one check (digitization, acceptance), with the reason on the audit chain."""
    ws = workspace_for(project_id, principal, store)
    version = ws.latest(ArtifactKind.DATASET, dataset_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"no dataset {dataset_id}")
    sid = str(ObservedDataset.from_content(version.content).study.get("study_id"))
    if sid in blinded_studies(ws):
        store.audit(ws.tenant_id).append(actor=principal.user_id, action="dataset.reveal", resource_type="dataset",
                                         resource_id=f"{project_id}/{dataset_id}@v{version.version}",
                                         after=version.sha256, reason=body.reason)
    return envelope(version.content)
