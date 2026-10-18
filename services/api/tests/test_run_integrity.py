"""Run integrity (2026-10-18): a pilot or production campaign starts only on a MAP a person signed, every e-signature
is an audit event, and the project's P6 phase follows its campaigns (`modeler_api.run_guard`, `part11`, `project_api`).
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from modeler_api.execution import get_campaign_runner
from modeler_api.main import app
from modeler_project import FileProjectStore
from modeler_storage.filestore import FileWriteStore

pytestmark = pytest.mark.req("T-06")

DEV = {"Authorization": "Bearer dev"}


class _RecordingRunner:
    def __init__(self):
        self.started: list[str] = []

    def start(self, request, *, read_root, project, question, model_risk):
        self.started.append(request.campaign_id)


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path), dev_auth=True, execution_backend="local")
    runner = _RecordingRunner()
    app.dependency_overrides[get_campaign_runner] = lambda: runner
    yield TestClient(app), runner
    app.dependency_overrides.clear()


def _map(tmp_path, *, signed: bool) -> tuple[str, str]:
    doc = {"version": 1, "compound": "Drug-A", "status": "SIGNED" if signed else "DRAFT",
           "signature": {"printed_name": "Dev User", "signature_id": "s1"} if signed else None}
    path = tmp_path / ("signed.json" if signed else "draft.json")
    path.write_bytes(json.dumps(doc).encode("utf-8"))
    return path.as_uri(), hashlib.sha256(path.read_bytes()).hexdigest()


def _start(client, map_uri):
    body = {"compound": "Drug-A", "map_id": "map-1", "cpf_uri": "file:///x/cpf.json", "cpf_sha256": "a" * 64,
            "map_uri": map_uri, "observed_uri": "file:///x/obs.json", "model_risk": "medium"}
    return client.post("/api/v1/projects/p1/campaigns", json=body, headers=DEV)


def test_a_pilot_starts_only_on_a_map_a_person_signed(client, tmp_path, monkeypatch):
    http, runner = client
    monkeypatch.setenv("MODELER_DEPLOYMENT", "pilot")
    draft_uri, draft_sha = _map(tmp_path, signed=False)
    refused = _start(http, draft_uri)
    assert refused.status_code == 409 and "not signed" in refused.json()["detail"] and not runner.started

    signed_uri, _ = _map(tmp_path, signed=True)            # signed in the model plan (P5)
    assert _start(http, signed_uri).status_code == 202

    approval = {"meaning": "Approved", "record_type": "map_approval", "record_id": "map-1", "record_sha256": draft_sha}
    assert http.post("/api/v1/projects/p1/signatures", json=approval, headers=DEV).status_code == 201
    assert _start(http, draft_uri).status_code == 202      # campaign:prepare's MAP, approved by its own signature
    assert len(runner.started) == 2


def test_development_may_start_an_unsigned_map(client, tmp_path, monkeypatch):
    http, runner = client
    monkeypatch.delenv("MODELER_DEPLOYMENT", raising=False)
    assert _start(http, _map(tmp_path, signed=False)[0]).status_code == 202 and runner.started


def test_the_model_risk_must_be_said_at_the_start(client, tmp_path):
    http, _runner = client
    body = {"compound": "Drug-A", "map_id": "map-1", "cpf_uri": "file:///x/cpf.json", "cpf_sha256": "a" * 64}
    assert http.post("/api/v1/projects/p1/campaigns", json=body, headers=DEV).status_code == 422


def test_every_signature_is_an_audit_event(client, tmp_path):
    http, _runner = client
    body = {"meaning": "Approved", "record_type": "map_approval", "record_id": "map-1", "record_sha256": "b" * 64}
    signed = http.post("/api/v1/projects/p1/signatures", json=body, headers=DEV).json()
    event = FileProjectStore(tmp_path).audit("dev").records()[-1].event
    assert (event.action, event.resource_type, event.resource_id) == ("signature.create", "map_approval", "map-1")
    assert event.after["signature_id"] == signed["signature_id"] and event.after["record_sha256"] == "b" * 64


def test_the_p6_phase_follows_the_projects_campaigns(client, tmp_path):
    http, _runner = client
    store = FileWriteStore(str(tmp_path))
    store.put_project("dev", {"id": "p1", "name": "P1", "compounds": ["Drug-A"], "openQuestions": 0, "risk": "medium",
                              "questions": [], "pipeline": True})

    def p6() -> str:
        phases = http.get("/api/v1/projects/p1/phases", headers=DEV).json()["data"]["phases"]
        return next(p["status"] for p in phases if p["phase"] == "P6")

    assert p6() == "NOT_STARTED"
    store.upsert_campaign("dev", {"id": "camp-1", "project": "p1", "status": "RUNNING"})
    assert p6() == "IN_REVIEW"
    store.upsert_campaign("dev", {"id": "camp-1", "project": "p1", "status": "COMPLETED"})
    assert p6() == "APPROVED"


@pytest.mark.req("T-16")
def test_the_plans_fit_reserve_is_the_runners():
    # the plan warns when a stage's share cannot hold a fit; it must use the reserve the runner keeps
    from modeler_contracts.runs import FitRoundRequest
    from modeler_project.plan import FIT_RESERVE_S

    assert FitRoundRequest.__dataclass_fields__["reserved_seconds"].default == FIT_RESERVE_S
