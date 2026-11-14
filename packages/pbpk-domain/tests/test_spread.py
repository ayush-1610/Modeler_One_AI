"""Spread conversion and the two PK-Sim error types (contracts §4.8)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from pbpk_domain import spread

pytestmark = pytest.mark.req("T-47")

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"


def test_the_sd_of_a_mean_from_its_standard_error_and_n():
    assert spread.sd_from_se(2.0, 16) == pytest.approx(8.0)
    assert spread.sd_from_se(1.5, 12) == pytest.approx(1.5 * math.sqrt(12))
    assert spread.sd_from_se(1.5, 1) == 1.5
    with pytest.raises(ValueError):
        spread.sd_from_se(1.5, 0)


def test_the_sd_of_an_arithmetic_mean_from_its_cv_percent():
    assert spread.sd_from_cv_percent(20.0, 50.0) == pytest.approx(10.0)
    assert spread.sd_from_cv_percent(0.0, 50.0) == 0.0
    assert spread.VERSION == "spread-1"


def _auxiliary_types(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "AuxiliaryType" and isinstance(value, str):
                found.add(value)
            found |= _auxiliary_types(value)
    elif isinstance(node, list):
        for value in node:
            found |= _auxiliary_types(value)
    return found


def test_both_error_types_are_harvested_from_the_golden_fixtures():
    """The two names are PK-Sim's own: each occurs as an observed data AuxiliaryType in a golden snapshot."""
    assert spread.ERROR_TYPES == (spread.ARITHMETIC_SD, spread.GEOMETRIC_SD) == ("ArithmeticStdDev", "GeometricStdDev")
    by_file = {path.name: _auxiliary_types(json.loads(path.read_text(encoding="utf-8")))
               for path in sorted(FIXTURES.glob("*.json"))}
    assert by_file, f"no golden fixtures under {FIXTURES}"
    seen = set().union(*by_file.values())
    assert set(spread.ERROR_TYPES) <= seen
    assert spread.GEOMETRIC_SD in by_file["Midazolam-Model.json"] and spread.GEOMETRIC_SD in by_file["Rifampicin-Model.json"]
    assert sum(spread.ARITHMETIC_SD in types for types in by_file.values()) > len(by_file) / 2
