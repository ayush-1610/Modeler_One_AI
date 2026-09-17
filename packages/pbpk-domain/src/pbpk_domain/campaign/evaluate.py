"""Judge a round's simulated profiles against observed PK, at the MAP's acceptance tier (task T-13 wiring).

`evaluate_round` (the Temporal activity) is a thin adapter over `assess_round` here. Given each simulated
study profile (concentration-time) and the observed PK for that study, this reduces the simulation to PK by
non-compartmental analysis (`pbpk_domain.nca`, T-18), compares predicted vs observed AUC and Cmax
(`pbpk_domain.acceptance`, tiered by ICH M15 model risk), and reports whether the tier gate passes plus the
fold-error metrics. Fitting and validation studies are judged in the same call but grouped separately by the
acceptance ruleset, because only validation studies show predictive performance.

Predicted and observed AUC/Cmax must be in the same units and the AUC of the same kind: predicted AUC is the
trapezoidal AUC to the last simulated time (matching the engine's ``AUC_tEnd``); pass ``auc_kind="inf"`` to
compare against an extrapolated observed AUC instead. Nothing here runs the engine or invents an observed
value; a study with no observed PK simply contributes no comparison.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pbpk_domain.acceptance import AcceptanceReport, Comparison, Role, evaluate
from pbpk_domain.m15 import Rating
from pbpk_domain.metrics import fraction_within_fold, gmfe
from pbpk_domain.nca import nca

AucKind = Literal["last", "inf"]


@dataclass(frozen=True)
class SimulatedProfile:
    study_id: str
    role: Role                      # "fitting" (INTERNAL) | "validation" (EXTERNAL)
    times: Sequence[float]
    concentrations: Sequence[float]


@dataclass(frozen=True)
class ObservedPK:
    """Observed PK for one study, in the same units and AUC kind as the predicted profile.

    ``tmax`` and ``thalf`` are optional and feed the diagnostics ruleset (T-14); they take no part in the
    acceptance gate, which compares AUC and Cmax only."""
    auc: float | None = None
    cmax: float | None = None
    tmax: float | None = None
    thalf: float | None = None


@dataclass(frozen=True)
class StudyPK:
    study_id: str
    role: Role
    predicted_auc: float | None
    predicted_cmax: float
    predicted_tmax: float
    predicted_thalf: float | None
    observed_auc: float | None
    observed_cmax: float | None
    observed_tmax: float | None
    observed_thalf: float | None


@dataclass(frozen=True)
class RoundAssessment:
    gate_passed: bool
    report: AcceptanceReport | None       # None when there was no observed PK to compare against
    studies: tuple[StudyPK, ...]
    findings: tuple[str, ...]
    metrics: dict[str, Any]


def _predicted_auc(result, auc_kind: AucKind) -> float | None:
    return result.auc_inf if auc_kind == "inf" else result.auc_last


def assess_round(
    simulated: Sequence[SimulatedProfile],
    observed: Mapping[str, ObservedPK],
    *,
    model_risk: Rating,
    auc_kind: AucKind = "last",
) -> RoundAssessment:
    """Reduce each simulated profile to PK, compare with the observed PK, and judge the tier gate."""
    studies: list[StudyPK] = []
    comparisons: list[Comparison] = []
    findings: list[str] = []

    for profile in simulated:
        if len(profile.times) < 2:
            findings.append(f"{profile.study_id}: fewer than two simulated points; skipped")
            continue
        result = nca(list(profile.times), list(profile.concentrations))
        obs = observed.get(profile.study_id)
        pred_auc = _predicted_auc(result, auc_kind)
        studies.append(StudyPK(
            study_id=profile.study_id, role=profile.role,
            predicted_auc=pred_auc, predicted_cmax=result.c_max, predicted_tmax=result.t_max,
            predicted_thalf=result.t_half,
            observed_auc=obs.auc if obs else None, observed_cmax=obs.cmax if obs else None,
            observed_tmax=obs.tmax if obs else None, observed_thalf=obs.thalf if obs else None,
        ))
        if obs is None:
            findings.append(f"{profile.study_id}: no observed PK; not compared")
            continue
        if obs.auc is not None and pred_auc is not None and pred_auc > 0:
            comparisons.append(Comparison(profile.study_id, "AUC", pred_auc, obs.auc, profile.role))
        if obs.cmax is not None and result.c_max > 0:
            comparisons.append(Comparison(profile.study_id, "Cmax", result.c_max, obs.cmax, profile.role))

    if not comparisons:
        findings.append("no observed PK to compare against; acceptance gate cannot be judged this round")
        return RoundAssessment(
            gate_passed=False, report=None, studies=tuple(studies), findings=tuple(findings),
            metrics=_metrics(studies, report=None),
        )

    report = evaluate(comparisons, model_risk)
    if not report.passes:
        for v in report.failures():
            findings.append(
                f"{v.comparison.study} {v.comparison.quantity} ({v.comparison.role}): "
                f"ratio {v.ratio:.2f} outside {v.limit} (PE {v.prediction_error_pct:+.0f}%)"
            )
    return RoundAssessment(
        gate_passed=report.passes, report=report, studies=tuple(studies), findings=tuple(findings),
        metrics=_metrics(studies, report=report),
    )


def _metrics(studies: Sequence[StudyPK], *, report: AcceptanceReport | None) -> dict[str, Any]:
    # per (study, quantity) pass/fail, so diagnostics can read whether each study's AUC/Cmax was in limits
    passed = {(v.comparison.study, v.comparison.quantity): v.passes for v in report.verdicts} if report else {}
    metrics: dict[str, Any] = {
        "studies": [
            {
                "study_id": s.study_id, "role": s.role,
                "predicted_auc": s.predicted_auc, "observed_auc": s.observed_auc,
                "predicted_cmax": s.predicted_cmax, "observed_cmax": s.observed_cmax,
                "predicted_tmax": s.predicted_tmax, "observed_tmax": s.observed_tmax,
                "predicted_thalf": s.predicted_thalf, "observed_thalf": s.observed_thalf,
                "auc_in_limits": passed.get((s.study_id, "AUC")),
                "cmax_in_limits": passed.get((s.study_id, "Cmax")),
            }
            for s in studies
        ],
    }
    for quantity, pred_attr, obs_attr in (("AUC", "predicted_auc", "observed_auc"), ("Cmax", "predicted_cmax", "observed_cmax")):
        pred = [getattr(s, pred_attr) for s in studies if getattr(s, obs_attr) is not None and getattr(s, pred_attr) is not None]
        obs = [getattr(s, obs_attr) for s in studies if getattr(s, obs_attr) is not None and getattr(s, pred_attr) is not None]
        if pred and obs:
            metrics[quantity] = {
                "n": len(pred),
                "gmfe": gmfe(pred, obs).value,
                "fraction_within_2fold": fraction_within_fold(pred, obs, 2.0).value,
            }
    if report is not None:
        metrics["tier"] = report.tier
        metrics["ruleset"] = report.ruleset
        metrics["groups"] = [
            {"role": g.role, "quantity": g.quantity, "n": g.n,
             "fraction_within": g.fraction_within, "required_fraction": g.required_fraction, "passes": g.passes}
            for g in report.groups
        ]
    return metrics
