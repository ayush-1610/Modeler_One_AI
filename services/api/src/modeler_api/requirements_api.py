"""P1 data plan and feasibility (plan §7, T-42 / T-43): derived from the brief, overridable item by item, approved.

The requirement matrix is a deterministic derivation of the brief (REQUIREMENTS/main, derived from BRIEF/main), so a
brief edit makes it stale and re-deriving brings it up to date; a person's overrides (provider, purpose, the literature
cross-check of a client item) are kept across re-derivations. The feasibility report (FEASIBILITY/main) is derived
the same way. The P1 gate closes when the brief and the data plan are both approved.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modeler_api.project_api import Reader, StoreDep, Writer, version_view, workspace_for
from modeler_api.responses import envelope
from modeler_project import ArtifactKind, ArtifactStatus, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.feasibility import check
from modeler_project.requirements import Provider, RequirementMatrix, RequirementOverride, derive

router = APIRouter(prefix="/api/v1", tags=["requirements"])
MAIN = "main"


def derive_data_plan(ws: Workspace, *, actor: str, reason: str, extra: RequirementOverride | None = None) -> None:
    """(Re-)derive the requirement matrix and the feasibility report from the latest brief."""
    brief_version = ws.latest(ArtifactKind.BRIEF, MAIN)
    if brief_version is None:
        raise HTTPException(status_code=404, detail="no brief to derive the data plan from")
    brief = ProjectBrief.from_content(brief_version.content)
    previous_version = ws.latest(ArtifactKind.REQUIREMENTS, MAIN)
    previous = RequirementMatrix.from_content(previous_version.content) if previous_version else None
    overrides = list(previous.overrides) if previous else []
    if extra is not None:
        overrides = [o for o in overrides if o.req_id != extra.req_id] + [extra]
    matrix = derive(brief, tuple(overrides), previous=previous)
    ws.commit(ArtifactKind.REQUIREMENTS, MAIN, matrix.to_content(), derived_from=[brief_version.ref], actor=actor,
              reason=reason)
    ws.commit(ArtifactKind.FEASIBILITY, MAIN, check(brief).to_content(), derived_from=[brief_version.ref], actor=actor,
              reason=reason)


def _view(ws: Workspace) -> dict[str, Any]:
    version = ws.latest(ArtifactKind.REQUIREMENTS, MAIN)
    if version is None:
        raise HTTPException(status_code=404, detail="no data plan yet: derive it from the brief")
    feasibility = ws.latest(ArtifactKind.FEASIBILITY, MAIN)
    brief_version = ws.latest(ArtifactKind.BRIEF, MAIN)
    matrix = RequirementMatrix.from_content(version.content)
    applicable = [i for i in matrix.items if i.applies != "no"]
    return {
        "artifact": version_view(ws, version, with_content=False),
        "matrix": matrix.to_content(),
        "counts": {
            "applicable": len(applicable),
            "by_provider": {p: sum(i.provider == p for i in applicable) for p in sorted({i.provider for i in applicable})},
            "undetermined": sum(i.applies == "undetermined" for i in matrix.items),
            "to_harvest": sum(i.pksim_status == "TO_HARVEST" for i in applicable),
        },
        "feasibility": {**(feasibility.content if feasibility else {"lines": []}),
                        "status": ws.status(feasibility).value if feasibility else None},
        "brief_status": ws.status(brief_version).value if brief_version else None,
    }


@router.post("/projects/{project_id}/requirements:derive")
def derive_requirements(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    derive_data_plan(ws, actor=principal.user_id, reason="derived from the brief")
    return envelope(_view(ws))


@router.get("/projects/{project_id}/requirements")
def get_requirements(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope(_view(workspace_for(project_id, principal, store)))


class OverrideRequest(BaseModel):
    provider: Provider | None = None
    purpose: str | None = None
    cross_check: bool | None = None
    reason: str = Field(min_length=1)


@router.put("/projects/{project_id}/requirements/{req_id}")
def override_requirement(project_id: str, req_id: str, body: OverrideRequest, principal: Writer,
                         store: StoreDep) -> dict[str, Any]:
    """A person's decision on one item (who provides it, for what, cross-check it) — kept across re-derivations."""
    ws = workspace_for(project_id, principal, store)
    current = ws.latest(ArtifactKind.REQUIREMENTS, MAIN)
    if current is None or RequirementMatrix.from_content(current.content).get(req_id) is None:
        raise HTTPException(status_code=404, detail=f"no requirement {req_id}")
    if body.provider is None and body.purpose is None and body.cross_check is None:
        raise HTTPException(status_code=422, detail="change the provider, the purpose or the cross-check")
    override = RequirementOverride(req_id=req_id, provider=body.provider, purpose=body.purpose,
                                   cross_check=body.cross_check, reason=body.reason, by=principal.user_id)
    derive_data_plan(ws, actor=principal.user_id, reason=f"{req_id}: {body.reason}", extra=override)
    return envelope(_view(ws))


class ApproveRequest(BaseModel):
    note: str = ""


@router.post("/projects/{project_id}/requirements:approve")
def approve_requirements(project_id: str, body: ApproveRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """Closes P1 with the brief (D-07: named approval). The brief must be approved first and the plan up to date."""
    ws = workspace_for(project_id, principal, store)
    brief = ws.latest(ArtifactKind.BRIEF, MAIN)
    if brief is None or ws.status(brief) is not ArtifactStatus.APPROVED:
        raise HTTPException(status_code=409, detail="approve the brief first: the data plan is derived from it")
    version = ws.latest(ArtifactKind.REQUIREMENTS, MAIN)
    if version is None:
        raise HTTPException(status_code=404, detail="no data plan")
    try:
        ws.approve(version.ref, by=principal.user_id, printed_name=principal.printed_name, meaning="Reviewed",
                   note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return envelope(_view(ws))
