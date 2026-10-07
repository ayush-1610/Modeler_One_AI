"""T-55: external-validation feedback cycles (plan §12.3 N4, §12.4), on a scripted executor and a real MAP / CPF.

Software only: the verdicts are scripted; the PK-Sim acceptance (Dapagliflozin fed failure → learn → S5 on the
remaining fed study) is the server's."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from modeler_orchestrator import local_runner
from modeler_orchestrator.feedback import check_learn, diagnose, learn_stage
from modeler_orchestrator.local_runner import CampaignArtifactWriter, check_feedback, resolve_escalation
from modeler_storage.filestore import FileReadStore, FileWriteStore
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import FoodState, FormulationKind, QuestionOfInterest, Route, StudyRecord, split_studies
from pbpk_domain.cpf import CPF, FitPolicy, ParameterRecord, ParameterStatus, Plausibility, Provenance
from pbpk_domain.m15 import Rating

from .scripted import ScriptedExecutor, patch_planning, request

STAGES = ["S0", "S1", "S2", "S3", "SJ", "S4", "S5", "S6"]


def _path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


def _cpf() -> CPF:
    prov = Provenance(source_type="measured", reference="Example 2020")
    return CPF(compound="Example-A", parameters=(
        ParameterRecord(id="phys.mw", value=408.5, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.6, unit="Log Units", status=ParameterStatus.PREDICTED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=4.0)),
        ParameterRecord(id="phys.solubility.ref", value=0.1, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov,
                        plausibility=Plausibility(lower=0.001, upper=10.0)),
        ParameterRecord(id="bind.fu", value=0.02, status=ParameterStatus.FIXED, provenance=prov),
    ))


def _inputs(tmp_path: Path, fed: int = 3) -> tuple[str, str]:
    def s(sid, **kw):
        base = dict(study_id=sid, n=12, design="SD", route=Route.ORAL, dose_mg=10.0,
                    formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15)
        return StudyRecord(**{**base, **kw})
    studies = [s("iv", route=Route.IV_BOLUS, dose_mg=5), s("po-1", dose_mg=5, n=20), s("po-2", dose_mg=50, n=20),
               s("po-3", dose_mg=20, n=10), *[s(f"fed-{i}", food_state=FoodState.FED, n=20 - i) for i in range(1, fed + 1)]]
    cpf = _cpf()
    doc = generate_map(compound="Example-A", cpf=cpf, studies=studies,
                       split=split_studies(studies, QuestionOfInterest(measured_fed_solubility=True)), objective="o",
                       context_of_use="c", food_effect_in_question=False, model_risk=Rating.MEDIUM,
                       engine_image_digest="sha256:abcd", software_versions={"pksim": "12"}, seed=42,
                       campaign_budget_seconds=3600).sign(printed_name="MIDD Lead", signature_id="sig-map")
    (tmp_path / "inputs").mkdir()
    map_path, cpf_path = tmp_path / "inputs" / "map.json", tmp_path / "inputs" / "cpf.json"
    map_path.write_text(doc.model_dump_json(), encoding="utf-8")
    cpf_path.write_text(cpf.model_dump_json(), encoding="utf-8")
    return map_path.as_uri(), cpf_path.as_uri()


def _writer(root: Path) -> CampaignArtifactWriter:
    return CampaignArtifactWriter(store=FileWriteStore(str(root)), tenant_id="t1", campaign_id="camp-s", project="p",
                                  compound="X", question="q", model_risk="medium", budget_seconds=3600, stages=STAGES)


_S5 = ["po-3", "fed-1", "fed-2", "fed-3"]


def _first_cycle(tmp_path, monkeypatch, **script):
    patch_planning(monkeypatch)
    map_uri, cpf_uri = _inputs(tmp_path, **script.pop("inputs", {}))
    req = replace(request(STAGES), map_uri=map_uri, map_sha256="m1", cpf_uri=cpf_uri)
    executor = ScriptedExecutor(engine=None, writer=_writer(tmp_path), verdicts={("S5", "A"): False},  # type: ignore[arg-type]
                                studies={"S5": script.pop("s5", _S5)},
                                study_ok={("po-3", "A"): True, ("fed-2", "A"): True, ("fed-3", "A"): True}, **script)
    outcome = executor.run(req)
    return outcome, FileReadStore(str(tmp_path))


@pytest.mark.req("T-55")
def test_an_s5_failure_waits_for_a_feedback_decision_with_its_diagnosis(tmp_path, monkeypatch):
    outcome, read = _first_cycle(tmp_path, monkeypatch)
    assert outcome.status == "ESCALATED" and "S5" in outcome.reason
    campaign = read.get_campaign("t1", "camp-s")
    diagnosis = campaign["feedbackPending"]
    (fed1,) = diagnosis["failing"]
    assert (fed1["study_id"], fed1["class"], fed1["failed"], fed1["direction"]) == ("fed-1", "PO-FED", ["AUC", "Cmax"],
                                                                                 "over-predicted")
    assert fed1["learn_stage"] == "S3" and "fed, and no fed study trains the model" in fed1["differences"]
    assert diagnosis["classes"]["PO-FED"]["unspent"] == ["fed-2", "fed-3"] and diagnosis["classes"]["PO-FED"]["learn"]["possible"]
    escalation = next(e for e in read.list_escalations("t1") if e["campaignId"] == "camp-s")
    assert escalation["reasonCode"] == "EXTERNAL_VALIDATION_FAILED"
    assert [o["id"] for o in escalation["options"]] == ["accept_best", "learn", "new_evidence", "abort"]
    assert not any(o.get("disabled") for o in escalation["options"])


@pytest.mark.req("T-55")
def test_learn_moves_the_failing_study_and_confirms_on_the_external_studies_left(tmp_path, monkeypatch):
    """Plan §12.3 N4 (b), T-55 acceptance in software: fed-1 fails S5 → learn → it trains S3 (a signed MAP deviation),
    SJ and S4 run with it, S5 judges fed-2 and fed-3 only, and the history is on the record."""
    _first_cycle(tmp_path, monkeypatch)
    cycle2 = {}

    def executor(**kwargs):
        cycle2["executor"] = ScriptedExecutor(**kwargs, verdicts={("S3", "A"): "L"},
                                              studies={"S3": ["fed-1"], "S4": ["iv", "po-1", "po-2", "fed-1"],
                                                       "S5": ["po-3", "fed-2", "fed-3"]})
        return cycle2["executor"]

    monkeypatch.setattr(local_runner, "LocalExecutor", executor)
    result = resolve_escalation(read_root=str(tmp_path), tenant_id="t1", campaign_id="camp-s", stage="S5", action="learn",
                                payload={"studies": ["fed-1"]}, signature_id="sig-learn", printed_name="MIDD Lead",
                                note="fed exposure is the question", background=False)
    assert result["remaining_stages"] == ["S3", "SJ", "S4", "S5", "S6"]
    campaign = FileReadStore(str(tmp_path)).get_campaign("t1", "camp-s")
    assert campaign["status"] == "AWAITING_SIGNATURE" and campaign["cycle"] == 2 and campaign["feedbackPending"] is None
    calls = cycle2["executor"].calls
    assert ("S3", "A", "", "fit phys.logp") in calls and ("S5", "L", "", None) in calls      # re-entered at S3, S5 on L
    assert ("S1", "L", "after-S3", None) in calls                                            # the no-regression gate

    (decision,) = campaign["feedback"]
    assert (decision["action"], decision["studies"], decision["stages"], decision["cycle"]) == ("learn", ["fed-1"],
                                                                                               {"fed-1": "S3"}, 2)
    map_uri = campaign["resume"]["request"]["map_uri"]          # the rest of the campaign runs on the deviated MAP
    assert map_uri.endswith("/inputs/map-cycle2.json") and campaign["resume"]["request"]["cycle"] == 2
    deviated = json.loads(_path(map_uri).read_text())
    assert deviated["version"] == 2 and deviated["signature"]["signature_id"] == "sig-learn" and deviated["supersedes_sha256"]
    assert {s["study_id"]: s["assignment"] for s in deviated["studies"]}["fed-1"] == "INTERNAL"
    assert sorted(s["stage"] for s in deviated["scenarios"] if s["study_id"] == "fed-1") == ["S3", "S4"]
    assert any("rest on fed-2, fed-3 only" in line for line in deviated["split_limitations"])

    ledger = campaign["ledger"]["entries"]
    learn, fit = ledger[-2], ledger[-1]
    assert learn["kind"] == "learn" and learn["cycle"] == 2 and learn.get("event")
    assert (fit["stage"], fit["cycle"], fit["cpf_after"]) == ("S3", 2, "sha-L")
    assert [(v["study_id"], v["before"], v["after"]) for v in fit["verdicts"]] == [("fed-1", "fail", "pass")]
    s3 = next(s for s in campaign["stages"] if s["stage"] == "S3")
    assert {r["cycle"] for r in s3["rounds"]} == {1, 2}


@pytest.mark.req("T-55")
def test_a_class_with_no_other_external_study_cannot_learn(tmp_path, monkeypatch):
    _outcome, read = _first_cycle(tmp_path, monkeypatch, inputs={"fed": 1}, s5=["po-3", "fed-1"])
    campaign = read.get_campaign("t1", "camp-s")
    learn = next(o for o in campaign["feedbackPending"]["options"] if o["id"] == "learn")
    assert "external validation of PO-FED not achievable" in learn["disabled"]
    with pytest.raises(ValueError, match="not achievable"):
        check_feedback(campaign, "S5", "learn", {})
    # the limitation is recorded with the reason the class could not learn
    resolve_escalation(read_root=str(tmp_path), tenant_id="t1", campaign_id="camp-s", stage="S5", action="accept_best",
                       signature_id="sig-lim", note="fed claims withdrawn", background=False, engine=lambda job: None)
    campaign = read.get_campaign("t1", "camp-s")
    assert campaign["feedback"][0]["action"] == "limitation"
    notes = next(s for s in campaign["stages"] if s["stage"] == "S5")["notes"]
    assert any("fed-1 failed external validation" in n for n in notes) and any("not achievable" in n for n in notes)


@pytest.mark.req("T-55")
def test_new_evidence_replaces_one_measured_value_and_reruns_the_chain(tmp_path, monkeypatch):
    _outcome, read = _first_cycle(tmp_path, monkeypatch)
    campaign = read.get_campaign("t1", "camp-s")
    with pytest.raises(ValueError, match="stored in mg/ml"):
        check_feedback(campaign, "S5", "new_evidence", {"parameter": "phys.solubility.ref", "value": 0.3, "unit": "mg/l",
                                                        "reference": "client FeSSIF report"})
    with pytest.raises(ValueError, match="plausibility"):
        check_feedback(campaign, "S5", "new_evidence", {"parameter": "phys.solubility.ref", "value": 50, "unit": "mg/ml",
                                                        "reference": "client FeSSIF report"})
    with pytest.raises(ValueError, match="source"):
        check_feedback(campaign, "S5", "new_evidence", {"parameter": "phys.solubility.ref", "value": 0.3, "unit": "mg/ml"})
    cycle2 = {}

    def executor(**kwargs):
        cycle2["executor"] = ScriptedExecutor(**kwargs)
        return cycle2["executor"]

    monkeypatch.setattr(local_runner, "LocalExecutor", executor)
    result = resolve_escalation(read_root=str(tmp_path), tenant_id="t1", campaign_id="camp-s", stage="S5",
                                action="new_evidence", signature_id="sig-ev", background=False,
                                payload={"parameter": "phys.solubility.ref", "value": 0.3, "unit": "mg/ml",
                                         "reference": "client FeSSIF report"})
    assert result["remaining_stages"] == ["S1", "S2", "S3", "SJ", "S4", "S5", "S6"]
    campaign = read.get_campaign("t1", "camp-s")
    entry = campaign["ledger"]["entries"][-1]
    assert (entry["kind"], entry["cycle"], entry["stage"]) == ("new evidence", 2, "S5")
    assert entry["changes"] == [{"parameter": "phys.solubility.ref", "before": 0.1, "after": 0.3, "unit": "mg/ml",
                                 "status": "FIXED", "fitted_at_stage": None}]
    assert "prompted by S5 (fed-1)" in entry["reason"]
    new_cpf = CPF.model_validate_json(_path(campaign["resume"]["cpf_uri"]).read_text())   # waiting at the S6 signature
    assert new_cpf.get("phys.solubility.ref").provenance.reference == "client FeSSIF report"
    assert {c[0] for c in cycle2["executor"].calls} >= {"S1", "S2", "S3", "S4", "S5"}
    notes = next(s for s in campaign["stages"] if s["stage"] == "S5")["notes"]
    assert any("model-risk review (D-06)" in n for n in notes)


@pytest.mark.req("T-55")
def test_the_learn_cap_per_class_needs_a_signed_deviation_reason():
    map_doc = {"studies": [{"study_id": f"fed-{i}", "study_class": "PO-FED"} for i in (1, 2)],
               "scenarios": [{"study_id": f"fed-{i}", "stage": "S5", "route": "oral", "food_state": "fed",
                              "formulation": "solution", "dose_mg": 10} for i in (1, 2)]}
    studies = [{"study_id": "fed-1", "auc_in_limits": False, "cmax_in_limits": True},
               {"study_id": "fed-2", "auc_in_limits": True, "cmax_in_limits": True}]
    diagnosis = diagnose(map_doc, studies, influence=None, history=[{"action": "learn", "classes": ["PO-FED"]}])
    assert diagnosis["classes"]["PO-FED"]["learn"]["needs_deviation"]
    with pytest.raises(ValueError, match="cap 1"):
        check_learn(["fed-1"], diagnosis)
    assert check_learn(["fed-1"], diagnosis, beyond_cap="the second fed study is a different meal") == ["PO-FED"]
    with pytest.raises(ValueError, match="only studies that failed"):
        check_learn(["fed-2"], diagnosis)


@pytest.mark.req("T-55")
def test_learn_stage_follows_the_maps_placement():
    solution = {"study_id": "po-1", "stage": "S2", "route": "oral", "formulation": "solution", "food_state": "fasted"}
    assert learn_stage({"route": "iv_bolus"}, []) == "S1"
    assert learn_stage({"route": "oral", "food_state": "fed", "formulation": "solution"}, [solution]) == "S3"
    assert learn_stage({"route": "oral", "food_state": "fasted", "formulation": "solution"}, [solution]) == "S2"
    assert learn_stage({"route": "oral", "food_state": "fasted", "formulation": "ir_tablet"}, [solution]) == "S3"
    assert learn_stage({"route": "oral", "food_state": "fasted", "formulation": "ir_tablet"}, []) == "S2"


@pytest.mark.req("T-55")
def test_learn_refits_the_affected_stage_only(tmp_path, monkeypatch):
    """MS-01 §6.6 / plan §12.4: learn at S2 queues [S2, SJ, S4, S5, …] (S3 is not refitted; SJ re-judges it)."""
    import modeler_orchestrator.feedback as fb

    monkeypatch.setattr(fb, "learn_map", lambda *a, **k: ("file:///m2.json", "m2", {
        "stages": {"po-3": "S2"}, "statement": "po-3 moved", "studies": ["po-3"], "classes": ["PO-SOL-FASTED"]}))
    diagnosis = {"failing": [{"study_id": "po-3", "class": "PO-SOL-FASTED"}],
                 "classes": {"PO-SOL-FASTED": {"learn": {"possible": True}}}}
    req = replace(request(["S0", "S1", "S2", "S3", "SJ", "S4", "S5", "S6", "S7"]), map_uri="file:///m1.json")
    writer = _writer(tmp_path)
    new_req, _uri, _sha, queue = local_runner._start_cycle(writer, req, diagnosis, "learn", {}, cpf_uri="file:///c",
                                                           cpf_sha="c", signature_id="s", printed_name="p", note="")
    assert queue == ["S2", "SJ", "S4", "S5", "S6", "S7"] and new_req.cycle == 2 and new_req.map_uri == "file:///m2.json"


@pytest.mark.req("T-55")
def test_the_diagnosis_follows_ms01_6_6_and_suggests_but_does_not_decide():
    """MS-01 §6.6: a documented difference → limitation (path 1); else another external study of the class → learn
    (path 2); else → not achievable (path 3). The suggestion is shown; the person decides and signs."""
    train = [{"study_id": f"po-{d}", "stage": "S2", "route": "oral", "food_state": "fasted", "formulation": "solution",
              "dose_mg": d} for d in (5, 50)]
    ext = [{"study_id": sid, "stage": "S5", "route": "oral", "food_state": food, "formulation": "solution", "dose_mg": dose}
           for sid, food, dose in (("po-20", "fasted", 20), ("po-25", "fasted", 25), ("fed-1", "fed", 10))]
    map_doc = {"scenarios": [*train, *ext],
               "studies": [{"study_id": "po-20", "study_class": "PO-SOL-FASTED"},
                           {"study_id": "po-25", "study_class": "PO-SOL-FASTED"},
                           {"study_id": "fed-1", "study_class": "PO-FED"}]}
    fail = {"auc_in_limits": False, "cmax_in_limits": True, "predicted_auc": 300.0, "observed_auc": 100.0}
    ok = {"auc_in_limits": True, "cmax_in_limits": True}
    out = diagnose(map_doc, [{"study_id": "po-20", **fail}, {"study_id": "po-25", **ok}, {"study_id": "fed-1", **fail}],
                   influence=None, history=[])
    paths = {f["study_id"]: f["ms01"]["path"] for f in out["failing"]}
    assert paths == {"po-20": 2, "fed-1": 1}                                       # fed: no fed training → limitation
    assert out["recommendation"]["action"] == "learn" and out["recommendation"]["studies"] == ["po-20"]
    alone = diagnose({**map_doc, "scenarios": [*train, ext[0]], "studies": map_doc["studies"][:1]},
                     [{"study_id": "po-20", **fail}], influence=None, history=[])
    assert alone["failing"][0]["ms01"]["path"] == 3 and alone["recommendation"]["action"] == "accept_best"
    assert "not achievable" in alone["recommendation"]["why"]
