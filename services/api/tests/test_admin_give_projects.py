"""Giving a person projects from the admin console: how the projects made under the pilot's DEV sign-in reach the people
who sign in through Keycloak (deploy/keycloak/README.md, going live). Only `modeler-admin` with a fresh step-up; each
membership an audit event on the company's chain."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app

pytestmark = pytest.mark.req("T-05", "T-06")

WORK = ["modeler-viewer", "modeler-curator", "modeler-reviewer"]
PEOPLE = {"owner": ("platform", ["modeler-admin"]), "ana": ("dev", WORK), "kc-ayush": ("dev", WORK)}


class _Verifier:
    """`Bearer owner` is the platform's owner with a fresh step-up; `-stale` without one."""

    def verify(self, token: str) -> dict:
        who = token.removesuffix("-stale")
        tenant, roles = PEOPLE[who]
        fresh = not token.endswith("-stale")
        return {"sub": who, "name": who.title(), "tenant_id": tenant, "realm_access": {"roles": roles}, "projects": [],
                "acr": "loa2" if fresh else "loa1", "auth_time": int(time.time()) if fresh else None}


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _create(client: TestClient, who: str, name: str) -> str:
    answer = client.post("/api/v1/projects", json={"name": name, "compound": "Exampleamide"}, headers=_as(who))
    assert answer.status_code == 201, answer.text
    return answer.json()["data"]["id"]


def test_a_persons_projects_or_every_project_of_the_company_are_given_with_a_step_up_and_audited(client, tmp_path):
    made = _create(client, "ana", "Renal Demo")                        # ana stands for the DEV sign-in's dev-user
    projects = tmp_path / "dev" / "projects.json"
    doc = json.loads(projects.read_text(encoding="utf-8"))
    doc["projects"].append({**doc["projects"][0], "id": "older", "name": "Made before memberships"})   # no member at all
    projects.write_text(json.dumps(doc), encoding="utf-8")
    client.get("/api/v1/projects", headers=_as("kc-ayush"))           # the Keycloak person signs in once
    assert client.get(f"/api/v1/projects/{made}", headers=_as("kc-ayush")).status_code == 403

    stale = client.post("/api/v1/admin/companies/dev:give-projects", json={"to": "kc-ayush", "from": "ana", "reason": "x"},
                        headers=_as("owner-stale"))
    assert stale.status_code == 403 and stale.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    page = client.post("/api/v1/admin/companies/dev:give-projects",
                       json={"to": "kc-ayush", "from": "ana", "reason": "going live on Keycloak"}, headers=_as("owner"))
    assert page.status_code == 200, page.text
    assert client.get(f"/api/v1/projects/{made}", headers=_as("kc-ayush")).status_code == 200
    assert client.get("/api/v1/projects/older", headers=_as("kc-ayush")).status_code == 403

    client.post("/api/v1/admin/companies/dev:give-projects", json={"to": "kc-ayush", "reason": "the older ones too"},
                headers=_as("owner"))
    assert client.get("/api/v1/projects/older", headers=_as("kc-ayush")).status_code == 200
    events = [json.loads(line)["event"] for line in (tmp_path / "dev" / "audit.jsonl").read_text().splitlines()]
    given = [e for e in events if e["action"] == "project.member.add" and e["after"] == {"member": "kc-ayush"}]
    assert [(e["actor"], e["resource_id"]) for e in given] == [("owner", made), ("owner", "older")]
    assert given[0]["reason"] == "admin console: the projects of ana: going live on Keycloak"
    assert given[1]["reason"] == "admin console: every project of the company: the older ones too"


def test_only_someone_who_has_signed_in_receives_projects_and_only_the_owner_gives_them(client):
    _create(client, "ana", "Renal Demo")
    unknown = client.post("/api/v1/admin/companies/dev:give-projects", json={"to": "nobody", "reason": "x"},
                          headers=_as("owner"))
    assert unknown.status_code == 409 and "signed in" in unknown.json()["detail"]
    refused = client.post("/api/v1/admin/companies/dev:give-projects", json={"to": "ana", "reason": "x"}, headers=_as("ana"))
    assert refused.status_code == 403
    assert client.post("/api/v1/admin/companies/nope:give-projects", json={"to": "ana", "reason": "x"},
                       headers=_as("owner")).status_code == 404
