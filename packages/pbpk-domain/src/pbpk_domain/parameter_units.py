"""Unit conversion of a stated parameter value to the unit the CPF / PK-Sim stores (MS-01 §2.2), by code, never by an
agent (architecture pack §6.1 policy 2: no LLM arithmetic).

Only plain unit changes are done here (cm/s → cm/min, % → fraction, mg/l → mg/ml, h → min …). Anything that is a
scientific transformation rather than a unit change (CLint → CLspec needs IVIVE scaling; an absolute clearance in l/h
needs a body weight) raises `ConversionError` with the reason, so the value waits for a person or the IVIVE step.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class Converted:
    value: float
    unit: str | None
    how: str            # the conversion in words, stored with the evidence


def _k(unit: str | None) -> str:
    if unit is None:
        return ""
    return unicodedata.normalize("NFKC", unit).strip().lower().replace("μ", "µ").replace(" ", "")


_UNITLESS = {"", "-", "none", "unitless", "dimensionless", "logunits", "log units", "loguints", "fraction", "ratio"}
# protein binding stated as the bound share ("30 % bound"), and the unbound share stated in percent (keys without spaces)
_BOUND = {"%bound", "percentbound", "%proteinbound", "%protein-bound", "bound%", "fractionbound"}
_UNBOUND = {"%unbound", "percentunbound", "%free", "unbound%"}
# target unit, then alias -> factor to the target unit
_FAMILIES: dict[str, tuple[str, dict[str, float]]] = {
    "g/mol": ("g/mol", {"g/mol": 1.0, "da": 1.0, "kda": 1000.0, "gmol-1": 1.0, "g·mol-1": 1.0}),
    "mg/ml": ("mg/ml", {"mg/ml": 1.0, "g/l": 1.0, "mg/l": 1e-3, "µg/ml": 1e-3, "ug/ml": 1e-3, "mcg/ml": 1e-3,
                        "ng/ml": 1e-6, "µg/l": 1e-6, "ug/l": 1e-6, "g/ml": 1e3, "mg/100ml": 1e-2}),
    "cm/min": ("cm/min", {"cm/min": 1.0, "cm/s": 60.0, "cm/sec": 60.0, "cm/h": 1 / 60, "µm/s": 6e-3, "um/s": 6e-3,
                          "nm/s": 6e-6, "m/s": 6000.0, "10^-6cm/s": 6e-5, "1e-6cm/s": 6e-5}),
    "min": ("min", {"min": 1.0, "minutes": 1.0, "h": 60.0, "hr": 60.0, "hours": 60.0, "s": 1 / 60, "sec": 1 / 60}),
    "µmol/l": ("µmol/l", {"µmol/l": 1.0, "umol/l": 1.0, "µm": 1.0, "um": 1.0, "nmol/l": 1e-3, "nm": 1e-3,
                          "mmol/l": 1e3, "mm": 1e3}),
    "ml/min/kg": ("ml/min/kg", {"ml/min/kg": 1.0, "l/h/kg": 1000 / 60, "ml/h/kg": 1 / 60, "l/min/kg": 1000.0}),
}
# CPF id prefix -> the family of its storage unit (None: dimensionless). Units are MS-01 §2.2's.
_TARGETS: tuple[tuple[str, str | None], ...] = (
    ("phys.mw", "g/mol"), ("phys.logp", None), ("phys.pka", None), ("bind.fu", "fraction"), ("dist.bp_ratio", None),
    ("phys.solubility.ref", "mg/ml"), ("perm.intestinal", "cm/min"), ("perm.cellular", "cm/min"),
    ("elim.renal.gfr_fraction", None), ("elim.hepatic.total_cl", "ml/min/kg"), ("elim.ehc_fraction", None),
    ("elim.fe_urine", "fraction"), ("elim.fm", "fraction"),
    ("form.", "min"),
)


def target_family(target: str) -> str | None | bool:
    """The storage family of a CPF id; False when the id is not converted here (e.g. CLspec needs IVIVE)."""
    if target.startswith("elim.hepatic.") and target.endswith(".clspec"):
        return False
    if target.startswith("elim.hepatic.") and target.endswith(".km"):
        return "µmol/l"
    if target.startswith("form.") and target.endswith(".shape"):
        return None
    for prefix, family in _TARGETS:
        if target == prefix or target.startswith(prefix + ".") or (prefix.endswith(".") and target.startswith(prefix)):
            return family
    return False


def to_storage_unit(target: str, value: float, unit: str | None) -> Converted:
    family = target_family(target)
    key = _k(unit)
    if family is False:
        if target.endswith(".clspec"):
            raise ConversionError("CLint → CLspec is an IVIVE scaling (system, protein, fu,inc), not a unit change")
        raise ConversionError(f"no storage unit known for {target}; enter the PK-Sim value by hand")
    if family is None:
        if key in _UNITLESS:
            return Converted(float(value), None, "dimensionless, unchanged")
        raise ConversionError(f"{target} is dimensionless; the stated unit {unit!r} is unexpected")
    if family == "fraction":
        if key in _BOUND and target == "bind.fu":
            # a source stating protein binding gives the bound share; PK-Sim takes the unbound fraction
            bound = float(value) / (100.0 if key.startswith(("%", "percent")) else 1.0)
            if not 0 <= bound < 1:
                raise ConversionError(f"a bound share must be in [0, 1); {value} {unit} is not")
            return Converted(1.0 - bound, None, f"{value} {unit} → fu = 1 − {bound:g} = {1.0 - bound:g}")
        if key in _UNBOUND:
            return Converted(float(value) / 100.0, None, f"{value} {unit} → fraction {float(value) / 100.0:g}")
        if key in ("%", "percent", "per cent"):
            return Converted(float(value) / 100.0, None, f"{value} % → fraction {float(value) / 100.0:g}")
        if key in _UNITLESS:
            if not 0 < float(value) <= 1:
                raise ConversionError(f"a fraction must be in (0, 1]; {value} looks like a percentage: state the unit %")
            return Converted(float(value), None, "fraction, unchanged")
        raise ConversionError(f"{unit!r} is not a fraction or a percentage")
    storage, aliases = _FAMILIES[family]
    factor = aliases.get(key)
    if factor is None:
        if target.endswith(".total_cl") and key in ("l/h", "ml/min"):
            raise ConversionError("an absolute clearance needs the body weight to become ml/min/kg")
        raise ConversionError(f"cannot convert {unit!r} to {storage} for {target}")
    converted = float(value) * factor
    how = "unchanged" if factor == 1.0 else f"{value} {unit} × {factor:g} = {converted:g} {storage}"
    return Converted(converted, storage, how)
