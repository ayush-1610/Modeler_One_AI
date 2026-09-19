from __future__ import annotations

import json

from fastapi.testclient import TestClient

from modeler_api.auth import AuthError, get_verifier
from modeler_api.main import app
from modeler_api.read_api import FileReadStore, get_read_store, project_cpf_view
from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.cpf.models import FitPolicy


class FakeVerifier:
    def __init__(self, claims):
        self.claims = claims

    def verify(self, token):
        if self.claims is None:
            raise AuthError("rejected")
        return self.claims


def claims(*, tenant="dev", roles=("modeler-viewer",), projects=("example-a",)):
    return {"sub": "u", "name": "Dev", "tenant_id": tenant, "realm_access": {"roles": list(roles)},
            "projects": list(projects), "acr": "loa1"}


def _cpf() -> CPF:
    prov = Provenance(source_type="measured", reference="Smith 2019")
    return CPF(compound="Example-A", version=4, parameters=(
        ParameterRecord(id="phys.mw", value=300.0, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.5, unit="Log Units", status=ParameterStatus.FITTED,
                        provenance=Provenance(source_type="ParameterIdentification", reference="S1 round 3"),
                        fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=4.0)),
        ParameterRecord(id="bind.fu", value=0.12, unit="", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=1.4, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="elim.renal.gfr_fraction", value=1.0, unit="", status=ParameterStatus.PREDICTED,
                        provenance=Provenance(source_type="assumed")),
    ))  # note: no phys.pka -> 5/6 complete


class FakeStore:
    def list_projects(self, tenant_id):
        return [{"id": "example-a", "name": "Example-A program", "compounds": ["Example-A"], "openQuestions": 2, "risk": "high"}]

    def get_project(self, tenant_id, project_id):
        return next((p for p in self.list_projects(tenant_id) if p["id"] == project_id), None)

    def get_cpf(self, tenant_id, project_id, compound):
        return _cpf() if compound == "Example-A" else None


def client_with(claims_dict, store=None) -> TestClient:
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims_dict)
    app.dependency_overrides[get_read_store] = lambda: store or FakeStore()
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _auth():
    return {"Authorization": "Bearer tok"}


# --- projection ----------------------------------------------------------------------------------


def test_cpf_view_projects_parameters_and_completeness():
    view = project_cpf_view(_cpf())
    assert view["compound"] == "Example-A" and view["version"] == 4
    assert view["completeness"] == round(5 / 6, 3)  # missing pKa
    assert view["ready"] is False
    logp = next(p for p in view["parameters"] if p["id"] == "phys.logp")
    assert logp["status"] == "fitted" and logp["source"] == "ParameterIdentification"
    assert logp["fittableStages"] == ["S1"]


# --- endpoints -----------------------------------------------------------------------------------


def test_list_projects():
    r = client_with(claims()).get("/api/v1/projects", headers=_auth())
    assert r.status_code == 200
    assert r.json()["data"]["projects"][0]["id"] == "example-a"


def test_get_project_and_404():
    c = client_with(claims(projects=("example-a",)))
    assert c.get("/api/v1/projects/example-a", headers=_auth()).status_code == 200
    r = client_with(claims(projects=("nope",))).get("/api/v1/projects/nope", headers=_auth())
    # member of "nope" but the store has no such project -> 404
    assert r.status_code == 404


def test_get_cpf_returns_projection():
    r = client_with(claims()).get("/api/v1/projects/example-a/compounds/Example-A/cpf", headers=_auth())
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["compound"] == "Example-A"
    assert any(p["id"] == "elim.renal.gfr_fraction" for p in data["parameters"])


def test_cpf_unknown_compound_is_404():
    r = client_with(claims()).get("/api/v1/projects/example-a/compounds/Ghost/cpf", headers=_auth())
    assert r.status_code == 404


def test_non_member_project_is_403():
    r = client_with(claims(projects=("other",))).get("/api/v1/projects/example-a", headers=_auth())
    assert r.status_code == 403


def test_missing_token_is_401():
    assert client_with(claims()).get("/api/v1/projects").status_code == 401


def test_unconfigured_store_is_503():
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims())
    # no read store override, and MODELER_READ_ROOT unset -> get_read_store raises 503
    app.dependency_overrides.pop(get_read_store, None)
    r = TestClient(app).get("/api/v1/projects", headers=_auth())
    assert r.status_code == 503


# --- FileReadStore -------------------------------------------------------------------------------


def test_file_read_store_roundtrip(tmp_path):
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev" / "projects.json").write_text(json.dumps(
        {"projects": [{"id": "example-a", "name": "Example-A program", "compounds": ["Example-A"], "openQuestions": 1, "risk": "high"}]}))
    (tmp_path / "dev" / "cpf").mkdir()
    (tmp_path / "dev" / "cpf" / "Example-A.json").write_text(_cpf().model_dump_json())

    store = FileReadStore(str(tmp_path))
    assert store.list_projects("dev")[0]["id"] == "example-a"
    assert store.get_project("dev", "example-a")["risk"] == "high"
    assert store.get_cpf("dev", "example-a", "Example-A").compound == "Example-A"
    assert store.get_cpf("dev", "example-a", "Ghost") is None
    assert store.list_projects("other-tenant") == []  # tenant isolation by path
