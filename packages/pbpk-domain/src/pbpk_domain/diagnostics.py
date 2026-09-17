"""Deterministic diagnostics: round evidence -> cause -> ordered permitted actions (MS-01 §5, task T-14).

The rules and thresholds live in ``rulesets/diag_rules.yaml`` (versioned, UNVERIFIED until an SME approves
them). `compute_evidence` turns a round's PK residuals and fit signals into the named evidence labels the
rules key on; `diagnose` fires every rule whose evidence is present, escalates when an escalate-type rule
fires (a fitted parameter at its bound, time-dependent clearance, a gastric-emptying/meal question), and
otherwise returns the fired fit rules' actions — ordered, restricted to the stage's permitted candidates and
branches, and with actions already tried removed. It never invents an action outside the ruleset; the
strategist agent (T-15) only chooses among what this returns.

Actions are strings ``"{op} {target}"`` where op is fit / branch / switch / fix_and_refit / switch_algorithm
and target is the same token the MAP stage plan uses (e.g. ``elim.hepatic.{enzyme}.clspec``); the enzyme/name
placeholder is resolved when the action is applied.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml


@dataclass(frozen=True)
class StudyResidual:
    """One study's predicted/observed PK ratios and profile-shape signals for the round's stage."""
    study_id: str
    role: str = "fitting"                 # "fitting" (INTERNAL) | "validation" (EXTERNAL)
    route: str = "oral"                   # "iv" | "oral"
    dose_mg: float | None = None
    auc_ratio: float | None = None        # predicted / observed AUC
    cmax_ratio: float | None = None
    tmax_ratio: float | None = None
    thalf_ratio: float | None = None      # predicted / observed terminal t1/2
    observed_auc: float | None = None     # for the dose-normalized AUC trend
    auc_in_limits: bool | None = None
    # profile-shape signals from a residual analysis (optional; default off until that analysis is wired):
    early_phase_off: bool = False         # early concentrations (< 2x tmax,IV) off
    vss_off: bool = False
    permeability_shape_off: bool = False  # first distribution-phase shape off
    secondary_peak: bool = False          # secondary peak(s) after absorption in the observed profile
    accumulation_off: bool = False        # MD accumulation ratio off with the single dose fine


@dataclass(frozen=True)
class FitSignals:
    """Optimiser evidence from the round's fit (present once fitting is wired)."""
    at_bound: tuple[str, ...] = ()
    correlated_pairs: tuple[tuple[str, str], ...] = ()
    starts_agreement: float | None = None


@dataclass(frozen=True)
class FedSignals:
    """Fed-vs-fasted comparison for S3 (round-level)."""
    auc_ratio_off: bool = False
    cmax_consistent: bool = False
    tmax_off: bool = False


_NO_FIT = FitSignals()   # immutable default (frozen); avoids a call in argument defaults
_NO_FED = FedSignals()


@dataclass(frozen=True)
class Evidence:
    labels: frozenset[str]
    extras: dict[str, Any] = field(default_factory=dict)  # at_bound param, correlated pair, dose trend, ...


@dataclass(frozen=True)
class Diagnosis:
    evidence: tuple[str, ...]
    causes: tuple[str, ...]
    permitted_actions: tuple[str, ...]
    escalate: bool
    reason: str | None = None


