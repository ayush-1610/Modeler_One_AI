"""The single-node escalation:resolve endpoint — a signed review-inbox decision moves a stopped campaign.

Unlike escalation:decide (Temporal signal + password step-up), this path applies the decision to the persisted
campaign and takes its signature from the OIDC token's step-up, so no password crosses the wire.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

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


def _patch_settings(monkeypatch, tmp_path, backend="local"):
    import modeler_api.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(execution_backend=backend, read_root=str(tmp_path)))


def test_abort_is_applied_and_signed(tmp_path, monkeypatch):
    seed_campaign(tmp_path)
    _patch_settings(monkeypatch, tmp_path)
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


def test_without_step_up_nothing_is_applied(tmp_path, monkeypatch):
    seed_campaign(tmp_path)
    _patch_settings(monkeypatch, tmp_path)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims(acr="loa1"))

    r = TestClient(app).post(URL, json={"action": "abort"}, headers=_auth())
    assert r.status_code == 403
    # the campaign must be untouched: an unsigned decision cannot move it
    campaign = json.loads((tmp_path / "t1" / "campaigns.json").read_text())["campaigns"][0]
    assert campaign["status"] == "ESCALATED"
    assert json.loads((tmp_path / "t1" / "escalations.json").read_text())["escalations"]


def test_stale_step_up_is_rejected(tmp_path, monkeypatch):
    seed_campaign(tmp_path)
    _patch_settings(monkeypatch, tmp_path)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims(auth_time=int(time.time()) - 3600))
    r = TestClient(app).post(URL, json={"action": "abort"}, headers=_auth())
    assert r.status_code == 403


def test_non_member_of_the_campaign_project_is_403(tmp_path, monkeypatch):
    seed_campaign(tmp_path)
    _patch_settings(monkeypatch, tmp_path)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims(projects=("other",)))
    r = TestClient(app).post(URL, json={"action": "abort"}, headers=_auth())
    assert r.status_code == 403


def test_campaign_without_an_open_escalation_is_422(tmp_path, monkeypatch):
    seed_campaign(tmp_path, with_escalation=False)
    _patch_settings(monkeypatch, tmp_path)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    r = TestClient(app).post(URL, json={"action": "retry"}, headers=_auth())
    assert r.status_code == 422
    assert "no open escalation" in r.text


def test_unknown_campaign_is_404(tmp_path, monkeypatch):
    seed_campaign(tmp_path)
    _patch_settings(monkeypatch, tmp_path)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    r = TestClient(app).post("/api/v1/campaigns/ghost/stages/S1/escalation:resolve",
                             json={"action": "abort"}, headers=_auth())
    assert r.status_code == 404


def test_temporal_backend_points_at_the_other_endpoint(tmp_path, monkeypatch):
    seed_campaign(tmp_path)
    _patch_settings(monkeypatch, tmp_path, backend="temporal")
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    r = TestClient(app).post(URL, json={"action": "abort"}, headers=_auth())
    assert r.status_code == 409
    assert "escalation:decide" in r.text
