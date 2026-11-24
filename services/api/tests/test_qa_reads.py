"""R-S05 (design-review/BACKEND_CHANGE_REQUIREMENTS.md; the owner's default, not objected): the QA role reads every
project of its company, and changes or signs none of them, a project with no owner on record included (whose members
edit it). Another company's projects stay closed to it."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import ownership
from modeler_api.auth import get_verifier, principal_from_claims
from modeler_api.config import get_settings
from modeler_api.main import app
from modeler_api.memberships import admit
from modeler_storage.filestore import FileWriteStore

pytestmark = pytest.mark.req("T-05", "T-06")

CURATOR = ["modeler-viewer", "modeler-curator"]
PEOPLE = {"ana": ("acme", CURATOR), "quinn": ("acme", ["modeler-qa"]), "zed": ("other", CURATOR),
          "both": ("acme", ["modeler-qa", "modeler-curator"])}


def _claims(token: str) -> dict:
    tenant, roles = PEOPLE[token]
    return {"sub": token, "name": token.title(), "tenant_id": tenant, "realm_access": {"roles": roles}, "projects": [],
            "acr": "loa2", "auth_time": int(time.time())}


class _Verifier:
    def verify(self, token: str) -> dict:
        return _claims(token)


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def test_qa_reads_every_project_of_its_company_and_changes_or_signs_none(client):
    c, root = client
    owned = c.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Renaldrug"}, headers=_as("ana")).json()["data"]["id"]
    # a project made before memberships were kept: no owner on record, so its members edit it
    FileWriteStore(str(root)).put_project("acme", {"id": "legacy", "name": "Legacy", "compounds": ["Oldamide"], "openQuestions": 0,
                                                   "risk": "medium", "questions": []})
    elsewhere = c.post("/api/v1/projects", json={"name": "Other Co", "compound": "Otheramide"}, headers=_as("zed")).json()["data"]["id"]

    # reads: every project of its company, none of another's
    listed = {p["id"] for p in c.get("/api/v1/projects", headers=_as("quinn")).json()["data"]["projects"]}
    assert {owned, "legacy"} <= listed and elsewhere not in listed
    for pid in (owned, "legacy"):
        for path in (f"/api/v1/projects/{pid}", f"/api/v1/projects/{pid}/members", f"/api/v1/projects/{pid}/audit",
                     f"/api/v1/projects/{pid}/signatures", f"/api/v1/projects/{pid}/agent-runs"):
            answer = c.get(path, headers=_as("quinn"))
            assert answer.status_code == 200, (path, answer.text)
    assert c.get(f"/api/v1/projects/{elsewhere}", headers=_as("quinn")).status_code in (403, 404)

    # every change and every signature refused, on the owned project and on the one with no owner alike
    signature = {"meaning": "approval", "record_type": "artifact", "record_id": "x", "record_sha256": "0" * 64}
    assert c.post("/api/v1/projects", json={"name": "Mine", "compound": "Qaamide"}, headers=_as("quinn")).status_code == 403
    for pid in (owned, "legacy"):
        for path, body in ((f"/api/v1/projects/{pid}/signatures", signature),
                           (f"/api/v1/projects/{pid}/members", {"subject": "ana"}),
                           (f"/api/v1/projects/{pid}:archive", {"reason": "done"})):
            refused = c.post(path, json=body, headers=_as("quinn"))
            assert refused.status_code == 403, (path, refused.text)
    settings = get_settings()
    quinn = admit(principal_from_claims(_claims("quinn")), settings)
    assert "legacy" in quinn.projects
    assert not ownership.may_change("legacy", quinn, settings, signing=True)          # an escalation decision too
    assert not ownership.may_change(owned, quinn, settings)


def test_a_person_who_also_changes_projects_keeps_only_their_memberships(client):
    """The read grant is QA's alone: a person who is QA and a curator reads and changes what they are a member of, so
    holding QA never opens the company's other projects to their changes."""
    c, _root = client
    owned = c.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Renaldrug"}, headers=_as("ana")).json()["data"]["id"]
    both = admit(principal_from_claims(_claims("both")), get_settings())
    assert owned not in both.projects
    assert c.get(f"/api/v1/projects/{owned}", headers=_as("both")).status_code == 403
