"""Derived facts (contracts §6.3, v1 `compute-1`): computed from the ledger's values, each naming its inputs.

(a) The SD of an arithmetic mean point from its spread, as `intake_rules.yaml` `landing.sd_from` lists (SE and CV%):
    from an SE with the n of that time point, else the series' n (the one `n` the ledger holds for the value's study
    and arm, named as an input too); no n: nothing is derived (D5 warns). From a CV% with the mean. The result is a
    SPREAD FACT: the same entity, field, time, statistic and conditions, `value` None, `spread` the SD, `spread_kind`
    "SD", computed by `pbpk_domain.spread` (`spread-1/sd_from_se`, `spread-1/sd_from_cv_percent`): the same functions
    D1a's profile calls, so the number a reviewer sees beside its inputs is the number the campaign gets. Nothing is
    derived for a geometric mean or a median.
(b) A `dose` written in g or µg: a `dose` in mg (`fields.MASS_UNITS`, `compute-1/dose_to_mg`).

A dose from a strength times a unit count, salt to free base and per-kg doses are not derived in this build (§11.8).
A value of no subject ("study not stated") is not derived from until a person assigns it. A value joined to its study
from another file through a link code made (a cross-file value) is not used, as the value or as a series' n, until a
person confirmed that (study, file) link (`ledger_links.link_settled`, the owner's condition 4): a derived fact carries
no `cross_file` of its own, so it must never stand where its input still waits for a reviewer. A derived fact an input
of which is no longer active, or waits for its link again, is set aside (`orphans`). A derived fact never conflicts with
its input (`ledger_view.find_conflicts`), and it is always verified with its inputs (the spot check).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from modeler_intake.fields import MASS_UNITS, known_unit
from modeler_project.intake_records import LinkConfirmation
from modeler_project.intake_rules import IntakeRules
from modeler_project.intake_rules import rules as load_rules
from modeler_project.ledger_entities import now
from modeler_project.ledger_links import latest_confirmations, link_settled
from modeler_project.ledger_models import EntityRef, Fact, ValueState
from modeler_project.ledger_view import LedgerReader, is_spread_fact, is_unassigned
from pbpk_domain import spread

COMPUTE = "compute-1"
SD_FROM_SE = f"{spread.VERSION}/sd_from_se"
SD_FROM_CV = f"{spread.VERSION}/sd_from_cv_percent"
DOSE_TO_MG = f"{COMPUTE}/dose_to_mg"
ORPHANED = "its input is no longer active"           # the reason a derived fact with an input gone is excluded
# the reason a derived fact is set aside while an input is a cross-file value whose link no person has confirmed
UNCONFIRMED = "its input waits for its cross-file link to be confirmed"
_ACTIVE = ("proposed", "confirmed")


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _series_n(values: list[ValueState]) -> dict[tuple[str | None, str | None], list[ValueState]]:
    """The `n` values the ledger holds, by (study, arm): the series' n of a mean whose point states none."""
    found: dict[tuple[str | None, str | None], list[ValueState]] = {}
    for value in values:
        number = _number(value.value)
        if value.field == "n" and value.method != "derived" and value.entity.study and number is not None \
                and number.is_integer() and number >= 1:
            found.setdefault((value.entity.study, value.entity.arm), []).append(value)
    return found


def _base(value: ValueState) -> dict[str, Any]:
    return dict(id="", delivery=value.delivery, entity=value.entity, field=value.field, conditions=dict(value.conditions),
                time=value.time, time_unit=value.time_unit, time_actual=value.time_actual, statistic=value.statistic,
                method="derived", by="code", at=now())


def _sd(value: ValueState, n_values: Mapping[tuple[str | None, str | None], list[ValueState]],
        rules: IntakeRules) -> Fact | None:
    if value.spread is None or value.spread_kind not in rules.landing.sd_from.get(value.statistic or "", ()):
        return None
    if value.spread_kind == "SE":
        n, inputs = value.n_at, (value.id,)
        if n is None:
            stated = n_values.get((value.entity.study, value.entity.arm), [])
            numbers = {int(v.value) for v in stated}                       # type checked in _series_n
            if len(numbers) != 1:
                return None
            n, inputs = numbers.pop(), (value.id, stated[0].id)
        if n < 1:
            return None
        sd = spread.sd_from_se(value.spread, n)
        if not math.isfinite(sd):                                          # an overflow: no number to store (§13)
            return None
        return Fact(**_base(value), value=None, unit=value.unit, spread=sd, spread_kind="SD", n=n, derived_from=inputs,
                    compute=SD_FROM_SE)
    if value.spread_kind == "CV%":
        mean = _number(value.value)
        if mean is None:
            return None
        sd = spread.sd_from_cv_percent(value.spread, mean)
        if not math.isfinite(sd):
            return None
        return Fact(**_base(value), value=None, unit=value.unit, spread=sd, spread_kind="SD", n=value.n_at,
                    derived_from=(value.id,), compute=SD_FROM_CV)
    return None


