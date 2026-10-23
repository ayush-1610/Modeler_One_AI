"""Project members (production readiness P3; `modeler_project.members`, `modeler_api.memberships`, `members_api`).

A signed-in person opens the projects in their token's `projects` claim and those they are a member of on the
platform: a new project's creator is its first member and adds the people who have signed in. Every change is an
audit event; removing needs a reason, and a project keeps its last member. The DEV principal's `*` is unchanged.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app

pytestmark = pytest.mark.req("T-05", "T-06")

ROLES = ["modeler-viewer", "modeler-curator", "modeler-reviewer"]


class _Verifier:
    """Each bearer token is a person: `Bearer ana` signs in as subject `ana`."""

    def verify(self, token: str) -> dict:
        return {"sub": token, "name": token.title(), "tenant_id": "acme", "realm_access": {"roles": ROLES},
                "projects": ["from-the-token"] if token == "tok" else [], "acr": "loa1"}


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _create(client: TestClient, who: str, name: str = "Renal Demo") -> str:
    answer = client.post("/api/v1/projects", json={"name": name, "compound": "Renaldrug"}, headers=_as(who))
    assert answer.status_code == 201, answer.text
    return answer.json()["data"]["id"]


def _audit(tmp_path) -> list[dict]:
    lines = (tmp_path / "acme" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event"] for line in lines]


def test_the_creator_opens_the_new_project_and_others_do_not(client, tmp_path):
    pid = _create(client, "ana")
    assert client.get(f"/api/v1/projects/{pid}", headers=_as("ana")).status_code == 200
    assert client.get(f"/api/v1/projects/{pid}", headers=_as("ben")).status_code == 403
    page = client.get(f"/api/v1/projects/{pid}/members", headers=_as("ana")).json()["data"]
    assert [(m["subject"], m["name"], m["added_by"]) for m in page["members"]] == [("ana", "Ana", "Ana")]
    assert page["managed"] is True
    assert [e["action"] for e in _audit(tmp_path)] == ["project.member.add"]


def test_the_project_list_shows_only_the_persons_own_projects(client):
    mine = _create(client, "ana", "Ana's")
    _create(client, "ben", "Ben's")
    listed = client.get("/api/v1/projects", headers=_as("ana")).json()["data"]["projects"]
    assert [p["id"] for p in listed] == [mine]


def test_a_member_adds_a_person_who_has_signed_in_and_the_change_is_audited(client, tmp_path):
    pid = _create(client, "ana")
    refused = client.post(f"/api/v1/projects/{pid}/members", json={"subject": "ben"}, headers=_as("ana"))
    assert refused.status_code == 409 and "signed in" in refused.json()["detail"]
    client.get("/api/v1/projects", headers=_as("ben"))  # Ben signs in once
    assert client.get(f"/api/v1/projects/{pid}/members", headers=_as("ana")).json()["data"]["people"] == [
        {"subject": "ben", "name": "Ben"}]
    added = client.post(f"/api/v1/projects/{pid}/members", json={"subject": "ben", "reason": "reviews the fits"},
                        headers=_as("ana"))
    assert added.status_code == 200, added.text
    assert [m["subject"] for m in added.json()["data"]["members"]] == ["ana", "ben"]
    assert added.json()["data"]["people"] == []
    assert client.get(f"/api/v1/projects/{pid}", headers=_as("ben")).status_code == 200
    last = _audit(tmp_path)[-1]
    assert (last["actor"], last["action"], last["resource_id"], last["after"], last["reason"]) == (
        "ana", "project.member.add", pid, {"member": "ben"}, "reviews the fits")


def test_removing_needs_a_reason_and_a_project_keeps_its_last_member(client, tmp_path):
    pid = _create(client, "ana")
    client.get("/api/v1/projects", headers=_as("ben"))
    client.post(f"/api/v1/projects/{pid}/members", json={"subject": "ben"}, headers=_as("ana"))
    no_reason = client.post(f"/api/v1/projects/{pid}/members:remove", json={"subject": "ben", "reason": ""}, headers=_as("ana"))
    assert no_reason.status_code == 422
    removed = client.post(f"/api/v1/projects/{pid}/members:remove", json={"subject": "ben", "reason": "left the team"},
                          headers=_as("ana"))
    assert [m["subject"] for m in removed.json()["data"]["members"]] == ["ana"]
    assert client.get(f"/api/v1/projects/{pid}", headers=_as("ben")).status_code == 403
    last = client.post(f"/api/v1/projects/{pid}/members:remove", json={"subject": "ana", "reason": "done"}, headers=_as("ana"))
    assert last.status_code == 409 and "at least one member" in last.json()["detail"]
    assert [(e["action"], e["reason"]) for e in _audit(tmp_path)][-1] == ("project.member.remove", "left the team")


def test_a_non_member_can_neither_see_nor_change_the_members(client):
    pid = _create(client, "ana")
    client.get("/api/v1/projects", headers=_as("ben"))
    assert client.get(f"/api/v1/projects/{pid}/members", headers=_as("ben")).status_code == 403
    assert client.post(f"/api/v1/projects/{pid}/members", json={"subject": "ben"}, headers=_as("ben")).status_code == 403


def test_creating_a_project_with_anothers_project_name_does_not_join_it(client):
    theirs = _create(client, "ana")
    mine = _create(client, "ben")
    assert mine != theirs and mine.startswith(f"{theirs}-")
    assert client.get(f"/api/v1/projects/{theirs}", headers=_as("ben")).status_code == 403
    assert client.get(f"/api/v1/projects/{theirs}", headers=_as("ana")).json()["data"]["name"] == "Renal Demo"


def test_the_tokens_projects_claim_still_admits(client, tmp_path):
    (tmp_path / "acme").mkdir()
    (tmp_path / "acme" / "projects.json").write_text(json.dumps({"projects": [
        {"id": "from-the-token", "name": "Seeded", "compounds": ["X"], "openQuestions": 0, "risk": "low"}]}), encoding="utf-8")
    assert client.get("/api/v1/projects/from-the-token", headers=_as("tok")).status_code == 200
    assert [p["id"] for p in client.get("/api/v1/projects", headers=_as("tok")).json()["data"]["projects"]] == ["from-the-token"]


def test_the_dev_principal_keeps_every_project_and_writes_no_memberships(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path), dev_auth=True)
    with TestClient(app) as client:
        pid = client.post("/api/v1/projects", json={"name": "Dev", "compound": "X"}, headers=_as("dev")).json()["data"]["id"]
        page = client.get(f"/api/v1/projects/{pid}/members", headers=_as("dev")).json()["data"]
    assert page["managed"] is False
    assert [m["subject"] for m in page["members"]] == ["dev-user"]  # the creator is recorded; access stays `*`
