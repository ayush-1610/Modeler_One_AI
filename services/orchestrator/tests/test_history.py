"""T-54: parameter diffs and the influence map (software; the sensitivities come from S6 on PK-Sim)."""

from __future__ import annotations

import json

import pytest

from modeler_orchestrator.history import Ledger, influence_map, parameter_changes, study_verdict


def _cpf(path, values: dict[str, tuple]) -> str:
    params = [{"id": pid, "value": v, "unit": "u", "status": status, "fitted_at_stage": stage,
               **({"fit_policy": {"lower": 0, "upper": 10}} if status != "FIXED" else {})}
              for pid, (v, status, stage) in values.items()]
    path.write_text(json.dumps({"parameters": params}), encoding="utf-8")
    return path.as_uri()


@pytest.mark.req("T-54")
def test_parameter_changes_list_value_status_and_fitting_stage(tmp_path):
    before = _cpf(tmp_path / "a.json", {"phys.logp": (2.0, "PREDICTED", None), "cl.hep": (5.0, "FITTED", "S1"),
                                        "phys.mw": (400.0, "FIXED", None)})
    after = _cpf(tmp_path / "b.json", {"phys.logp": (2.4, "FITTED", "S2"), "cl.hep": (5.0, "FITTED", "S1"),
                                       "phys.mw": (400.0, "FIXED", None)})
    assert parameter_changes(before, after) == [{"parameter": "phys.logp", "before": 2.0, "after": 2.4, "unit": "u",
                                                 "status": "FITTED", "fitted_at_stage": "S2"}]
    assert parameter_changes(before, "file:///nowhere.json") is None
    entry = Ledger().change(stage="S2", kind="fit", reason="r", before=(before, "a"), after=(after, "b"))
    assert [c["parameter"] for c in entry["changes"]] == ["phys.logp"] and "note" not in entry


@pytest.mark.req("T-54")
def test_study_verdict_reads_the_round_flags():
    assert study_verdict({"auc_in_limits": True, "cmax_in_limits": False}) == "fail"
    assert study_verdict({"auc_in_limits": True, "cmax_in_limits": None}) == "pass"
    assert study_verdict({"auc_in_limits": None, "cmax_in_limits": None}) == "not judged"


@pytest.mark.req("T-54")
def test_the_influence_map_is_structural_from_the_map_and_quantitative_from_s6(tmp_path):
    cpf = _cpf(tmp_path / "c.json", {"cl.hep": (5.0, "FITTED", "S1"), "form.tab.weibull.t50": (30.0, "FITTED", "S3"),
                                     "food.fed_solubility_factor": (1.5, "PREDICTED", None), "phys.mw": (400.0, "FIXED", None)})
    map_doc = {"scenarios": [
        {"study_id": "iv-1", "stage": "S1", "route": "iv", "formulation": "solution", "food_state": "fasted"},
        {"study_id": "po-tab", "stage": "S3", "route": "oral", "formulation": "ir_tablet", "food_state": "fasted",
         "formulation_name": "tab"},
        {"study_id": "po-fed", "stage": "S5", "route": "oral", "formulation": "ir_tablet", "food_state": "fed",
         "formulation_name": "tab"},
    ]}
    prediction = {"sensitivity": {"po-tab": [{"parameter": "form.tab.weibull.t50", "pk_parameter": "C_max", "value": -0.42},
                                             {"parameter": "cl.hep", "pk_parameter": "AUC_inf", "value": -0.98}]}}
    out = influence_map(map_doc, cpf, prediction, cpf_sha="c")
    assert out["parameters"] == ["cl.hep", "food.fed_solubility_factor", "form.tab.weibull.t50"]   # FIXED left out
    assert out["studies"] == ["iv-1", "po-fed", "po-tab"] and out["quantitative"]
    cells = out["cells"]
    assert cells["cl.hep"]["iv-1"]["structural"] and cells["cl.hep"]["po-tab"]["auc"] == -0.98
    assert not cells["form.tab.weibull.t50"]["iv-1"]["structural"] and cells["form.tab.weibull.t50"]["po-tab"]["cmax"] == -0.42
    assert [s for s, c in cells["food.fed_solubility_factor"].items() if c["structural"]] == ["po-fed"]
    assert influence_map(map_doc, cpf, None, cpf_sha="c")["quantitative"] is False
