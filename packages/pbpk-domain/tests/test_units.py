"""Observed data are compared with PK-Sim output in the engine's units: minutes and µmol/l."""

from __future__ import annotations

import pytest

from pbpk_domain.units import UnitError, minutes_per, normalize_profile, umol_per_l_per


def test_mass_concentration_converts_through_the_molecular_weight():
    # 225.2 ng/ml of a 225.2 g/mol compound is 1 µmol/l
    assert umol_per_l_per("ng/ml", 225.2) * 225.2 == pytest.approx(1.0)
    assert umol_per_l_per("mg/L", 225.2) * 225.2 == pytest.approx(1000.0)
    assert umol_per_l_per("nM", None) == pytest.approx(1e-3)
    assert umol_per_l_per("μmol/l", None) == 1.0  # Greek mu is folded to the micro sign


def test_mass_unit_without_molecular_weight_raises():
    with pytest.raises(UnitError, match="molecular weight"):
        umol_per_l_per("ng/ml", None)


def test_unknown_units_raise_rather_than_pass_through():
    with pytest.raises(UnitError):
        umol_per_l_per("mg", 100.0)
    with pytest.raises(UnitError):
        minutes_per("fortnight")


def test_profile_in_hours_and_ng_per_ml_becomes_minutes_and_umol_per_l():
    profile = {"times": [0.5, 1, 24], "values": [225.2, 450.4, 22.52], "time_unit": "h", "unit": "ng/ml",
               "sd": [22.52, 45.04, 2.252], "lloq": 2.252}
    out = normalize_profile(profile, 225.2)
    assert out["times"] == [30.0, 60.0, 1440.0]
    assert out["values"] == pytest.approx([1.0, 2.0, 0.1])
    assert out["sd"] == pytest.approx([0.1, 0.2, 0.01]) and out["lloq"] == pytest.approx(0.01)
    assert (out["time_unit"], out["unit"]) == ("min", "µmol/l")
    assert (out["source_time_unit"], out["source_unit"]) == ("h", "ng/ml")
    assert profile["time_unit"] == "h"  # the input is not mutated
