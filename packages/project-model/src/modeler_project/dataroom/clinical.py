"""A clinical study from the cells code read (plan 2026-11-21 v2 §8 "Analysis sets", "Mean profiles",
"Recomputation"): samples, subject flow, the modeling and AUC sets, mean profiles per arm, NCA per subject beside the
client's values, exposure per arm. Every rule is `dataroom_rules.yaml`'s and is written out on the view.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence

from modeler_project.dataroom.extract import parse_number
from modeler_project.dataroom.model import (
    Arm,
    ArmProfile,
    CheckedFact,
    Chip,
    Exposure,
    MeanPoint,
    Problem,
    ReadTable,
    Sample,
    StudyView,
    SubjectNca,
    SubjectSet,
    Value,
)
from modeler_project.dataroom.rules import Rules, load_rules
from pbpk_domain.nca import nca

_TIME_FACTOR = {"h": 1.0, "hr": 1.0, "hrs": 1.0, "hour": 1.0, "hours": 1.0, "min": 1 / 60, "mins": 1 / 60,
                "minute": 1 / 60, "minutes": 1 / 60, "d": 24.0, "day": 24.0, "days": 24.0}
_PK_ROLES = ("cmax", "tmax", "auc_t", "auc_inf", "t_half", "lambda_z")
_LABEL = {"cmax": "Cmax", "tmax": "Tmax", "auc_t": "AUC0–t", "auc_inf": "AUC0–inf", "t_half": "t½", "lambda_z": "λz"}


def subject_id(text: str) -> str:
    """A subject as one id however it is written: "007" and "7" are one subject; "S-07" stays as written."""
    raw = text.strip()
    return str(int(raw)) if raw.isdigit() else raw


def subjects_in(text: str) -> list[str]:
    """The subject numbers a fact lists: "1, 3, 5-7 and 12" -> 1, 3, 5, 6, 7, 12 (a fact's value holds the numbers only;
    its reason is its note)."""
    out: list[str] = []
    for m in re.finditer(r"(\d+)\s*(?:[-–—]|to)\s*(\d+)|(?<![\d.])(\d+)(?![\d.])", text):
        if m.group(1):
            a, b = int(m.group(1)), int(m.group(2))
            out.extend(str(k) for k in range(a, b + 1)) if 0 <= b - a < 500 else out.extend((str(a), str(b)))
        else:
            out.append(str(int(m.group(3))))
    return list(dict.fromkeys(out))


_ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6"}


def _period_named(text: str, periods: Sequence[str]) -> str:
    """The period a sentence names ("period-II", "Period 2"), as the data writes it; "" when none of them."""
    for m in re.finditer(r"period[\s\-_]*([IVX]+|\d+)\b", text, re.IGNORECASE):
        raw = m.group(1).upper()
        number = _ROMAN.get(raw, raw)
        for p in periods:
            if p.strip().upper() in (raw, number) or (p.strip().isdigit() and p.strip().lstrip("0") == number):
                return p
    return ""


def _time_factor(unit: str) -> float | None:
    return _TIME_FACTOR.get(unit.strip().lower().rstrip("."))


def samples_from(table: ReadTable) -> tuple[list[Sample], list[Problem], str]:
    """Every concentration of a concentrations table (one row per subject and period, its times across or down), with
    the problems met and the concentration unit."""
    desc = table.description
    problems: list[Problem] = []
    factor = _time_factor(desc.time_unit) if desc.time_unit else None
    if factor is None:
        factor = 1.0
        problems.append(Problem(code="TIME_UNIT_NOT_STATED", message=f"the table on {desc.part} of {desc.file} states no time "
                                f"unit{'' if not desc.time_unit else f' it knows ({desc.time_unit!r})'}: hours are assumed, confirm"))
    missing = {t.strip().lower() for t in desc.missing_tokens}
    blq = {t.strip().lower() for t in desc.blq_tokens}
    out: list[Sample] = []
    for row in table.rows:
        if row.summary:
            continue
        one = {c.role: c for c in row.cells if c.role in ("subject", "period", "treatment", "sequence", "time")}
        subject = subject_id(one["subject"].text) if "subject" in one else ""
        if not subject:
            continue
        values = [c for c in row.cells if c.role == "value"]
        for cell in values:
            time = cell.time
            if time is None and "time" in one:
                time = parse_number(one["time"].text)
            if time is None:
                problems.append(Problem(code="NO_TIME", message=f"line {row.line}: a value with no time", where=cell.chip))
                continue
            text = cell.text.strip()
            low = text.lower()
            number = parse_number(text)
            is_missing = not text or low in missing
            is_blq = not is_missing and (low in blq or low.startswith("<") or "blq" in low or "bql" in low
                                         or (desc.zero_means_blq and number == 0))
            if not is_missing and not is_blq and number is None:
                problems.append(Problem(code="UNREADABLE_VALUE", message=f"line {row.line}: {text!r} is not a concentration",
                                        where=cell.chip))
                is_missing = True
            out.append(Sample(subject=subject, period=one["period"].text.strip() if "period" in one else "",
                              treatment=one["treatment"].text.strip() if "treatment" in one else "",
                              sequence=one["sequence"].text.strip() if "sequence" in one else "",
                              time_h=round(time * factor, 6), text=text,
                              value=None if (is_missing or is_blq) else number, blq=is_blq, missing=is_missing,
                              chip=cell.chip))
    return out, problems, desc.value_unit


def _nca_points(samples: Sequence[Sample]) -> tuple[list[float], list[float]]:
    """A profile's points for NCA: below the LLOQ before the first quantifiable sample counts 0; after it, left out."""
    ts, cs, seen = [], [], False
    for s in sorted(samples, key=lambda s: s.time_h):
        if s.missing:
            continue
        if s.value is not None and s.value > 0:
            seen = True
            ts.append(s.time_h)
            cs.append(s.value)
        elif not seen:
            ts.append(s.time_h)
            cs.append(0.0)
    return ts, cs


