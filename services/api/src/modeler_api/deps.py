"""What the API's routers share: roles, the project store, the workspace, artifact views and blinding (phase 5a).

These lived in `project_api`, a router, so every phase router imported another router (docs/ARCHITECTURE_BOUNDARIES.md,
rule B3 and coupling C3). A router imports from here; this module defines no route. Tests override `get_project_store`
(`app.dependency_overrides`), and `project_api` still re-exports it, so either name finds the same function.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException

from modeler_api.auth import Principal, require_project, require_role
from modeler_api.config import SettingsDep, get_settings
from modeler_project import ArtifactKind, ArtifactVersion, FileProjectStore, ProjectStore, Workspace
from modeler_project import blinding as blind

READ_ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer")
WRITE_ROLES = ("modeler-curator", "modeler-reviewer")
Reader = Annotated[Principal, Depends(require_role(*READ_ROLES))]
Writer = Annotated[Principal, Depends(require_role(*WRITE_ROLES))]
MiddLead = Annotated[Principal, Depends(require_role("modeler-reviewer"))]


def get_project_store(settings: SettingsDep) -> ProjectStore:
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


def impact_view(report) -> dict[str, Any]:
    return {
        "target": report.target.model_dump(mode="json") if report.target else None,
        "unchanged": report.unchanged,
        "changes": [{"path": c.path, "before": c.before, "after": c.after, "kind": c.kind} for c in report.changes],
        "affected": [{"ref": i.ref.model_dump(mode="json"), "status": i.status.value, "effect": i.effect,
                      "needs_signature": i.needs_signature} for i in report.affected],
        "notes": list(report.notes),
    }


def project_record(ws: Workspace) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.read_root:
        return None
    from modeler_storage.filestore import FileReadStore

    return FileReadStore(settings.read_root).get_project(ws.tenant_id, ws.project_id)


def model_risk(ws: Workspace) -> str | None:
    """The human-confirmed model risk: the plan's (P5) once it exists, else the brief's acceptance tier."""
    from modeler_project.plan import current

    _version, plan = current(ws)
    if plan is not None:
        return plan.structure.model_risk
    brief = ws.latest(ArtifactKind.BRIEF, "main")
    if brief is None:
        return None
    from modeler_project.brief import ProjectBrief

    return ProjectBrief.from_content(brief.content).value("acceptance.tier")


def blinded_studies(ws: Workspace) -> set[str]:
    return blind.blinded_studies(ws, project_record(ws), model_risk(ws))


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


def hidden_paths(ws: Workspace, kind: ArtifactKind, content: dict[str, Any]) -> tuple[str, ...]:
    """History paths that would show blinded values (a dataset's series and reported PK, a catalog's studies)."""
    if kind is ArtifactKind.DATASET and str((content.get("study") or {}).get("study_id")) in blinded_studies(ws):
        return ("series", "reported")
    if kind is ArtifactKind.STUDY_CATALOG and blinded_studies(ws):
        return ("studies",)
    return ()


def blinding_view(ws: Workspace) -> dict[str, Any]:
    state = blind.setting(project_record(ws), model_risk(ws))
    return {**state, "map_signed": blind.map_signed(ws), "blinded": sorted(blinded_studies(ws)),
            "external": sorted(blind.external_studies(ws))}
