"""Run integrity (2026-10-18): a pilot or production campaign starts only on a MAP a person signed, and on the CPF it
signed (D-36, 2026-10-19); every e-signature is an audit event, and the project's P6 phase follows its campaigns
(`modeler_api.run_guard`, `part11`, `project_api`).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from fastapi.testclient import TestClient

from modeler_api.execution import get_campaign_runner
from modeler_api.main import app
from modeler_project import FileProjectStore
from modeler_storage.filestore import FileWriteStore
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import FoodState, FormulationKind, QuestionOfInterest, Route, StudyRecord, split_studies
from pbpk_domain.cpf import CPF, FitPolicy, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

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


def _cpf(logp_upper: float = 4.0) -> CPF:
    prov = Provenance(source_type="measured", reference="Example 2020")
    return CPF(compound="Drug-A", parameters=(
        ParameterRecord(id="phys.mw", value=408.5, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.6, unit="Log Units", status=ParameterStatus.PREDICTED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=logp_upper)),
        ParameterRecord(id="bind.fu", value=0.02, status=ParameterStatus.FIXED, provenance=prov),
    ))


def _map(tmp_path, *, signed: bool) -> tuple[str, str]:
    """A MAP generated from `_cpf()` (beside it as cpf.json), signed in the model plan or left a draft."""
    (tmp_path / "cpf.json").write_text(_cpf().model_dump_json(), encoding="utf-8")
    studies = [StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0,
                           formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15)]
    doc = generate_map(compound="Drug-A", cpf=_cpf(), studies=studies, split=split_studies(studies, QuestionOfInterest()),
                       objective="predict", context_of_use="MIDD", food_effect_in_question=False, model_risk=Rating.MEDIUM,
                       engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"})
    if signed:
        doc = doc.sign(printed_name="Dev User", signature_id="s1")
    path = tmp_path / ("signed.json" if signed else "draft.json")
    path.write_bytes(doc.model_dump_json().encode("utf-8"))
    return path.as_uri(), hashlib.sha256(path.read_bytes()).hexdigest()


def _start(client, map_uri, cpf_uri: str | None = None):
    beside = (Path(unquote(urlparse(map_uri).path)).parent / "cpf.json").as_uri()
    body = {"compound": "Drug-A", "map_id": "map-1", "cpf_uri": cpf_uri or beside, "cpf_sha256": "a" * 64,
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


def test_a_pilot_start_cannot_override_the_signed_stage_budgets(client, tmp_path, monkeypatch):
    # the owner's decision (2026-10-18): MS-01's fixed shares of the signed budget; more time = a larger budget, re-signed
    http, runner = client
    monkeypatch.setenv("MODELER_DEPLOYMENT", "pilot")
    signed_uri, _ = _map(tmp_path, signed=True)
    body = {"compound": "Drug-A", "map_id": "map-1", "cpf_uri": "file:///x/cpf.json", "cpf_sha256": "a" * 64,
            "map_uri": signed_uri, "model_risk": "medium", "stage_budgets_seconds": {"S1": 7200}}
    refused = http.post("/api/v1/projects/p1/campaigns", json=body, headers=DEV)
    assert refused.status_code == 422 and "raise its budget in the model plan" in refused.json()["detail"]
    assert not runner.started
    monkeypatch.delenv("MODELER_DEPLOYMENT", raising=False)       # development: the reference runs set their own
    assert http.post("/api/v1/projects/p1/campaigns", json=body, headers=DEV).status_code == 202


def test_a_pilot_runs_only_on_the_cpf_its_map_signed(client, tmp_path, monkeypatch):
    # D-36: the signature binds the parameters the run uses, the fit bounds among them
    http, runner = client
    monkeypatch.setenv("MODELER_DEPLOYMENT", "pilot")
    signed_uri, _ = _map(tmp_path, signed=True)
    wider = tmp_path / "wider.json"
    wider.write_text(_cpf(logp_upper=6.0).model_dump_json(), encoding="utf-8")
    refused = _start(http, signed_uri, wider.as_uri())
    detail = refused.json()["detail"]
    assert refused.status_code == 409 and "not the one its MAP signed" in detail and not runner.started
    assert "phys.logp: bounds [1, 6] linear in the campaign's CPF, [1, 4] linear in the signed MAP" in detail
    missing = _start(http, signed_uri, (tmp_path / "nowhere.json").as_uri())
    assert missing.status_code == 409 and "could not be read" in missing.json()["detail"]
    assert _start(http, signed_uri).status_code == 202 and len(runner.started) == 1
    monkeypatch.delenv("MODELER_DEPLOYMENT", raising=False)       # development: S0 notes the departure instead
    assert _start(http, signed_uri, wider.as_uri()).status_code == 202


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
