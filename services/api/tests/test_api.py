from fastapi.testclient import TestClient

from modeler_api.main import app

client = TestClient(app)

MODEL_REQUEST = {
    "compounds": [
        {
            "name": "Example-A",
            "molecular_weight": {"value": 325.8, "unit": "g/mol"},
            "lipophilicity": {"value": 3.1, "unit": "Log Units"},
            "fraction_unbound": {"value": 0.03},
            "processes": [
                {"kind": "GlomerularFiltration", "data_source": "assumed", "gfr_fraction": {"value": 1.0}},
            ],
        }
    ],
    "subjects": [{"name": "Adult", "gender": "FEMALE", "age_years": 40, "seed": 7}],
    "protocols": [{"kind": "intravenous", "name": "IV 1 mg", "dose": {"value": 1, "unit": "mg"}, "infusion_time_min": 10}],
    "simulations": [{"name": "IV", "subject": "Adult", "compound": "Example-A", "protocol": "IV 1 mg", "end_time_h": 12}],
}


def test_preview_returns_hash_and_snapshot():
    response = client.post("/api/v1/model-versions/preview", json=MODEL_REQUEST)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]["snapshot_sha256"]) == 64
    assert body["data"]["snapshot"]["Simulations"][0]["Individual"] == "Adult"
    again = client.post("/api/v1/model-versions/preview", json=MODEL_REQUEST).json()
    assert again["data"]["snapshot_sha256"] == body["data"]["snapshot_sha256"]


def test_preview_reports_reference_issues():
    broken = {**MODEL_REQUEST, "simulations": [{**MODEL_REQUEST["simulations"][0], "protocol": "missing"}]}
    response = client.post("/api/v1/model-versions/preview", json=broken)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "UNKNOWN_PROTOCOL"


def test_m15_validation_reports_allowed_model_risk():
    response = client.post(
        "/api/v1/m15/validate",
        json={
            "stage": "planning",
            "table": {
                "question_of_interest": "Q",
                "model_influence": {"rating": "high"},
                "consequence_of_wrong_decision": {"rating": "low"},
            },
        },
    )
    data = response.json()["data"]
    assert data["complete"] is False
    assert data["allowed_model_risk"] == ["low", "medium", "high"]


def test_run_submission_requires_orchestrator():
    response = client.post(
        "/api/v1/runs",
        headers={"X-Tenant-Id": "t1"},
        json={"snapshot_uri": "file:///tmp/s.json", "snapshot_sha256": "a" * 64},
    )
    assert response.status_code == 503
