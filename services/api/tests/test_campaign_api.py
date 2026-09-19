"""map:generate endpoint (exposes the MS-01 MAP generator, auth-guarded)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app
from pbpk_domain.campaign.split import FoodState, FormulationKind, Route, StudyRecord
from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus, Provenance

URL = "/api/v1/projects/proj-1/questions/q-1/map:generate"


class FakeVerifier:
    def __init__(self, claims):
        self.claims = claims

    def verify(self, token):
        return self.claims


def claims(*, roles=("modeler-curator",), projects=("proj-1",)):
    return {"sub": "u1", "name": "Dr Lead", "tenant_id": "t1", "realm_access": {"roles": list(roles)},
            "projects": list(projects), "acr": "loa2", "auth_time": int(time.time())}


def client_with(claims_dict) -> TestClient:
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims_dict)
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _body() -> dict:
    prov = Provenance(source_type="measured", reference="x")
    cpf = CPF(compound="Drug-A", parameters=(
        ParameterRecord(id="phys.mw", value=300.0, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.5, unit="Log Units", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="bind.fu", value=0.1, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=0.5, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
    ))
    study = StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0, infusion_time_min=5.0,
                        formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15)
    return {
        "compound": "Drug-A", "cpf": cpf.model_dump(mode="json"), "studies": [study.model_dump(mode="json")],
        "objective": "predict exposure", "context_of_use": "MIDD", "food_effect_in_question": False,
        "model_risk": "medium", "engine_image_digest": "sha256:abcd", "software_versions": {"ospsuite": "12.4.4"},
    }


def _auth():
    return {"Authorization": "Bearer tok"}


def test_generates_a_map_for_a_project_member():
    r = client_with(claims()).post(URL, json=_body(), headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["question_id"] == "q-1"
    m = body["map"]
    assert m["version"] == 1 and m["status"] == "DRAFT"
    assert m["compound"] == "Drug-A"
    assert m["acceptance"]["tier"] == "medium"
    assert any(s["study_id"] == "iv" for s in m["studies"])


def test_requires_a_token():
    r = client_with(claims()).post(URL, json=_body())  # no Authorization
    assert r.status_code == 401


def test_wrong_project_is_403():
    r = client_with(claims(projects=("other",))).post(URL, json=_body(), headers=_auth())
    assert r.status_code == 403


def test_viewer_role_is_forbidden():
    r = client_with(claims(roles=("modeler-viewer",))).post(URL, json=_body(), headers=_auth())
    assert r.status_code == 403  # generating a MAP needs curator/reviewer


# --- start campaign: execution backend ------------------------------------------------------------

from types import SimpleNamespace

from modeler_api import campaign_api

CAMPAIGN_URL = "/api/v1/projects/proj-1/campaigns"


def _start_body() -> dict:
    return {"compound": "Drug-A", "map_id": "map-1", "cpf_uri": "file:///x/cpf.json",
            "cpf_sha256": "a" * 64, "map_uri": "file:///x/map.json", "observed_uri": "file:///x/obs.json",
            "question": "predict exposure", "model_risk": "medium"}


def test_start_campaign_local_backend_launches_runner(monkeypatch):
    launched = {}

    def fake_launch(request, *, read_root, project, question, model_risk):
        launched.update(campaign_id=request.campaign_id, read_root=read_root, project=project)

    monkeypatch.setattr(campaign_api, "_launch_local_campaign", fake_launch)
    monkeypatch.setattr(campaign_api, "get_settings", lambda: SimpleNamespace(
        execution_backend="local", read_root="/tmp/read-root", temporal_address=None, temporal_namespace="default"))

    r = client_with(claims()).post(CAMPAIGN_URL, json=_start_body(), headers=_auth())
    assert r.status_code == 202
    assert r.json()["status"] == "QUEUED"
    assert launched["project"] == "proj-1" and launched["read_root"] == "/tmp/read-root"
    assert launched["campaign_id"].startswith("camp_")


def test_start_campaign_local_without_read_root_is_503(monkeypatch):
    monkeypatch.setattr(campaign_api, "get_settings", lambda: SimpleNamespace(
        execution_backend="local", read_root="", temporal_address=None, temporal_namespace="default"))
    r = client_with(claims()).post(CAMPAIGN_URL, json=_start_body(), headers=_auth())
    assert r.status_code == 503


def test_start_campaign_temporal_backend_without_address_is_503(monkeypatch):
    monkeypatch.setattr(campaign_api, "get_settings", lambda: SimpleNamespace(
        execution_backend="temporal", read_root="/tmp/read-root", temporal_address=None, temporal_namespace="default"))
    r = client_with(claims()).post(CAMPAIGN_URL, json=_start_body(), headers=_auth())
    assert r.status_code == 503


def test_start_campaign_wrong_project_is_403(monkeypatch):
    monkeypatch.setattr(campaign_api, "get_settings", lambda: SimpleNamespace(
        execution_backend="local", read_root="/tmp/read-root", temporal_address=None, temporal_namespace="default"))
    r = client_with(claims(projects=("other",))).post(CAMPAIGN_URL, json=_start_body(), headers=_auth())
    assert r.status_code == 403
