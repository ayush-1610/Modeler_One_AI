from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from pbpk_domain.nca import auc_linup_logdown, nca, terminal_slope

GOLDEN = Path(__file__).parents[3] / "services" / "engine-worker" / "golden" / "results_sample" / "results.csv"


# --- analytic / synthetic checks -----------------------------------------------------------------


def test_cmax_and_tmax():
    result = nca([0, 1, 2, 4, 8], [0, 10, 20, 12, 3])
    assert result.c_max == 20
    assert result.t_max == 2
    assert result.t_last == 8
    assert result.c_last == 3


def test_auc_linear_on_rising_segments():
    # rising/flat segments use the linear trapezoid
    assert auc_linup_logdown([0, 1, 2], [0, 10, 20]) == pytest.approx(20.0)
    assert auc_linup_logdown([0, 2], [5, 5]) == pytest.approx(10.0)


def test_auc_log_down_on_falling_segment():
    # falling segment with positive endpoints uses the log trapezoid: dt*(c0-c1)/ln(c0/c1)
    assert auc_linup_logdown([0, 1], [20, 10]) == pytest.approx(10.0 / math.log(2.0))


def test_terminal_halflife_from_pure_exponential():
    k = 0.1
    times = list(range(0, 51, 2))
    concs = [100.0 * math.exp(-k * t) for t in times]
    lam, _n = terminal_slope(times, concs)
    assert lam == pytest.approx(k, rel=1e-6)
    result = nca(times, concs)
    assert result.t_half == pytest.approx(math.log(2) / k, rel=1e-6)
    # AUCinf of a mono-exponential from t0 is c0/k (here c0 = 100 at t=0)
    assert result.auc_inf == pytest.approx(100.0 / k, rel=0.02)


def test_no_declining_tail_gives_no_halflife():
    result = nca([0, 1, 2], [0, 5, 10])  # still rising -> no terminal slope
    assert result.lambda_z is None and result.t_half is None and result.auc_inf is None


def test_needs_two_points():
    with pytest.raises(ValueError, match="at least two"):
        nca([0], [5])


# --- validation against a real engine run (T-18 acceptance: within 1%) ---------------------------


@pytest.mark.skipif(not GOLDEN.exists(), reason="golden results sample not present")
def test_nca_reproduces_engine_pk_within_one_percent():
    rows = [r for r in csv.reader(GOLDEN.open(encoding="utf-8-sig")) if r]
    times = [float(r[1]) for r in rows[1:]]  # Time [min]
    concs = [float(r[2]) for r in rows[1:]]  # plasma [µmol/l]
    result = nca(times, concs)
    # engine pk_analyses.csv for the same run
    assert result.c_max == pytest.approx(50.25272, rel=1e-5)
    assert result.t_max / 60 == pytest.approx(0.18333334, rel=1e-4)  # min -> h
    assert result.auc_last == pytest.approx(4064.1245, rel=0.01)  # within 1%
