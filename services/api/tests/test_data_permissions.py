"""T-47: where a company's client files may be sent for an AI model to read (the governance review of model failover,
2026-11-22): in-house only unless a cloud service has the client's recorded permission; the agents that read client
files (A1, A4, A6-A10) get only the models the company allows, and with none left the work stops and says why.

Since 2026-11-24 (the owner) an administrator records it once for the whole company on Admin → Companies; the company's
people do not see it, and no project route reads or changes it."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from modeler_agents.llm import FallbackChat
from modeler_api import agent_jobs
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project.data_permissions import DataPermissions
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")

WORK = ["modeler-viewer", "modeler-curator", "modeler-reviewer"]
PEOPLE = {"owner": ("platform", ["modeler-admin"]), "ana": ("acme", WORK)}
API = "/api/v1/admin/companies/acme/data-permissions"
GRANT = {"in_house_only": False, "reason": "the client's letter of 2026-11-20",
         "services": {"groq": {"reference": "Letter ACME-2026-11-20", "expires": "2027-06-30"}}}


class _Verifier:
    """`Bearer owner` is the platform's owner with a fresh step-up; `-stale` without one; `ana` works for acme."""

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


def _project(client: TestClient) -> str:
    made = client.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Renaldrug"}, headers=_as("ana"))
    assert made.status_code == 201, made.text
    return made.json()["data"]["id"]


class _M:
    def __init__(self, provider):
        self.provider, self.model = provider, f"{provider}-m"


def test_a_company_starts_in_house_only_and_an_administrator_records_the_clients_written_permission(client, tmp_path):
    _project(client)
    page = client.get("/api/v1/admin/companies/acme", headers=_as("owner")).json()["data"]["data_permissions"]
    assert page["in_house_only"] is True and page["grants"] == [] and {s["service"] for s in page["services"]} >= {"groq", "nvidia"}

    unreferenced = client.put(API, json={"in_house_only": False, "services": {"groq": {"reference": ""}}, "reason": "x"},
                              headers=_as("owner"))
    assert unreferenced.status_code == 409 and "written permission" in unreferenced.json()["detail"]
    stale = client.put(API, json=GRANT, headers=_as("owner-stale"))
    assert stale.status_code == 403 and stale.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    assert client.put(API, json={**GRANT, "reason": " "}, headers=_as("owner")).status_code == 422
    assert client.put("/api/v1/admin/companies/nobody/data-permissions", json=GRANT, headers=_as("owner")).status_code == 404

    answer = client.put(API, json=GRANT, headers=_as("owner"))
    assert answer.status_code == 200, answer.text
    page = answer.json()["data"]["data_permissions"]
    (grant,) = page["grants"]
    assert (grant["service"], grant["reference"], grant["in_force"], grant["by"]) == ("groq", "Letter ACME-2026-11-20", True, "owner")
    assert page["history"][0]["reason"] == "the client's letter of 2026-11-20"

    events = [json.loads(line)["event"] for line in (tmp_path / "acme" / "audit.jsonl").read_text().splitlines()]
    (event,) = [e for e in events if e["action"] == "company.data_permissions.set"]
    assert (event["actor"], event["resource_type"], event["resource_id"]) == ("owner", "tenant", "acme")
    assert event["after"] == {"in_house_only": False, "services": {"groq": "Letter ACME-2026-11-20"}}


def test_the_companys_people_neither_see_nor_change_it(client):
    """The owner, 2026-11-24: the administrator sets it for every person of the company at once; it is not shown to them
    (it was a panel on each project's Data room and Settings before)."""
    pid = _project(client)
    assert client.put(API, json=GRANT, headers=_as("ana")).status_code == 403          # the admin console's role only
    assert client.get("/api/v1/admin/companies/acme", headers=_as("ana")).status_code == 403
    for method in ("get", "put"):
        gone = getattr(client, method)(f"/api/v1/projects/{pid}/data-permissions", headers=_as("ana"),
                                       **({"json": GRANT} if method == "put" else {}))
        assert gone.status_code in (404, 405), gone.text


def test_every_project_of_the_company_gets_only_the_models_its_files_may_go_to(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    ws, sibling, other = Workspace(store, "t1", "p1"), Workspace(store, "t1", "p2"), Workspace(store, "t2", "p1")
    chain = FallbackChat([_M("groq"), _M("litellm"), _M("nvidia")], labels=["gpt-oss-120b", "Qwen Coder", "Nemotron Ultra"])
    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (chain, None))
    model, problem = agent_jobs.project_model("A8", ws)               # in-house only: the cloud ones are left out
    assert problem is None and (model.provider, model.model) == ("litellm", "litellm-m")
    DataPermissions(store, "t1").set(in_house_only=False, services={"nvidia": {"reference": "Email 2026-11-22"}}, by="owner",
                                     reason="the client allowed NVIDIA for the sample")
    for project in (ws, sibling):                                      # one record, every project of the company
        model, _ = agent_jobs.project_model("A8", project)
        assert isinstance(model, FallbackChat) and model.labels == ["Qwen Coder", "Nemotron Ultra"]
    model, _ = agent_jobs.project_model("A8", other)                   # another company keeps its own record
    assert (model.provider, model.model) == ("litellm", "litellm-m")

    monkeypatch.setattr(agent_jobs, "chat_model", lambda agent=None: (_M("groq"), None))
    model, problem = agent_jobs.project_model("A8", ws)               # nothing allowed left: stops, says who records it
    assert model is None and "may not be sent to GroqCloud" in problem and "an administrator records" in problem
    status = agent_jobs.agents_status("A8", ws=ws)
    assert status["enabled"] is False and "may not be sent to GroqCloud" in status["problem"]


def test_a_permission_the_earlier_project_panel_recorded_is_no_longer_read(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    legacy = tmp_path / "t1" / "projects" / "p1" / "data_permissions.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"in_house_only": False, "services": {"groq": {"reference": "L-1", "expires": ""}},
                                  "history": []}), encoding="utf-8")
    assert not DataPermissions.of(Workspace(store, "t1", "p1")).allows("groq")    # in-house until the admin records it


def test_a_permission_that_has_ended_no_longer_lets_files_go(tmp_path):
    from datetime import date

    store = FileProjectStore(tmp_path)
    DataPermissions(store, "t1").set(in_house_only=False, services={"groq": {"reference": "L-1", "expires": "2099-01-31"}},
                                     by="owner", reason="until the end of the study")
    perms = DataPermissions(store, "t1")
    assert perms.allows("groq", date(2099, 1, 31)) and not perms.allows("groq", date(2099, 2, 1))
    assert not perms.allows("nvidia") and perms.allows("litellm")
    DataPermissions(store, "t1").set(in_house_only=True, services={"groq": {"reference": "L-1"}}, by="owner", reason="withdrawn")
    assert not DataPermissions(store, "t1").allows("groq")              # in-house only overrides every grant
