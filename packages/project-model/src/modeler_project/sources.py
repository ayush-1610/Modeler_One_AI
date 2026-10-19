"""Which value a model input takes when several sources give one (D-32; redesign §3.2). Values flow in without a
per-item decision (D-27): every value not excluded counts, and this module picks the one the CPF carries.

- Values that agree after conversion to the PK-Sim unit are one value with all its sources.
- Values further apart, but within the conflict fold, are settled by source: the best source wins, the others stay
  listed as alternatives for the review at signing.
- Values beyond the fold conflict, and the parameter waits until a person keeps one.

Nothing is averaged: the kept number is always one source's own. A value a person accepted outranks any value only
proposed, and a value carrying a hold flag (`source_selection.yaml`) enters only once a person accepts or corrects it.
The thresholds and the order are a provisional data rule, UNVERIFIED until the SME signs (T-30).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

import yaml

from modeler_project.evidence import EvidenceItem, EvidenceState


@dataclass(frozen=True)
class SelectionRule:
    version: str
    status: str
    agreement_relative: float
    conflict_fold: float
    source_order: tuple[str, ...]
    hold_flags: tuple[str, ...]


@lru_cache
def rule() -> SelectionRule:
    raw = yaml.safe_load(resources.files("modeler_project").joinpath("source_selection.yaml").read_text(encoding="utf-8"))
    return SelectionRule(version=str(raw["version"]), status=raw["status"], agreement_relative=float(raw["agreement_relative"]),
                         conflict_fold=float(raw["conflict_fold"]), source_order=tuple(raw["source_order"]),
                         hold_flags=tuple(raw["hold_flags"]))


def included(item: EvidenceItem) -> bool:
    """Counts unless excluded (REJECTED, always with the person's reason)."""
    return item.state is not EvidenceState.REJECTED


def held(item: EvidenceItem) -> tuple[str, ...]:
    """The flags that keep a value out until a person accepts or corrects it (none once accepted)."""
    if item.state is EvidenceState.ACCEPTED:
        return ()
    return tuple(f for f in item.flags if f.startswith(rule().hold_flags))


Relation = Literal["agrees", "differs", "conflicts"]


def _value(item: EvidenceItem) -> float | str | None:
    return item.value_pksim if isinstance(item.value, int | float) else item.value


def compare(kept: EvidenceItem, other: EvidenceItem) -> tuple[Relation, float | None]:
    """How `other` stands against `kept`: (relation, difference in % of the kept value when both are numbers)."""
    a, b = _value(kept), _value(other)
    if isinstance(a, int | float) and isinstance(b, int | float):
        if a == b:
            return "agrees", 0.0
        if a == 0:
            return "conflicts", None
        pct = abs(b - a) / abs(a) * 100
        if pct <= rule().agreement_relative * 100 + 1e-9:
            return "agrees", pct
        if a * b > 0 and max(abs(a), abs(b)) / min(abs(a), abs(b)) <= rule().conflict_fold:
            return "differs", pct
        return "conflicts", pct
    same = str(a).strip().lower() == str(b).strip().lower()
    return ("agrees" if same else "conflicts"), None


@dataclass(frozen=True)
class Alternative:
    id: str
    relation: Relation
    differs_pct: float | None


@dataclass(frozen=True)
class Selection:
    kept: str | None                                  # the evidence id the CPF carries; None while a conflict waits
    agreeing: tuple[str, ...] = ()                    # other sources that agree with the kept value
    alternatives: tuple[Alternative, ...] = field(default_factory=tuple)
    conflict: bool = False

    def to_content(self) -> dict[str, Any]:
        return {"kept": self.kept, "agreeing": list(self.agreeing), "conflict": self.conflict,
                "alternatives": [{"id": a.id, "relation": a.relation, "differs_pct": None if a.differs_pct is None
                                  else round(a.differs_pct, 1)} for a in self.alternatives],
                "rule": f"source selection {rule().version} ({rule().status})"}


def _rank(item: EvidenceItem, agree_count: int) -> tuple:
    order = rule().source_order
    source = order.index(item.source_type.value) if item.source_type.value in order else len(order)
    return (item.state is not EvidenceState.ACCEPTED, source, item.confidence, -agree_count, item.proposed_at, item.id)


def select(candidates: list[EvidenceItem]) -> Selection:
    """The value one CPF parameter takes from its candidates (all included, none held)."""
    if not candidates:
        return Selection(kept=None)
    agree_counts = {c.id: sum(compare(c, o)[0] == "agrees" for o in candidates if o.id != c.id) for c in candidates}
    ranked = sorted(candidates, key=lambda c: _rank(c, agree_counts[c.id]))
    kept, rest = ranked[0], ranked[1:]
    agreeing, alternatives, conflict = [], [], False
    for other in rest:
        relation, pct = compare(kept, other)
        if relation == "agrees":
            agreeing.append(other.id)
            continue
        alternatives.append(Alternative(id=other.id, relation=relation, differs_pct=pct))
        # a person's accepted value stands against values only proposed; two accepted values in conflict wait on a person
        if relation == "conflicts" and (kept.state is not EvidenceState.ACCEPTED or other.state is EvidenceState.ACCEPTED):
            conflict = True
    return Selection(kept=None if conflict else kept.id, agreeing=tuple(agreeing), alternatives=tuple(alternatives),
                     conflict=conflict)
