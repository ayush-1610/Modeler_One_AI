"""Acceptance of predicted vs observed PK, tiered by ICH M15 model risk.

Limits come from ``rulesets/pbpk_acceptance_criteria.yaml``; see that file for the regulatory basis.
Fitting and validation studies are reported separately because only validation studies show
predictive performance; both must pass. Within a role, comparisons may carry a ``group`` (e.g. "fasted" /
"fed" for external validation, MS-01 §8), and each group is judged on its own so a good fasted fit cannot
hide a failing fed prediction.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal

import yaml

from pbpk_domain.m15 import Rating
from pbpk_domain.metrics import within_guest_limits

Role = Literal["fitting", "validation"]
_RULESET_SECTION = {"AUC": "pk_parameters", "Cmax": "pk_parameters", "AUCR": "ddi_ratios", "CmaxR": "ddi_ratios"}
_BOUNDARY_RTOL = 1e-12


def load_acceptance_ruleset() -> dict[str, Any]:
    text = resources.files("pbpk_domain.rulesets").joinpath("pbpk_acceptance_criteria.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def prediction_error_pct(predicted: float, observed: float) -> float:
    if observed <= 0:
        raise ValueError("observed value must be > 0")
    return (predicted - observed) / observed * 100


@dataclass(frozen=True)
class Comparison:
    study: str
    quantity: str  # AUC, Cmax, AUCR, CmaxR
    predicted: float
    observed: float
    role: Role
    group: str = ""  # sub-group judged separately within the role, e.g. "fasted" / "fed"; "" = the whole role


@dataclass(frozen=True)
class Verdict:
    comparison: Comparison
    ratio: float
    prediction_error_pct: float
    limit: str
    passes: bool


@dataclass(frozen=True)
class GroupResult:
    role: Role
    quantity: str
    n: int
    fraction_within: float
    required_fraction: float
    group: str = ""

    @property
    def passes(self) -> bool:
        return self.fraction_within >= self.required_fraction


@dataclass(frozen=True)
class AcceptanceReport:
    tier: str
    ruleset: str
    verdicts: list[Verdict]
    groups: list[GroupResult]

    @property
    def passes(self) -> bool:
        return bool(self.groups) and all(g.passes for g in self.groups)

    def failures(self) -> list[Verdict]:
        return [v for v in self.verdicts if not v.passes]


def _judge(comparison: Comparison, rule: dict[str, Any]) -> Verdict:
    if comparison.predicted <= 0 or comparison.observed <= 0:
        raise ValueError(f"{comparison.study} {comparison.quantity}: values must be > 0")
    ratio = comparison.predicted / comparison.observed
    if "guest_delta" in rule:
        delta = float(rule["guest_delta"])
        passes = within_guest_limits(comparison.predicted, comparison.observed, delta)
        limit = f"Guest limits (delta={delta:g})"
    else:
        fold = float(rule["max_fold"])
        passes = (1 / fold) * (1 - _BOUNDARY_RTOL) <= ratio <= fold * (1 + _BOUNDARY_RTOL)
        limit = f"{1 / fold:.2f}-{fold:g}-fold"
    return Verdict(comparison, ratio, prediction_error_pct(comparison.predicted, comparison.observed), limit, passes)


def evaluate(
    comparisons: Iterable[Comparison], model_risk: Rating, ruleset: dict[str, Any] | None = None
) -> AcceptanceReport:
    ruleset = ruleset or load_acceptance_ruleset()
    tier = ruleset["tiers"][str(model_risk)]
    verdicts: list[Verdict] = []
    grouped: dict[tuple[Role, str, str], list[Verdict]] = defaultdict(list)
    for comparison in comparisons:
        section = _RULESET_SECTION.get(comparison.quantity)
        if section is None:
            raise ValueError(f"no acceptance rule for quantity {comparison.quantity!r}")
        verdict = _judge(comparison, tier[section][comparison.quantity])
        verdicts.append(verdict)
        grouped[(comparison.role, comparison.group, comparison.quantity)].append(verdict)

    required = float(tier["min_fraction_within"])
    groups = [
        GroupResult(role, quantity, len(items), sum(v.passes for v in items) / len(items), required, group)
        for (role, group, quantity), items in sorted(grouped.items())
    ]
    return AcceptanceReport(
        tier=str(model_risk), ruleset=f"{ruleset['id']}@{ruleset['version']}", verdicts=verdicts, groups=groups
    )
