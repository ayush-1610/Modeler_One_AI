"""The guided create-project write path: create project → put CPF → upload studies → prepare campaign."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import write_api
from modeler_api.auth import get_verifier
from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_api.main import app
from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance


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
        # bound to PK-Sim's GFR process, or the pathway could not be placed and S0 refuses the CPF
        ParameterRecord(id="elim.renal.gfr_fraction", value=1.0, status=ParameterStatus.FIXED, provenance=prov,
                        engine_binding=EngineBinding(building_block="Compound", process="GlomerularFiltration",
                                                     parameter="GFR fraction", data_source="Literature")),
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


def _prepared(tmp_path, study: dict, body: dict | None = None):
    import json
    from pathlib import Path
    from urllib.parse import unquote, urlparse

    c = client_with(tmp_path)
    c.post("/api/v1/projects", json={"name": "Renal Demo", "compound": "Renaldrug"}, headers=_auth())
    c.put("/api/v1/projects/renal-demo/compounds/Renaldrug/cpf", json=_renal_cpf(), headers=_auth())
    c.post("/api/v1/projects/renal-demo/studies", json={"studies": [study]}, headers=_auth())
    r = c.post("/api/v1/projects/renal-demo/questions/q/campaign:prepare", json=body or {"compound": "Renaldrug"},
               headers=_auth())
    if r.status_code != 200:
        return r, None, None
    prep = r.json()["data"]
    load = lambda uri: json.loads(Path(unquote(urlparse(uri).path)).read_text())
    return r, prep, (load(prep["observed_uri"]), load(prep["map_uri"]))


def test_prepare_schedules_every_stage_by_default(tmp_path):
    """R0: the campaign used to be prepared for S0–S2 only (and the UI asked for S0–S1)."""
    _, prep, _ = _prepared(tmp_path, _study())
    assert prep["stages"] == ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"]


def test_prepare_converts_observed_data_to_engine_units(tmp_path):
    """Hours and ng/ml are converted to minutes and µmol/l, so the gate compares like with like."""
    study = _study() | {"profile": {"times": [0.5, 1, 2, 4, 8], "values": [9008.0, 7656.8, 4278.8, 1486.32, 90.08],
                                    "time_unit": "h", "unit": "ng/ml"}}
    _, _, (observed, map_doc) = _prepared(tmp_path, study)
    profile = observed["iv"]["profile"]
    assert profile["times"] == [30.0, 60.0, 120.0, 240.0, 480.0] and profile["unit"] == "µmol/l"
    assert abs(observed["iv"]["cmax"] - 40.0) < 1e-9  # 9008 ng/ml / 225.2 g/mol
    # the same study entered in native units gives the same AUC
    _, _, (obs_native, _) = _prepared(tmp_path / "native", _study())
    assert abs(observed["iv"]["auc"] - obs_native["iv"]["auc"]) < 1e-6 * obs_native["iv"]["auc"]
    # the simulation window covers the whole sampled period (8 h here)
    assert {sc["sim_end_time_h"] for sc in map_doc["scenarios"] if sc["study_id"] == "iv"} == {8.0}


def test_a_special_population_study_is_classified_special_not_fitted(tmp_path):
    """The upload keeps who was studied: a renal-impairment arm must never train the healthy model (MS-01 §3.2)."""
    study = _study() | {"population_type": "patient", "special_population": "renal_impairment"}
    _, _, (_observed, map_doc) = _prepared(tmp_path, study)
    row = next(s for s in map_doc["studies"] if s["study_id"] == "iv")
    assert row["study_class"] == "SPECIAL" and row["assignment"] != "INTERNAL"


def test_prepare_rejects_an_unknown_unit(tmp_path):
    study = _study() | {"profile": {"times": [1, 2], "values": [1.0, 0.5], "time_unit": "min", "unit": "mg"}}
    r, _, _ = _prepared(tmp_path, study)
    assert r.status_code == 422 and "not recognised" in r.json()["detail"]


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

@pytest.mark.req("T-08")
def test_two_projects_on_one_compound_keep_their_own_cpf(tmp_path):
    """A refit project and an as-published one on the same drug each keep their CPF (they shared one file before)."""
    write, read = FileWriteStore(str(tmp_path)), FileReadStore(str(tmp_path))
    write.put_cpf("t1", "as-is", "Drug", CPF(compound="Drug", version=1))
    write.put_cpf("t1", "refit", "Drug", CPF(compound="Drug", version=2))
    assert read.get_cpf("t1", "as-is", "Drug").version == 1
    assert read.get_cpf("t1", "refit", "Drug").version == 2
    # a CPF stored the old way (per tenant) is still read by a project without its own
    (tmp_path / "t1" / "cpf" / "Old.json").write_text(CPF(compound="Old").model_dump_json(), encoding="utf-8")
    assert read.get_cpf("t1", "any", "Old").compound == "Old"
