"""GET /runs/{id}/results — tenant-scoped read of ingested Parquet (T-08 API surface)."""

from __future__ import annotations

import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_api.results_api import get_results_dir

PLASMA = "Organism|PeripheralVenousBlood|Drug|Plasma (Peripheral Venous Blood)"


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dr Lead", "tenant_id": "t1", "realm_access": {"roles": ["modeler-viewer"]},
                "projects": ["proj-1"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    parquet = tmp_path / "tenants" / "t1" / "runs" / "run-1" / "results.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "individual_id": [0, 0, 0], "time": [0.0, 1.0, 2.0], "time_unit": ["min"] * 3,
        "path": [PLASMA] * 3, "unit": ["µmol/l"] * 3, "value": [0.0, 3.254684, 10.44706],
    }), parquet)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[get_results_dir] = lambda: tmp_path
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth():
    return {"Authorization": "Bearer tok"}


def test_lists_output_paths(client):
    r = client.get("/api/v1/runs/run-1/results", headers=_auth())
    assert r.status_code == 200
    assert r.json()["output_paths"] == [PLASMA]


def test_returns_the_concentration_series(client):
    r = client.get("/api/v1/runs/run-1/results", params={"path": PLASMA}, headers=_auth())
    assert r.status_code == 200
    series = r.json()["series"]
    assert [p["time"] for p in series] == [0.0, 1.0, 2.0]
    assert series[2]["value"] == 10.44706


def test_unknown_run_is_404(client):
    assert client.get("/api/v1/runs/nope/results", headers=_auth()).status_code == 404


def test_requires_a_token(client):
    assert client.get("/api/v1/runs/run-1/results").status_code == 401


def test_other_tenant_cannot_read(tmp_path, monkeypatch):
    # a principal for tenant "t2" resolves to tenants/t2/... which does not exist -> 404 (never reads t1)
    class V2:
        def verify(self, token):
            return {"sub": "u", "tenant_id": "t2", "realm_access": {"roles": ["modeler-viewer"]},
                    "projects": ["proj-1"], "acr": "loa2", "auth_time": int(time.time())}

    parquet = tmp_path / "tenants" / "t1" / "runs" / "run-1" / "results.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"individual_id": [0], "time": [0.0], "time_unit": ["min"], "path": [PLASMA], "unit": ["µmol/l"], "value": [1.0]}), parquet)
    app.dependency_overrides[get_verifier] = lambda: V2()
    app.dependency_overrides[get_results_dir] = lambda: tmp_path
    try:
        assert TestClient(app).get("/api/v1/runs/run-1/results", headers=_auth()).status_code == 404
    finally:
        app.dependency_overrides.clear()
