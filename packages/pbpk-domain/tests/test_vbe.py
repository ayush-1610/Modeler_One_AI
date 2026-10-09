"""Virtual bioequivalence trials (T-31 B6 PR 4): PK-Sim's per-individual PK into K crossover trials and the PoS."""

from __future__ import annotations

import math
import statistics
from pathlib import Path

import pytest

from pbpk_domain.vbe import VbeError, between_subject_cv, read_pk_analyses, run_trials, validation_gate

pytestmark = pytest.mark.req("T-31")
SAMPLE = Path(__file__).parents[3] / "services" / "engine-worker" / "golden" / "results_sample" / "pk_analyses.csv"


def test_pk_sims_own_pk_analyses_file_is_read_per_individual_for_the_named_output():
    text = SAMPLE.read_text(encoding="utf-8-sig")
    plasma = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"
    path, values = read_pk_analyses(text, plasma)
    assert path == plasma and values["C_max"] == {0: 50.25272} and set(values["AUC_inf"]) == {0}
    with pytest.raises(VbeError, match="2 outputs"):  # plasma and unbound plasma: never guessed
        read_pk_analyses(text)
    with pytest.raises(VbeError, match="no output 'Organism|Other'"):
        read_pk_analyses(text, "Organism|Other")


def _arms(ratio: float, n: int, *, noise: float = 0.0):
    base = {i: 100.0 * (1 + 0.37 * (i % 5)) for i in range(n)}
    wobble = {i: 1 + noise * (((i * 7919) % 11) - 5) / 5 for i in range(n)}
    test = {m: {i: base[i] * ratio * wobble[i] for i in base} for m in ("AUC_inf", "C_max")}
    reference = {m: dict(base) for m in ("AUC_inf", "C_max")}
    return test, reference


def test_identical_products_pass_every_trial_and_a_30_percent_difference_fails_them():
    common = dict(n_subjects=12, n_trials=5, limits=(0.80, 1.25), confidence=0.90, pos_threshold=0.8)
    same = run_trials(*_arms(1.0, 60, noise=0.05), **common)
    assert same["joint_probability_of_success"] == 1.0 and same["meets_threshold"]
    assert same["n_trials_run"] == 5 and len(same["metrics"]["C_max"]["trials"]) == 5
    assert 0.9 < same["metrics"]["AUC_inf"]["gmr_median"] < 1.1
    off = run_trials(*_arms(1.3, 60, noise=0.05), **common)
    assert off["metrics"]["AUC_inf"]["probability_of_success"] == 0.0 and not off["meets_threshold"]


def test_an_unusable_individual_is_excluded_by_name_and_trials_are_only_whole():
    test, reference = _arms(1.0, 30, noise=0.05)
    test["C_max"][3] = 0.0           # a subject with no positive exposure cannot enter a ratio
    del reference["AUC_inf"][4]      # nor one missing from an arm
    out = run_trials(test, reference, n_subjects=12, n_trials=5, limits=(0.80, 1.25), confidence=0.90, pos_threshold=0.8)
    assert out["excluded_individuals"] == [3, 4]
    assert out["n_trials_planned"] == 5 and out["n_trials_run"] == 2  # 28 usable individuals fill 2 trials of 12
    with pytest.raises(VbeError, match="cannot fill one trial"):
        run_trials(*_arms(1.0, 5), n_subjects=12, n_trials=1, limits=(0.8, 1.25), confidence=0.9, pos_threshold=0.8)


def test_between_subject_cv_is_the_log_normal_cv():
    s = 0.3
    logs = [s * z for z in (-1.5, -0.5, 0.5, 1.5)]
    expected = 100 * math.sqrt(math.exp(statistics.stdev(logs) ** 2) - 1)
    assert abs(between_subject_cv([math.exp(v) for v in logs]) - expected) < 1e-9


def test_the_gate_without_an_observed_study_never_passes():
    result = run_trials(*_arms(1.0, 24, noise=0.05), n_subjects=12, n_trials=2, limits=(0.8, 1.25), confidence=0.9,
                        pos_threshold=0.8)
    assert validation_gate(result, None, cv_fold=1.5)["status"] == "NOT_VALIDATED"
    other = {"source": "x", "metrics": {"AUC_tEnd": {"gmr": 1.0, "between_subject_cv_percent": 20}}}
    assert validation_gate(result, other, cv_fold=1.5)["status"] == "NOT_VALIDATED"
