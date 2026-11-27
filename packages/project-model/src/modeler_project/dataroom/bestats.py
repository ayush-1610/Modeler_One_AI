"""A study's average bioequivalence computed by code (plan 2026-11-26 §7 phase 3; the corpus audit's R01, R50, R55;
the owner's decision D3).

From the subjects' Cmax, AUC0–t and AUC0–inf on the analysis set the modeler chose (decision analysis-set:<study>),
test against reference as the question card's roles name them:

- **the GMR and its 90 % CI** (`pbpk_domain.bioequivalence`), Cmax on the chosen set and the AUCs on its subjects
  whose profiles are complete (the AUC set), as the room's exposures and the CSRs do: a 2×2 crossover by the standard
  analysis (sequence,
  subject within sequence, period, treatment) when each subject's periods give its sequence, the paired form when they
  do not, a parallel study by the pooled two-sample analysis. Computed twice when the client's NCA values are there:
  from our NCA, and from the client's values of the same subjects (the second isolates the statistics from the NCA);
- **the within-subject CV** (CVw = √(exp(MSE) − 1), a crossover's) beside the CRO's stated CV: shown to confirm (D3);
- **the conclusion** from the numbers: the full 90 % CI within the limits or not (R50);
- **the BE zone** (R55): the GMRs a balanced 2×2 crossover of the same n with this CVw would conclude bioequivalent;
- **the CSR's GMR and CI reproduced** within `be.csr_tolerance_pp` percentage points, or not (R01).

Every number is the rules' (`dataroom_rules.yaml` `be`, UNVERIFIED). A replicate design (a subject given one treatment
twice) is not analysed here: it needs its own model, and is said.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence

from modeler_project.dataroom.clinical import pk_role
from modeler_project.dataroom.extract import parse_number
from modeler_project.dataroom.model import BeResult, Problem, ReadTable, RoomStudy, SubjectNca
from modeler_project.dataroom.rules import Rules
from pbpk_domain.bioequivalence import StudyBeResult, be_zone, crossover_be, parallel_be

METRICS = (("cmax", "Cmax"), ("auc_t", "AUC0–t"), ("auc_inf", "AUC0–inf"))


def csr_metric(parameter: str) -> str:
    """The metric a CSR's BE line is about ("ln(Cmax)", "AUC0-t", "Log AUCinf" → cmax, auc_t, auc_inf), "" for another."""
    text = re.sub(r"(?i)^\s*(?:ln|log|log-?transformed)\s*[\s(_-]*", "", parameter.strip()).rstrip(")")
    return role if (role := pk_role(text)) in dict(METRICS) else ""


def _percent(text: str, *, cv: bool = False) -> float | None:
    """A ratio, CI bound or CV as a percent: "93.5", "93.5 %" and "0.935" are 93.5 (a ratio below 5 or a CV below 1.5
    written as a fraction)."""
    raw = text.strip()
    x = parse_number(raw.rstrip("%").strip())
    if x is None:
        return None
    return x if raw.endswith("%") or x >= (1.5 if cv else 5.0) else x * 100.0


def csr_values(tables: Sequence[ReadTable]) -> dict[str, dict[str, float]]:
    """The CSR's GMR, CI bounds and stated CV per metric, in percent, from its BE statistics tables."""
    out: dict[str, dict[str, float]] = {}
    for table in tables:
        for row in table.rows:
            if row.summary:
                continue
            one = {c.role: c.text for c in row.cells}
            metric = csr_metric(one.get("parameter", ""))
            if not metric:
                continue
            got = {k: x for k in ("ratio", "ci_low", "ci_high", "cv")
                   if (x := _percent(one.get(k, ""), cv=k == "cv")) is not None}
            if got:
                out.setdefault(metric, {}).update(got)
    return out


def _value(row: SubjectNca, metric: str, source: str, linear: bool) -> float | None:
    if source == "client":
        return row.client.get(metric)
    if metric == "auc_t" and linear:
        return row.auc_t_linear
    return getattr(row, metric)


