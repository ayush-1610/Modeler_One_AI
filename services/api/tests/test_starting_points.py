"""The project starting points (`reference_models.starting_point`): the published real-data model first, each one
runnable through the write API. The scripts that build a project from one (the showcase seeder, the e2e specs) read
them here; the `/templates` routes that served them to the retired wizard are gone (the console redesign, slice 9)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import write_api
from modeler_api.auth import get_verifier
from modeler_api.config import get_settings
from modeler_api.main import app
from modeler_api.reference_models import TEMPLATES, starting_point, starting_points
from modeler_storage.filestore import FileReadStore, FileWriteStore

pytestmark = pytest.mark.req("T-26")


class _Verifier:
    def verify(self, token):
        return {"sub": "u", "name": "Dev", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def client(tmp_path):
    root = str(tmp_path)
    app.dependency_overrides[get_verifier] = lambda: _Verifier()
    app.dependency_overrides[write_api._stores] = lambda: (FileReadStore(root), FileWriteStore(root))
    yield TestClient(app)
    app.dependency_overrides.clear()


AUTH = {"Authorization": "Bearer tok"}


def test_the_published_real_data_model_comes_first():
    points = starting_points()
    assert points[0]["id"] == "dapagliflozin-osp" and points[0]["real_data"] is True
    illustrative = next(t for t in points if t["id"] == "aciclovir-illustrative")
    assert illustrative["real_data"] is False and "not clinical data" in illustrative["name"]


def test_an_unknown_starting_point_is_a_key_error():
    with pytest.raises(KeyError):
        starting_point("nope", get_settings())


def test_the_retired_routes_answer_nothing(client):
    for path in ("/api/v1/templates", "/api/v1/templates/dapagliflozin-osp"):
        assert client.get(path, headers=AUTH).status_code == 404, path


@pytest.mark.parametrize("template_id", ["dapagliflozin-osp", "aciclovir-illustrative"])
def test_every_starting_point_runs_through_the_write_path(client, template_id):
    """What a script does with a starting point: create → CPF → studies → MAP inputs. Each must reach a ready MAP."""
    t = starting_point(template_id, get_settings())
    r = client.post("/api/v1/projects", json={"name": f"T {template_id}", "compound": t["compound"],
                                              "question": t["question"], "model_risk": t["model_risk"]}, headers=AUTH)
    project = r.json()["data"]
    pid, qid = project["id"], project["questions"][0]["id"]
    r = client.put(f"/api/v1/projects/{pid}/compounds/{t['compound']}/cpf", json=t["cpf"], headers=AUTH)
    assert r.status_code == 200 and r.json()["data"]["ready"] is True, r.text
    r = client.post(f"/api/v1/projects/{pid}/studies", json={"studies": t["studies"]}, headers=AUTH)
    assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/projects/{pid}/questions/{qid}/campaign:prepare", json={"compound": t["compound"]},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    prep = r.json()["data"]
    assert prep["stages"][0] == "S0" and prep["studies"]


def test_the_published_starting_point_carries_real_studies_and_names_what_it_left_out():
    t = starting_point("dapagliflozin-osp", get_settings())
    assert len(t["studies"]) == 40 and len(t["skipped"]) == 15
    assert any("Komoroski 2009" in s["reference"] for s in t["studies"])
    assert {s["origin"] for s in t["studies"]} == {"OSP_LIBRARY"}  # plan §9.4: the published clinical data
    assert t["cpf"]["compound"] == "Dapagliflozin"
    # The unplaceable-clearance S0 rule would refuse an unbound clearance: every elim.* record carries its binding.
    assert all(p.get("engine_binding") for p in t["cpf"]["parameters"] if p["id"].startswith("elim."))


def test_the_illustrative_starting_point_binds_its_clearance():
    """It used to ship without the GFR binding, so S0 refused it and the wizard's campaign could never start."""
    t = starting_point("aciclovir-illustrative", get_settings())
    gfr = next(p for p in t["cpf"]["parameters"] if p["id"] == "elim.renal.gfr_fraction")
    assert gfr["engine_binding"]["process"] == "GlomerularFiltration"
    assert {s["origin"] for s in t["studies"]} == {"ILLUSTRATIVE"}  # plan §9.4 item 4: never evidence


def test_every_published_single_compound_starting_point_loads():
    """Each OSP library starting point imports: its CPF and at least one study."""
    published = [tid for tid, spec in TEMPLATES.items() if spec.get("real_data")]
    assert len(published) >= 12
    for tid in published:
        content = starting_point(tid, get_settings())
        assert content["cpf"]["compound"] == TEMPLATES[tid]["compound"] and content["studies"], tid


def test_your_own_compound_starts_from_the_s0_parameters_each_missing():
    """The blank starting point lists what S0 requires; the gate is not satisfied until each has a value and source."""
    from pbpk_domain.cpf.completeness import check_completeness
    from pbpk_domain.cpf.models import CPF

    body = starting_point("own-compound", get_settings())
    assert body["blank"] is True and body["studies"] == [] and body["real_data"] is False
    cpf = CPF.model_validate(body["cpf"])
    assert all(p.status.value == "MISSING" and p.value is None for p in cpf.parameters)
    assert set(check_completeness(cpf).missing_ids) == {"phys.mw", "phys.logp", "phys.pka", "bind.fu",
                                                        "phys.solubility.ref", "elim"}
    clearance = cpf.get("elim.hepatic.total.plasma_clearance").engine_binding
    assert (clearance.process, clearance.parameter) == ("LiverClearance", "Plasma clearance")
