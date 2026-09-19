"""The guided create-project write path: create project → put CPF → upload studies → prepare campaign."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from modeler_api import write_api
from modeler_api.auth import get_verifier
from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_api.main import app
from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus, Provenance


class FakeVerifier:
    def __init__(self, claims):
        self.claims = claims

    def verify(self, token):
        return self.claims


def claims(*, roles=("modeler-curator",), projects=("*",)):
    return {"sub": "u", "name": "Dev", "tenant_id": "t1", "realm_access": {"roles": list(roles)},
            "projects": list(projects), "acr": "loa2", "auth_time": int(time.time())}


def client_with(tmp_path, claims_dict=None) -> TestClient:
    root = str(tmp_path)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims_dict or claims())
    app.dependency_overrides[write_api._stores] = lambda: (FileReadStore(root), FileWriteStore(root))
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def _auth():
    return {"Authorization": "Bearer tok"}


def _renal_cpf() -> dict:
    prov = Provenance(source_type="measured", reference="OSP Aciclovir")
    cpf = CPF(compound="Renaldrug", parameters=(
        ParameterRecord(id="phys.mw", value=225.2, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=-1.6, unit="Log Units", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.pka.neutral", value=1.0, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="bind.fu", value=0.85, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=1.3, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="elim.renal.gfr_fraction", value=1.0, status=ParameterStatus.FIXED, provenance=prov),
    ))
    return cpf.model_dump(mode="json")


def _study() -> dict:
    return {"study_id": "iv", "route": "iv_bolus", "dose_mg": 5.0, "infusion_time_min": 5.0,
            "formulation": "solution", "food_state": "fasted", "n": 12, "n_timepoints": 10,
            "profile": {"times": [30, 60, 120, 240, 480], "values": [40.0, 34.0, 19.0, 6.6, 0.4],
                        "time_unit": "min", "unit": "µmol/l"}}


def test_full_guided_write_flow(tmp_path):
    c = client_with(tmp_path)

    # 1. create the project
    r = c.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Renaldrug", "question": "FIH dose"},
               headers=_auth())
    assert r.status_code == 201
    project = r.json()["data"]
    assert project["id"] == "renal-demo" and project["compounds"] == ["Renaldrug"]
    assert project["questions"][0]["question"] == "FIH dose"
    assert FileReadStore(str(tmp_path)).get_project("t1", "renal-demo")["name"] == "Renal Demo"

    # 2. put the CPF
    r = c.put("/api/v1/projects/renal-demo/compounds/Renaldrug/cpf", json=_renal_cpf(), headers=_auth())
    assert r.status_code == 200
    assert r.json()["data"]["ready"] is True  # S0-complete renal CPF
    assert FileReadStore(str(tmp_path)).get_cpf("t1", "renal-demo", "Renaldrug").compound == "Renaldrug"

    # 3. upload observed studies
    r = c.post("/api/v1/projects/renal-demo/studies", json={"studies": [_study()]}, headers=_auth())
    assert r.status_code == 201 and r.json()["data"]["stored"] == 1

    # 4. prepare the campaign inputs (CPF + MAP + observed)
    r = c.post("/api/v1/projects/renal-demo/questions/qoi-1/campaign:prepare",
               json={"compound": "Renaldrug", "stages": ["S0", "S1"]}, headers=_auth())
    assert r.status_code == 200
    prep = r.json()["data"]
    assert prep["cpf_uri"].endswith("prep/qoi-1/cpf.json")
    assert prep["map_uri"].endswith("prep/qoi-1/map.json") and len(prep["map_sha256"]) == 64
    assert prep["observed_uri"].endswith("prep/qoi-1/observed.json")
    assert any(s["study_id"] == "iv" for s in prep["studies"])

    # the staged observed data carries NCA-derived auc/cmax plus the raw profile the fit reads
    import json
    from pathlib import Path
    from urllib.parse import unquote, urlparse
    observed = json.loads(Path(unquote(urlparse(prep["observed_uri"]).path)).read_text())
    assert observed["iv"]["cmax"] == 40.0 and observed["iv"]["auc"] > 0 and "profile" in observed["iv"]


def test_put_cpf_compound_mismatch_is_422(tmp_path):
    c = client_with(tmp_path)
    r = c.put("/api/v1/projects/p/compounds/Wrong/cpf", json=_renal_cpf(), headers=_auth())
    assert r.status_code == 422


def test_prepare_without_cpf_is_404(tmp_path):
    c = client_with(tmp_path)
    c.post("/api/v1/projects", json={"name": "Empty", "compound": "X"}, headers=_auth())
    r = c.post("/api/v1/projects/empty/questions/q/campaign:prepare", json={"compound": "X"}, headers=_auth())
    assert r.status_code == 404


def test_writes_require_curator_role(tmp_path):
    c = client_with(tmp_path, claims(roles=("modeler-viewer",)))
    r = c.post("/api/v1/projects", json={"name": "X", "compound": "Y"}, headers=_auth())
    assert r.status_code == 403


def test_writes_require_project_membership(tmp_path):
    c = client_with(tmp_path, claims(projects=("other",)))
    r = c.put("/api/v1/projects/renal-demo/compounds/Renaldrug/cpf", json=_renal_cpf(), headers=_auth())
    assert r.status_code == 403