def _sequence(rows: Mapping[str, SubjectNca], test: str, reference: str, periods: Sequence[str]) -> str | None:
    """A subject's sequence ("TR" or "RT") from the periods of its test and reference profiles, None when unknown."""
    a, b = rows[test].period, rows[reference].period
    if a in periods and b in periods and a != b:
        return "TR" if periods.index(a) < periods.index(b) else "RT"
    return None


def _result(metric: str, label: str, source: str, got: StudyBeResult, *, test: str, reference: str, set_name: str,
            csr: Mapping[str, float], rules: Rules) -> BeResult:
    low, high = rules.be.limits_percent
    gmr, lo, hi = (round(100 * x, 2) for x in (got.geometric_mean_ratio, got.ci_lower, got.ci_upper))
    inside = got.passes
    level = f"{100 * rules.be.confidence:g} %"
    conclusion = (f"the {level} CI {lo:.2f}–{hi:.2f} % lies {'within' if inside else 'outside'} {low:.2f}–{high:.2f} %: "
                  f"{'bioequivalent' if inside else 'not shown bioequivalent'} on {label}")
    zone = be_zone(got.mse, got.n, rules.be.confidence, (low / 100, high / 100)) if got.design != "parallel" and got.n >= 3 \
        else None
    diff: dict[str, float] = {}
    status = "none"
    theirs = {k: csr[k] for k in ("ratio", "ci_low", "ci_high") if k in csr}
    if theirs:
        ours = {"ratio": gmr, "ci_low": lo, "ci_high": hi}
        diff = {k: round(ours[k] - v, 2) for k, v in theirs.items()}
        status = "reproduced" if all(abs(d) <= rules.be.csr_tolerance_pp for d in diff.values()) else "differs"
    if "cv" in csr and got.design != "parallel":
        diff["cv"] = round(100 * got.cv - csr["cv"], 2)
    design = {"2x2 crossover": "the 2×2 crossover analysis (sequence, subject within sequence, period, treatment)",
              "paired": "the paired analysis (the periods do not give each subject's sequence: period effects not removed)",
              "parallel": "the parallel analysis (pooled variance)"}[got.design]
    return BeResult(
        metric=metric, label=label, test=test, reference=reference, source=source, analysis_set=set_name,  # type: ignore[arg-type]
        design=got.design, n=got.n, n_by_group=got.n_by_group, df=got.df, gmr_percent=gmr, ci_low_percent=lo,
        ci_high_percent=hi, cv_percent=round(100 * got.cv, 2), within_limits=inside, conclusion=conclusion,
        zone_low_percent=round(100 * zone[0], 2) if zone else None, zone_high_percent=round(100 * zone[1], 2) if zone else None,
        csr=dict(csr), csr_difference_pp=diff, csr_status=status,  # type: ignore[arg-type]
        rule=(f"log {label} on the {set_name} set{'' if metric == 'cmax' else ', its subjects with complete profiles (the AUC set)'}, "
              f"{design}; {level} CI on {got.df} degrees of freedom; limits {low:g}–{high:g} %; the CSR "
              f"reproduced within {rules.be.csr_tolerance_pp:g} percentage points (rules {rules.version}, "
              f"{rules.status})"))