def _linear_auc(ts: Sequence[float], cs: Sequence[float]) -> float:
    return sum((ts[i + 1] - ts[i]) * (cs[i] + cs[i + 1]) / 2 for i in range(len(ts) - 1))


def _geomean(values: Iterable[float | None]) -> float | None:
    xs = [v for v in values if v is not None and v > 0]
    return math.exp(statistics.fmean(math.log(v) for v in xs)) if xs else None


def _pct(ours: float | None, theirs: float | None) -> float | None:
    if ours is None or theirs is None or theirs == 0:
        return None
    return round(100.0 * (ours - theirs) / theirs, 3)


def _facts(facts: Sequence[CheckedFact], field: str) -> list[CheckedFact]:
    return [f for f in facts if f.ok and f.fact.field == field]


def _client_pk(tables: Sequence[ReadTable]) -> dict[tuple[str, str], tuple[dict[str, float], dict[str, Chip], str]]:
    """The client's NCA values per (subject, period), and the treatment they name."""
    out: dict[tuple[str, str], tuple[dict[str, float], dict[str, Chip], str]] = {}
    for table in tables:
        for row in table.rows:
            if row.summary:
                continue
            one = {c.role: c for c in row.cells}
            if "subject" not in one:
                continue
            values, chips = {}, {}
            for role in _PK_ROLES:
                if role in one and (x := parse_number(one[role].text)) is not None:
                    values[role], chips[role] = x, one[role].chip
            key = (subject_id(one["subject"].text), one["period"].text.strip() if "period" in one else "")
            out[key] = (values, chips, one["treatment"].text.strip() if "treatment" in one else "")
    return out


