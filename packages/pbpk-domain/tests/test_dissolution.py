"""T-48: dissolution profiles, their checks, f2 under its conditions, and the Weibull fit (PK-Sim parameterization)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pbpk_domain.dissolution import ENGINE_CONFIRMED, check_profile, f2, fit_weibull, profiles_from_rows, weibull_fraction

pytestmark = pytest.mark.req("T-48")
TIMES = (5, 10, 15, 20, 30, 45, 60)


def _rows(product: str, role: str, means: list[float], *, spread: float = 1.0, units: int = 12, medium: str = "pH 6.8"):
    rows = []
    for i, (t, m) in enumerate(zip(TIMES, means, strict=True)):
        offsets = np.linspace(-spread, spread, units)
        values = {"product": product, "role": role, "medium": medium, "apparatus": "USP 2", "rpm": 50, "time": t,
                  "time_unit": "min", **{f"vessel_{k + 1}": round(m + o, 3) for k, o in enumerate(offsets)}}
        rows.append({"values": values, "cells": {"time": f"Dissolution!L{i + 2}"}})
    return rows


def _profile(product, role, means, **kw):
    profiles, problems = profiles_from_rows(_rows(product, role, means, **kw))
    assert not problems
    return profiles[0]


def test_the_weibull_fit_recovers_known_parameters_in_pksim_parameterization():
    means = [100 * float(v) for v in weibull_fraction(np.array(TIMES), 22.0, 1.4)]
    fit = fit_weibull(_profile("Tab", "TEST", means, spread=0.0))
    assert fit.converged and fit.t50_min == pytest.approx(22.0, rel=1e-4) and fit.shape == pytest.approx(1.4, rel=1e-4)
    assert fit.rmse_percent < 1e-3 and fit.n_points == 7
    # half the dose is dissolved at t50 after the lag: the meaning of PK-Sim's "Dissolution time (50% dissolved)"
    assert float(weibull_fraction(np.array([22.0 + 5.0]), 22.0, 1.4, lag=5.0)[0]) == pytest.approx(0.5)
    # confirmed against PK-Sim's own release curve by the engine-image qualification (dissolution.ENGINE_CHECK)
    assert fit.engine_confirmed is ENGINE_CONFIRMED is True


def test_profile_checks_say_which_release_model_the_data_support():
    slow = [100 * float(v) for v in weibull_fraction(np.array(TIMES), 22.0, 1.4)]
    assert check_profile(_profile("A", "TEST", slow)) == ([], "Weibull")
    flags, kind = check_profile(_profile("B", "TEST", [70, 88, 95, 98, 99, 100, 100]))
    assert kind == "Dissolved"                                   # ≥ 85 % within 15 min (MS-01 §4 S2)
    flags, kind = check_profile(_profile("C", "TEST", [20, 35, 45, 52, 60, 61, 61.5]))
    assert kind == "Table" and "plateaus at 62 %" in flags[0]
    flags, _ = check_profile(_profile("D", "TEST", [30, 60, 90, 115, 112, 113, 113]))
    assert any("exceeds 110 %" in f for f in flags)


def test_f2_is_computed_only_under_its_conditions():
    reference = _profile("RLD", "RLD", [20, 38, 55, 66, 80, 90, 95])
    test = _profile("Test", "TEST", [15, 32, 49, 60, 74, 87, 94])
    result = f2(test, reference)
    # points up to and including the first above 85 %: 5 … 45 min; differences 5, 6, 6, 6, 6, 3
    diffs = np.array([5, 6, 6, 6, 6, 3], dtype=float)
    expected = 50 * math.log10(100 / math.sqrt(1 + float(np.mean(diffs ** 2))))
    assert result.applicable and result.value == pytest.approx(expected, abs=0.01) and result.similar
    assert result.times_used == (5, 10, 15, 20, 30, 45) and "UNVERIFIED" in result.ruleset

    few_units = f2(_profile("Test", "TEST", [15, 32, 49, 60, 74, 87, 94], units=6), reference)
    assert not few_units.applicable and "6 units, at least 12" in few_units.reasons[0]
    variable = f2(_profile("Test", "TEST", [15, 32, 49, 60, 74, 87, 94], spread=12.0), reference)
    assert not variable.applicable and any("CV" in r for r in variable.reasons)
    rapid = f2(_profile("Test", "TEST", [70, 88, 95, 98, 99, 100, 100]), _profile("RLD", "RLD", [72, 90, 96, 98, 99, 100, 100]))
    assert rapid.similar and not rapid.applicable and "similar without f2" in rapid.reasons[0]
