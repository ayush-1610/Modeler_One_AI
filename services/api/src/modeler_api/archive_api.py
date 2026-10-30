"""Archiving a project (page review 1, the owner's decision 5 of 2026-10-29: archive, never delete).

``POST /projects/{id}:archive`` hides a project from the Projects list and ``POST /projects/{id}:restore`` shows it again.
Both need a reason and are audit events (`modeler_project.archive`); nothing the project holds is changed or erased. A
project is not archived while one of its campaigns is queued or running.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modeler_api.auth import require_project
from modeler_api.config import SettingsDep
from modeler_api.deps import Writer
from modeler_api.memberships import archive_for
from modeler_api.responses import answers, envelope
from modeler_api.views.read import ProjectArchiveState
from modeler_project.archive import ArchiveError
from modeler_storage.filestore import FileReadStore

router = APIRouter(prefix="/api/v1", tags=["projects"])

LIVE = ("QUEUED", "RUNNING")


class ArchiveRequest(BaseModel):
    reason: str = Field(min_length=1)


def _ready(settings: SettingsDep) -> None:
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Project storage is not configured. Set MODELER_READ_ROOT.")


def _state(settings: SettingsDep, tenant_id: str, project_id: str) -> dict[str, Any]:
    archived = archive_for(settings, tenant_id).archived().get(project_id)
    return envelope({"project_id": project_id, "archived": dataclasses.asdict(archived) if archived else None})


@router.post("/projects/{project_id}:archive", **answers(ProjectArchiveState))
def archive_project(project_id: str, body: ArchiveRequest, principal: Writer, settings: SettingsDep) -> dict[str, Any]:
    require_project(project_id, principal)
    _ready(settings)
    if FileReadStore(settings.read_root).get_project(principal.tenant_id, project_id) is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    live = [c["id"] for c in FileReadStore(settings.read_root).list_campaigns(principal.tenant_id)
            if c.get("project") == project_id and c.get("status") in LIVE]
    if live:
        raise HTTPException(status_code=409, detail=f"campaign {', '.join(live)} is still queued or running: let it finish "
                                                    "or stop it before the project is archived")
    try:
        archive_for(settings, principal.tenant_id).archive(project_id, by=principal.user_id, reason=body.reason)
    except ArchiveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _state(settings, principal.tenant_id, project_id)


@router.post("/projects/{project_id}:restore", **answers(ProjectArchiveState))
def restore_project(project_id: str, body: ArchiveRequest, principal: Writer, settings: SettingsDep) -> dict[str, Any]:
    require_project(project_id, principal)
    _ready(settings)
    try:
        archive_for(settings, principal.tenant_id).restore(project_id, by=principal.user_id, reason=body.reason)
    except ArchiveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _state(settings, principal.tenant_id, project_id)
