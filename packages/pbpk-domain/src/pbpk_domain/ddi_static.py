"""Static DDI screening models used to triage mechanisms before dynamic PBPK (F-301 step 1).

Formulas are generic; cut-offs and concentration multipliers live in a versioned ruleset. Screening
refuses to run on a ruleset that clinical pharmacology has not approved against the adopted ICH M12
text, unless the caller explicitly opts into exploratory use.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml

GUT_VOLUME_L = 0.25


class RulesetNotApprovedError(RuntimeError):
    pass


def r1_reversible(imax_u_um: float, ki_u_um: float) -> float:
    return 1 + imax_u_um / ki_u_um


def gut_inhibitor_concentration_um(dose_mg: float, molecular_weight_g_per_mol: float, volume_l: float = GUT_VOLUME_L) -> float:
    """Dose dissolved in the gut volume, in µM (mg / (g/mol) = mmol)."""
    return dose_mg / molecular_weight_g_per_mol * 1000 / volume_l


def r1_gut(i_gut_um: float, ki_u_um: float) -> float:
    return 1 + i_gut_um / ki_u_um


def r2_time_dependent(
    imax_u_um: float, ki_inact_u_um: float, kinact_per_h: float, kdeg_per_h: float, multiplier: float
) -> float:
    concentration = multiplier * imax_u_um
    kobs = kinact_per_h * concentration / (ki_inact_u_um + concentration)
    return (kobs + kdeg_per_h) / kdeg_per_h


def r3_induction(imax_u_um: float, ec50_u_um: float, emax: float, multiplier: float, d: float = 1.0) -> float:
    concentration = multiplier * imax_u_um
    return 1 / (1 + d * emax * concentration / (ec50_u_um + concentration))


def aucr_mechanistic_static(fm: float, inhibitor_u_um: float, ki_u_um: float) -> float:
    """Victim AUC ratio for competitive inhibition of one pathway with fraction metabolized fm."""
    if not 0 <= fm <= 1:
        raise ValueError("fm must be in [0, 1]")
    return 1 / (fm / (1 + inhibitor_u_um / ki_u_um) + (1 - fm))


@dataclass(frozen=True)
class PerpetratorInVitro:
    imax_u_um: float
    dose_mg: float | None = None
    molecular_weight_g_per_mol: float | None = None
    ki_u_um: float | None = None
    ki_inact_u_um: float | None = None
    kinact_per_h: float | None = None
    kdeg_per_h: float | None = None
    ec50_u_um: float | None = None
    emax: float | None = None


@dataclass(frozen=True)
class ScreenResult:
    model: str
    value: float
    cutoff: float
    flagged: bool
    ruleset: str


def load_ruleset(name: str = "ddi_static_screening") -> dict[str, Any]:
    text = resources.files("pbpk_domain.rulesets").joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _flag(value: float, rule: dict[str, Any]) -> bool:
    if rule["flag_when"] == ">=":
        return value >= rule["cutoff"]
    if rule["flag_when"] == "<=":
        return value <= rule["cutoff"]
    raise ValueError(f"unknown comparison {rule['flag_when']!r}")


def screen(inputs: PerpetratorInVitro, ruleset: dict[str, Any], *, allow_unapproved: bool = False) -> list[ScreenResult]:
    if ruleset.get("status") != "SME_APPROVED" and not allow_unapproved:
        raise RulesetNotApprovedError(
            f"ruleset {ruleset.get('id')}@{ruleset.get('version')} has status {ruleset.get('status')!r}; "
            "approve it or pass allow_unapproved=True for exploratory use"
        )
    tag = f"{ruleset['id']}@{ruleset['version']}"
    models = ruleset["models"]
    results: list[ScreenResult] = []

    def add(model: str, value: float) -> None:
        rule = models[model]
        results.append(ScreenResult(model, value, rule["cutoff"], _flag(value, rule), tag))

    if inputs.ki_u_um is not None:
        add("reversible_inhibition", r1_reversible(inputs.imax_u_um, inputs.ki_u_um))
        if inputs.dose_mg is not None and inputs.molecular_weight_g_per_mol is not None:
            rule = models["reversible_inhibition_gut"]
            i_gut = gut_inhibitor_concentration_um(inputs.dose_mg, inputs.molecular_weight_g_per_mol, rule["gut_volume_l"])
            add("reversible_inhibition_gut", r1_gut(i_gut, inputs.ki_u_um))
    if None not in (inputs.ki_inact_u_um, inputs.kinact_per_h, inputs.kdeg_per_h):
        rule = models["time_dependent_inhibition"]
        add(
            "time_dependent_inhibition",
            r2_time_dependent(inputs.imax_u_um, inputs.ki_inact_u_um, inputs.kinact_per_h, inputs.kdeg_per_h, rule["imax_multiplier"]),
        )
    if inputs.ec50_u_um is not None and inputs.emax is not None:
        rule = models["induction"]
        add("induction", r3_induction(inputs.imax_u_um, inputs.ec50_u_um, inputs.emax, rule["imax_multiplier"], rule["d"]))
    return results
