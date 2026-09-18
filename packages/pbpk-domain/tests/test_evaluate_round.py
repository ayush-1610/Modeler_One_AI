from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pbpk_domain.campaign.evaluate import ObservedPK, SimulatedProfile, assess_round
from pbpk_domain.m15 import Rating

GOLDEN = Path(__file__).parents[3] / "services" / "engine-worker" / "golden" / "results_sample" / "results.csv"


def _golden_profile(role: str = "fitting", study_id: str = "aciclovir") -> SimulatedProfile:
    rows = [r for r in csv.reader(GOLDEN.open(encoding="utf-8-sig")) if r]
    times = [float(r[1]) for r in rows[1:]]
    concs = [float(r[2]) for r in rows[1:]]
    return SimulatedProfile(study_id=study_id, role=role, times=times, concentrations=concs)


# engine pk_analyses.csv values for the golden run
GOLDEN_AUC = 4064.1245
GOLDEN_CMAX = 50.25272


def test_predicted_pk_matches_engine() -> None:
    a = assess_round([_golden_profile()], {}, model_risk=Rating.MEDIUM)
    pk = a.studies[0]
    assert pk.predicted_cmax == pytest.approx(GOLDEN_CMAX, rel=1e-5)
    assert pk.predicted_auc == pytest.approx(GOLDEN_AUC, rel=0.01)
    assert pk.predicted_tmax == pytest.approx(11.0, rel=1e-6)  # minutes


@pytest.mark.req("D6", "T-18")
def test_gate_passes_when_prediction_matches_observed() -> None:
    obs = {"aciclovir": ObservedPK(auc=GOLDEN_AUC, cmax=GOLDEN_CMAX)}
    a = assess_round([_golden_profile()], obs, model_risk=Rating.HIGH)
    assert a.gate_passed is True
    assert a.report is not None and a.report.passes
    assert a.metrics["AUC"]["gmfe"] < 1.02


def test_gate_fails_when_prediction_is_off() -> None:
    obs = {"aciclovir": ObservedPK(auc=GOLDEN_AUC * 3.0, cmax=GOLDEN_CMAX * 3.0)}  # 3-fold under-prediction
    a = assess_round([_golden_profile()], obs, model_risk=Rating.HIGH)
    assert a.gate_passed is False
    assert any("AUC" in f for f in a.findings)
    assert a.report is not None and not a.report.passes


def test_no_observed_pk_cannot_judge_gate() -> None:
    a = assess_round([_golden_profile()], {}, model_risk=Rating.MEDIUM)
    assert a.gate_passed is False
    assert a.report is None
    assert any("no observed PK" in f for f in a.findings)
    # predicted PK is still reported for the record
    assert a.studies[0].predicted_cmax > 0


def test_fitting_and_validation_grouped_separately() -> None:
    fitting = _golden_profile(role="fitting", study_id="train")
    validation = _golden_profile(role="validation", study_id="test")
    obs = {
        "train": ObservedPK(auc=GOLDEN_AUC, cmax=GOLDEN_CMAX),
        "test": ObservedPK(auc=GOLDEN_AUC, cmax=GOLDEN_CMAX),
    }
    a = assess_round([fitting, validation], obs, model_risk=Rating.MEDIUM)
    roles = {(g["role"], g["quantity"]) for g in a.metrics["groups"]}
    assert ("fitting", "AUC") in roles
    assert ("validation", "AUC") in roles
    assert a.gate_passed is True


def test_auc_kind_inf_uses_extrapolated_auc() -> None:
    a_last = assess_round([_golden_profile()], {}, model_risk=Rating.MEDIUM, auc_kind="last")
    a_inf = assess_round([_golden_profile()], {}, model_risk=Rating.MEDIUM, auc_kind="inf")
    # AUCinf >= AUClast (adds the extrapolated tail)
    assert a_inf.studies[0].predicted_auc >= a_last.studies[0].predicted_auc


def test_short_profile_is_skipped_with_finding() -> None:
    a = assess_round([SimulatedProfile("x", "fitting", [0.0], [1.0])], {}, model_risk=Rating.MEDIUM)
    assert a.studies == ()
    assert any("fewer than two" in f for f in a.findings)
