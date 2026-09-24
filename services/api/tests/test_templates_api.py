"""The wizard's starting points: the published real-data model first, each one runnable through the write API."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import write_api
from modeler_api.auth import get_verifier
from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_api.main import app

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


def test_templates_list_the_published_real_data_model_first(client):
    templates = client.get("/api/v1/templates", headers=AUTH).json()["data"]["templates"]
    assert templates[0]["id"] == "dapagliflozin-osp" and templates[0]["real_data"] is True
    illustrative = next(t for t in templates if t["id"] == "aciclovir-illustrative")
    assert illustrative["real_data"] is False and "not clinical data" in illustrative["name"]


def test_templates_need_an_authenticated_reader(tmp_path):
    app.dependency_overrides.clear()
    # refused either way: 401/403 with a verifier, 503 when auth is not configured at all
    assert TestClient(app).get("/api/v1/templates").status_code in (401, 403, 503)


def test_unknown_template_is_404(client):
    assert client.get("/api/v1/templates/nope", headers=AUTH).status_code == 404


@pytest.mark.parametrize("template_id", ["dapagliflozin-osp", "aciclovir-illustrative"])
def test_every_template_runs_through_the_wizards_write_path(client, template_id):
    """What the wizard does with a template: create → CPF → studies → MAP. Each must reach a ready MAP."""
    t = client.get(f"/api/v1/templates/{template_id}", headers=AUTH).json()["data"]
    r = client.post("/api/v1/projects", json={"name": f"T {template_id}", "compound": t["compound"],
                                              "question": t["question"]}, headers=AUTH)
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


def test_the_published_template_carries_real_studies_and_names_what_it_left_out(client):
    t = client.get("/api/v1/templates/dapagliflozin-osp", headers=AUTH).json()["data"]
    assert len(t["studies"]) == 40 and len(t["skipped"]) == 15
    assert any("Komoroski 2009" in s["reference"] for s in t["studies"])
    assert t["cpf"]["compound"] == "Dapagliflozin"
    # The unplaceable-clearance S0 rule would refuse an unbound clearance: every elim.* record carries its binding.
    assert all(p.get("engine_binding") for p in t["cpf"]["parameters"] if p["id"].startswith("elim."))


def test_the_illustrative_template_binds_its_clearance(client):
    """It used to ship without the GFR binding, so S0 refused it and the wizard's campaign could never start."""
    t = client.get("/api/v1/templates/aciclovir-illustrative", headers=AUTH).json()["data"]
    gfr = next(p for p in t["cpf"]["parameters"] if p["id"] == "elim.renal.gfr_fraction")
    assert gfr["engine_binding"]["process"] == "GlomerularFiltration"


def test_every_published_single_compound_template_loads():
    """Each OSP library template the wizard lists imports: its CPF and at least one study."""
    from modeler_api.templates_api import _TEMPLATES, _content

    published = [tid for tid, spec in _TEMPLATES.items() if spec.get("real_data")]
    assert len(published) >= 12
    for tid in published:
        content = _content(tid, _TEMPLATES[tid])
        assert content["cpf"]["compound"] == _TEMPLATES[tid]["compound"] and content["studies"], tid
