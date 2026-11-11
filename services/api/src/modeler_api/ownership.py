"""Only a project's owner changes it (the owner, 2026-11-10: "the one who creates project will be owner who only can
edit and do anything in project, sharing that project with other members within that company is available but they
can only see/read only"; `modeler_project.members` keeps the owner).

`owner_guard` is a dependency of every router whose routes act on a project (`main.py`): a write to a path with a
`{project_id}` passes for the project's owner, and for a reviewer on a signing route (answer 6); every read passes.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from modeler_api.auth import CurrentPrincipal, Principal
from modeler_api.config import Settings, SettingsDep
from modeler_api.memberships import memberships_for

# The writes a reviewer the project is shared with still makes: signing (the owner, 2026-11-10, answer 6: an approval
# by a second person, which ICH M15 and Part 11 review expect, not an edit).
SIGNING_ROUTES = frozenset({("POST", "/api/v1/projects/{project_id}/signatures"),
                            ("POST", "/api/v1/projects/{project_id}/plan:sign")})
REVIEWER = "modeler-reviewer"


def owner_guard(request: Request, principal: CurrentPrincipal, settings: SettingsDep) -> None:
    """Only a project's owner changes it; the people it is shared with read it (the owner, 2026-11-10, answer 4).

    A dependency of every router whose routes act on a project: a write (POST, PUT, PATCH, DELETE) to a path with a
    `{project_id}` passes for the project's owner, and for a reviewer on a signing route; reads pass."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    project_id = request.path_params.get("project_id")
    if not project_id:
        return
    route = request.scope.get("route")
    ensure_owner(project_id, principal, settings, signing=(request.method, getattr(route, "path", "")) in SIGNING_ROUTES)


def ensure_owner(project_id: str, principal: Principal, settings: Settings, *, signing: bool = False) -> None:
    """Refuse a change to a project by anyone but its owner (a signing change: or a reviewer it is shared with).

    Also called by the routes that change a project through one of its campaigns (a signed escalation decision).
    A project with no owner on record (made before memberships were kept) keeps the earlier rule, its members edit,
    until the administrator gives it an owner. The pilot's DEV principal (`*`, every project) is left as it was."""
    if not settings.read_root or "*" in principal.projects:
        return
    if signing and REVIEWER in principal.roles:
        return
    memberships = memberships_for(settings, principal.tenant_id)
    owner = memberships.owner(project_id)
    if owner is None or owner == principal.user_id:
        return
    name = next((p.name for p in memberships.people() if p.subject == owner), owner)
    raise HTTPException(status_code=403, detail={"code": "NOT_OWNER",
                                                 "message": f"only the project's owner, {name}, changes it; it is shared "
                                                            "with you to read"})
