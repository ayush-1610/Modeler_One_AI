"""MS-01's action for a non-identifiable pair (§5; diag-rules `non_identifiable_pair`, PI-2b; UNVERIFIED for the SME).

Two fitted parameters correlated beyond |r| > 0.95 cannot be told apart by the data. MS-01 says: "fix the one with the
more reliable source; refit". The owner's rule of 2026-10-25 makes that concrete:
- the parameter with the more reliable source is fixed at its source value as the signed MAP recorded it, and the
  others of the fit are refitted;
- more reliable is the higher evidence grade (A best, D worst), and a measured value (status FIXED) beats a predicted
  one (PREDICTED);
- grade is compared when both parameters have one, status when both are measured or predicted (FITTED and DERIVED
  are not ranked). Where the two point at different parameters, the grade decides (the owner, 2026-10-27);
- where neither decides, nothing is guessed and the round escalates to the modeller: an equal grade and status, or a
  pair neither comparison ranks.

Both facts come from the signed MAP's parameter table (`MapParameter.grade`, `.status`), so the choice is the one the
signature covers, not the campaign CPF's current state (which says FITTED once a value has been fitted).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pbpk_domain.campaign.map import MapParameter
from pbpk_domain.cpf import CPF, ParameterStatus, Provenance

GRADES = ("A", "B", "C", "D")                    # the evidence register's confidence grades, best first
STATUS_RANK = {"FIXED": 0, "PREDICTED": 1}       # measured beats predicted; FITTED and DERIVED are not ranked
_STATUS_WORD = {"FIXED": "measured", "PREDICTED": "predicted"}


@dataclass(frozen=True)
class FixChoice:
    """The parameter to fix at its signed source value, and its partner, refitted."""
    fixed: str
    refit: str
    value: float
    unit: str | None
    status: str
    source: str | None
    reason: str


def describe(parameter: MapParameter) -> str:
    """How the signed MAP rates a parameter's source, for the notes: its grade and whether it is measured."""
    grade = f"grade {parameter.grade}" if parameter.grade in GRADES else "no grade"
    return f"{grade}, {_STATUS_WORD.get(parameter.status, parameter.status.lower())}"


def _better(rank_a: int | None, rank_b: int | None) -> str | None:
    """'a' or 'b' when both are ranked and one is better (lower), else None."""
    if rank_a is None or rank_b is None or rank_a == rank_b:
        return None
    return "a" if rank_a < rank_b else "b"


def choose_fixed(a: str, b: str, parameters: Mapping[str, MapParameter]) -> FixChoice | str:
    """Which of the pair to fix (the more reliable source) and which to refit; a str says why the rule cannot decide."""
    pa, pb = parameters.get(a), parameters.get(b)
    missing = [pid for pid, p in ((a, pa), (b, pb)) if p is None]
    if missing:
        return f"{' and '.join(missing)} not in the signed MAP's parameter table, so there is no signed source to compare"
    rated = f"{a} ({describe(pa)}), {b} ({describe(pb)})"
    by_grade = _better(GRADES.index(pa.grade) if pa.grade in GRADES else None,
                       GRADES.index(pb.grade) if pb.grade in GRADES else None)
    by_status = _better(STATUS_RANK.get(pa.status), STATUS_RANK.get(pb.status))
    winner = by_grade or by_status  # the grade decides where the two disagree
    if winner is None:
        return f"neither source is more reliable: {rated}"
    fixed, refit = (pa, pb) if winner == "a" else (pb, pa)
    if not isinstance(fixed.value, int | float) or isinstance(fixed.value, bool):
        return f"{fixed.id} has no numeric source value in the signed MAP"
    basis = ("a higher grade" + (", which decides over its predicted status" if by_status and by_status != by_grade else "")
             if by_grade else "measured, not predicted")
    return FixChoice(fixed=fixed.id, refit=refit.id, value=float(fixed.value), unit=fixed.unit, status=fixed.status,
                     source=fixed.source,
                     reason=f"{fixed.id} has the more reliable source ({basis}: {rated})")


def fix_at_source(cpf: CPF, choice: FixChoice, *, note: str) -> CPF:
    """A new CPF version with the chosen parameter back at its signed source value and status (no fit, no CI). Its fit
    policy is kept: the caller leaves it out of the stage's later fits."""
    record = cpf.get(choice.fixed)
    if record is None:
        raise ValueError(f"cannot fix {choice.fixed!r}: the CPF for {cpf.compound} has no such parameter")
    if (record.unit or None) != (choice.unit or None):
        raise ValueError(f"cannot fix {choice.fixed!r}: the signed MAP records it in {choice.unit!r}, the CPF in {record.unit!r}")
    fixed = record.model_copy(update={
        "value": choice.value, "status": ParameterStatus(choice.status), "fitted_at_stage": None, "uncertainty": None,
        "provenance": Provenance(source_type=choice.source or "Unknown", reference=note,
                                 supersedes=f"{cpf.compound}@{cpf.version}:{choice.fixed}"),
    })
    return cpf.replace(fixed, note=note)
