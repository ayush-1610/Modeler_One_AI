"""The PI spec names an SD's error type only when it is not arithmetic (contracts §8.2, D1a; plan 2026-11-12 L-c).

Every observed block without a geometric SD stays byte for byte what it was (the spec is hashed and is part of the
submission bundle); run_pi.R reads an absent type as arithmetic. The two names are pbpk_domain.spread's, harvested from
the OSP reference snapshots. A geometric SD is a dimensionless factor, so the unit conversion leaves it as reported, and
a spread kept verbatim (it carries its own unit) is never touched. Nothing here runs PK-Sim.
"""

from __future__ import annotations

import json

import pytest

from pbpk_domain import spread
from pbpk_domain.fit_spec import pi_observed
from pbpk_domain.units import normalize_profile

pytestmark = pytest.mark.req("T-13")
TODAY_WITH_SD = ('{"name": "obs", "time": [0.5, 1, 4], "time_unit": "h", "values": [12.0, 20.0, 5.0], "unit": "ng/ml", '
                 '"dimension": "Concentration (mass)", "mol_weight": 300.0, "sd": [1, 2, 0.5], "lloq": 0.1}')
TODAY_NO_SD = ('{"name": "o", "time": [1, 2], "time_unit": "h", "values": [1.0, 0.5], "unit": "ng/ml", '
               '"dimension": "Concentration (mass)", "mol_weight": 300.0, "sd": []}')


def _with_sd(**kwargs):
    return pi_observed("obs", [0.5, 1, 4], [12.0, 20.0, 5.0], time_unit="h", unit="ng/ml", mol_weight=300.0, sd=[1, 2, 0.5],
                       lloq=0.1, **kwargs)


def _no_sd(**kwargs):
    return pi_observed("o", [1, 2], [1.0, 0.5], time_unit="h", unit="ng/ml", mol_weight=300.0, **kwargs)


def test_an_arithmetic_sd_and_no_sd_give_todays_block_byte_for_byte():
    # the literals were printed by pi_observed at 045ffc3, before the error type existed
    for kwargs in ({}, {"error_type": None}, {"error_type": spread.ARITHMETIC_SD}):
        assert json.dumps(_with_sd(**kwargs), ensure_ascii=False) == TODAY_WITH_SD
        assert json.dumps(_no_sd(**kwargs), ensure_ascii=False) == TODAY_NO_SD
    # a geometric type with no SD to type: nothing to label, the block is today's
    assert json.dumps(_no_sd(error_type=spread.GEOMETRIC_SD), ensure_ascii=False) == TODAY_NO_SD
    assert json.dumps(pi_observed("o", [1, 2], [1.0, 0.5], time_unit="h", unit="ng/ml", mol_weight=300.0, sd=[],
                                  error_type=spread.GEOMETRIC_SD), ensure_ascii=False) == TODAY_NO_SD


def test_the_key_appears_only_for_a_geometric_sd_and_another_name_is_refused():
    block = _with_sd(error_type=spread.GEOMETRIC_SD)
    assert block["error_type"] == "GeometricStdDev" == spread.GEOMETRIC_SD
    assert {k: v for k, v in block.items() if k != "error_type"} == json.loads(TODAY_WITH_SD)
    assert spread.ERROR_TYPES == ("ArithmeticStdDev", "GeometricStdDev")
    for wrong in ("geometric", "GeometricSD", "SE", "CV%", ""):
        with pytest.raises(ValueError, match="not one of the PK-Sim error types"):
            _with_sd(error_type=wrong)
    # never a None in the block: run_job.R re-serialises the spec and a null comes back as {}
    for b in (_with_sd(), _no_sd(), block, _with_sd(error_type=spread.ARITHMETIC_SD)):
        assert all(v is not None for v in b.values())


def test_the_unit_conversion_scales_an_arithmetic_sd_as_today_and_leaves_a_factor_and_a_verbatim_spread():
    base = {"times": [0.5, 1, 4], "values": [12.0, 20.0, 5.0], "time_unit": "h", "unit": "ng/ml", "sd": [1.0, 2.0, 0.5],
            "lloq": 0.1}
    arithmetic = normalize_profile(base, 300.0)
    assert arithmetic["sd"] == [1.0 / 300.0, 2.0 / 300.0, 0.5 / 300.0]          # µg/l / MW: as before
    assert arithmetic["values"] == [12.0 / 300.0, 20.0 / 300.0, 5.0 / 300.0] and arithmetic["times"] == [30.0, 60.0, 240.0]
    labelled = normalize_profile({**base, "sd_type": spread.ARITHMETIC_SD}, 300.0)
    assert labelled["sd"] == arithmetic["sd"]
    geometric = normalize_profile({**base, "sd": [1.4, 1.5, 1.9], "sd_type": spread.GEOMETRIC_SD}, 300.0)
    assert geometric["sd"] == [1.4, 1.5, 1.9] and geometric["sd_type"] == spread.GEOMETRIC_SD   # a factor: unscaled
    assert geometric["values"] == arithmetic["values"] and geometric["lloq"] == arithmetic["lloq"]
    verbatim = {"kind": "SE", "values": [0.8, 1.1, 0.3], "unit": "ng/ml"}
    kept = normalize_profile({**base, "sd": None, "spread": verbatim, "warnings": ["the SE is kept as reported"]}, 300.0)
    assert kept["spread"] == {"kind": "SE", "values": [0.8, 1.1, 0.3], "unit": "ng/ml"} and kept["sd"] is None
    assert kept["warnings"] == ["the SE is kept as reported"]
