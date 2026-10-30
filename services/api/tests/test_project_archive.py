"""Archiving a project (page review 1, the owner's decision 5 of 2026-10-29: archive, never delete).

A project is a Part 11 record, so it is never erased: archiving hides it from the Projects list and keeps everything it
holds; restoring shows it again. Both need a reason and are audit events; a project with a campaign still running is
not archived.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_storage.filestore import FileWriteStore

pytestmark = pytest.mark.req("T-05")

ROLES = ["modeler-viewer", "modeler-curator", "modeler-reviewer"]


class _Verifier:
    def verify(self, token: str) -> dict:
        return {"sub": token, "name": token.title(), "tenant_id": "acme", "realm_access": {"roles": ROLES},
                "projects": [], "acr": "loa1"}


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


ANA = {"Authorization": "Bearer ana"}


def _create(client: TestClient, name: str) -> str:
    answer = client.post("/api/v1/projects", json={"name": name, "compound": "Drugol"}, headers=ANA)
    assert answer.status_code == 201, answer.text
    return answer.json()["data"]["id"]


def _listed(client: TestClient) -> dict[str, dict | None]:
    return {p["id"]: p["archived"] for p in client.get("/api/v1/projects", headers=ANA).json()["data"]["projects"]}


def _audit(tmp_path) -> list[dict]:
    lines = (tmp_path / "acme" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event"] for line in lines]


def test_an_archived_project_is_kept_marked_with_who_and_why_and_restored_with_a_reason(client, tmp_path):
    test, real = _create(client, "Test project"), _create(client, "Real project")
    assert _listed(client) == {test: None, real: None}
    no_reason = client.post(f"/api/v1/projects/{test}:archive", json={"reason": ""}, headers=ANA)
    assert no_reason.status_code == 422
    archived = client.post(f"/api/v1/projects/{test}:archive", json={"reason": "a test project, not client work"}, headers=ANA)
    assert archived.status_code == 200, archived.text
    state = archived.json()["data"]
    assert state["project_id"] == test and state["archived"]["by"] == "ana"
    assert state["archived"]["reason"] == "a test project, not client work"
    listed = _listed(client)
    assert listed[real] is None and listed[test]["reason"] == "a test project, not client work"   # listed, marked
    assert client.get(f"/api/v1/projects/{test}", headers=ANA).status_code == 200                 # nothing is erased
    restored = client.post(f"/api/v1/projects/{test}:restore", json={"reason": "archived by mistake"}, headers=ANA)
    assert restored.status_code == 200 and restored.json()["data"]["archived"] is None
    events = [e for e in _audit(tmp_path) if e["action"].startswith("project.")]
    archive, restore = (e for e in events if e["action"] in ("project.archive", "project.restore"))
    assert (archive["action"], archive["resource_id"], archive["reason"]) == ("project.archive", test,
                                                                              "a test project, not client work")
    assert (restore["action"], restore["reason"], restore["before"]["by"]) == ("project.restore", "archived by mistake", "ana")
    # the project's own record shows them, with its members (events on the project itself, not on an artifact)
    history = [e["action"] for e in client.get(f"/api/v1/projects/{test}/audit", headers=ANA).json()["data"]["events"]]
    assert history[:2] == ["project.restore", "project.archive"] and "project.member.add" in history


def test_a_project_with_a_running_campaign_is_not_archived(client, tmp_path):
    pid = _create(client, "Busy project")
    FileWriteStore(str(tmp_path)).upsert_campaign("acme", {"id": "camp-1", "project": pid, "status": "RUNNING"})
    refused = client.post(f"/api/v1/projects/{pid}:archive", json={"reason": "done"}, headers=ANA)
    assert refused.status_code == 409 and "camp-1" in refused.json()["detail"]
    assert _listed(client)[pid] is None


def test_a_project_the_person_may_not_open_is_not_archived(client):
    pid = _create(client, "Ana's project")
    assert client.post(f"/api/v1/projects/{pid}:archive", json={"reason": "x"},
                       headers={"Authorization": "Bearer ben"}).status_code == 403
