"""Virtual bioequivalence trials (T-31, F-304; analysis template ``vbe-crossover``, decision D-26).

Every virtual subject receives the TEST product and its reference on separate occasions: the engine runs both arms on
the same individuals, each arm with its own seeded intra-subject variability (the population task's occasion). From
the two arms' per-individual PK this module forms K virtual crossover trials of n subjects (individuals in id order),
judges each by the confidence interval of its geometric mean ratio (`bioequivalence.paired_crossover_ci`), and
reports the probability of success per metric and jointly (every metric passing in the same trial).

The metrics are PK-Sim's own PK parameter names (harvested catalog). The design, limits and threshold come from the
template and the person's inputs; all of it is UNVERIFIED until a PBPK SME and QA sign the template.
"""

from __future__ import annotations

import csv
import io
import math
import statistics
from collections.abc import Mapping

from pbpk_domain.bioequivalence import BioequivalenceResult, paired_crossover_ci

VBE_METRICS = ("AUC_inf", "C_max")


class VbeError(ValueError):
    """The arms' PK cannot form the trials the design asks for."""


def read_pk_analyses(text: str, quantity_path: str | None = None,
                     metrics: tuple[str, ...] = VBE_METRICS) -> tuple[str, dict[str, dict[int, float]]]:
    """PK-Sim's ``pk_analyses.csv`` (IndividualId, QuantityPath, Parameter, Value, Unit) as {metric: {individual:
    value}} for one output: `quantity_path`, or the file's only output when none is named."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    paths = sorted({r["QuantityPath"] for r in rows})
    if quantity_path is None:
        if len(paths) != 1:
            raise VbeError(f"pk_analyses.csv has {len(paths)} outputs ({', '.join(paths)}); name the one to judge")
        quantity_path = paths[0]
    elif quantity_path not in paths:
        raise VbeError(f"pk_analyses.csv has no output {quantity_path!r} ({', '.join(paths) or 'none'})")
    values: dict[str, dict[int, float]] = {m: {} for m in metrics}
    for r in rows:
        if r["QuantityPath"] == quantity_path and r["Parameter"] in values:
            try:
                values[r["Parameter"]][int(r["IndividualId"])] = float(r["Value"])
            except ValueError:
                values[r["Parameter"]][int(r["IndividualId"])] = math.nan
    missing = [m for m in metrics if not values[m]]
    if missing:
        raise VbeError(f"pk_analyses.csv has no {', '.join(missing)} for {quantity_path}")
    return quantity_path, values


def _usable(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def between_subject_cv(values: list[float]) -> float:
    """The between-subject CV (%) of log-normally distributed exposure: √(exp(s²) − 1), s the SD of the logs."""
    s = statistics.stdev(math.log(v) for v in values)
    return 100.0 * math.sqrt(math.exp(s * s) - 1.0)


def validation_gate(result: dict, observed: Mapping | None, *, cv_fold: float) -> dict:
    """F-304: does the model reproduce the observed BE study? Per metric the observed study names, the simulated
    reference arm's between-subject CV must lie within `cv_fold` of the observed one, and the observed GMR within the
    simulated trials' 5–95 %. No observed study gives "not validated", never a pass (real-data rule, D-19)."""
    if not observed:
        return {"status": "NOT_VALIDATED", "reason": "no observed BE study (REQ-vbe.be_study) was given: the VBE result "
                                                     "is not validated"}
    checks, missing = [], []
    for metric, row in observed["metrics"].items():
        simulated = result["metrics"].get(metric)
        if simulated is None:
            missing.append(metric)
            continue
        ratio = simulated["between_subject_cv_percent"] / float(row["between_subject_cv_percent"])
        checks.append({"metric": metric, "check": "between_subject_cv", "simulated": simulated["between_subject_cv_percent"],
                       "observed": float(row["between_subject_cv_percent"]), "ratio": ratio,
                       "passes": 1 / cv_fold <= ratio <= cv_fold})
        gmr = float(row["gmr"])
        checks.append({"metric": metric, "check": "observed_gmr_within_simulated_5_95", "observed": gmr,
                       "simulated_p05": simulated["gmr_p05"], "simulated_p95": simulated["gmr_p95"],
                       "passes": simulated["gmr_p05"] <= gmr <= simulated["gmr_p95"]})
    if missing or not checks:
        return {"status": "NOT_VALIDATED", "checks": checks,
                "reason": f"the observed study's {', '.join(missing) or 'metrics'} are not simulated metrics "
                          f"({', '.join(result['metrics'])})"}
    failed = [f"{c['metric']} {c['check']}" for c in checks if not c["passes"]]
    return {"status": "FAILED" if failed else "PASSED", "checks": checks, "source": observed.get("source"),
            "cv_fold": cv_fold, "reason": ("the model does not reproduce the observed BE study: " + ", ".join(failed))
            if failed else "the model reproduces the observed BE study's variability and GMR"}


def _trial_row(result: BioequivalenceResult) -> dict:
    return {"gmr": result.geometric_mean_ratio, "lower": result.ci_lower, "upper": result.ci_upper,
            "passes": result.passes}


def run_trials(test: Mapping[str, Mapping[int, float]], reference: Mapping[str, Mapping[int, float]], *,
               n_subjects: int, n_trials: int, limits: tuple[float, float], confidence: float,
               pos_threshold: float) -> dict:
    """K trials of n subjects from the two arms' PK, each judged per metric; the probability of success per metric
    and joint, against the threshold. An individual without a positive, finite value of every metric in both arms
    is excluded and named; trials are formed from the rest in id order, as many whole trials as they fill."""
    if n_subjects < 2 or n_trials < 1:
        raise VbeError("a trial needs at least 2 subjects, and at least 1 trial is needed")
    metrics = tuple(test)
    ids = sorted(set.intersection(*(set(test[m]) | set(reference[m]) for m in metrics)))
    excluded = [i for i in ids if not all(_usable(test[m].get(i)) and _usable(reference[m].get(i)) for m in metrics)]
    kept = [i for i in ids if i not in set(excluded)]
    trials_run = min(n_trials, len(kept) // n_subjects)
    if trials_run == 0:
        raise VbeError(f"{len(kept)} usable individuals cannot fill one trial of {n_subjects}")
    per_metric: dict[str, list[BioequivalenceResult]] = {}
    for m in metrics:
        per_metric[m] = []
        for k in range(trials_run):
            members = kept[k * n_subjects:(k + 1) * n_subjects]
            per_metric[m].append(paired_crossover_ci([test[m][i] for i in members], [reference[m][i] for i in members],
                                                     confidence=confidence, limits=limits))
    joint = sum(all(per_metric[m][k].passes for m in metrics) for k in range(trials_run)) / trials_run
    summary = {}
    for m, results in per_metric.items():
        gmrs = [r.geometric_mean_ratio for r in results]
        summary[m] = {"probability_of_success": sum(r.passes for r in results) / trials_run,
                      "gmr_median": statistics.median(gmrs), "gmr_p05": _percentile(gmrs, 0.05),
                      "gmr_p95": _percentile(gmrs, 0.95),
                      "between_subject_cv_percent": between_subject_cv([reference[m][i] for i in kept]),
                      "trials": [_trial_row(r) for r in results]}
    return {
        "metrics": summary, "joint_probability_of_success": joint, "pos_threshold": pos_threshold,
        "meets_threshold": joint >= pos_threshold, "limits": list(limits), "confidence": confidence,
        "n_subjects": n_subjects, "n_trials_planned": n_trials, "n_trials_run": trials_run,
        "individuals": len(ids), "excluded_individuals": excluded,
    }
