"""Only a project's owner changes it (the owner, 2026-11-10, answers 4 and 6): its creator owns it; the people it is
shared with read it; a reviewer among them still signs it; the administrator can give it another owner."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app

pytestmark = pytest.mark.req("T-05", "T-06")

CURATOR = ["modeler-viewer", "modeler-curator"]
REVIEWER = ["modeler-viewer", "modeler-reviewer"]
PEOPLE = {"ana": CURATOR, "ben": CURATOR, "rita": REVIEWER, "owner": ["modeler-admin"]}


class _Verifier:
    def verify(self, token: str) -> dict:
        return {"sub": token, "name": token.title(), "tenant_id": "acme" if token != "owner" else "platform",
                "realm_access": {"roles": PEOPLE[token]}, "projects": [], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _shared(client: TestClient) -> str:
    """ana makes a project and shares it with ben and rita."""
    pid = client.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Renaldrug"}, headers=_as("ana")).json()["data"]["id"]
    for who in ("ben", "rita"):
        client.get("/api/v1/projects", headers=_as(who))                 # each signs in once
        assert client.post(f"/api/v1/projects/{pid}/members", json={"subject": who}, headers=_as("ana")).status_code == 200
    return pid


def test_the_creator_owns_the_project_and_the_people_it_is_shared_with_read_it(client):
    pid = _shared(client)
    page = client.get(f"/api/v1/projects/{pid}/members", headers=_as("ben")).json()["data"]
    assert (page["owner"], page["owner_name"], page["you_change_it"]) == ("ana", "Ana", False)
    assert client.get(f"/api/v1/projects/{pid}/members", headers=_as("ana")).json()["data"]["you_change_it"] is True
    assert client.get(f"/api/v1/projects/{pid}", headers=_as("ben")).status_code == 200          # reads
    for path, body in ((f"/api/v1/projects/{pid}:archive", {"reason": "done"}),
                       (f"/api/v1/projects/{pid}/members", {"subject": "rita"})):
        refused = client.post(path, json=body, headers=_as("ben"))
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "NOT_OWNER"
        assert "only the project's owner, Ana, changes it" in refused.json()["detail"]["message"]
    assert client.post(f"/api/v1/projects/{pid}:archive", json={"reason": "done"}, headers=_as("ana")).status_code == 200


def test_a_reviewer_it_is_shared_with_still_signs_it_but_changes_nothing_else(client):
    pid = _shared(client)
    body = {"meaning": "approval", "record_type": "artifact", "record_id": "x", "record_sha256": "0" * 64}
    signed = client.post(f"/api/v1/projects/{pid}/signatures", json=body, headers=_as("rita"))
    assert not (signed.status_code == 403 and "NOT_OWNER" in signed.text)      # past the owner rule (the signature's own checks follow)
    archived = client.post(f"/api/v1/projects/{pid}:archive", json={"reason": "x"}, headers=_as("rita"))
    assert archived.status_code == 403 and archived.json()["detail"]["code"] == "NOT_OWNER"


def test_the_owner_stays_a_member_and_the_administrator_gives_the_project_another_owner(client, tmp_path):
    pid = _shared(client)
    stays = client.post(f"/api/v1/projects/{pid}/members:remove", json={"subject": "ana", "reason": "x"}, headers=_as("ana"))
    assert stays.status_code == 409 and "the owner stays a member" in stays.json()["detail"]
    given = client.post("/api/v1/admin/companies/acme:give-projects",
                        json={"to": "ben", "from": "ana", "owner": True, "reason": "Ana left"}, headers=_as("owner"))
    assert given.status_code == 200, given.text
    assert client.post(f"/api/v1/projects/{pid}:archive", json={"reason": "x"}, headers=_as("ana")).status_code == 403
    assert client.post(f"/api/v1/projects/{pid}:archive", json={"reason": "x"}, headers=_as("ben")).status_code == 200
    events = [json.loads(line)["event"] for line in (tmp_path / "acme" / "audit.jsonl").read_text().splitlines()]
    (change,) = [e for e in events if e["action"] == "project.owner.set" and e["actor"] == "owner"]
    assert (change["before"], change["after"], change["reason"]) == ({"owner": "ana"}, {"owner": "ben"},
                                                                     "admin console: the projects of ana: Ana left")


def test_a_project_made_before_owners_were_kept_takes_its_creator_and_one_with_no_creator_keeps_the_old_rule(client, tmp_path):
    pid = _shared(client)
    members = tmp_path / "acme" / "members.json"
    doc = json.loads(members.read_text(encoding="utf-8"))
    doc.pop("owners")                                                       # as written before this change
    members.write_text(json.dumps(doc), encoding="utf-8")
    assert client.get(f"/api/v1/projects/{pid}/members", headers=_as("ben")).json()["data"]["owner"] == "ana"
    for row in doc["projects"][pid].values():
        row["added_by"] = "someone else"                                   # no member added themselves: no creator known
    members.write_text(json.dumps(doc), encoding="utf-8")
    page = client.get(f"/api/v1/projects/{pid}/members", headers=_as("ben")).json()["data"]
    assert page["owner"] is None and page["you_change_it"] is True
    assert client.post(f"/api/v1/projects/{pid}:archive", json={"reason": "x"}, headers=_as("ben")).status_code == 200


def test_a_signed_campaign_decision_is_the_owners_or_a_reviewers_it_is_shared_with(client, tmp_path):
    pid = _shared(client)
    campaign = {"id": "camp-1", "project": pid, "compound": "Renaldrug", "status": "ESCALATED", "stages": []}
    (tmp_path / "acme" / "campaigns.json").write_text(json.dumps({"campaigns": [campaign]}), encoding="utf-8")
    body = {"action": "abort", "note": "x"}
    refused = client.post("/api/v1/campaigns/camp-1/stages/S2/escalation:resolve", json=body, headers=_as("ben"))
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "NOT_OWNER"
    for who in ("ana", "rita"):                     # past the owner rule: refused next because no escalation is open
        passed = client.post("/api/v1/campaigns/camp-1/stages/S2/escalation:resolve", json=body, headers=_as(who))
        assert passed.status_code == 409 and "not open" in passed.json()["detail"], passed.text


def test_every_write_to_a_project_passes_the_owner_rule():
    """A router added later whose routes change a project must carry `owner_guard` (main.py `OWNER_ONLY_WRITES`)."""
    from modeler_api.ownership import owner_guard

    writes, unguarded = 0, []
    for included in (r for r in app.router.routes if hasattr(r, "original_router")):
        context = included.include_context
        guarded = any(d.dependency is owner_guard for d in context.dependencies or [])
        for route in included.original_router.routes:
            path = (context.prefix or "") + route.path
            if "{project_id}" in path and set(getattr(route, "methods", ())) & {"POST", "PUT", "PATCH", "DELETE"}:
                writes += 1
                if not guarded and not any(d.dependency is owner_guard for d in route.dependencies):
                    unguarded.append(path)
    assert writes > 50 and unguarded == []