@lru_cache(maxsize=1)
def load_diag_ruleset() -> dict[str, Any]:
    text = resources.files("pbpk_domain.rulesets").joinpath("diag_rules.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def diag_ruleset_version() -> str:
    r = load_diag_ruleset()
    return f"{r['id']}@{r['version']}-{r['status']}"


def _fitting(residuals: Sequence[StudyResidual]) -> list[StudyResidual]:
    fits = [r for r in residuals if r.role == "fitting"]
    return fits or list(residuals)


def _dose_trend(residuals: Sequence[StudyResidual], rel: float) -> str | None:
    """'increasing' / 'decreasing' / 'flat' in observed dose-normalized AUC across the dose range, or None."""
    by_dose: dict[float, float] = {}
    for r in residuals:
        if r.dose_mg and r.dose_mg > 0 and r.observed_auc is not None and r.observed_auc > 0:
            by_dose[r.dose_mg] = r.observed_auc / r.dose_mg
    if len(by_dose) < 2:
        return None
    ordered = [by_dose[d] for d in sorted(by_dose)]
    change = (ordered[-1] - ordered[0]) / ordered[0]
    if change > rel:
        return "increasing"
    if change < -rel:
        return "decreasing"
    return "flat"


def compute_evidence(
    residuals: Sequence[StudyResidual],
    *,
    fit: FitSignals = _NO_FIT,
    fed: FedSignals = _NO_FED,
    ruleset: dict[str, Any] | None = None,
) -> Evidence:
    """Compute the evidence labels present this round from the PK residuals and fit signals."""
    th = (ruleset or load_diag_ruleset())["thresholds"]
    hi, lo = float(th["ratio_high"]), float(th["ratio_low"])
    fits = _fitting(residuals)
    labels: set[str] = set()
    extras: dict[str, Any] = {}

    def any_fit(pred) -> bool:
        return any(pred(r) for r in fits)

    # Clearance: terminal t1/2 ratio out of band with AUC off in the same direction.
    if any_fit(lambda r: r.thalf_ratio is not None and r.auc_ratio is not None and r.thalf_ratio > hi and r.auc_ratio > hi):
        labels.add("clearance_off")
    if any_fit(lambda r: r.thalf_ratio is not None and r.auc_ratio is not None and r.thalf_ratio < lo and r.auc_ratio < lo):
        labels.add("clearance_off")

    # Distribution (IV): AUC in limits, early concentrations off, Vss off.
    if any_fit(lambda r: r.route == "iv" and r.auc_in_limits and r.early_phase_off and r.vss_off):
        labels.add("distribution_off")
    # Permeability-limited (IV): distribution-phase shape off with Vss fine.
    if any_fit(lambda r: r.route == "iv" and r.permeability_shape_off and not r.vss_off):
        labels.add("permeability_limited")

    # Oral absorption rate from the Cmax/tmax pattern.
    if any_fit(lambda r: r.route == "oral" and r.cmax_ratio is not None and r.tmax_ratio is not None and r.cmax_ratio > hi and r.tmax_ratio < lo):
        labels.add("absorption_fast")
    if any_fit(lambda r: r.route == "oral" and r.cmax_ratio is not None and r.tmax_ratio is not None and r.cmax_ratio < lo and r.tmax_ratio > hi and r.auc_in_limits):
        labels.add("absorption_slow")

    # Dose-dependence of exposure (observed dose-normalized AUC across the dose range).
    trend = _dose_trend([r for r in fits if r.route == "oral"], float(th["dose_norm_auc_rel"]))
    if trend:
        extras["dose_trend"] = trend
    if trend == "increasing":
        labels.add("dose_norm_auc_increasing")
    auc_low = any_fit(lambda r: r.route == "oral" and r.auc_ratio is not None and r.auc_ratio < lo)
    if auc_low and trend == "decreasing":
        labels.add("auc_low_dose_dependent")
    elif auc_low and trend != "increasing":
        labels.add("auc_low_dose_independent")

    if any_fit(lambda r: r.route == "oral" and r.secondary_peak):
        labels.add("secondary_peak")
    if any_fit(lambda r: r.accumulation_off):
        labels.add("accumulation_off")

    # Fed state (S3, round-level).
    if fed.auc_ratio_off and fed.cmax_consistent:
        labels.add("fed_solubility")
    if fed.tmax_off:
        labels.add("fed_tmax_off")

    # Optimiser signals.
    if fit.at_bound:
        labels.add("param_at_bound")
        extras["at_bound"] = list(fit.at_bound)
    if fit.correlated_pairs:
        labels.add("correlated_pair")
        extras["correlated_pair"] = list(fit.correlated_pairs[0])
    if fit.starts_agreement is not None and fit.starts_agreement < float(th["starts_agreement_min"]):
        labels.add("starts_disagree")

    return Evidence(labels=frozenset(labels), extras=extras)


def _action_string(action: dict[str, str], extras: dict[str, Any]) -> str | None:
    op, target = action["op"], action["target"]
    if op == "fix_and_refit":
        pair = extras.get("correlated_pair")
        return f"fix_and_refit {pair[0]}|{pair[1]}" if pair else None
    return f"{op} {target}"


def _action_valid(action: dict[str, str], stage_candidates: set[str], stage_branches: set[str]) -> bool:
    op, target = action["op"], action["target"]
    if op == "fit":
        return target in stage_candidates
    if op == "branch":
        return target in stage_branches
    if op == "switch":  # switch dominant enzyme to Michaelis-Menten: permitted when Km/Vmax are candidates
        root = target.rsplit(".", 1)[0]
        return f"{root}.km" in stage_candidates or f"{root}.vmax" in stage_candidates
    return op in ("fix_and_refit", "switch_algorithm")


def diagnose(
    residuals: Sequence[StudyResidual],
    *,
    stage: str,
    stage_candidates: Sequence[str] = (),
    stage_branches: Sequence[str] = (),
    actions_tried: Sequence[str] = (),
    fit: FitSignals = _NO_FIT,
    fed: FedSignals = _NO_FED,
    ruleset: dict[str, Any] | None = None,
) -> Diagnosis:
    """Map the round's evidence to permitted actions for this stage (MS-01 §5)."""
    ruleset = ruleset or load_diag_ruleset()
    ev = compute_evidence(residuals, fit=fit, fed=fed, ruleset=ruleset)
    candidates, branches, tried = set(stage_candidates), set(stage_branches), set(actions_tried)

    fired = [rule for rule in ruleset["rules"] if stage in rule["stages"] and rule["evidence"] in ev.labels]
    evidence_labels = tuple(sorted(ev.labels))

    escalations = [r for r in fired if r["type"] == "escalate"]
    if escalations:
        rule = escalations[0]
        reason = rule["cause"]
        if rule["evidence"] == "param_at_bound" and ev.extras.get("at_bound"):
            reason = f"{rule['cause']}: {', '.join(ev.extras['at_bound'])}"
        return Diagnosis(
            evidence=evidence_labels, causes=(rule["cause"],), permitted_actions=(), escalate=True, reason=reason
        )

    permitted: list[str] = []
    for rule in fired:
        for action in rule["actions"]:
            text = _action_string(action, ev.extras)
            if text is None or not _action_valid(action, candidates, branches) or text in tried or text in permitted:
                continue
            permitted.append(text)

    if permitted:
        return Diagnosis(
            evidence=evidence_labels, causes=tuple(r["cause"] for r in fired),
            permitted_actions=tuple(permitted), escalate=False,
        )

    reason = (
        "all permitted actions for the matched diagnosis have already been tried"
        if fired else "no diagnostic rule matched the round's evidence"
    )
    return Diagnosis(
        evidence=evidence_labels, causes=tuple(r["cause"] for r in fired),
        permitted_actions=(), escalate=True, reason=reason,
    )
