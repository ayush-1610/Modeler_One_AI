# Project members (production readiness P3, 2026-10-15)

Status: **built** (2026-10-15, branch `project-members`). The owner approved it in the production-readiness plan,
including the change to the locked `auth.py`, on 2026-10-15. Builds on K1–K3 (Keycloak) and P2 (Part 11 records).

## Why
Under Keycloak, the API opens a project only when its id is in the person's `projects` token claim
(`require_project`). A project made in the web therefore stayed closed to its own creator until an administrator
added its id in Keycloak. The DEV principal's `*` hid this in pilot and development.

## What is decided
1. **The platform keeps its own memberships**, per tenant in `<read_root>/<tenant>/members.json`
   (`modeler_project.members`). Writes are atomic under a cross-process file lock.
2. **A project's creator is its first member**, on both creation routes (`POST /projects`, `POST /projects:initiate`).
3. **A member adds people who have signed in to the tenant at least once.** Each person who signs in is remembered by
   token subject, with their name, so a member picks them from a list and never types an id.
4. **Removing needs a reason, and a project keeps its last member.**
5. **Every change is an audit event** (`project.member.add`, `project.member.remove`, with the reason). In production
   the audit chain is mirrored to PostgreSQL (P2), so the membership history is there too.
6. **Access is the token's claim plus the memberships** (`modeler_api.memberships.admit`, called by
   `auth.current_principal`). The Keycloak `projects` attribute stays valid; it is needed only for projects made before
   this, or outside the web.
7. **The project list shows only the projects the person may open.**
8. **The DEV principal is unchanged:** its `*` still opens every project. The creator is recorded, and the panel says
   that memberships take effect under Keycloak sign-in.
9. **`POST /projects` no longer overwrites a project the person may not open.** A same-named project gets a new id, as
   `POST /projects:initiate` already did.

## Locked file changed (named in the CHANGELOG, hash refreshed)
- `services/api/src/modeler_api/auth.py`: `current_principal` adds the platform memberships.

## Tests
- `services/api/tests/test_project_members.py` (8): creator access and 403 for others; the filtered list; adding
  needs a signed-in person; removing needs a reason and keeps the last member; non-members can neither read nor change
  members; a same-named project does not join another's; the token claim still admits; the DEV principal is unchanged.
- `apps/web/e2e/members.spec.ts` (dev mode) and `apps/web/e2e/oidc-signing.spec.ts` against Keycloak: a colleague is
  refused, added in the Members panel, and then opens the project.
