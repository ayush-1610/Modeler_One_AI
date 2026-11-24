"""A project's records the console redesign's slice 7 shows (design-review/BACKEND_CHANGE_REQUIREMENTS.md R-N05, R-N09):
the agent runs on a project, listed (`GET /projects/{id}/agent-runs`), and the signatures given on its records
(`GET /projects/{id}/signatures`), escalation decisions on its campaigns included, which `GET /audit` never listed."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from modeler_agents.run_store import FileRunStore
from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore

H = {"Authorization": "Bearer t"}
PROPOSAL = b"PBPK model of exampleamide.\nObjective: predict exposure after a single oral dose of 50 mg in healthy adults.\n"


class FakeVerifier:
    def __init__(self, user: str = "u1", projects: tuple[str, ...] = ("*",)):
        self.user, self.projects = user, list(projects)

    def verify(self, token):
        return {"sub": self.user, "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": self.projects, "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    monkeypatch.setenv("MODELER_READ_ROOT", str(tmp_path))
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    from modeler_api.config import reload_settings

    reload_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    yield TestClient(app), store, tmp_path
    app.dependency_overrides.clear()
    reload_settings()


def _initiate(c, drug: str = "Exampleamide") -> str:
    response = c.post("/api/v1/projects:initiate", headers=H, data={"drug_name": drug, "extract": "false"},
                      files=[("files", ("proposal.txt", PROPOSAL, "text/plain"))])
    assert response.status_code == 201, response.text
    return response.json()["data"]["project_id"]


def _run(root, tenant: str, project: str, agent: str, *, steps: list[dict] = (), status: str = "COMPLETED") -> str:
    runs = FileRunStore(root, project_id=project)
    run_id = runs.start_run(tenant_id=tenant, agent=agent, provider="ollama", model="qwen", campaign_id=None,
                            budget={"max_turns": 4}, started_by="u1")
    for seq, step in enumerate(steps, start=1):
        runs.record_step(run_id=run_id, seq=seq, kind=step["type"], content=step, usage={})
    runs.finish_run(run_id=run_id, status=status, input_tokens=1200, output_tokens=300, cost_usd=0.0, summary={})
    time.sleep(0.01)                     # distinct start times: the list is newest first
    return run_id


@pytest.mark.req("T-48")
def test_a_projects_agent_runs_are_listed_newest_first_with_refusals_and_fallbacks_and_paged(client):
    c, _store, root = client
    pid, other = _initiate(c), _initiate(c, "Otheramide")
    first = _run(root, "t1", pid, "A1", steps=[{"type": "model_turn", "turn": 1},
                                                {"type": "tool_call_rejected", "turn": 1, "error": "no such tool"},
                                                {"type": "tool_call_rejected", "turn": 2, "error": "bad arguments"}])
    second = _run(root, "t1", pid, "A2", steps=[{"type": "model_switch", "turn": 1, "from": "ollama/qwen",
                                                  "to": "nvidia/nemotron", "why": "it is resting after a recent failure"}])
    _run(root, "t1", other, "A1")                                  # another project's
    _run(root, "t2", pid, "A1")                                    # another company's run under the same project id

    answer = c.get(f"/api/v1/projects/{pid}/agent-runs", headers=H)
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert [r["run_id"] for r in data["runs"]] == [second, first] and data["next_before"] is None
    newest, oldest = data["runs"]
    assert (newest["agent"], newest["model"], newest["started_by"], newest["status"]) == ("A2", "qwen", "u1", "COMPLETED")
    assert newest["agent_label"] == "A2 · searches the literature"
    assert (newest["fallback_from"], newest["refusals"]) == ("ollama/qwen", 0)
    assert (oldest["refusals"], oldest["fallback_from"], oldest["turns"]) == (2, None, 1)
    assert (oldest["input_tokens"], oldest["output_tokens"]) == (1200, 300) and oldest["finished_at"]
    assert "cost_usd" not in oldest and "summary" not in oldest              # the cost stays in the admin console

    # paged: one at a time, the next page from the cursor, stable
    page = c.get(f"/api/v1/projects/{pid}/agent-runs", headers=H, params={"limit": 1}).json()["data"]
    assert [r["run_id"] for r in page["runs"]] == [second] and page["next_before"] == second
    rest = c.get(f"/api/v1/projects/{pid}/agent-runs", headers=H, params={"limit": 1, "before": second}).json()["data"]
    assert [r["run_id"] for r in rest["runs"]] == [first] and rest["next_before"] is None
    assert c.get(f"/api/v1/projects/{pid}/agent-runs", headers=H, params={"before": "ar_unknown"}).status_code == 404
    assert c.get(f"/api/v1/projects/{pid}/agent-runs", headers=H, params={"limit": 0}).status_code == 422
    # the detail of a listed run answers; another project's run is not this project's
    assert c.get(f"/api/v1/projects/{pid}/agent-runs/{first}", headers=H).status_code == 200

    # a person who is not a member of the project reads none of it
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier("u2", (other,))
    assert c.get(f"/api/v1/projects/{pid}/agent-runs", headers=H).status_code in (403, 404)


def _sign(store: FileProjectStore, record_type: str, record_id: str, *, n: int) -> str:
    signature_id = f"sig-{n}"
    store.audit("t1").append(actor="u1", action="signature.create", resource_type=record_type, resource_id=record_id,
                             reason=f"Dev User | Approved | 2026-11-24 10:0{n}:00 UTC",
                             after={"signature_id": signature_id, "record_sha256": f"{n}" * 64, "meaning": "Approved",
                                    "auth_method": "oidc:loa2"})
    return signature_id


@pytest.mark.req("T-06")
def test_a_projects_signatures_include_escalation_decisions_on_its_campaigns_which_its_audit_trail_omits(client):
    c, store, root = client
    pid, other = _initiate(c), _initiate(c, "Otheramide")
    campaigns = root / "t1" / "campaigns.json"
    campaigns.parent.mkdir(parents=True, exist_ok=True)
    campaigns.write_text(json.dumps({"campaigns": [{"id": "camp-ab12", "project": pid}, {"id": "camp-cd34", "project": other}]}))
    mine = [_sign(store, "map", f"{pid}/plan-v2", n=1),
            _sign(store, "intake-confirmation", f"{pid}/delivery/study/st-3", n=2),
            _sign(store, "escalation", "camp-ab12-S2", n=3)]                 # a decision on this project's campaign
    _sign(store, "escalation", "camp-cd34-S2", n=4)                          # on another project's campaign
    _sign(store, "map", f"{other}/plan-v1", n=5)
    store.audit("t1").append(actor="u1", action="artifact.commit", resource_type="map", resource_id=f"{pid}/plan-v2")

    answer = c.get(f"/api/v1/projects/{pid}/signatures", headers=H)
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert data["chain_verifies"] is True
    assert [s["signature_id"] for s in data["signatures"]] == list(reversed(mine))        # newest first
    decision = data["signatures"][0]
    assert (decision["record_type"], decision["record_id"], decision["meaning"]) == ("escalation", "camp-ab12-S2", "Approved")
    assert (decision["signer_id"], decision["printed_name"], decision["record_sha256"]) == ("u1", "Dev User", "3" * 64)
    assert decision["manifestation"].startswith("Dev User | Approved |") and decision["signed_at"]
    # the gap this route closes: the project's audit trail keeps only ids that start with the project's
    audit = c.get(f"/api/v1/projects/{pid}/audit", headers=H).json()["data"]["events"]
    assert "camp-ab12-S2" not in {e["resource_id"] for e in audit}

    app.dependency_overrides[get_verifier] = lambda: FakeVerifier("u2", (other,))         # not a member
    assert c.get(f"/api/v1/projects/{pid}/signatures", headers=H).status_code in (403, 404)
