"""The project list can carry each project's steps and its owner's name (the console redesign, R-N03): Home, Your work
and Projects read them in one request instead of one `/steps` and one `/members` per project. Only on request
(`?with=steps,owner`), so other callers keep today's payload and cost."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app

pytestmark = pytest.mark.req("T-05", "T-06")

CURATOR = ["modeler-viewer", "modeler-curator"]
PEOPLE = {"ana": CURATOR, "ben": CURATOR}


class _Verifier:
    def verify(self, token: str) -> dict:
        return {"sub": token, "name": token.title(), "tenant_id": "acme", "realm_access": {"roles": PEOPLE[token]},
                "projects": [], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _two_projects(client: TestClient) -> tuple[str, str]:
    """ana makes two projects and shares the first with ben."""
    shared = client.post("/api/v1/projects", json={"name": "Shared", "compound": "Sharedol"}, headers=_as("ana")).json()["data"]["id"]
    own = client.post("/api/v1/projects", json={"name": "Own", "compound": "Ownol"}, headers=_as("ana")).json()["data"]["id"]
    client.get("/api/v1/projects", headers=_as("ben"))                     # ben signs in once
    assert client.post(f"/api/v1/projects/{shared}/members", json={"subject": "ben"}, headers=_as("ana")).status_code == 200
    return shared, own


def test_the_list_carries_each_projects_steps_as_its_steps_route_answers_them(client):
    shared, own = _two_projects(client)
    listed = client.get("/api/v1/projects", params={"with": "steps,owner"}, headers=_as("ana"))
    assert listed.status_code == 200, listed.text
    items = {p["id"]: p for p in listed.json()["data"]["projects"]}
    assert set(items) == {shared, own}
    for pid, item in items.items():
        alone = client.get(f"/api/v1/projects/{pid}/steps", headers=_as("ana")).json()["data"]["steps"]
        assert item["steps"] == alone
        assert (item["owner"], item["owner_name"]) == ("ana", "Ana")


def test_a_member_sees_only_the_projects_shared_with_them_and_whose_they_are(client):
    shared, _ = _two_projects(client)
    items = client.get("/api/v1/projects", params={"with": "steps,owner"}, headers=_as("ben")).json()["data"]["projects"]
    assert [p["id"] for p in items] == [shared]
    assert items[0]["owner_name"] == "Ana" and [s["step"] for s in items[0]["steps"]] == ["start", "inputs", "review", "run"]


def test_without_with_the_list_is_unchanged_and_each_part_comes_alone(client):
    _two_projects(client)
    plain = client.get("/api/v1/projects", headers=_as("ana")).json()["data"]["projects"]
    assert all("steps" not in p and "owner" not in p and "owner_name" not in p for p in plain)
    only_owner = client.get("/api/v1/projects", params={"with": "owner"}, headers=_as("ana")).json()["data"]["projects"]
    assert all(p["owner_name"] == "Ana" and "steps" not in p for p in only_owner)


def test_an_unknown_part_is_refused_in_words(client):
    refused = client.get("/api/v1/projects", params={"with": "steps,secrets"}, headers=_as("ana"))
    assert refused.status_code == 422 and "secrets" in refused.text
