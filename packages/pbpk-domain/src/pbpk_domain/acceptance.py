"""Acceptance of predicted vs observed PK, tiered by ICH M15 model risk.

Limits come from ``rulesets/pbpk_acceptance_criteria.yaml``; see that file for the regulatory basis.
Fitting and validation studies are reported separately because only validation studies show
predictive performance; both must pass. Within a role, comparisons may carry a ``group`` (e.g. "fasted" /
"fed" for external validation, MS-01 §8), and each group is judged on its own so a good fasted fit cannot
hide a failing fed prediction. In a model system each analyte is its own group too (MS-01 v1.3 §6.5, §8): a
metabolite is judged by the same tier limits as the parent, and a good parent fit cannot hide a failing metabolite.

A MAP may set a stricter internal target, |prediction error| ≤ t % (MS-01 §8: "Stricter MAP criteria (e.g. |PE| ≤ 10 %)
are allowed for internal groups; they must never be looser than the tier"). It applies to the AUC and Cmax of the
fitting (internal) comparisons on top of the tier's limit; validation (external) comparisons are judged by the tier only.
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


def loosest_internal_target(model_risk: Rating | str, ruleset: dict[str, Any] | None = None) -> float:
    """The largest internal target |prediction error| % no looser than the tier (MS-01 §8). With f the tier's tightest
    fold limit on AUC and Cmax, a ratio within ±t % stays inside [1/f, f] only when t ≤ (1 − 1/f) × 100
    (medium, 1.5-fold: 33.3 %)."""
    tier = (ruleset or load_acceptance_ruleset())["tiers"][str(model_risk)]
    fold = min(float(rule["max_fold"]) for rule in tier["pk_parameters"].values() if "max_fold" in rule)
    return (1 - 1 / fold) * 100


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
    analyte: str = ""  # a model system's analyte, judged as its own group; "" = the single compound


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
    analyte: str = ""

    @property
    def passes(self) -> bool:
        return self.fraction_within >= self.required_fraction


@dataclass(frozen=True)
class AcceptanceReport:
    tier: str
    ruleset: str
    verdicts: list[Verdict]
    groups: list[GroupResult]
    internal_target_pe: float | None = None   # the MAP's stricter target for internal groups, when one is set

    @property
    def passes(self) -> bool:
        return bool(self.groups) and all(g.passes for g in self.groups)

    def failures(self) -> list[Verdict]:
        return [v for v in self.verdicts if not v.passes]


def _judge(comparison: Comparison, rule: dict[str, Any], target_pe: float | None = None) -> Verdict:
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
    pe = prediction_error_pct(comparison.predicted, comparison.observed)
    if target_pe is not None:
        passes = passes and abs(pe) <= target_pe * (1 + _BOUNDARY_RTOL)
        limit = f"{limit} and |PE| ≤ {target_pe:g} %"
    return Verdict(comparison, ratio, pe, limit, passes)


def evaluate(
    comparisons: Iterable[Comparison], model_risk: Rating, ruleset: dict[str, Any] | None = None, *,
    internal_target_pe: float | None = None,
) -> AcceptanceReport:
    """Judge each comparison by the tier's limit (and, for an internal AUC or Cmax, the MAP's stricter target) and each
    group by the fraction within. `ruleset` is the criteria the MAP recorded (`MapAcceptance.as_ruleset`); without
    it, the ruleset file."""
    ruleset = ruleset or load_acceptance_ruleset()
    tier = ruleset["tiers"][str(model_risk)]
    if internal_target_pe is not None:
        widest = loosest_internal_target(model_risk, ruleset)
        if not 0 < internal_target_pe <= widest + 1e-9:
            raise ValueError(f"the internal target |PE| ≤ {internal_target_pe:g} % is looser than the {model_risk} "
                             f"tier allows ({widest:.1f} %, MS-01 §8)")
    verdicts: list[Verdict] = []
    grouped: dict[tuple[Role, str, str, str], list[Verdict]] = defaultdict(list)
    for comparison in comparisons:
        section = _RULESET_SECTION.get(comparison.quantity)
        if section is None:
            raise ValueError(f"no acceptance rule for quantity {comparison.quantity!r}")
        target = internal_target_pe if comparison.role == "fitting" and section == "pk_parameters" else None
        verdict = _judge(comparison, tier[section][comparison.quantity], target)
        verdicts.append(verdict)
        grouped[(comparison.role, comparison.analyte, comparison.group, comparison.quantity)].append(verdict)

    required = float(tier["min_fraction_within"])
    groups = [
        GroupResult(role, quantity, len(items), sum(v.passes for v in items) / len(items), required, group, analyte)
        for (role, analyte, group, quantity), items in sorted(grouped.items())
    ]
    return AcceptanceReport(
        tier=str(model_risk), ruleset=f"{ruleset['id']}@{ruleset['version']}", verdicts=verdicts, groups=groups,
        internal_target_pe=internal_target_pe,
    )
