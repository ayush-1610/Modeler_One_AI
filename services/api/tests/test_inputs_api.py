"""T-49: the P4 endpoints — assemble, structure choices, accept, and hand-over to the campaign path."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_api.main import app
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.dataset_register import decide_dataset, propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import decide, propose
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-49")
H = {"Authorization": "Bearer t"}


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dev User", "tenant_id": "t1", "realm_access": {"roles": ["modeler-curator"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    import modeler_api.config as cfg

    store = FileProjectStore(tmp_path / "projects")
    read_root = tmp_path / "read-root"
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(read_root=str(read_root), execution_backend="local"))
    monkeypatch.setattr("modeler_api.inputs_api.get_settings", lambda: SimpleNamespace(read_root=str(read_root)))
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    FileWriteStore(str(read_root)).put_project("t1", {"id": "p1", "name": "P1", "compounds": ["Renaldrug"], "pipeline": True})
    ws = Workspace(store, "t1", "p1")
    brief = empty_brief("Renaldrug", by="u1")
    b = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u1", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[b.ref], actor="u1", reason="derived")
    source = SourceRef(title="FDA review", year=2019, locator="Table 2")
    for target, value, unit, conditions in (("phys.mw", 225.2, "g/mol", {}), ("phys.logp", -1.56, None, {"type": "logP"}),
                                            ("bind.fu", 0.85, None, {}), ("phys.solubility.ref", 1.3, "mg/ml", {}),
                                            ("phys.pka", 2.3, None, {"type": "base"}), ("elim.renal.gfr_fraction", 1.0, None, {}),
                                            ("elim.hepatic.CYP3A4.clspec", 0.01, "l/µmol/min", {})):
        item = propose(ws, EvidenceItem(id=new_id(), target=target, value=value, unit=unit, conditions=conditions, source=source,
                                        source_type=SourceType.REGULATORY_REVIEW, quote=f"{target} {value}"), actor="u1")
        extra = {"value_pksim": value, "unit_pksim": unit} if target.endswith("clspec") else {}
        decide(ws, item.id, state=EvidenceState.ACCEPTED, reason="checked", by="u1", **extra)
    ds = ObservedDataset(id=new_dataset_id(), kind="profile", origin=Origin.CLIENT, provider="CLIENT", time_unit="h", unit="µmol/l",
                         study={"study_id": "cl-iv", "n": 12, "route": "iv_infusion", "dose_mg": 250, "infusion_time_min": 60,
                                "formulation": "solution", "food_state": "fasted", "n_timepoints": 5},
                         series=(Series(times=(0.5, 1, 2, 4, 8), values=(20.0, 35.0, 21.0, 9.0, 2.0), n=12),))
    propose_dataset(ws, ds, actor="u1")
    decide_dataset(ws, ds.id, state=EvidenceState.ACCEPTED, reason="client report", by="u1")
    yield TestClient(app), ws, read_root
    app.dependency_overrides.clear()


def test_inputs_are_assembled_chosen_accepted_and_handed_to_the_campaign_path(setup):
    c, _ws, read_root = setup
    view = c.post("/api/v1/projects/p1/inputs:assemble", headers=H).json()["data"]
    assert view["readiness"]["content"]["ready"] is False
    clspec = next(r for r in view["records"] if r["id"] == "elim.hepatic.CYP3A4.clspec")
    assert set(clspec["candidates"]) == {"MetabolizationSpecific_FirstOrder", "rCYP450_FirstOrder"} and clspec["block"] == "Compound"
    early = c.post("/api/v1/projects/p1/inputs:accept", headers=H, json={})
    assert early.status_code == 409 and "not ready" in early.json()["detail"]
    bad = c.put("/api/v1/projects/p1/inputs/choices", headers=H,
                json={"kind": "process", "key": "elim.hepatic.CYP3A4", "value": "Made_Up", "reason": "x"})
    assert bad.status_code == 422 and "not a harvested process" in bad.json()["detail"]
    early_publish = c.post("/api/v1/projects/p1/inputs:publish", headers=H)
    assert early_publish.status_code == 409
    # CYP3A4 needs an expression profile from the library: readiness says so if it is missing, otherwise it is ready
    view = c.put("/api/v1/projects/p1/inputs/choices", headers=H,
                 json={"kind": "process", "key": "elim.hepatic.CYP3A4", "value": "MetabolizationSpecific_FirstOrder",
                       "reason": "first-order specific clearance, as the OSP models write it"}).json()["data"]
    failing = [ch for ch in view["readiness"]["content"]["checks"] if not ch["ok"]]
    assert view["readiness"]["content"]["ready"], failing
    assert c.post("/api/v1/projects/p1/inputs:accept", headers=H, json={"note": "inputs complete"}).status_code == 200
    published = c.post("/api/v1/projects/p1/inputs:publish", headers=H).json()["data"]["published"]
    assert published["studies"] == ["cl-iv"]
    read = FileReadStore(str(read_root))
    assert read.get_cpf("t1", "p1", "Renaldrug").get("phys.logp").provenance.method == "InVitro"
    assert read.list_studies("t1", "p1")[0]["origin"] == "CLIENT"
