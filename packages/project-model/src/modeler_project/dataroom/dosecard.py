"""The dose in both bases, salt and free base (plan 2026-11-26 §7 phase 3; the corpus audit's R14: "when the MW basis
changes, recompute the molar dose automatically and record both bases"; P01's model was given a salt dose against the
base's molecular weight, +46 % molar dose).

PK-Sim models the molecule, so the compound's molecular weight is the free base's and the dose it is given must be the
base's too. From the delivery's quoted facts, code reads:

- the dose as written (`study.dose`, else the first `product.strength`) and its basis: the `substance.dose_basis` fact,
  else the dose's own words ("equivalent to 90 mg <base>", "as the free base" → base; "100 mg hydrochloride" → salt);
- each molecular weight (`substance.mw`), the salt's or the base's by its own words (a salt's name, "free base");
- the salt form (`substance.salt`).

When the dose is the salt's and both molecular weights are known, the base dose is dose × MW(base) / MW(salt), and
the molar dose dose(base) / MW(base). What is not known is said, never assumed: a salt form with no stated basis, a
salt dose with a molecular weight missing, a "salt" lighter than its base.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from modeler_project.dataroom.model import CheckedFact, Chip, DoseCard, Problem

_SALT = re.compile(r"\bsalt\b|hydrochloride|\bHCl\b|mesylate|mesilate|besylate|besilate|maleate|fumarate|tartrate|citrate|"
                   r"succinate|sulfate|sulphate|phosphate|acetate|tosylate|hydrobromide|bromide|chloride|\bsodium\b|"
                   r"potassium|calcium|magnesium|meglumine|tromethamine|hydrate", re.IGNORECASE)
_BASE = re.compile(r"\bfree\s+(?:base|acid|form)\b|\bas\s+(?:the\s+)?base\b|\bbase\b|equivalent\s+to|\bequiv\.?\b",
                   re.IGNORECASE)


def _form(f: CheckedFact) -> str:
    """A molecular weight's form, 'base', 'salt' or '', by what the fact is about (its value, subject and note; not its
    quote, which often names both forms: "the hydrochloride (393.9) … the free base (357.4)")."""
    words = f"{f.fact.value} {f.fact.subject} {f.fact.note}"
    if re.search(r"(?i)free\s+(?:base|acid)|\bbase\b", words):
        return "base"
    return "salt" if _SALT.search(words) else ""


def _basis(f: CheckedFact) -> str:
    """'base', 'salt' or '' from a fact's own words (the base's words win: "the hydrochloride, equivalent to 90 mg
    base" is a base dose)."""
    words = f"{f.fact.value} {f.fact.note} {f.fact.quote}"
    if _BASE.search(words):
        return "base"
    if _SALT.search(words):
        return "salt"
    return ""


def _chips(*facts: CheckedFact | None) -> tuple[Chip, ...]:
    return tuple(f.chip for f in facts if f is not None and f.chip)


def dose_card(facts: Sequence[CheckedFact]) -> tuple[DoseCard | None, list[Problem]]:
    """The dose in both bases and the problems; None when the delivery states no dose."""
    ok = [f for f in facts if f.ok]
    dose = next((f for f in ok if f.fact.field == "study.dose" and f.number), None) or next(
        (f for f in ok if f.fact.field == "product.strength" and f.number), None)
    if dose is None:
        return None, []
    stated = next((f for f in ok if f.fact.field == "substance.dose_basis"), None)
    salt = next((f for f in ok if f.fact.field == "substance.salt" and _SALT.search(f.fact.value)
                 and not _BASE.search(f.fact.value)), None)
    basis = (_basis(stated) if stated else "") or _basis(dose)
    mws = [f for f in ok if f.fact.field == "substance.mw" and f.number]
    mw_salt = next((f for f in mws if _form(f) == "salt"), None)
    # the base's: one said to be, else one said to be neither (a compound's molecular weight is the molecule's)
    mw_base = next((f for f in mws if _form(f) == "base"), None) or next((f for f in mws if not _form(f)), None)
    problems: list[Problem] = []
    written = f"{dose.fact.value} {dose.fact.unit}".strip()
    mg = dose.number
    as_base = as_salt = None
    factor = None
    rule = ""
    if mw_base and mw_salt:
        if mw_salt.number <= mw_base.number:  # type: ignore[operator]
            problems.append(Problem(code="SALT_MW_NOT_HEAVIER", severity="error", where=mw_salt.chip, message=(
                f"the salt's molecular weight ({mw_salt.fact.value}) is not above the base's ({mw_base.fact.value}): "
                "the two are swapped, or one is of another form; the dose is not converted")))
        else:
            factor = mw_base.number / mw_salt.number  # type: ignore[operator]
    if basis == "salt":
        as_salt = mg
        if factor:
            as_base = round(mg * factor, 4)  # type: ignore[operator]
            rule = (f"{written} of the salt × MW(base) {mw_base.number:g} / MW(salt) {mw_salt.number:g} "  # type: ignore[union-attr]
                    f"= {as_base:g} mg of the free base")
        else:
            problems.append(Problem(code="DOSE_BASIS_NEEDS_MW", where=dose.chip, message=(
                f"the dose {written} is the salt's, but the {'base' if not mw_base else 'salt'}'s molecular weight is "
                "not given: PK-Sim's dose must be the free base's (dose × MW base / MW salt); ask for both molecular "
                "weights")))
    elif basis == "base":
        as_base = mg
        if factor:
            as_salt = round(mg / factor, 4)  # type: ignore[operator]
            rule = f"{written} of the free base; as the salt × MW(salt) / MW(base) = {as_salt:g} mg"
    elif salt is not None:
        problems.append(Problem(code="DOSE_BASIS_UNKNOWN", where=dose.chip, message=(
            f"the drug is given as a salt ({salt.fact.value}), but nothing says whether the dose {written} is the salt's "
            "or the free base's: PK-Sim's dose must be the base's; ask which")))
    elif mw_salt is None:
        # no salt form is stated anywhere: the dose is the molecule's own
        as_base = mg
        rule = f"no salt form is stated: {written} is the molecule's dose"
    molar = round(as_base / mw_base.number * 1000.0, 4) if as_base is not None and mw_base and mw_base.number else None
    return DoseCard(
        dose_written=written, basis=basis or "unknown", salt=salt.fact.value if salt else "",  # type: ignore[arg-type]
        mw_base=mw_base.number if mw_base else None, mw_salt=mw_salt.number if mw_salt else None,
        dose_as_base_mg=as_base, dose_as_salt_mg=as_salt, molar_dose_umol=molar, rule=rule,
        sources=_chips(dose, stated, salt, mw_base, mw_salt)), problems


__all__ = ["dose_card"]
