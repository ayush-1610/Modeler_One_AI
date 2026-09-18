"""Escalation/deviation API (T-17): a stage resumes only through a signed decision.

Uses FastAPI dependency overrides so the flow is tested without Keycloak, Temporal or a database: a fake
verifier stands in for step-up auth, a fake signaler records the workflow signal, a fake store records the row.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from modeler_api.escalations import get_signaler, get_store, get_verifier
from modeler_api.main import app

SHA = "a" * 64


class FakeVerifier:
    def __init__(self, ok: bool):
        self.ok = ok

    def verify(self, user_id: str, password: str, second_factor: str) -> bool:
        return self.ok


class FakeSignaler:
    def __init__(self) -> None:
        self.escalations: list[dict] = []
        self.deviations: list[dict] = []

    async def signal_escalation(self, *, campaign_id, stage, decision) -> None:
        self.escalations.append({"campaign_id": campaign_id, "stage": stage, "decision": decision})

    async def signal_deviation(self, *, campaign_id, stage, deviation) -> None:
        self.deviations.append({"campaign_id": campaign_id, "stage": stage, "deviation": deviation})


class FakeStore:
    def __init__(self) -> None:
        self.decisions: list[dict] = []

    async def record_escalation_decision(self, *, campaign_id, stage, decision, signature_id) -> None:
        self.decisions.append({"campaign_id": campaign_id, "stage": stage, "signature_id": signature_id})

    async def record_deviation(self, *, campaign_id, deviation, signature_id) -> None:
        self.decisions.append({"campaign_id": campaign_id, "signature_id": signature_id})


@pytest.fixture
def wired():
    signaler, store = FakeSignaler(), FakeStore()

    def use(*, verify_ok: bool):
        app.dependency_overrides[get_verifier] = lambda: FakeVerifier(verify_ok)
        app.dependency_overrides[get_signaler] = lambda: signaler
        app.dependency_overrides[get_store] = lambda: store
        return TestClient(app), signaler, store

    yield use
    app.dependency_overrides.clear()


def _decision_body(**kw):
    body = dict(action="accept_best", note="reviewed the diagnostics", escalation_id="esc-1", record_sha256=SHA,
                signer_id="u1", printed_name="Dr Lead", password="pw", second_factor="123456")
    body.update(kw)
    return body


def test_decision_options_from_ms01():
    r = TestClient(app).get("/api/v1/escalations/decision-options")
    assert r.status_code == 200
    actions = {o["action"] for o in r.json()["options"]}
    assert actions == {"retry", "accept_best", "abort"}
    assert all(o["required_signature"] == "Approved" for o in r.json()["options"])


def test_valid_signature_signals_and_records(wired):
    client, signaler, store = wired(verify_ok=True)
    r = client.post("/api/v1/campaigns/camp1/stages/S1/escalation:decide", json=_decision_body(), headers={"X-Tenant-Id": "t1"})
    assert r.status_code == 200
    assert r.json()["action"] == "accept_best"
    assert r.json()["signature"]["manifestation"].startswith("Dr Lead | Approved")
    # the workflow was signalled and the decision recorded
    assert len(signaler.escalations) == 1
    assert signaler.escalations[0]["decision"].action == "accept_best"
    assert signaler.escalations[0]["decision"].signature_id == r.json()["signature"]["signature_id"]
    assert len(store.decisions) == 1


def test_bad_signature_is_rejected_and_never_signals(wired):
    client, signaler, store = wired(verify_ok=False)  # credentials rejected by the IdP
    r = client.post("/api/v1/campaigns/camp1/stages/S1/escalation:decide", json=_decision_body(), headers={"X-Tenant-Id": "t1"})
    assert r.status_code == 403
    assert signaler.escalations == []  # the escalated stage is NOT resumed without a valid signature
    assert store.decisions == []


def test_missing_second_factor_is_rejected(wired):
    client, signaler, _ = wired(verify_ok=True)
    r = client.post("/api/v1/campaigns/camp1/stages/S1/escalation:decide",
                    json=_decision_body(second_factor=""), headers={"X-Tenant-Id": "t1"})
    assert r.status_code == 422  # pydantic min_length: both identification components are required
    assert signaler.escalations == []


def test_signaler_not_configured_returns_503():
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(True)
    try:
        r = TestClient(app).post("/api/v1/campaigns/c/stages/S1/escalation:decide", json=_decision_body(), headers={"X-Tenant-Id": "t1"})
        assert r.status_code == 503  # signalling not wired -> service unavailable, no partial action
    finally:
        app.dependency_overrides.clear()


def test_deviation_requires_signature(wired):
    client, signaler, _store = wired(verify_ok=True)
    body = dict(stage="S3", description="moved a fed study to internal", record_sha256=SHA,
                signer_id="u1", printed_name="Dr Lead", password="pw", second_factor="123456")
    r = client.post("/api/v1/campaigns/camp1/deviations", json=body, headers={"X-Tenant-Id": "t1"})
    assert r.status_code == 201
    assert len(signaler.deviations) == 1 and signaler.deviations[0]["deviation"].stage == "S3"
