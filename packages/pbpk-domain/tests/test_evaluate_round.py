from __future__ import annotations

import csv
import math
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


def test_prediction_is_reduced_over_the_observed_window():
    """A perfect model must not be scored as wrong just because the simulation runs longer than the study
    sampled. Comparing AUC-to-last across different intervals biases the ratio — badly for a slow compound."""
    from pbpk_domain.campaign.evaluate import ObservedPK, SimulatedProfile, assess_round
    from pbpk_domain.m15 import Rating
    from pbpk_domain.nca import nca

    # a slowly eliminated profile simulated to 24 h, but only sampled to 12 h
    times = [i * 30.0 for i in range(49)]
    concs = [100.0 * math.exp(-0.0005 * t) for t in times]
    sampled = [(t, c) for t, c in zip(times, concs, strict=True) if t <= 720]
    observed_auc = nca([t for t, _ in sampled], [c for _, c in sampled]).auc_last

    profile = SimulatedProfile(study_id="s", role="fitting", times=times, concentrations=concs)
    obs = ObservedPK(auc=observed_auc, cmax=concs[0], t_last=720.0)

    assessment = assess_round([profile], {"s": obs}, model_risk=Rating.HIGH)

    study = assessment.studies[0]
    assert study.predicted_auc == pytest.approx(observed_auc, rel=1e-6)  # identical model, identical window
    assert assessment.gate_passed, assessment.findings

    # and without the window it is scored as roughly twice the observed exposure
    naive = assess_round([profile], {"s": ObservedPK(auc=observed_auc, cmax=concs[0])}, model_risk=Rating.HIGH)
    assert naive.studies[0].predicted_auc > observed_auc * 1.5
    assert not naive.gate_passed


def test_the_prediction_is_read_at_the_observed_sampling_times():
    """Like with like: an IV peak between samples is not compared with the sampled observed Cmax; the prediction is
    interpolated at the observed times (the Dapagliflozin IV microdose is sampled from 5 min)."""
    times = [0.0, 1.0, 2.0, 5.0, 10.0, 60.0, 120.0]
    concs = [0.0, 10.0, 8.0, 5.0, 3.0, 1.0, 0.5]
    sampled = (5.0, 10.0, 60.0, 120.0)
    obs = ObservedPK(auc=None, cmax=5.0, t_first=5.0, t_last=120.0, sample_times=sampled)
    result = assess_round([SimulatedProfile("s", "fitting", times, concs)], {"s": obs}, model_risk=Rating.HIGH)
    study = result.studies[0]
    assert study.predicted_cmax == 5.0 and study.predicted_tmax == 5.0


def _biexp(times, a=10.0, alpha=0.05, b=2.0, beta=0.005):
    return [a * math.exp(-alpha * t) + b * math.exp(-beta * t) for t in times]


@pytest.mark.req("T-14")
def test_iv_profile_shape_evidence_early_phase_and_vss():
    # A prediction with the observed elimination but a smaller initial volume (peak twice as high, same AUC share
    # late on): the early samples read high and Vss reads low, the IV distribution rule's evidence (MS-01 §5).
    t = [5.0, 15, 30, 60, 120, 240, 480, 720, 1440]
    obs_c = _biexp(t)
    pred_times = [float(x) for x in range(0, 1441, 5)]
    pred = _biexp(pred_times, a=30.0)
    observed = {"iv": ObservedPK(auc=None, cmax=max(obs_c), tmax=5.0, sample_times=tuple(t), sample_values=tuple(obs_c),
                                 infusion_time=1.0)}
    study = assess_round([SimulatedProfile("iv", "fitting", pred_times, pred)], observed, model_risk=Rating.MEDIUM).studies[0]
    assert study.early_ratio > 1.25
    assert study.vss_ratio < 0.8
    # identical curves: both ratios 1
    same = assess_round([SimulatedProfile("iv", "fitting", pred_times, _biexp(pred_times))], observed,
                        model_risk=Rating.MEDIUM).studies[0]
    assert same.early_ratio == pytest.approx(1.0, rel=1e-3) and same.vss_ratio == pytest.approx(1.0, rel=1e-3)
    # an oral study (no infusion time) carries no IV shape evidence
    oral = {"iv": ObservedPK(auc=None, cmax=max(obs_c), tmax=5.0, sample_times=tuple(t), sample_values=tuple(obs_c))}
    s = assess_round([SimulatedProfile("iv", "fitting", pred_times, pred)], oral, model_risk=Rating.MEDIUM).studies[0]
    assert (s.early_ratio, s.vss_ratio) == (None, None)
