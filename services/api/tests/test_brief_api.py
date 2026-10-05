"""T-41: P0 initiate and the P1 brief through the API, with the agent scripted and PubChem stubbed."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_agents.llm import ChatResult, ToolCall
from modeler_api import brief_api, project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore
from modeler_project.identity import IdentityError

pytestmark = pytest.mark.req("T-41")
H = {"Authorization": "Bearer t"}
PROPOSAL = (b"PBPK model of exampleamide.\nObjective: predict exposure after a single oral dose of 50 mg in healthy adults.\n"
            b"The client will provide the clinical PK data of study EX-101.")


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    monkeypatch.setenv("MODELER_READ_ROOT", str(tmp_path))
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    from modeler_api.config import get_settings

    get_settings.cache_clear()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    yield TestClient(app), store
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _initiate(c) -> str:
    response = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": "Exampleamide", "extract": "false",
                                                                     "context": "Generic IR tablet project for a US client."},
                      files=[("files", ("proposal.txt", PROPOSAL, "text/plain"))])
    assert response.status_code == 201, response.text
    return response.json()["data"]["project_id"]


def test_initiate_creates_project_documents_and_a_first_brief(client):
    c, _ = client
    pid = _initiate(c)
    assert pid == "exampleamide-pbpk"
    docs = c.get(f"/api/v1/projects/{pid}/documents", headers=H).json()["data"]["documents"]
    assert sorted(d["role"] for d in docs) == ["context", "proposal"]
    proposal = next(d for d in docs if d["role"] == "proposal")
    page = c.get(f"/api/v1/projects/{pid}/documents/{proposal['sha256']}/pages/1", headers=H).json()["data"]
    assert "single oral dose of 50 mg" in page["text"]
    raw = c.get(f"/api/v1/projects/{pid}/documents/{proposal['sha256']}/raw", headers=H)
    assert raw.content == PROPOSAL
    view = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]
    assert view["brief"]["fields"]["drug.name"]["value"] == "Exampleamide"
    assert view["agents"]["enabled"] is False and view["blocking"] > 0
    project = c.get(f"/api/v1/projects/{pid}", headers=H)
    assert project.status_code == 200 and project.json()["data"]["compounds"] == ["Exampleamide"]


def test_unsupported_upload_is_refused(client):
    c, _ = client
    r = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": "X", "extract": "false"},
               files=[("files", ("scan.gif", b"GIF89a", "image/gif"))])
    assert r.status_code == 422 and "unsupported" in r.json()["detail"]


def test_extraction_with_a_scripted_agent_then_edit_preview_answer_and_approve(client):
    c, store = client
    pid = _initiate(c)
    sha = next(d["sha256"] for d in c.get(f"/api/v1/projects/{pid}/documents", headers=H).json()["data"]["documents"]
               if d["role"] == "proposal")

    class Scripted:
        provider, model = "test", "scripted"

        def __init__(self):
            self.turns = [[("propose_field", {"path": "scenarios[0].dose", "value": "50", "unit": "mg",
                                              "quote": "single oral dose of 50 mg", "doc_sha256": sha, "page": 1})], []]

        def complete(self, messages, tools):
            calls = self.turns.pop(0)
            return ChatResult(content="done", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                              tool_calls=tuple(ToolCall(id="c", name=n, arguments=a) for n, a in calls))

    def no_pubchem(name):
        raise IdentityError("PubChem is not reachable from this host")

    result = brief_api.run_extraction(store, "t1", pid, by="u1", model=Scripted(), fetch_identity=no_pubchem)
    assert result["status"] == "COMPLETED" and result["accepted"] == 1 and result["brief_version"] == 2
    run = c.get(f"/api/v1/projects/{pid}/agent-runs/{result['run_id']}", headers=H).json()["data"]
    assert run["run"]["status"] == "COMPLETED" and any(s["kind"] == "tool_result" for s in run["steps"])

    view = c.get(f"/api/v1/projects/{pid}/brief", headers=H).json()["data"]
    dose = view["brief"]["groups"]["scenarios"][0]["dose"]
    assert dose["status"] == "EXTRACTED" and dose["citations"][0]["quote"] == "single oral dose of 50 mg"

    edit = {"changes": [{"path": "scenarios[0].dose", "status": "EDITED", "value": 100, "note": "amendment 1"}],
            "reason": "client amended the dose"}
    preview = c.put(f"/api/v1/projects/{pid}/brief", headers=H, json={**edit, "preview": True}).json()["data"]["impact"]
    assert any(ch["path"].endswith("dose.value") for ch in preview["changes"])
    assert c.get(f"/api/v1/projects/{pid}/artifacts/brief/main", headers=H).json()["data"]["version"] == 2
    saved = c.put(f"/api/v1/projects/{pid}/brief", headers=H, json=edit).json()["data"]
    assert saved["artifact"]["version"] == 3 and saved["artifact"]["reason"] == "client amended the dose"

    refused = c.post(f"/api/v1/projects/{pid}/brief:approve", headers=H, json={})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "BRIEF_NOT_READY"

    bad = c.put(f"/api/v1/projects/{pid}/brief", headers=H,
                json={"changes": [{"path": "drug.modality", "status": "EDITED", "value": "pill", "note": "x"}], "reason": "r"})
    assert bad.status_code == 422 and "not one of" in bad.json()["detail"]


@pytest.mark.req("T-42")
def test_approved_brief_derives_the_data_plan_which_takes_overrides_and_closes_p1(client):
    c, store = client
    pid = _initiate(c)
    sha = next(d["sha256"] for d in c.get(f"/api/v1/projects/{pid}/documents", headers=H).json()["data"]["documents"]
               if d["role"] == "proposal")
    from modeler_project import ArtifactKind, Workspace
    from modeler_project.brief import Citation, FieldStatus, ProjectBrief
    from modeler_project.brief_ops import agent_set

    ws = Workspace(store, "t1", pid)
    brief = ProjectBrief.from_content(ws.latest(ArtifactKind.BRIEF, "main").content)
    cite = (Citation(doc_sha256=sha, page=1, quote="single oral dose of 50 mg"),)
    for path, value in [("proj.title", "Exampleamide PBPK"), ("proj.type", "research"), ("drug.modality", "small_molecule"),
                        ("qoi.text", "exposure after 50 mg"), ("qoi.context_of_use", "internal decision"),
                        ("qoi.applications", ["APP-01"]), ("products[0].name", "50 mg tablet"), ("products[0].role", "TEST"),
                        ("scenarios[0].population", "healthy adults"), ("scenarios[0].route", "oral"),
                        ("scenarios[0].dose", 50), ("data_plan[0].item", "clinical PK of EX-101"),
                        ("data_plan[0].category", "clinical_pk_oral"), ("data_plan[0].provider", "CLIENT")]:
        brief = agent_set(brief, path, value=value, unit=None, citations=cite, status=FieldStatus.EXTRACTED, confidence="A",
                          by="agent:t")
    ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), derived_from=ws.latest(ArtifactKind.BRIEF, "main").derived_from,
              actor="agent:t", reason="filled")
    assert c.post(f"/api/v1/projects/{pid}/requirements:approve", headers=H, json={}).status_code == 409

    approved = c.post(f"/api/v1/projects/{pid}/brief:approve", headers=H, json={"note": "checked against the PDF"})
    assert approved.status_code == 200, approved.text
    plan = c.get(f"/api/v1/projects/{pid}/requirements", headers=H).json()["data"]
    assert plan["brief_status"] == "APPROVED" and plan["counts"]["applicable"] > 10
    po = next(i for i in plan["matrix"]["items"] if i["req_id"] == "REQ-obs.po_fasted_range")
    assert po["provider"] == "CLIENT" and po["provider_statement"] == "clinical PK of EX-101"

    changed = c.put(f"/api/v1/projects/{pid}/requirements/REQ-phys.logp", headers=H,
                    json={"provider": "CLIENT", "reason": "the client measured logD7.4"}).json()["data"]
    logp = next(i for i in changed["matrix"]["items"] if i["req_id"] == "REQ-phys.logp")
    assert logp["provider"] == "CLIENT" and logp["provider_source"] == "override"
    assert c.post(f"/api/v1/projects/{pid}/requirements:approve", headers=H, json={}).status_code == 200
    phases = {p["phase"]: p["status"] for p in c.get(f"/api/v1/projects/{pid}/phases", headers=H).json()["data"]["phases"]}
    assert phases["P1"] == "APPROVED"
