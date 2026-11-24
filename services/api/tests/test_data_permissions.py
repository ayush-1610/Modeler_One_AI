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
