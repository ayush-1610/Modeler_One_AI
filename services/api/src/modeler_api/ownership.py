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
from modeler_api.memberships import memberships_for, reads_only

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
    route = (request.method, getattr(request.scope.get("route"), "path", ""))
    ensure_owner(project_id, principal, settings, signing=route in SIGNING_ROUTES)


def ensure_owner(project_id: str, principal: Principal, settings: Settings, *, signing: bool = False) -> None:
    """Refuse a change to a project by anyone but its owner (a signing change: or a reviewer it is shared with).

    Also called by the routes that change a project through one of its campaigns (a signed escalation decision).
    A project with no owner on record (made before memberships were kept) keeps the earlier rule, its members edit,
    until the administrator gives it an owner. The pilot's DEV principal (`*`, every project) is left as it was."""
    if may_change(project_id, principal, settings, signing=signing):
        return
    memberships = memberships_for(settings, principal.tenant_id)
    owner = memberships.owner(project_id)
    name = next((p.name for p in memberships.people() if p.subject == owner), owner)
    raise HTTPException(status_code=403, detail={"code": "NOT_OWNER",
                                                 "message": f"only the project's owner, {name}, changes it; it is shared "
                                                            "with you to read"})


def may_change(project_id: str, principal: Principal, settings: Settings, *, signing: bool = False) -> bool:
    """`ensure_owner`'s rule as an answer rather than a refusal: whether this person may change the project (signing: or
    sign for it). Lists use it to say what a person may do, so a page never offers what the route will refuse (redesign
    review R-S02: the decision pop-up asked people who may not sign)."""
    if not settings.read_root or "*" in principal.projects:
        return True
    if reads_only(principal):           # QA reads every project of its company and changes or signs none (R-S05)
        return False
    if signing and REVIEWER in principal.roles:
        return True
    owner = memberships_for(settings, principal.tenant_id).owner(project_id)
    return owner is None or owner == principal.user_id
