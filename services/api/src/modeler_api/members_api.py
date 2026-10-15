"""Project members (production readiness P3; `modeler_project.members`).

``GET /projects/{id}/members`` lists who may open the project and the people a member can add (those who have signed
in to this workspace). Adding and removing are audited; removing needs a reason, and a project keeps its last member.
A person's access is their token's `projects` claim and these memberships (`modeler_api.memberships.admit`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modeler_api.auth import require_project
from modeler_api.config import SettingsDep
from modeler_api.deps import Reader, Writer
from modeler_api.memberships import memberships_for
from modeler_api.responses import answers, envelope
from modeler_api.views.members import MembersPage
from modeler_project.members import MembershipError

router = APIRouter(prefix="/api/v1", tags=["members"])


class MemberAdd(BaseModel):
    subject: str = Field(min_length=1)
    reason: str = ""


class MemberRemove(BaseModel):
    subject: str = Field(min_length=1)
    reason: str = Field(min_length=1)


def _page(settings: SettingsDep, tenant_id: str, project_id: str, *, managed: bool) -> dict[str, Any]:
    memberships = memberships_for(settings, tenant_id)
    members = memberships.members(project_id)
    current = {m.subject for m in members}
    return envelope({
        "members": [{"subject": m.subject, "name": m.name, "added_by": m.added_by, "added_at": m.added_at} for m in members],
        "people": [{"subject": p.subject, "name": p.name} for p in memberships.people() if p.subject not in current],
        "managed": managed,
    })


def _ready(settings: SettingsDep) -> None:
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Project storage is not configured. Set MODELER_READ_ROOT.")


@router.get("/projects/{project_id}/members", **answers(MembersPage))
def list_members(project_id: str, principal: Reader, settings: SettingsDep) -> dict[str, Any]:
    require_project(project_id, principal)
    _ready(settings)
    return _page(settings, principal.tenant_id, project_id, managed="*" not in principal.projects)


@router.post("/projects/{project_id}/members", **answers(MembersPage))
def add_member(project_id: str, body: MemberAdd, principal: Writer, settings: SettingsDep) -> dict[str, Any]:
    require_project(project_id, principal)
    _ready(settings)
    try:
        memberships_for(settings, principal.tenant_id).add(project_id, body.subject, by=principal.user_id,
                                                           reason=body.reason.strip() or "added by a member")
    except MembershipError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _page(settings, principal.tenant_id, project_id, managed="*" not in principal.projects)


@router.post("/projects/{project_id}/members:remove", **answers(MembersPage))
def remove_member(project_id: str, body: MemberRemove, principal: Writer, settings: SettingsDep) -> dict[str, Any]:
    require_project(project_id, principal)
    _ready(settings)
    try:
        memberships_for(settings, principal.tenant_id).remove(project_id, body.subject, by=principal.user_id,
                                                              reason=body.reason)
    except MembershipError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _page(settings, principal.tenant_id, project_id, managed="*" not in principal.projects)
