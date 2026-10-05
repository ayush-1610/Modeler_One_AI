"""A campaign on a model system, end to end without an engine: the API stores the system beside its CPFs, prepare
stages it and plans each study on its analyte, the round builds every compound, and the evaluation reads each study
on its analyte's curve — gating only the fitted parent's plasma (owner decision 3, phase 1)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modeler_api import write_api
from modeler_api.auth import get_verifier
from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_api.main import app
from modeler_contracts.runs import RoundContext, RoundRunResult
from modeler_orchestrator.campaign_activities import build_round_snapshot, evaluate_round, plan_campaign
from pbpk_domain.campaign.map import MapDocument
from pbpk_domain.reference.osp_import import import_osp_system
from pbpk_domain.system import links_of

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"
pytestmark = pytest.mark.req("T-13")


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


def test_a_verapamil_campaign_is_planned_built_and_judged_per_analyte(client, tmp_path):
    imported = import_osp_system(json.loads((FIXTURES / "Verapamil-Model.json").read_text(encoding="utf-8")))
    system = imported.system
    by_analyte = {}
    for study in imported.studies:
        by_analyte.setdefault(study["analyte"], study)
    chosen = [by_analyte["R-Verapamil"], by_analyte["Sum-Verapamil Plasma (Peripheral Venous Blood)"],
              by_analyte["R-Norverapamil"]]

    assert client.post("/api/v1/projects", json={"name": "Verapamil", "compound": "R-Verapamil", "question": "q"},
                       headers=AUTH).status_code == 201
    # the system is refused until every compound's CPF is there
    links = links_of(system).model_dump(mode="json")
    r = client.put("/api/v1/projects/verapamil/system", json=links, headers=AUTH)
    assert r.status_code == 422 and "no CPF for" in r.json()["detail"]
    for cpf in system.compounds:
        assert client.put(f"/api/v1/projects/verapamil/compounds/{cpf.compound}/cpf", json=cpf.model_dump(mode="json"),
                          headers=AUTH).status_code == 200
    r = client.put("/api/v1/projects/verapamil/system", json=links, headers=AUTH)
    assert r.status_code == 200 and r.json()["data"]["sha256"] == system.sha256
    assert client.post("/api/v1/projects/verapamil/studies", json={"studies": chosen}, headers=AUTH).status_code == 201

    # a metabolite is not a parent: the campaign fits a parent
    r = client.post("/api/v1/projects/verapamil/questions/q/campaign:prepare", json={"compound": "R-Norverapamil"},
                    headers=AUTH)
    assert r.status_code == 422 and "not a parent" in r.json()["detail"]
    r = client.post("/api/v1/projects/verapamil/questions/q/campaign:prepare", json={"compound": "R-Verapamil"},
                    headers=AUTH)
    assert r.status_code == 200
    prep = r.json()["data"]
    assert prep["model_system_sha256"] == system.sha256 and prep["system_uri"].endswith("prep/q/system.json")
    map_doc = MapDocument.model_validate_json(Path(prep["map_uri"].removeprefix("file://")).read_text(encoding="utf-8"))
    assert map_doc.model_system_sha256 == system.sha256
    plan = {s.study_id: s for s in map_doc.scenarios}
    rv, total, norv = (plan[s["study_id"]] for s in chosen)
    assert (rv.gated, total.gated, norv.gated) == (True, False, False)
    assert total.analyte_output.endswith("|Sum-Verapamil Plasma (Peripheral Venous Blood)")

    ctx_args = dict(campaign_id="c1", tenant_id="t1", round_index=1, cpf_uri=prep["cpf_uri"], cpf_sha256=prep["cpf_sha256"],
                    pending_action=None, map_uri=prep["map_uri"], observed_uri=prep["observed_uri"],
                    system_uri=prep["system_uri"], system_sha256=prep["system_sha256"])
    # S0 checks every compound of the system
    from modeler_contracts.runs import CampaignRequest

    ready = plan_campaign(CampaignRequest(campaign_id="c1", tenant_id="t1", compound="R-Verapamil", map_id="m",
                                          cpf_uri=prep["cpf_uri"], cpf_sha256=prep["cpf_sha256"], system_uri=prep["system_uri"]))
    assert ready.ready is True

    # the round builds all four compounds, formation and the sum observers
    stage = total.stage
    build = build_round_snapshot(RoundContext(stage=stage, **ctx_args))
    snapshot = json.loads(Path(build.snapshot_uri.removeprefix("file://")).read_text(encoding="utf-8"))
    assert {c["Name"] for c in snapshot["Compounds"]} == set(system.roles)
    assert {o["Name"] for o in snapshot.get("ObserverSets", [])} == {"Sum-Verapamil", "Sum-Norverapamil"}

    # evaluation reads the sum study on the sum observer's curve, and keeps it out of the gate
    times = [float(t) for t in range(0, 24 * 60 + 1, 10)]
    curve = [0.0] + [1.0 / (1 + t / 300.0) for t in times[1:]]
    zero = [0.0] * len(times)
    in_stage = [s for s in map_doc.scenarios if s.stage == stage]
    bundle = {"profiles": {s.study_id: {
        "times_min": times, "concentrations": zero, "unit": "µmol/l",
        "path": "Organism|PeripheralVenousBlood|R-Verapamil|Plasma (Peripheral Venous Blood)",
        "outputs": {s.analyte_output: {"concentrations": curve, "unit": "µmol/l"}}} for s in in_stage}}
    results = tmp_path / "profiles.json"
    results.write_text(json.dumps(bundle), encoding="utf-8")
    evaluation = evaluate_round(RoundContext(stage=stage, **ctx_args),
                                RoundRunResult(results_uri=results.as_uri(), cpf_uri=prep["cpf_uri"], cpf_sha256="b" * 64))
    rows = {row["study_id"]: row for row in evaluation.metrics["studies"]}
    assert rows[total.study_id]["gated"] is False
    assert rows[total.study_id]["predicted_cmax"] == pytest.approx(max(curve))  # the observer's curve, not the zero plasma


def test_a_stage_whose_studies_are_all_reported_analytes_is_skipped_with_its_reason():
    # Verapamil's IV data are racemic sums: in phase 1 no study there measures the fitted parent's plasma, so S1 has
    # nothing to judge or fit — skipped and named, not escalated as "no diagnostic rule matched"
    from pbpk_domain.campaign.map import generate_map, stage_coverage
    from pbpk_domain.campaign.split import QuestionOfInterest, StudyRecord, split_studies
    from pbpk_domain.m15 import Rating

    imported = import_osp_system(json.loads((FIXTURES / "Verapamil-Model.json").read_text(encoding="utf-8")))
    studies = [StudyRecord.model_validate({k: v for k, v in s.items() if k in StudyRecord.model_fields})
               for s in imported.studies]
    map_doc = generate_map(compound="R-Verapamil", cpf=imported.system.cpf("R-Verapamil"), studies=studies,
                           split=split_studies(studies, QuestionOfInterest()), objective="t", context_of_use="t",
                           food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="t",
                           software_versions={}, system=imported.system)
    s1 = stage_coverage(map_doc, "S1")
    assert s1.studies and s1.skip_reason and "reported but not gated" in s1.skip_reason
    assert all(not s.gated for s in map_doc.scenarios if s.stage == "S1")
