"""Canonical units for comparing observed data with the engine's output.

PK-Sim reports plasma concentration in µmol/l against time in minutes (the round's ``profiles.json``). An
observed profile arrives in whatever the study reported — ng/ml over hours is typical — so before any
comparison (the acceptance gate's AUC and Cmax, the observed window, the fit's dataset) it is converted once to
those canonical units. Mass concentrations need the compound's molecular weight: c[µmol/l] = c[µg/l] / MW[g/mol].

Unit spellings follow the intake tables (``modeler_intake.validate``); an unrecognised unit raises rather than
being passed through, because a silent unit mismatch corrupts every ratio computed from it.
"""

from __future__ import annotations

import unicodedata
from typing import Any

CANONICAL_TIME_UNIT = "min"
CANONICAL_CONCENTRATION_UNIT = "µmol/l"

# alias -> factor to µg/l
_MASS_TO_UG_PER_L = {
    "pg/l": 1e-6, "ng/l": 1e-3, "µg/l": 1.0, "ug/l": 1.0, "mg/l": 1e3, "g/l": 1e6,
    "pg/ml": 1e-3, "ng/ml": 1.0, "µg/ml": 1e3, "ug/ml": 1e3, "mcg/ml": 1e3, "mg/ml": 1e6,
}
# alias -> factor to µmol/l
_MOLAR_TO_UMOL_PER_L = {
    "fmol/l": 1e-9, "pmol/l": 1e-6, "nmol/l": 1e-3, "µmol/l": 1.0, "umol/l": 1.0, "mmol/l": 1e3, "mol/l": 1e6,
    "fmol/ml": 1e-6, "pmol/ml": 1e-3, "nmol/ml": 1.0, "µmol/ml": 1e3, "mmol/ml": 1e6, "mol/ml": 1e9,
    "fm": 1e-9, "pm": 1e-6, "nm": 1e-3, "µm": 1.0, "um": 1.0, "mm": 1e3,
}
# alias -> factor to minutes
_TIME_TO_MIN = {
    "s": 1 / 60, "sec": 1 / 60, "min": 1.0, "minute": 1.0, "minutes": 1.0,
    "h": 60.0, "hr": 60.0, "hrs": 60.0, "hour": 60.0, "hours": 60.0, "hour(s)": 60.0,
    "d": 1440.0, "day": 1440.0, "days": 1440.0, "day(s)": 1440.0,
}


class UnitError(ValueError):
    """A unit that cannot be converted to the canonical one (unknown, or mass without a molecular weight)."""


def _key(unit: str) -> str:
    return unicodedata.normalize("NFKC", unit).strip().lower().replace("μ", "µ")


def is_molar(unit: str) -> bool:
    return _key(unit) in _MOLAR_TO_UMOL_PER_L


def minutes_per(unit: str) -> float:
    """Factor converting a time in ``unit`` to minutes."""
    factor = _TIME_TO_MIN.get(_key(unit))
    if factor is None:
        raise UnitError(f"time unit {unit!r} is not recognised")
    return factor


def umol_per_l_per(unit: str, mol_weight: float | None) -> float:
    """Factor converting a plasma concentration in ``unit`` to µmol/l (mass units need ``mol_weight`` g/mol)."""
    key = _key(unit)
    if key in _MOLAR_TO_UMOL_PER_L:
        return _MOLAR_TO_UMOL_PER_L[key]
    if key in _MASS_TO_UG_PER_L:
        if not mol_weight or mol_weight <= 0:
            raise UnitError(f"concentration unit {unit!r} is a mass unit; converting it needs the molecular weight")
        return _MASS_TO_UG_PER_L[key] / mol_weight
    raise UnitError(f"concentration unit {unit!r} is not recognised")


def normalize_profile(profile: dict[str, Any], mol_weight: float | None) -> dict[str, Any]:
    """The profile in minutes and µmol/l, with SD and LLOQ scaled alike; the reported units are kept under
    ``source_time_unit`` / ``source_unit`` for the record."""
    t_factor = minutes_per(profile.get("time_unit", CANONICAL_TIME_UNIT))
    c_factor = umol_per_l_per(profile.get("unit", CANONICAL_CONCENTRATION_UNIT), mol_weight)
    out = dict(profile)
    out["times"] = [float(t) * t_factor for t in profile["times"]]
    out["values"] = [float(v) * c_factor for v in profile["values"]]
    if profile.get("sd"):
        out["sd"] = [float(v) * c_factor for v in profile["sd"]]
    if profile.get("lloq") is not None:
        out["lloq"] = float(profile["lloq"]) * c_factor
    out["time_unit"] = CANONICAL_TIME_UNIT
    out["unit"] = CANONICAL_CONCENTRATION_UNIT
    out["source_time_unit"] = profile.get("time_unit", CANONICAL_TIME_UNIT)
    out["source_unit"] = profile.get("unit", CANONICAL_CONCENTRATION_UNIT)
    return out
