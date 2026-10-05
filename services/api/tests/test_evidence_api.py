"""T-44: the P2 evidence endpoints — manual path, decisions, gate; the A2 run with a scripted model."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-44")
H = {"Authorization": "Bearer t"}


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    ws = Workspace(store, "t1", "p1")
    brief = ws.commit(ArtifactKind.BRIEF, "main", empty_brief("Exampleamide", by="u1").to_content(), actor="u1", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(empty_brief("Exampleamide", by="u1")).to_content(),
              derived_from=[brief.ref], actor="system", reason="derived")
    yield TestClient(app), ws
    app.dependency_overrides.clear()


def test_manual_evidence_needs_a_source_and_is_graded(setup):
    c, _ws = setup
    no_source = c.post("/api/v1/projects/p1/evidence", headers=H, json={
        "req_id": "REQ-bind.fu", "target": "bind.fu", "value": 9.0, "unit": "%", "source_type": "PUBLICATION"})
    assert no_source.status_code == 422 and "cite the source" in no_source.json()["detail"]
    ok = c.post("/api/v1/projects/p1/evidence", headers=H, json={
        "req_id": "REQ-bind.fu", "target": "bind.fu", "value": 9.0, "unit": "%", "source_type": "REGULATORY_REVIEW",
        "doi": "10.1/fda-review", "conditions": {"species": "human", "matrix": "plasma", "method": "ED",
                                                 "drug concentration": "1 µM"}})
    item = ok.json()["data"]
    assert ok.status_code == 201 and item["value_pksim"] == pytest.approx(0.09) and item["state"] == "PROPOSED"

    refused = c.post("/api/v1/projects/p1/evidence:research", headers=H)
    assert refused.status_code == 409 and "agents are off" in refused.json()["detail"]

    view = c.post(f"/api/v1/projects/p1/evidence/{item['id']}:decide", headers=H,
                  json={"state": "ACCEPTED", "reason": "FDA review table 3"}).json()["data"]
    fu = next(r for r in view["coverage"] if r["req_id"] == "REQ-bind.fu")
    assert fu["status"] == "ACCEPTED" and "REQ-phys.logp" in view["blocking"]
    gate = c.post("/api/v1/projects/p1/evidence:approve", headers=H, json={})
    assert gate.status_code == 409 and "still open" in gate.json()["detail"]


def test_research_job_runs_a2_and_records_the_run(setup):
    from modeler_agents.llm import ChatResult
    from modeler_api.evidence_api import run_research_job

    c, ws = setup

    class Quiet:
        provider, model = "test", "s"

        def complete(self, messages, tools):
            return ChatResult(content="nothing found", tool_calls=(), finish_reason="", usage={}, model="s")

    result = run_research_job(ws.store, "t1", "p1", model=Quiet())
    assert result["status"] == "COMPLETED"
    view = c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]
    assert view["runs"][0]["run_id"] == result["run_id"]