def be_results(view: RoomStudy, *, set_name: str, csr: Mapping[str, Mapping[str, float]], rules: Rules
               ) -> tuple[tuple[BeResult, ...], list[Problem]]:
    """The study's BE per metric (from our NCA, and from the client's when every subject has it) and the problems."""
    tests = [a.treatment for a in view.arms if a.role == "test"]
    references = [a.treatment for a in view.arms if a.role == "reference"]
    treatments = {r.treatment for r in view.nca}
    if len(treatments) < 2:
        return (), []
    if len(tests) != 1 or len(references) != 1 or not {tests[0], references[0]} <= treatments:
        return (), [Problem(code="BE_NOT_COMPUTED", severity="info", message=(
            f"{view.study_id}: the test and reference treatments are not known one each (the question card's products "
            f"tied to the data's treatments {', '.join(sorted(treatments))}): bioequivalence not computed"))]
    test, reference = tests[0], references[0]
    members = set(next((s.subjects for s in view.sets if s.name == set_name), ()))
    # AUC on the subjects of the set whose profiles run to their last scheduled sample (the AUC set), as the room's
    # exposures and the CSRs do (P03's AUCs were reproduced within 0.1 percentage points this way, its Cmax on the
    # modeling set)
    complete = set(next((s.subjects for s in view.sets if s.name == "auc"), members))
    by: dict[str, dict[str, list[SubjectNca]]] = defaultdict(lambda: defaultdict(list))
    for row in view.nca:
        if row.subject in members and row.treatment in (test, reference):
            by[row.subject][row.treatment].append(row)
    if any(len(v) > 1 for t in by.values() for v in t.values()):
        return (), [Problem(code="BE_NOT_COMPUTED", severity="info", message=(
            f"{view.study_id}: a subject has the same treatment in more than one period (a replicate design): its "
            "bioequivalence needs the replicate analysis, not computed here"))]
    linear = view.nca_method_client == "linear trapezoidal"
    crossover = any(len(t) == 2 for t in by.values())
    results: list[BeResult] = []
    problems: list[Problem] = []
    for source in ("ours", "client"):
        for metric, label in METRICS:
            mine = {s: t for s, t in by.items() if metric == "cmax" or s in complete}
            if crossover:
                pairs = [(s, {k: v[0] for k, v in t.items()}) for s, t in sorted(mine.items()) if len(t) == 2]
                pairs = [(s, rows) for s, rows in pairs if all((x := _value(rows[k], metric, source, linear)) is not None
                                                                and x > 0 for k in (test, reference))]
                if len(pairs) < 3:
                    continue
                seqs = [_sequence(rows, test, reference, view.periods) for _s, rows in pairs]
                got = crossover_be([_value(rows[test], metric, source, linear) for _s, rows in pairs],  # type: ignore[misc]
                                   [_value(rows[reference], metric, source, linear) for _s, rows in pairs],  # type: ignore[misc]
                                   sequences=None if None in seqs or len(set(seqs)) != 2 else seqs,  # type: ignore[arg-type]
                                   confidence=rules.be.confidence,
                                   limits=(rules.be.limits_percent[0] / 100, rules.be.limits_percent[1] / 100))
            else:
                values = {k: [x for t in mine.values() for r in t.get(k, ()) if (x := _value(r, metric, source, linear))
                              is not None and x > 0] for k in (test, reference)}
                if min(len(v) for v in values.values()) < 2:
                    continue
                got = parallel_be(values[test], values[reference], confidence=rules.be.confidence,
                                  limits=(rules.be.limits_percent[0] / 100, rules.be.limits_percent[1] / 100))
            results.append(_result(metric, label, source, got, test=test, reference=reference, set_name=set_name,
                                   csr=csr.get(metric, {}), rules=rules))
    # the CSR's numbers not reproduced (R01): said once per metric, from the client's NCA where there is one (that
    # isolates the statistics and the analysis set from the NCA), else from ours
    for metric, label in METRICS:
        mine = [r for r in results if r.metric == metric and r.csr_status != "none"]
        if not mine:
            continue
        best = next((r for r in mine if r.source == "client"), mine[0])
        if best.csr_status == "differs":
            problems.append(Problem(code="BE_CSR_DIFFERS", message=(
                f"{view.study_id}, {label}: the CSR's GMR {best.csr.get('ratio', float('nan')):.2f} % "
                f"({best.csr.get('ci_low', float('nan')):.2f}–{best.csr.get('ci_high', float('nan')):.2f} %) is not "
                f"reproduced within {rules.be.csr_tolerance_pp:g} percentage points: ours from "
                f"{'the client' if best.source == 'client' else 'our'} NCA on the {set_name} set is {best.gmr_percent:.2f} % "
                f"({best.ci_low_percent:.2f}–{best.ci_high_percent:.2f} %, n {best.n}): another analysis set, the "
                "model, or the values differ")))
    return tuple(results), problems


__all__ = ["METRICS", "be_results", "csr_metric", "csr_values"]