def study_view(study_id: str, *, concentrations: Sequence[ReadTable], pk_tables: Sequence[ReadTable] = (),
               facts: Sequence[CheckedFact] = (), arms: Sequence[Arm] = (), study_values: Sequence[Value] = (),
               rules: Rules | None = None) -> StudyView:
    """The study: samples → sets → mean profiles → NCA → exposure, every step's rule written on the view."""
    rules = rules or load_rules()
    problems: list[Problem] = []
    samples: list[Sample] = []
    unit = ""
    for table in concentrations:
        got, found, table_unit = samples_from(table)
        samples += got
        problems += found
        unit = unit or table_unit
    if not samples:
        return StudyView(study_id=study_id, facts=tuple(study_values), arms=tuple(arms), problems=(
            Problem(code="NO_CONCENTRATIONS", severity="error", message="no concentration table was read for this study"),
            *problems))
    by_profile: dict[tuple[str, str], list[Sample]] = defaultdict(list)
    for s in samples:
        by_profile[(s.subject, s.period)].append(s)
    periods = sorted({s.period for s in samples}, key=lambda p: (parse_number(p) is None, parse_number(p) or 0, p))
    times = sorted({s.time_h for s in samples})
    treatment_of = {key: next((s.treatment for s in got if s.treatment), "") for key, got in by_profile.items()}
    subjects = sorted({s.subject for s in samples}, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x))

    def dosed_in(subject: str, period: str) -> bool:
        return any(not s.missing for s in by_profile.get((subject, period), ()))

    def n_missing(subject: str, period: str) -> int:
        return sum(1 for s in by_profile.get((subject, period), ()) if s.missing)

    def quantifiable(subject: str, period: str) -> int:
        return sum(1 for s in by_profile.get((subject, period), ()) if s.time_h > 0 and s.value is not None and s.value > 0)

    def has_last(subject: str, period: str) -> bool:
        last = [s for s in by_profile.get((subject, period), ()) if s.time_h == times[-1]]
        return bool(last) and not last[0].missing

    sets: list[SubjectSet] = []
    excluded: dict[str, str] = {}
    dosed = [s for s in subjects if any(dosed_in(s, p) for p in periods)]
    sets.append(SubjectSet(name="dosed", label="Dosed", subjects=tuple(dosed),
                           rule="a concentration in at least one period"))
    for p in periods:
        sets.append(SubjectSet(name=f"dosed:{p}", label=f"Dosed, period {p}",
                               subjects=tuple(s for s in subjects if dosed_in(s, p)), rule=f"a concentration in period {p}"))
    all_periods = [s for s in dosed if all(dosed_in(s, p) for p in periods)]
    # completed: dosed in every period and sampled through each (at most two scheduled samples missing), and not one
    # the client lists as withdrawn or excluded; the client's own list of completers, when given, is compared with it
    sampled = [s for s in all_periods if all(n_missing(s, p) <= 2 for p in periods)]
    listed = _facts(facts, "study.completed_subjects")
    excluded_facts = _facts(facts, "study.excluded_subjects")
    out = {s: f.fact.note or f.fact.value for f in excluded_facts for s in subjects_in(f.fact.value)}
    completed = [s for s in sampled if s not in out]
    rule = "dosed in every period, sampled through each (at most two scheduled samples missing)"
    chips: tuple[Chip, ...] = ()
    if excluded_facts:
        rule += ", and not withdrawn or excluded by the client"
        chips = tuple(f.chip for f in excluded_facts if f.chip)
    for s in all_periods:
        if s in out:
            excluded[s] = f"the client lists it: {out[s]}"
        elif s not in sampled:
            excluded[s] = "sampling stopped early in a period (withdrawn or dropped out)"
    if listed:
        theirs = set(subjects_in(listed[0].fact.value))
        for s in sorted(theirs ^ set(completed), key=lambda x: int(x) if x.isdigit() else 0):
            problems.append(Problem(code="COMPLETERS_DIFFER", where=listed[0].chip, message=(
                f"subject {s}: the client lists it as completed, the data does not" if s in theirs
                else f"subject {s}: completed by the data, not on the client's list")))
        chips += tuple(f.chip for f in listed if f.chip)
    source = "sponsor" if (listed or excluded_facts) else "calculated"
    for s in dosed:
        if s not in all_periods:
            excluded.setdefault(s, "not dosed in every period")
    sets.append(SubjectSet(name="completed", label="Completed", subjects=tuple(completed), rule=rule, source=source,
                           sources=chips))
    k = rules.analysis_sets.evaluable_min_quantifiable
    evaluable = [s for s in completed if all(quantifiable(s, p) >= k for p in periods)]
    for s in completed:
        if s not in evaluable:
            bad = [p for p in periods if quantifiable(s, p) < k]
            all_blq = all(quantifiable(s, p) == 0 for p in bad)
            excluded[s] = (f"every sample below the LLOQ in period {', '.join(bad)}: a possible non-absorber or dosing error"
                           if all_blq else f"fewer than {k} quantifiable concentrations in period {', '.join(bad)}")
    modeling = evaluable
    sets.append(SubjectSet(name="modeling", label="Proposed modeling set", subjects=tuple(modeling),
                           rule=f"completed, and at least {k} quantifiable concentrations after the dose in every period"))
    auc = [s for s in modeling if all(has_last(s, p) for p in periods)]
    sets.append(SubjectSet(name="auc", label=f"AUC set (complete to {times[-1]:g} h)", subjects=tuple(auc),
                           rule=f"the modeling set with the {times[-1]:g} h sample present in every period"))
    statistical = _facts(facts, "study.statistical_set")
    client_pk = _client_pk(pk_tables)
    if statistical:
        sets.append(SubjectSet(name="client_statistical", label="Client's statistical set", source="sponsor",
                               subjects=tuple(s for s in subjects if s in set(subjects_in(statistical[0].fact.value))),
                               rule="as the client lists it", sources=tuple(f.chip for f in statistical if f.chip)))
    elif client_pk:
        in_pk = sorted({s for s, _ in client_pk}, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x))
        sets.append(SubjectSet(name="client_statistical", label="Client's PK set", source="sponsor", subjects=tuple(in_pk),
                               rule="the subjects of the client's PK parameter file"))
    for f in _facts(facts, "study.n_dosed"):
        if f.number is None:
            continue
        period = _period_named(f"{f.fact.subject} {f.fact.note} {f.fact.quote}", periods)
        ours = next((x for x in sets if x.name == f"dosed:{period}"), None) if period else sets[0]
        if ours is not None and int(f.number) != len(ours.subjects):
            problems.append(Problem(code="DOSED_DIFFERS", where=f.chip, message=(
                f"the client says {f.fact.value} dosed{f' in period {period}' if period else ''}; the concentration data has "
                f"a concentration for {len(ours.subjects)}")))

    # mean profiles per arm on the modeling set
    treatments = sorted({t for t in treatment_of.values() if t})
    profiles: list[ArmProfile] = []
    for set_name, members in (("modeling", modeling),):
        for trt in treatments:
            keys = [(s, p) for s in members for p in periods if treatment_of.get((s, p)) == trt]
            points = []
            for t in times:
                at = [x for key in keys for x in by_profile[key] if x.time_h == t]
                present = [x for x in at if not x.missing]
                arith = [0.0 if x.value is None else x.value for x in present]
                quant = [x.value for x in present if x.value is not None and x.value > 0]
                points.append(MeanPoint(
                    time_h=t, n=len(arith), mean=round(statistics.fmean(arith), 6) if arith else None,
                    sd=round(statistics.stdev(arith), 6) if len(arith) > 1 else None, n_geo=len(quant),
                    geomean=round(_geomean(quant), 6) if quant else None, n_blq=sum(1 for x in present if x.blq),
                    n_missing=len(at) - len(present)))
            profiles.append(ArmProfile(treatment=trt, analysis_set=set_name, n_subjects=len(keys), points=tuple(points)))

    # NCA per profile, beside the client's
    tol, tmax_tol = rules.nca.tolerance_percent, rules.nca.tmax_tolerance_h
    rows: list[SubjectNca] = []
    log_diffs, lin_diffs = [], []
    for (subject, period), got in sorted(by_profile.items()):
        ts, cs = _nca_points(got)
        if sum(1 for c in cs if c > 0) < 3:
            continue
        res = nca(ts, cs)
        ours = {"cmax": res.c_max, "tmax": res.t_max, "auc_t": res.auc_last, "auc_inf": res.auc_inf, "t_half": res.t_half,
                "lambda_z": res.lambda_z}
        client, _chips, _trt = client_pk.get((subject, period), ({}, {}, ""))
        lin = _linear_auc(ts, cs)
        if "auc_t" in client:
            log_diffs.append(_pct(res.auc_last, client["auc_t"]))
            lin_diffs.append(_pct(lin, client["auc_t"]))
        rows.append(SubjectNca(subject=subject, period=period, treatment=treatment_of.get((subject, period), ""),
                               cmax=res.c_max, tmax=res.t_max, auc_t=round(res.auc_last, 6), auc_t_linear=round(lin, 6),
                               auc_inf=None if res.auc_inf is None else round(res.auc_inf, 6),
                               t_half=None if res.t_half is None else round(res.t_half, 6),
                               lambda_z=None if res.lambda_z is None else round(res.lambda_z, 8), client=client))
    method = ""
    if lin_diffs:
        med_log = statistics.median(abs(d) for d in log_diffs if d is not None)
        med_lin = statistics.median(abs(d) for d in lin_diffs if d is not None)
        method = "linear trapezoidal" if med_lin < med_log else "linear-up/log-down"
    use_linear = method == "linear trapezoidal"
    checked: list[SubjectNca] = []
    for row in rows:
        diffs: dict[str, float] = {}
        ours = {"cmax": row.cmax, "auc_t": row.auc_t_linear if use_linear else row.auc_t, "auc_inf": row.auc_inf,
                "lambda_z": row.lambda_z, "t_half": row.t_half}
        for role, theirs in row.client.items():
            if role == "tmax":
                if row.tmax is not None:
                    diffs["tmax"] = round(row.tmax - theirs, 4)
            elif (d := _pct(ours.get(role), theirs)) is not None:
                diffs[role] = d
        checked.append(row.model_copy(update={"differences": diffs}))
        off = [r for r, d in diffs.items() if (abs(d) > tmax_tol if r == "tmax" else abs(d) > tol and r in ("cmax", "auc_t"))]
        if off:
            problems.append(Problem(code="NCA_DIFFERS", message=(
                f"subject {row.subject}, period {row.period}: " + "; ".join(
                    f"{_LABEL[r]} ours {('%.4g' % (ours.get(r) if r != 'tmax' else row.tmax))} vs the client's {row.client[r]:.4g}"
                    + (" (both by the linear trapezoidal rule, ours at the nominal times)" if r == "auc_t" and use_linear else "")
                    for r in off))))
    if lin_diffs and use_linear:
        problems.append(Problem(code="CLIENT_NCA_METHOD", severity="info", message=(
            "the client's AUCs follow the linear trapezoidal rule (median difference "
            f"{statistics.median(abs(d) for d in lin_diffs if d is not None):.2f} %); ours is linear-up/log-down, shown "
            "beside it")))

    # exposure per arm: Cmax and Tmax on the modeling set, AUC on the AUC set; geometric means
    exposures: list[Exposure] = []
    by_key = {(r.subject, r.period): r for r in checked}
    for trt in treatments:
        for metric, members, stat in (("cmax", modeling, "geometric_mean"), ("auc_t", auc, "geometric_mean"),
                                      ("auc_inf", auc, "geometric_mean"), ("tmax", modeling, "arithmetic_mean"),
                                      ("tmax", modeling, "median")):
            got = [by_key[(s, p)] for s in members for p in periods
                   if (s, p) in by_key and by_key[(s, p)].treatment == trt]
            if metric == "auc_t" and use_linear:
                ours_v = [r.auc_t_linear for r in got]
            else:
                ours_v = [getattr(r, metric) for r in got]
            theirs = [r.client.get(metric) for r in got]
            if stat == "geometric_mean":
                value, client = _geomean(ours_v), _geomean(theirs) if all(t is not None for t in theirs) and theirs else None
            elif stat == "median":
                xs = [v for v in ours_v if v is not None]
                value = statistics.median(xs) if xs else None
                ys = [t for t in theirs if t is not None]
                client = statistics.median(ys) if ys and len(ys) == len(theirs) else None
            else:
                xs = [v for v in ours_v if v is not None]
                value = statistics.fmean(xs) if xs else None
                ys = [t for t in theirs if t is not None]
                client = statistics.fmean(ys) if ys and len(ys) == len(theirs) else None
            exposures.append(Exposure(treatment=trt, analysis_set="auc" if members is auc else "modeling", n=len(got),
                                      metric=metric, statistic=stat, value=None if value is None else round(value, 4),
                                      unit=("h" if metric == "tmax" else (unit if metric == "cmax" else f"{unit}·h")),
                                      client=None if client is None else round(client, 4),
                                      difference_percent=_pct(value, client)))
    lloq_facts = _facts(facts, "study.lloq")
    return StudyView(study_id=study_id, facts=tuple(study_values), arms=tuple(arms), periods=tuple(periods),
                     times_h=tuple(times), sets=tuple(sets), excluded={s: r for s, r in excluded.items() if r},
                     profiles=tuple(profiles), nca=tuple(checked), exposures=tuple(exposures), nca_method_client=method,
                     concentration_unit=unit, lloq=lloq_facts[0].number if lloq_facts else None, problems=tuple(problems))
