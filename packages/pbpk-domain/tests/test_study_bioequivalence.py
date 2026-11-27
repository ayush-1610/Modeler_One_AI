"""A clinical study's average bioequivalence from its subjects' values (plan 2026-11-26 §7 phase 3; the corpus audit's
R01, R50 and R55). The 2×2 crossover estimator is checked against an independent least-squares fit of the ANOVA model
(subject, period, treatment) on made-up data, not against itself."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from pbpk_domain.bioequivalence import be_zone, crossover_be, paired_crossover_ci, parallel_be

pytestmark = pytest.mark.req("T-47")


def _study(n_tr: int, n_rt: int, seed: int = 7):
    """Made-up 2×2 crossover values with a subject effect, a period effect (+8 %) and a true T/R of 0.95."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n_tr + n_rt):
        sequence = "TR" if i < n_tr else "RT"
        subject = rng.normal(0, 0.3)
        for period, treatment in enumerate(sequence, start=1):
            log_y = 4.0 + subject + (0.077 if period == 2 else 0.0) + (math.log(0.95) if treatment == "T" else 0.0)
            out.append((i, sequence, period, treatment, math.exp(log_y + rng.normal(0, 0.18))))
    return out


def _ols(rows):
    """The ANOVA model's treatment effect, its standard error and the residual MSE by least squares."""
    subjects = sorted({r[0] for r in rows})
    x = np.array([[1.0 if r[0] == s else 0.0 for s in subjects] + [1.0 if r[2] == 2 else 0.0, 1.0 if r[3] == "T" else 0.0]
                  for r in rows])
    y = np.log([r[4] for r in rows])
    beta, residual, *_ = np.linalg.lstsq(x, y, rcond=None)
    df = len(rows) - x.shape[1]
    mse = float(residual[0] / df)
    se = math.sqrt(mse * np.linalg.inv(x.T @ x)[-1, -1])
    return float(beta[-1]), se, mse, df


@pytest.mark.parametrize(("n_tr", "n_rt"), [(12, 12), (7, 6)])
def test_the_2x2_crossover_equals_the_anova_with_subject_period_and_treatment(n_tr, n_rt):
    rows = _study(n_tr, n_rt)
    by = {(r[0], r[3]): r for r in rows}
    ids = sorted({r[0] for r in rows})
    got = crossover_be([by[(i, "T")][4] for i in ids], [by[(i, "R")][4] for i in ids],
                       sequences=[by[(i, "T")][1] for i in ids])
    effect, se, mse, df = _ols(rows)
    q = stats.t.ppf(0.95, df)
    assert got.design == "2x2 crossover" and got.df == df == n_tr + n_rt - 2 and got.n_by_group == (n_tr, n_rt)
    assert got.geometric_mean_ratio == pytest.approx(math.exp(effect), rel=1e-12)
    assert got.mse == pytest.approx(mse, rel=1e-12)
    assert got.ci_lower == pytest.approx(math.exp(effect - q * se), rel=1e-12)
    assert got.ci_upper == pytest.approx(math.exp(effect + q * se), rel=1e-12)
    assert got.cv == pytest.approx(math.sqrt(math.exp(mse) - 1), rel=1e-12)


def test_without_sequences_a_crossover_is_the_paired_analysis():
    t, r = [100.0, 120.0, 90.0, 110.0], [105.0, 118.0, 99.0, 104.0]
    got = crossover_be(t, r)
    paired = paired_crossover_ci(t, r)
    assert got.design == "paired" and got.df == 3
    assert (got.geometric_mean_ratio, got.ci_lower, got.ci_upper) == pytest.approx(
        (paired.geometric_mean_ratio, paired.ci_lower, paired.ci_upper), rel=1e-12)


def test_a_parallel_study_is_the_pooled_two_sample_analysis():
    t, r = [80.0, 95.0, 110.0, 70.0, 101.0], [90.0, 120.0, 100.0, 85.0]
    got = parallel_be(t, r)
    welch_free = stats.ttest_ind(np.log(t), np.log(r), equal_var=True)
    lt, lr = np.log(t), np.log(r)
    se = (lt.mean() - lr.mean()) / welch_free.statistic
    q = stats.t.ppf(0.95, 7)
    assert got.design == "parallel" and got.df == 7
    assert got.ci_lower == pytest.approx(math.exp(lt.mean() - lr.mean() - q * se), rel=1e-10)


def test_the_be_zone_is_the_gmrs_whose_ci_lies_inside_the_limits():
    """R55: exp(±t·√(2σw²/n)) inside ln 0.8 … ln 1.25. A GMR at the zone's edge has its CI on the limit."""
    mse, n = math.log(1 + 0.2 ** 2), 24          # CVw 20 %
    low, high = be_zone(mse, n)
    h = stats.t.ppf(0.95, n - 2) * math.sqrt(2 * mse / n)
    assert low * math.exp(-h) == pytest.approx(0.80) and high * math.exp(h) == pytest.approx(1.25)
    assert 0.88 < low < 0.89 and 1.13 < high < 1.14
    assert be_zone(math.log(1 + 0.6 ** 2), 6) is None        # too variable for 6 subjects: no GMR passes
