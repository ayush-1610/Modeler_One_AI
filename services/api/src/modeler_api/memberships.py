"""Project access from the platform's own memberships (production readiness P3; `modeler_project.members`).

A signed-in person is admitted to the projects their token's `projects` claim names and to those they are a member of
on the platform: a project's creator, and the people its members add. Each person who signs in is remembered, so a
member can add them. The DEV principal's `*` membership (pilot, development) is left as it is.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from modeler_api.part11 import audit_mirror
from modeler_project import FileProjectStore
from modeler_project.archive import ProjectArchive
from modeler_project.members import Memberships

if TYPE_CHECKING:
    from modeler_api.auth import Principal
    from modeler_api.config import Settings


def memberships_for(settings: Settings, tenant_id: str) -> Memberships:
    store = FileProjectStore(settings.read_root, audit_mirror=audit_mirror(settings))
    return Memberships(store.root, tenant_id, store.audit(tenant_id))


def archive_for(settings: Settings, tenant_id: str) -> ProjectArchive:
    """The tenant's archived projects (page review 1: archive, never delete), audited like the memberships."""
    store = FileProjectStore(settings.read_root, audit_mirror=audit_mirror(settings))
    return ProjectArchive(store.root, tenant_id, store.audit(tenant_id))


def admit(principal: Principal, settings: Settings) -> Principal:
    """The principal with its platform memberships added to the token's projects."""
    if not settings.read_root or "*" in principal.projects:
        return principal
    memberships = memberships_for(settings, principal.tenant_id)
    memberships.remember(principal.user_id, principal.printed_name)
    return dataclasses.replace(principal, projects=principal.projects | memberships.projects_of(principal.user_id))


def record_creator(settings: Settings, principal: Principal, project_id: str) -> None:
    """A new project's creator is its first member."""
    if settings.read_root:
        memberships = memberships_for(settings, principal.tenant_id)
        memberships.remember(principal.user_id, principal.printed_name)
        memberships.add(project_id, principal.user_id, by=principal.user_id, reason="created the project")
