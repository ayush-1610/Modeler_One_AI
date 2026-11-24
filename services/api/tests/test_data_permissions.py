"""T-47: where a project's client files may be sent for an AI model to read (the governance review of model failover,
2026-11-22): in-house only unless a cloud service has the client's recorded permission; the agents that read client
files (A1, A4, A6-A10) get only the models the project allows, and with none left the work stops and says why."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_agents.llm import FallbackChat
from modeler_api import agent_jobs, project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project.data_permissions import DataPermissions
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")
H = {"Authorization": "Bearer t"}
API = "/api/v1/projects/p1/data-permissions"


class FakeVerifier:
    step_up = True

    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2" if self.step_up else "loa1", "auth_time": int(time.time())}


@pytest.fixture
def setup(tmp_path):
    store = FileProjectStore(tmp_path)
    verifier = FakeVerifier()
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    yield TestClient(app), store, verifier
    app.dependency_overrides.clear()


class _M:
    def __init__(self, provider):
        self.provider, self.model = provider, f"{provider}-m"


def test_a_project_starts_in_house_only_and_a_cloud_service_needs_the_clients_written_permission(setup):
    c, store, verifier = setup
    page = c.get(API, headers=H).json()["data"]
    assert page["in_house_only"] is True and page["grants"] == [] and {s["service"] for s in page["services"]} >= {"groq", "nvidia"}
    unreferenced = c.put(API, headers=H, json={"in_house_only": False, "services": {"groq": {"reference": ""}}, "reason": "x"})
    assert unreferenced.status_code == 409 and "written permission" in unreferenced.json()["detail"]
    verifier.step_up = False
    assert c.put(API, headers=H, json={"in_house_only": False, "services": {"groq": {"reference": "L-1"}}, "reason": "x"}
                 ).status_code == 403                               # confirmed with the step-up
    verifier.step_up = True
    page = c.put(API, headers=H, json={"in_house_only": False, "reason": "the client's letter of 2026-11-20",
                                       "services": {"groq": {"reference": "Letter ACME-2026-11-20", "expires": "2027-06-30"}}}
                 ).json()["data"]
    (grant,) = page["grants"]
    assert (grant["service"], grant["reference"], grant["in_force"], grant["by"]) == ("groq", "Letter ACME-2026-11-20", True, "u1")
    events = [r.event for r in store.audit("t1").records() if r.event.action == "project.data_permissions.set"]
    assert events and events[-1].after == {"in_house_only": False, "services": {"groq": "Letter ACME-2026-11-20"}}
    assert page["history"][0]["reason"] == "the client's letter of 2026-11-20"


def test_an_agent_gets_only_the_models_its_projects_files_may_go_to(tmp_path, monkeypatch):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    chain = FallbackChat([_M("groq"), _M("litellm"), _M("nvidia")], labels=["gpt-oss-120b", "Qwen Coder", "Nemotron Ultra"])
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (chain, None))
    model, problem = agent_jobs.project_model("A8", ws)               # in-house only: the cloud ones are left out
    assert problem is None and (model.provider, model.model) == ("litellm", "litellm-m")
    DataPermissions(ws).set(in_house_only=False, services={"nvidia": {"reference": "Email 2026-11-22"}}, by="u1",
                            reason="the client allowed NVIDIA for the sample")
    model, _ = agent_jobs.project_model("A8", ws)
    assert isinstance(model, FallbackChat) and model.labels == ["Qwen Coder", "Nemotron Ultra"]
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_M("groq"), None))
    model, problem = agent_jobs.project_model("A8", ws)               # nothing allowed left: stops, says what to record
    assert model is None and "may not be sent to GroqCloud" in problem and "record the client's permission" in problem
    status = agent_jobs.agents_status("A8", ws=ws)
    assert status["enabled"] is False and "may not be sent to GroqCloud" in status["problem"]


def test_a_permission_that_has_ended_no_longer_lets_files_go(tmp_path):
    from datetime import date

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    DataPermissions(ws).set(in_house_only=False, services={"groq": {"reference": "L-1", "expires": "2099-01-31"}}, by="u1",
                            reason="until the end of the study")
    perms = DataPermissions(ws)
    assert perms.allows("groq", date(2099, 1, 31)) and not perms.allows("groq", date(2099, 2, 1))
    assert not perms.allows("nvidia") and perms.allows("litellm")
    DataPermissions(ws).set(in_house_only=True, services={"groq": {"reference": "L-1"}}, by="u1", reason="withdrawn")
    assert not DataPermissions(ws).allows("groq")                       # in-house only overrides every grant


ROLES = {"ana": ["modeler-viewer", "modeler-curator"], "ben": ["modeler-viewer", "modeler-curator"],
         "rita": ["modeler-viewer", "modeler-reviewer"], "boss": ["modeler-viewer", "modeler-admin"]}


class _People:
    def verify(self, token: str) -> dict:
        return {"sub": token, "name": token.title(), "tenant_id": "acme", "realm_access": {"roles": ROLES[token]},
                "projects": [], "acr": "loa2", "auth_time": int(time.time())}


def test_only_the_projects_owner_or_an_administrator_records_where_its_files_may_go(tmp_path, api_settings):
    """The owner, 2026-11-24: "restrict granting permission to the project owner and admin". A curator or reviewer the
    project is shared with reads it and is told who changes it; the owner and an administrator change it."""
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _People
    try:
        c = TestClient(app)
        _as = lambda who: {"Authorization": f"Bearer {who}"}
        pid = c.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Renaldrug"}, headers=_as("ana")).json()["data"]["id"]
        for who in ("ben", "rita", "boss"):
            c.get("/api/v1/projects", headers=_as(who))                          # each signs in once
            assert c.post(f"/api/v1/projects/{pid}/members", json={"subject": who}, headers=_as("ana")).status_code == 200
        api = f"/api/v1/projects/{pid}/data-permissions"
        grant = {"in_house_only": False, "services": {"groq": {"reference": "Letter L-1"}}, "reason": "the client agreed"}

        seen = c.get(api, headers=_as("ben")).json()["data"]
        assert seen["you_change_it"] is False and seen["who_changes_it"] == "the project's owner, Ana, or an administrator"
        for who in ("ben", "rita"):
            refused = c.put(api, json=grant, headers=_as(who))
            assert refused.status_code == 403 and refused.json()["detail"]["code"] == "NOT_OWNER_OR_ADMIN", refused.text
        assert c.get(api, headers=_as("ana")).json()["data"]["you_change_it"] is True
        assert c.put(api, json=grant, headers=_as("ana")).status_code == 200
        assert c.get(api, headers=_as("boss")).json()["data"]["you_change_it"] is True
        withdrawn = c.put(api, json={"in_house_only": True, "services": {}, "reason": "withdrawn"}, headers=_as("boss"))
        assert withdrawn.status_code == 200, withdrawn.text
        assert [h["by"] for h in withdrawn.json()["data"]["history"]] == ["boss", "ana"]
    finally:
        app.dependency_overrides.clear()
