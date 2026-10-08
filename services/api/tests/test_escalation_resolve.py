"""The single-node escalation:resolve endpoint — a signed review-inbox decision moves a stopped campaign.

Unlike escalation:decide (Temporal signal + password step-up), this path applies the decision to the persisted
campaign and takes its signature from the OIDC token's step-up, so no password crosses the wire.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app

URL = "/api/v1/campaigns/camp-1/stages/S1/escalation:resolve"


class FakeVerifier:
    def __init__(self, claims):
        self.claims = claims

    def verify(self, token):
        return self.claims


def claims(*, roles=("modeler-reviewer",), projects=("proj-1",), acr="loa2", auth_time=None):
    return {"sub": "u1", "name": "Dr Reviewer", "tenant_id": "t1", "realm_access": {"roles": list(roles)},
            "projects": list(projects), "acr": acr, "auth_time": auth_time if auth_time is not None else int(time.time())}


def seed_campaign(tmp_path, *, with_escalation=True):
    """A campaign stopped at an S1 escalation, with the resume state the decision needs."""
    tenant = tmp_path / "t1"
    tenant.mkdir(parents=True, exist_ok=True)
    campaign = {
        "id": "camp-1", "project": "proj-1", "compound": "Drug", "question": "q", "modelRisk": "medium",
        "budgetSeconds": 600, "elapsedSeconds": 5, "currentStage": "S1", "status": "ESCALATED",
        "stages": [{"stage": "S0", "label": "Readiness", "status": "PASSED", "rounds": []},
                   {"stage": "S1", "label": "IV disposition", "status": "ESCALATED", "rounds": []}],
        "gof": [],
        "resume": {
            "request": {"campaign_id": "camp-1", "tenant_id": "t1", "compound": "Drug", "map_id": "m",
                        "cpf_uri": "file:///none/cpf.json", "cpf_sha256": "a" * 64, "map_uri": "", "map_sha256": "",
                        "observed_uri": "", "observed_sha256": "", "stages": ["S0", "S1"],
                        "stage_budgets_seconds": {}, "max_rounds_per_stage": 4, "seed": 1,
                        "signature_timeout_days": 14},
            "cpf_uri": "file:///none/cpf.json", "cpf_sha256": "a" * 64,
            "completed_stages": ["S0"], "escalated_stage": "S1",
        } if with_escalation else None,
    }
    (tenant / "campaigns.json").write_text(json.dumps({"campaigns": [campaign]}))
    (tenant / "escalations.json").write_text(json.dumps({"escalations": [{"id": "camp-1-S1", "campaignId": "camp-1"}]}))
    return campaign


def teardown_function():
    app.dependency_overrides.clear()


def _auth():
    return {"Authorization": "Bearer tok"}


@pytest.fixture
def local_settings(tmp_path, api_settings):
    return lambda backend="local": api_settings(execution_backend=backend, read_root=str(tmp_path))


def test_abort_is_applied_and_signed(tmp_path, monkeypatch, local_settings):
    seed_campaign(tmp_path)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())

    r = TestClient(app).post(URL, json={"action": "abort", "note": "not recoverable"}, headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ABORTED" and body["action"] == "abort"
    assert body["signature"]["signature_id"]
    assert "Approved" in body["signature"]["manifestation"]

    # the campaign is closed out and the review item is gone
    campaign = json.loads((tmp_path / "t1" / "campaigns.json").read_text())["campaigns"][0]
    assert campaign["status"] == "ABORTED"
    assert json.loads((tmp_path / "t1" / "escalations.json").read_text())["escalations"] == []


def test_without_step_up_nothing_is_applied(tmp_path, monkeypatch, local_settings):
    seed_campaign(tmp_path)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims(acr="loa1"))

    r = TestClient(app).post(URL, json={"action": "abort"}, headers=_auth())
    assert r.status_code == 403
    # the campaign must be untouched: an unsigned decision cannot move it
    campaign = json.loads((tmp_path / "t1" / "campaigns.json").read_text())["campaigns"][0]
    assert campaign["status"] == "ESCALATED"
    assert json.loads((tmp_path / "t1" / "escalations.json").read_text())["escalations"]


def test_stale_step_up_is_rejected(tmp_path, monkeypatch, local_settings):
    seed_campaign(tmp_path)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims(auth_time=int(time.time()) - 3600))
    r = TestClient(app).post(URL, json={"action": "abort"}, headers=_auth())
    assert r.status_code == 403


def test_non_member_of_the_campaign_project_is_403(tmp_path, monkeypatch, local_settings):
    seed_campaign(tmp_path)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims(projects=("other",)))
    r = TestClient(app).post(URL, json={"action": "abort"}, headers=_auth())
    assert r.status_code == 403


def test_campaign_without_an_open_escalation_is_422(tmp_path, monkeypatch, local_settings):
    seed_campaign(tmp_path, with_escalation=False)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    r = TestClient(app).post(URL, json={"action": "retry"}, headers=_auth())
    assert r.status_code == 422
    assert "no open escalation" in r.text


def test_unknown_campaign_is_404(tmp_path, monkeypatch, local_settings):
    seed_campaign(tmp_path)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    r = TestClient(app).post("/api/v1/campaigns/ghost/stages/S1/escalation:resolve",
                             json={"action": "abort"}, headers=_auth())
    assert r.status_code == 404


def test_temporal_backend_points_at_the_other_endpoint(tmp_path, monkeypatch, local_settings):
    seed_campaign(tmp_path)
    local_settings("temporal")
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    r = TestClient(app).post(URL, json={"action": "abort"}, headers=_auth())
    assert r.status_code == 409
    assert "escalation:decide" in r.text


SIGN_URL = "/api/v1/campaigns/camp-1/stages/S6/escalation:resolve"


def _seed_signature_gate(tmp_path, *, exploratory: bool):
    """A campaign waiting for the S4/S5 signature whose S1 pass was judged on synthetic data only."""
    from modeler_storage.filestore import FileWriteStore

    campaign = seed_campaign(tmp_path)
    campaign["status"] = "AWAITING_SIGNATURE"
    campaign["resume"]["escalated_stage"] = "S6"
    campaign["realData"] = {"S1": {"judged": 2, "real": 0, "byOrigin": {"SYNTHETIC": 2}, "notReal": ["a", "b"],
                                   "notEvaluable": [], "passable": False, "label": "TEST ONLY: no real observed data"}}
    (tmp_path / "t1" / "campaigns.json").write_text(json.dumps({"campaigns": [campaign]}))
    (tmp_path / "t1" / "escalations.json").write_text(json.dumps({"escalations": [{"id": "camp-1-S6", "campaignId": "camp-1"}]}))
    FileWriteStore(str(tmp_path)).put_project("t1", {"id": "proj-1", "name": "P", "compounds": ["Drug"],
                                                     "exploratory": exploratory})


@pytest.mark.req("T-46")
def test_the_evaluation_of_test_data_is_refused_before_a_signature_is_taken(tmp_path, monkeypatch, local_settings):
    _seed_signature_gate(tmp_path, exploratory=False)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    r = TestClient(app).post(SIGN_URL, json={"action": "approve"}, headers=_auth())
    assert r.status_code == 409 and "not real" in r.text and "S1: TEST ONLY" in r.text
    campaign = json.loads((tmp_path / "t1" / "campaigns.json").read_text())["campaigns"][0]
    assert campaign["status"] == "AWAITING_SIGNATURE"
    assert json.loads((tmp_path / "t1" / "escalations.json").read_text())["escalations"]


FEEDBACK_URL = "/api/v1/campaigns/camp-1/feedback:decide"


def _seed_feedback(tmp_path, *, learnable: bool):
    """A campaign stopped at a failed external validation (S5) with its diagnosis."""
    campaign = seed_campaign(tmp_path)
    campaign["resume"]["escalated_stage"] = "S5"
    reason = "confirmed afterwards on fed-2" if learnable else "external validation of PO-FED not achievable: no other"
    campaign["resume"]["feedback"] = {
        "failing": [{"study_id": "fed-1", "class": "PO-FED", "failed": ["AUC"], "learn_stage": "S3"}],
        "classes": {"PO-FED": {"failing": ["fed-1"], "unspent": ["fed-2"] if learnable else [], "cycles": 0,
                               "learn": {"possible": learnable, "reason": reason}}},
        "notAchievable": [] if learnable else [reason],
    }
    (tmp_path / "t1" / "campaigns.json").write_text(json.dumps({"campaigns": [campaign]}))
    (tmp_path / "t1" / "escalations.json").write_text(json.dumps({"escalations": [{"id": "camp-1-S5", "campaignId": "camp-1"}]}))


@pytest.mark.req("T-55")
def test_a_learn_the_guardrails_forbid_is_refused_before_a_signature_is_taken(tmp_path, monkeypatch, local_settings):
    _seed_feedback(tmp_path, learnable=False)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    r = TestClient(app).post(FEEDBACK_URL, json={"action": "learn", "note": "try"}, headers=_auth())
    assert r.status_code == 409 and "not achievable" in r.text
    assert json.loads((tmp_path / "t1" / "escalations.json").read_text())["escalations"]      # still open
    r = TestClient(app).post(FEEDBACK_URL, json={"action": "new_evidence"}, headers=_auth())
    assert r.status_code == 422 and "parameter" in r.text
    r = TestClient(app).post(FEEDBACK_URL, json={"action": "approve"}, headers=_auth())       # not a feedback decision
    assert r.status_code == 422


@pytest.mark.req("T-55")
def test_a_feedback_signature_binds_the_decisions_content(tmp_path, monkeypatch, local_settings):
    import modeler_orchestrator.local_runner as runner
    from modeler_orchestrator.feedback import decision_digest

    _seed_feedback(tmp_path, learnable=True)
    local_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    applied = {}
    # answers as local_runner.resolve_escalation does when a campaign continues (the typed answer requires its keys)
    monkeypatch.setattr(runner, "resolve_escalation", lambda **kw: applied.update(kw) or {
        "campaign_id": kw["campaign_id"], "stage": kw["stage"], "action": kw["action"], "status": "RUNNING",
        "remaining_stages": []})
    signed = {}
    import modeler_api.escalations as esc

    real_sign = esc.sign_after_step_up
    monkeypatch.setattr(esc, "sign_after_step_up", lambda **kw: signed.update(kw) or real_sign(**kw))
    r = TestClient(app).post(FEEDBACK_URL, json={"action": "learn", "studies": ["fed-1"], "note": "fed is the question"},
                             headers=_auth())
    assert r.status_code == 200, r.text
    payload = {"studies": ["fed-1"], "beyond_cap": ""}
    assert signed["record_sha256"] == decision_digest("camp-1", "S5", "learn", payload)
    assert applied["payload"] == payload and applied["signature_id"] == r.json()["signature"]["signature_id"]
    assert applied["printed_name"] == "Dr Reviewer" and applied["note"] == "fed is the question"
