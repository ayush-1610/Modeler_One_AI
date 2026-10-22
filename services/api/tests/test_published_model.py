"""R5: a published OSP model of the project's drug is a source of the inputs (in place of the Quick start wizard).

Software only: the values and datasets are the published model's, proposed citing it; nothing here runs PK-Sim."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-44")
H = {"Authorization": "Bearer t"}


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def project(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store

    def make(drug: str, pid: str) -> Workspace:
        ws = Workspace(store, "t1", pid)
        brief = ws.commit(ArtifactKind.BRIEF, "main", empty_brief(drug, by="u1").to_content(), actor="u1", reason="start")
        ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(empty_brief(drug, by="u1")).to_content(),
                  derived_from=[brief.ref], actor="system", reason="derived")
        return ws

    yield TestClient(app), make
    app.dependency_overrides.clear()


def test_the_published_model_of_the_drug_is_offered_and_its_values_and_studies_flow_in(project):
    c, make = project
    make("Dapagliflozin", "p1")
    offered = c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["published_models"]
    assert offered == [{"id": "dapagliflozin-osp", "name": "Dapagliflozin — published OSP model, real clinical data"}]

    taken = c.post("/api/v1/projects/p1/evidence:published-model", headers=H, json={"template_id": "dapagliflozin-osp"})
    assert taken.status_code == 200, taken.text
    out = taken.json()["data"]
    assert out["model"] == "Dapagliflozin" and out["values"] > 30 and out["datasets"] > 30 and out["already"] == 0

    register = c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]
    clspec = next(e for e in register["evidence"] if e["target"] == "elim.hepatic.UGT1A9.clspec")
    assert clspec["source_type"] == "OSP_LIBRARY" and clspec["state"] == "PROPOSED"          # flows in, never accepted
    assert clspec["source"]["url"] == "https://github.com/Open-Systems-Pharmacology/Dapagliflozin-Model"
    assert "value of the published OSP Dapagliflozin model" in clspec["note"]
    boulton = next(d for d in register["datasets"] if d["study"]["study_id"] == "boulton-2013-14c-dapagliflozin-iv")
    assert boulton["origin"] == "OSP_LIBRARY" and boulton["source"]["title"].startswith("OSP Dapagliflozin model observed data")

    rows = c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]
    assert any(r["id"] == "elim.hepatic.UGT1A9.clspec" for r in rows["compound"])           # the values reached the inputs
    assert any(s["study_id"] == "boulton-2013-14c-dapagliflozin-iv" for s in rows["studies"])

    again = c.post("/api/v1/projects/p1/evidence:published-model", headers=H, json={"template_id": "dapagliflozin-osp"})
    assert again.json()["data"]["values"] == 0 and again.json()["data"]["datasets"] == 0      # taking it twice adds nothing
    assert again.json()["data"]["already"] == out["values"] + out["datasets"]


def test_a_published_model_of_another_drug_is_refused(project):
    c, make = project
    make("Exampleamide", "p2")
    assert c.get("/api/v1/projects/p2/inputs", headers=H).json()["data"]["published_models"] == []
    refused = c.post("/api/v1/projects/p2/evidence:published-model", headers=H, json={"template_id": "dapagliflozin-osp"})
    assert refused.status_code == 422 and "this project's drug is Exampleamide" in refused.json()["detail"]
    missing = c.post("/api/v1/projects/p2/evidence:published-model", headers=H, json={"template_id": "aciclovir-illustrative"})
    assert missing.status_code == 404                                       # an illustrative template is not a published model
