"""Starting a campaign (the execution backend, auth-guarded). `map:generate`, a stateless MAP from a client-supplied CPF,
is retired (the console redesign's slice 9): the plan canvas generates, persists and signs the MAP."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app

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


def _auth():
    return {"Authorization": "Bearer tok"}


def test_the_retired_map_generate_answers_nothing():
    assert client_with(claims()).post(URL, json={}, headers=_auth()).status_code in (404, 405)


# --- start campaign: execution backend ------------------------------------------------------------


from modeler_api.execution import get_campaign_runner

CAMPAIGN_URL = "/api/v1/projects/proj-1/campaigns"


def _start_body() -> dict:
    return {"compound": "Drug-A", "map_id": "map-1", "cpf_uri": "file:///x/cpf.json",
            "cpf_sha256": "a" * 64, "map_uri": "file:///x/map.json", "observed_uri": "file:///x/obs.json",
            "question": "predict exposure", "model_risk": "medium"}


class _RecordingRunner:
    """A CampaignRunner (modeler_contracts.ports) that records the start instead of running a campaign."""

    def __init__(self):
        self.started = {}

    def start(self, request, *, read_root, project, question, model_risk):
        self.started.update(campaign_id=request.campaign_id, read_root=read_root, project=project)


def test_start_campaign_local_backend_launches_runner(api_settings):
    runner = _RecordingRunner()
    app.dependency_overrides[get_campaign_runner] = lambda: runner
    launched = runner.started
    api_settings(execution_backend="local", read_root="/tmp/read-root", temporal_address=None)

    r = client_with(claims()).post(CAMPAIGN_URL, json=_start_body(), headers=_auth())
    assert r.status_code == 202
    assert r.json()["status"] == "QUEUED"
    assert launched["project"] == "proj-1" and launched["read_root"] == "/tmp/read-root"
    assert launched["campaign_id"].startswith("camp_")


def test_start_campaign_local_without_read_root_is_503(monkeypatch, api_settings):
    api_settings(execution_backend="local", read_root="", temporal_address=None)
    r = client_with(claims()).post(CAMPAIGN_URL, json=_start_body(), headers=_auth())
    assert r.status_code == 503


def test_start_campaign_temporal_backend_without_address_is_503(monkeypatch, api_settings):
    api_settings(execution_backend="temporal", read_root="/tmp/read-root", temporal_address=None)
    r = client_with(claims()).post(CAMPAIGN_URL, json=_start_body(), headers=_auth())
    assert r.status_code == 503


def test_start_campaign_wrong_project_is_403(monkeypatch, api_settings):
    api_settings(execution_backend="local", read_root="/tmp/read-root", temporal_address=None)
    r = client_with(claims(projects=("other",))).post(CAMPAIGN_URL, json=_start_body(), headers=_auth())
    assert r.status_code == 403