def _dose_mg(value: ValueState) -> Fact | None:
    number = _number(value.value)
    if value.field != "dose" or number is None or not value.unit:
        return None
    unit = known_unit("dose", value.unit)
    if unit is None or unit == "mg" or unit not in MASS_UNITS:
        return None
    mg = round(number * MASS_UNITS[unit], 9)
    if not math.isfinite(mg):
        return None
    return Fact(**_base(value), value=mg, unit="mg", derived_from=(value.id,), compute=DOSE_TO_MG)


def _slot(compute: str | None, entity: EntityRef, field: str, time: float | None, statistic: str | None,
          conditions: Mapping[str, str]) -> tuple[Any, ...]:
    return (compute, entity.model_dump_json(), field, time, statistic, tuple(sorted(conditions.items())))


def _same(old: ValueState, new: Fact) -> bool:
    return (old.entity == new.entity and old.value == new.value and old.unit == new.unit and old.spread == new.spread
            and old.spread_kind == new.spread_kind and old.n_at == new.n and old.time == new.time
            and old.time_unit == new.time_unit and old.statistic == new.statistic and old.conditions == new.conditions)


def derivations(reader: LedgerReader, *, rules: IntakeRules | None = None,
                confirmations: Sequence[LinkConfirmation] = ()) -> list[Fact]:
    """The derived facts to add (id ""): each with `derived_from` and `compute`, no anchor. One the ledger holds
    already, the same, is not given again (derive twice adds nothing); one whose content changed (its input's entity
    after an assignment) supersedes the earlier one; one that takes the place of a derived fact whose input is no
    longer active (an input superseded by a re-read or a correction) supersedes it. A cross-file value whose link no
    person has confirmed (`confirmations`: review.jsonl's `link` lines) is used neither as an input nor as a series' n."""
    rules = rules or load_rules()
    latest = latest_confirmations(reader, confirmations)
    values = [v for v in reader.values() if link_settled(v, latest)]
    active = {v.id for v in values}
    derived = [v for v in values if v.method == "derived"]
    existing = {(v.compute, v.derived_from): v for v in derived}
    stale = {_slot(v.compute, v.entity, v.field, v.time, v.statistic, v.conditions): v for v in derived
             if any(i not in active for i in v.derived_from)}
    n_values = _series_n(values)
    out: list[Fact] = []
    for value in values:
        if value.method == "derived" or is_spread_fact(value) or is_unassigned(value.entity, value.field):
            continue
        for made in (_sd(value, n_values, rules), _dose_mg(value)):
            if made is None:
                continue
            old = existing.get((made.compute, made.derived_from))
            if old is not None and _same(old, made):
                continue
            replaced = old or stale.get(_slot(made.compute, made.entity, made.field, made.time, made.statistic,
                                              made.conditions))
            out.append(made.model_copy(update={"supersedes": replaced.id if replaced is not None else None}))
    return out


def orphans(reader: LedgerReader, confirmations: Sequence[LinkConfirmation] = ()) -> list[tuple[str, str]]:
    """The active derived facts an input of which is no longer active (superseded or excluded), or is a cross-file
    value whose link no person has confirmed (`confirmations`), with the reason they are excluded when no successor
    supersedes them."""
    latest = latest_confirmations(reader, confirmations)
    out = []
    for value in reader.values():
        if value.method != "derived":
            continue
        inputs = {i: reader.value(i) for i in value.derived_from}
        gone = [i for i, found in inputs.items() if found is None or found.status not in _ACTIVE]
        waiting = [i for i, found in inputs.items() if i not in gone and found is not None
                   and not link_settled(found, latest)]
        if gone:
            out.append((value.id, f"{ORPHANED}: {', '.join(gone)}"))
        elif waiting:
            out.append((value.id, f"{UNCONFIRMED}: {', '.join(waiting)}"))
    return out
