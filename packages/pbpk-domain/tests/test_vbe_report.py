"""The MAR reports the S6 virtual bioequivalence (T-31 B6 PR 6): design, PoS, the F-304 gate, and an M15 table."""

from __future__ import annotations

import pytest

from pbpk_domain.report.campaign_mar import assemble_campaign_mar
from pbpk_domain.report.mar import check_report
from pbpk_domain.vbe import run_trials, validation_gate

from .test_map import _cpf, _map
from .test_vbe import _arms

pytestmark = pytest.mark.req("T-31")


def _vbe(observed=None) -> dict:
    trials = run_trials(*_arms(1.02, 48, noise=0.05), n_subjects=12, n_trials=4, limits=(0.80, 1.25), confidence=0.90,
                        pos_threshold=0.8)
    return {"template": "vbe-crossover", "template_version": "0.2.0-draft", "status": "RUN", "design_study": "rld-sd",
            "dose_mg": 10.0, "food_state": "fasted", "population": "European_ICRP_2002", "seed": 5,
            "occasion_seeds": {"test": 11, "reference": 12}, "formulations": {"test": "Test", "reference": "Ref"},
            "variability": [{"parameter": "Organism|Stomach|Gastric emptying time", "cv_percent": 20, "source": "cited"}],
            "limits_name": "standard", "limits_source": "FDA and EMA", "limits_verified": True, **trials,
            "validation": validation_gate(trials, observed, cv_fold=1.5)}


def test_an_unvalidated_vbe_is_reported_as_such_with_its_design_and_an_m15_table():
    mar = assemble_campaign_mar(map_doc=_map(), final_cpf=_cpf(), stage_evidence={}, prediction={"vbe": _vbe()})
    assert not check_report(mar)
    tables = {t.id: t for t in mar.evidence.tables}
    assert {"vbe_design", "vbe_results"} <= set(tables) and "vbe_validation" not in tables
    assert tables["vbe_results"].rows[-1][0].startswith("Joint")
    prediction = next(s for s in mar.sections if s.number == "6").body
    assert prediction.startswith("**This virtual bioequivalence result is not validated (NOT_VALIDATED):**")
    limits = next(s for s in mar.sections if s.number == "8").body
    assert "not validated (NOT_VALIDATED)" in limits and "DRAFT and UNVERIFIED" in limits
    assert "does not support a bioequivalence decision" in next(s for s in mar.sections if s.number == "9").body
    assert len(mar.m15_tables) == 2 and "Virtual bioequivalence of Test against Ref" in mar.m15_tables[1].question_of_interest


def test_a_validated_vbe_shows_the_gate_and_a_vbe_that_did_not_run_says_why():
    first = _vbe()
    cv, mid = (first["metrics"]["AUC_inf"][k] for k in ("between_subject_cv_percent", "gmr_median"))
    observed = {"source": "client BE study", "metrics": {"AUC_inf": {"gmr": mid, "between_subject_cv_percent": cv}}}
    mar = assemble_campaign_mar(map_doc=_map(), final_cpf=_cpf(), stage_evidence={},
                                prediction={"vbe": _vbe(observed)})
    assert not check_report(mar)
    assert "vbe_validation" in {t.id for t in mar.evidence.tables}
    assert "Validation against the observed BE study: **PASSED**" in next(s for s in mar.sections if s.number == "6").body
    not_run = {"template": "vbe-crossover", "template_version": "0.2.0-draft", "status": "NOT_RUN",
               "reason": "the engine stopped: x", "validation": {"status": "NOT_VALIDATED", "reason": "the VBE did not run"}}
    mar = assemble_campaign_mar(map_doc=_map(), final_cpf=_cpf(), stage_evidence={}, prediction={"vbe": not_run})
    assert "**The virtual bioequivalence (vbe-crossover 0.2.0-draft) did not run:** the engine stopped: x" in \
        next(s for s in mar.sections if s.number == "6").body
    assert "not run: the engine stopped: x" in mar.m15_tables[1].technical_criteria
