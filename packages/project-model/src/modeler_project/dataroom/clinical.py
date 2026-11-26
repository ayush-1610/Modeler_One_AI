"""A clinical study from the cells code read (plan 2026-11-21 v2 §8 "Analysis sets", "Mean profiles",
"Recomputation"): samples, subject flow, the modeling and AUC sets, mean profiles per arm, NCA per subject beside the
client's values, exposure per arm. Every rule is `dataroom_rules.yaml`'s and is written out on the view.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence

from modeler_intake.room_specs import TableDescription
from modeler_project.dataroom.extract import parse_number, token_sets
from modeler_project.dataroom.flags import exclusion_flags
from modeler_project.dataroom.model import (
    Arm,
    ArmProfile,
    CheckedFact,
    Chip,
    Exposure,
    MeanPoint,
    Problem,
    ReadRow,
    ReadTable,
    RoomStudy,
    Sample,
    SubjectNca,
    SubjectSet,
    Value,
)
from modeler_project.dataroom.observed import is_statistic, means_of
from modeler_project.dataroom.reproduce import Profile, reproduction
from modeler_project.dataroom.rules import Rules, load_rules
from pbpk_domain.nca import NcaResult, nca

_TIME_FACTOR = {"h": 1.0, "hr": 1.0, "hrs": 1.0, "hour": 1.0, "hours": 1.0, "min": 1 / 60, "mins": 1 / 60,
                "minute": 1 / 60, "minutes": 1 / 60, "d": 24.0, "day": 24.0, "days": 24.0}
_PK_ROLES = ("cmax", "tmax", "auc_t", "auc_inf", "t_half", "lambda_z")
_LABEL = {"cmax": "Cmax", "tmax": "Tmax", "auc_t": "AUC0–t", "auc_inf": "AUC0–inf", "t_half": "t½", "lambda_z": "λz"}


def subject_id(text: str) -> str:
    """A subject as one id however it is written: "007", "7", "S07", "Subj-7" are subject 7; a site-subject id keeps its
    parts ("101-001" is 101-1); anything else stays as written."""
    raw = re.sub(r"\s+", " ", text.strip())
    if re.fullmatch(r"\d+", raw):
        return str(int(raw))
    m = re.fullmatch(r"(?i)(?:s|sub|subj|subject|pt|patient|id)?[\s._#-]*0*(\d+)", raw)
    if m:
        return str(int(m.group(1)))
    m = re.fullmatch(r"(\d+)\s*[-/]\s*(\d+)", raw)
    if m:
        return f"{int(m.group(1))}-{int(m.group(2))}"
    return raw


def subjects_in(text: str, known: Iterable[str] = ()) -> list[str]:
    """The subjects a fact lists, as `subject_id` writes them: "03-05, 07, 11 to 13 and 20" -> 3, 4, 5, 7, 11, 12, 13,
    20; "S06, S09"; "101-001, 101-005" and "01-007" (site-subject ids, not ranges: the subject part is written longer
    than the site, with its zeros); "34, 35 38" (a missing comma). With the study's own subjects (`known`), a token that
    names one of them is that subject, never a range: "01-007" is subject 01-007 when the data has it (a new delivery,
    2026-11-24: it was read as subjects 1 to 7). A fact's value holds the subjects only; its reason is its note."""
    ids = set(known)
    out: list[str] = []
    # "14 (01, 02, 06 …)": a count, then the subjects in brackets (the count is not a subject)
    counted = re.fullmatch(r"\s*\d+\s*\((.+)\)\s*\.?\s*", text, re.DOTALL)
    text = (counted.group(1) if counted else text).replace("(", " ").replace(")", " ")
    for token in re.split(r"[,;&]|\band\b", text):
        token = token.strip()
        if not token:
            continue
        if subject_id(token) in ids:
            out.append(subject_id(token))
            continue
        site = re.fullmatch(r"(\d+)\s*[-/]\s*(0\d+)", token)
        site_subject = bool(site) and len(site.group(2)) > len(site.group(1))       # type: ignore[union-attr]
        rng = re.fullmatch(r"(?i)[a-z]*\s*0*(\d+)\s*(?:-|–|—|to)\s*[a-z]*\s*0*(\d+)", token)
        if rng and 0 < int(rng.group(2)) - int(rng.group(1)) < 500 and not site_subject \
                and not re.fullmatch(r"\d{3,}-0\d+", token):
            out.extend(str(k) for k in range(int(rng.group(1)), int(rng.group(2)) + 1))
            continue
        pieces = token.split() if all(re.fullmatch(r"[A-Za-z]*\d+", w) for w in token.split()) else [token]
        out.extend(subject_id(w) for w in pieces if re.search(r"\d", w))
    return list(dict.fromkeys(out))


_ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6"}


def _code_key(code: str) -> str:
    """A treatment code without the words around it: "Treatment R", "Trt. R", "Arm R" and "R" are one code."""
    return re.sub(r"(?i)\b(?:treatment|trt|arm|regimen|group|code|period)\b\.?|[\s:_.-]+", "", code).lower()
# an occasion that is a study day or visit of a multiple-dose study, as files write it
_DAY = re.compile(r"(?i)\bday\b|^d\s*\d+$|\bvisit\b|steady|\bss\b")


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
    """The factor to hours of a time unit as a file writes it ("h", "hours post-dose", "min after dosing")."""
    words = re.findall(r"[a-z]+", unit.lower())
    return _TIME_FACTOR.get(words[0]) if words else None


def samples_from(table: ReadTable) -> tuple[list[Sample], list[Problem], str]:
    """Every concentration of a concentrations table (one row per subject and period, its times across or down), with
    the problems met and the concentration unit."""
    desc = table.description
    problems: list[Problem] = []
    factor = _time_factor(desc.time_unit) if desc.time_unit else None
    if factor is None:
        factor = 1.0
        problems.append(Problem(code="TIME_UNIT_NOT_STATED", severity="error", message=(
            f"the table on {desc.part} of {desc.file} states no time unit"
            f"{'' if not desc.time_unit else f' code knows ({desc.time_unit!r})'}: shown in hours, not sent to the model")))
    missing, blq = token_sets(desc)
    out: list[Sample] = []
    for row in table.rows:
        if row.summary or any(c.role == "statistic" and c.text.strip() for c in row.cells):
            continue
        # "time" is the nominal (scheduled) time; an "actual_time" column is kept by the file, not used for the means
        one = {c.role: c for c in row.cells if c.role in ("subject", "period", "treatment", "sequence", "time", "actual_time",
                                                           "analyte")}
        if "subject" in one and is_statistic(one["subject"].text):
            continue                     # the client's own "Mean", "SD" or "N" line, not a subject: `observed`
        actual = parse_number(one["actual_time"].text, decimal_comma=table.decimal_comma) if "actual_time" in one else None
        subject = subject_id(one["subject"].text) if "subject" in one else ""
        if not subject:
            continue
        values = [c for c in row.cells if c.role == "value"]
        for cell in values:
            time = cell.time
            if time is None and "time" in one:
                time = parse_number(one["time"].text, decimal_comma=table.decimal_comma)
            if time is None:
                problems.append(Problem(code="NO_TIME", message=f"line {row.line}: a value with no time", where=cell.chip))
                continue
            text = cell.text.strip()
            low = text.lower()
            number = parse_number(text, decimal_comma=table.decimal_comma)
            # below the LLOQ is a measurement: a BLQ marker counts as one even when the description also lists it as a
            # missing sample (that description is refused with TOKEN_BOTH_MISSING_AND_BLQ)
            marked_blq = bool(text) and (low.startswith("<") or "blq" in low or "bql" in low or "bloq" in low)
            is_missing = not marked_blq and (not text or low in missing)
            is_blq = not is_missing and (marked_blq or low in blq or (desc.zero_means_blq and number == 0))
            if not is_missing and not is_blq and number is None:
                problems.append(Problem(code="UNREADABLE_VALUE", message=f"line {row.line}: {text!r} is not a concentration",
                                        where=cell.chip))
                is_missing = True
            out.append(Sample(subject=subject, period=one["period"].text.strip() if "period" in one else "",
                              treatment=one["treatment"].text.strip() if "treatment" in one else "",
                              sequence=one["sequence"].text.strip() if "sequence" in one else "",
                              time_h=round(time * factor, 6), text=text,
                              actual_h=None if actual is None else round(actual * factor, 6),
                              value=None if (is_missing or is_blq) else number, blq=is_blq, missing=is_missing,
                              chip=cell.chip, subject_text=one["subject"].text.strip(), analyte=analyte_of(row, desc)))
    return out, problems, desc.value_unit


def analyte_of(row: ReadRow, desc: TableDescription) -> str:
    """What a line measured, as written: its analyte cell, else the table's analyte constant ("" when neither names
    one)."""
    cell = next((c for c in row.cells if c.role == "analyte" and c.text.strip()), None)
    return re.sub(r"\s+", " ", (cell.text if cell else desc.constants.get("analyte", "")).strip())


def _analyte_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def analytes_in(tables: Sequence[ReadTable]) -> list[str]:
    """The analytes the tables name, each once (as first written, in the order the tables give them)."""
    seen: dict[str, str] = {}
    for table in tables:
        for row in table.rows:
            name = analyte_of(row, table.description)
            if name:
                seen.setdefault(_analyte_key(name), name)
    return list(seen.values())


def for_analyte(table: ReadTable, analyte: str) -> ReadTable:
    """The table's lines of one analyte (each line's analyte cell, else the table's constant), the rest left out."""
    want = _analyte_key(analyte)
    return table.model_copy(update={"rows": tuple(r for r in table.rows if _analyte_key(analyte_of(r, table.description)) == want)})


def unnamed_lines(table: ReadTable) -> int:
    """The data lines that name no analyte (no analyte cell and no analyte constant)."""
    return sum(1 for r in table.rows if not r.summary and not analyte_of(r, table.description))


def colliding_samples(table: ReadTable) -> str:
    """Why a concentration table's description cannot be right when two of its samples share an analyte, a subject, an
    occasion and a time with different values: a column that separates them (a study day, a period, a treatment) was
    not given that role (a new delivery, 2026-11-24: a "Day" column described as a group made Day 1 and Day 7 collide,
    about 230 samples, and no exposure). Samples of different analytes never collide (a CRO's PC dataset holds the drug
    and its metabolites, line by line). "" when none collide."""
    samples, _problems, _unit = samples_from(table)
    seen: dict[tuple[str, str, str, str, float], Sample] = {}
    clashes = 0
    for x in samples:
        key = (_analyte_key(x.analyte), x.subject, x.period, x.treatment, x.time_h)
        first = seen.setdefault(key, x)
        if first is not x and (first.value, first.blq, first.missing) != (x.value, x.blq, x.missing):
            clashes += 1
    if not clashes:
        return ""
    roles = {c.role for c in table.description.columns}
    # each column's header as the file writes it (the read cells keep it), else the agent's label
    written = {spec.index: cell.label for spec, cell in zip(table.description.columns, table.rows[0].cells, strict=False)}
    candidates = [f"column {c.index}{f' ({written.get(c.index) or c.label})' if written.get(c.index) or c.label else ''}"
                  for c in table.description.columns if c.role in ("group", "dose", "matrix")]
    hint = (f"; {', '.join(candidates)} may be what separates them" if candidates else
            "; a column that separates them may be left undescribed")
    missing = [r for r in ("period", "treatment") if r not in roles]
    return (f"{clashes} samples share a subject, {'/'.join(missing) or 'occasion'} and time with a different value: the "
            f"lines are not one profile each{hint}. Give the column that tells them apart its role (a study day or "
            "visit is the period; a product or dose level is the treatment)")


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


def _shown(value: float | None) -> str:
    return "none" if value is None else f"{value:.4g}"


def _tier_words(role: str, d: float | None, tier: str, pass_pct: float, investigate_pct: float) -> str:
    """Why a client's value is flagged, in the tier's words (dataroom_rules nca.reproduce, UNVERIFIED)."""
    if d is None:
        return "ours cannot be computed: no terminal phase under the settings found"
    size = f"{d:+.2f} h" if role == "tmax" else f"{d:+.1f} %"
    if tier == "differ":
        return (f"{size}; no NCA setting tried reproduces it: the data differ, ask the client" if role == "tmax" else
                f"{size}, beyond {investigate_pct:g} % under every setting tried: the data differ, ask the client")
    if role == "cmax":
        return f"{size}: no NCA setting changes Cmax, so the value itself differs (a re-assay or a transcription?)"
    if role == "tmax" or abs(d) > investigate_pct:
        return f"{size}: only another setting reproduces it, for this profile alone; investigate"
    return f"{size}, within {pass_pct:g}–{investigate_pct:g} %: investigate, a setting differs"


def _facts(facts: Sequence[CheckedFact], field: str) -> list[CheckedFact]:
    return [f for f in facts if f.ok and f.fact.field == field]


# a PK parameter's name or CDISC code (PPTESTCD) as files write it, by its letters and digits only: the role it fills
_PK_NAMES = {"cmax": "cmax", "tmax": "tmax", "auclst": "auc_t", "auclast": "auc_t", "auct": "auc_t", "auc0t": "auc_t",
             "auc0tlast": "auc_t", "auc0last": "auc_t", "aucifo": "auc_inf", "aucinf": "auc_inf", "auc0inf": "auc_inf",
             "aucinfobs": "auc_inf", "lamzhl": "t_half", "thalf": "t_half", "t12": "t_half", "halflife": "t_half",
             "lamz": "lambda_z", "lambdaz": "lambda_z"}


def pk_role(name: str) -> str:
    """The PK role a parameter's name or CDISC code stands for ("CMAX", "AUC0-t", "AUCIFO", "t1/2" → cmax, auc_t,
    auc_inf, t_half); "" for any other (a partial AUC, a clearance, a model's parameter: kept, not compared)."""
    return _PK_NAMES.get(re.sub(r"[^a-z0-9]", "", name.lower().replace("½", "12").replace("∞", "inf")), "")


def _client_pk(tables: Sequence[ReadTable]) -> tuple[dict[tuple[str, str], dict[str, float]], list[Problem]]:
    """The client's NCA values, keyed by (subject, period) and, when the file names it, also by (subject, treatment);
    a subject with one row only is also keyed (subject, "only"): in a parallel study the PK table names the arm in its
    own words ("Novaprazole 20 mg") where the data writes a code ("A"), or names none (a new delivery, 2026-11-24).
    A long table (a line per parameter: "parameter" and "value") gives one row per subject and occasion; a parameter
    given twice there with two values is not compared, and said."""
    out: dict[tuple[str, str], dict[str, float]] = {}
    problems: list[Problem] = []
    rows: list[tuple[str, tuple[tuple[str, str], ...], dict[str, float]]] = []
    for table in tables:
        long: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, float]] = {}
        twice: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
        for row in table.rows:
            if row.summary:
                continue
            one = {c.role: c for c in row.cells}
            if "subject" not in one:
                continue
            subject = subject_id(one["subject"].text)
            occasion = tuple((role, one[role].text.strip()) for role in ("period", "treatment")
                             if role in one and one[role].text.strip())
            if "parameter" in one and "value" in one:
                role = pk_role(one["parameter"].text)
                x = parse_number(one["value"].text, decimal_comma=table.decimal_comma)
                got = long.setdefault((subject, occasion), {})
                if role and x is not None:
                    if role in got and got[role] != x:
                        twice.add((subject, occasion, role))
                    got.setdefault(role, x)
                continue
            rows.append((subject, occasion, {role: x for role in _PK_ROLES if role in one and (
                x := parse_number(one[role].text, decimal_comma=table.decimal_comma)) is not None}))
        for subject, occasion, role in sorted(twice):
            long[(subject, occasion)].pop(role, None)
            problems.append(Problem(code="PK_PARAMETER_TWICE", message=(
                f"subject {subject}{''.join(f', {t}' for _r, t in occasion)}: {_LABEL[role]} is given twice with "
                f"two values in the PK table on {table.description.part} of {table.description.file}: not compared")))
        rows += [(subject, occasion, values) for (subject, occasion), values in long.items()]
    rows_of: dict[str, list[dict[str, float]]] = defaultdict(list)
    for subject, occasion, values in rows:
        rows_of[subject].append(values)
        for role, text in occasion:
            out[(subject, f"{role}:{text}")] = values
    for subject, got in rows_of.items():
        if len(got) == 1:
            out[(subject, "only")] = got[0]
    return out, problems


_ROMAN_NUMBER = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}


def occasion_key(text: str) -> str:
    """An occasion as one key however it is written: the period's number when it names one ("Period 2", "PERIOD II",
    "P2", "2" → "2"), else the text in lower case ("" for none)."""
    raw = text.strip()
    m = re.search(r"(?i)\bperiod[\s_-]*([IVX]+|\d+)\b|^\s*p?\s*(\d+)\s*$", raw)
    if m:
        got = m.group(1) or m.group(2)
        return str(_ROMAN_NUMBER.get(got.upper(), got if got.isdigit() else 0)).lstrip("0") or got
    return re.sub(r"\s+", " ", raw).lower()


def _given(table: ReadTable) -> list[dict[str, str]]:
    """A dosing table's lines by role, with the dose's unit."""
    unit = next((c.unit for c in table.description.columns if c.role == "dose"), "")
    out = []
    for row in table.rows:
        one = {c.role: c.text.strip() for c in row.cells}
        if one.get("subject") and one.get("treatment"):
            out.append({**one, "dose_unit": unit})
    return out


def _product(line: dict[str, str]) -> tuple[str, str, str]:
    return (line["treatment"], line.get("route", ""), line.get("form", ""))


def _dose(line: dict[str, str]) -> str:
    return f"{line['dose']} {line['dose_unit']}".strip() if line.get("dose") else ""


def dose_arms(tables: Sequence[ReadTable]) -> tuple[bool, str, str]:
    """Whether a product of the dosing data was given at more than one dose (a decision for the modeler: do the doses
    make arms?), the suggestion ("per_dose" or "one_arm") and why: one arm per dose when a subject was given two doses
    of it on two occasions (the design's dose levels, a dose-ranging crossover), or when at most four doses each went to
    two subjects or more (parallel dose groups); else one arm per product, each subject's own dose (individualised,
    e.g. by weight)."""
    lines = [ln for t in tables for ln in _given(t)]
    by_product: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    occasions: dict[tuple[tuple[str, str, str], str], dict[str, str]] = defaultdict(dict)
    for ln in lines:
        if dose := _dose(ln):
            by_product[_product(ln)][dose].add(subject_id(ln["subject"]))
            occasions[(_product(ln), subject_id(ln["subject"]))][occasion_key(ln.get("period", ""))] = dose
    several = {p: d for p, d in by_product.items() if len(d) > 1}
    if not several:
        return False, "per_dose", ""
    for (product, subject), doses in occasions.items():
        if product in several and len(set(doses.values())) > 1:
            return True, "per_dose", (f"subject {subject} was given {product[0]} at {' and '.join(sorted(set(doses.values())))} "
                                      "on different occasions: the doses are the design's")
    if all(len(d) <= 4 and all(len(s) >= 2 for s in d.values()) for d in several.values()):
        product, doses = next(iter(several.items()))
        return True, "per_dose", (f"{product[0]}: {len(doses)} doses, each given to two subjects or more "
                                  f"({', '.join(f'{k} to {len(v)}' for k, v in sorted(doses.items()))}): dose groups")
    product, doses = next(iter(several.items()))
    return True, "one_arm", (f"{product[0]}: {len(doses)} different doses, several given to one subject only: each "
                             "subject's own dose (individualised, e.g. by weight)")


def assignments(tables: Sequence[ReadTable], *, per_dose: bool) -> dict[tuple[str, str], str]:
    """Each subject's treatment on each occasion, as the dosing data writes it: the product, its dose (when the doses
    make arms, `dose_arms`), route and dosage form ("EXAMPLEAMIDE 100 mg ORAL TABLET"); two products given on one
    occasion are one treatment ("A + B"). Keyed (subject, `occasion_key`)."""
    given: dict[tuple[str, str], dict[tuple[str, str, str], list[str]]] = defaultdict(lambda: defaultdict(list))
    for t in tables:
        for ln in _given(t):
            doses = given[(subject_id(ln["subject"]), occasion_key(ln.get("period", "")))][_product(ln)]
            if (dose := _dose(ln)) and dose not in doses:
                doses.append(dose)
    out = {}
    for key, products in given.items():
        out[key] = " + ".join(" ".join(x for x in (name, "/".join(doses) if per_dose else "", route, form) if x)
                              for (name, route, form), doses in sorted(products.items()))
    return out


def _assigned(treatments: Mapping[tuple[str, str], str], x: Sample) -> str:
    """A sample's treatment from the dosing data: its subject's on its occasion, else the subject's only one."""
    got = treatments.get((x.subject, occasion_key(x.period)))
    if got is None:
        own = [v for (s, _o), v in treatments.items() if s == x.subject]
        got = own[0] if len(own) == 1 else ""
    return got


def _sort(ids: Iterable[str]) -> list[str]:
    def key(x: str) -> tuple:
        return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"(\d+)", x) if p)
    return sorted(ids, key=key)


def _mean_profile(members: Sequence[str], trt: str, keys_of: dict[str, list[tuple[str, str]]],
                  by_profile: dict[tuple[str, str], dict[float, Sample]], times: Sequence[float]) -> tuple[list[MeanPoint], int]:
    """An arm's mean profile over the members: each subject counts once (a replicate design's profiles of one
    treatment are averaged within the subject first); below the LLOQ is 0 in the arithmetic mean and left out of the
    geometric mean; a missing sample is left out of both."""
    subjects = [s for s in members if any(k for k in keys_of.get(s, ()) if k[1] == trt)]
    points = []
    for t in times:
        arith, quant, n_blq, n_missing = [], [], 0, 0
        for s in subjects:
            got = [by_profile.get((s, occ), {}).get(t) for occ, t_ in keys_of[s] if t_ == trt]
            present = [x for x in got if x is not None and not x.missing]
            if not present:
                n_missing += 1
                continue
            values = [0.0 if x.value is None else x.value for x in present]
            arith.append(statistics.fmean(values))
            positive = [x.value for x in present if x.value is not None and x.value > 0]
            if positive:
                quant.append(math.exp(statistics.fmean(math.log(v) for v in positive)))
            if all(x.blq for x in present):
                n_blq += 1
        points.append(MeanPoint(time_h=t, n=len(arith), mean=round(statistics.fmean(arith), 6) if arith else None,
                                sd=round(statistics.stdev(arith), 6) if len(arith) > 1 else None, n_geo=len(quant),
                                geomean=round(_geomean(quant), 6) if quant else None, n_blq=n_blq, n_missing=n_missing))
    return points, len(subjects)


def study_view(study_id: str, *, concentrations: Sequence[ReadTable], pk_tables: Sequence[ReadTable] = (),
               facts: Sequence[CheckedFact] = (), arms: Sequence[Arm] = (), study_values: Sequence[Value] = (),
               release: str = "", rules: Rules | None = None,
               treatments: Mapping[tuple[str, str], str] | None = None) -> RoomStudy:
    """The study: samples → sets → mean profiles → NCA → exposure, every step's rule written on the view.

    A profile is one subject on one occasion: a period when the data names periods, else a treatment (a crossover
    listed without its periods, or a parallel study). A crossover expects every subject on every occasion; a parallel
    study (each subject on one treatment) expects each subject on its own."""
    rules = rules or load_rules()
    problems: list[Problem] = []
    raw: list[Sample] = []
    unit = ""
    for table in concentrations:
        got, found, table_unit = samples_from(table)
        raw += got
        problems += found
        unit = unit or table_unit
    # concentration data that name no treatment (an SDTM PC dataset) take each profile's from the dosing data (EX)
    if treatments and raw and not any(x.treatment for x in raw):
        raw = [x.model_copy(update={"treatment": got}) if (got := _assigned(treatments, x)) else x for x in raw]
        if any(x.treatment for x in raw):
            problems.append(Problem(code="TREATMENT_FROM_DOSING", severity="info", message=(
                "the concentration data name no treatment: each profile's is what the dosing data say the subject was "
                "given on that occasion (product, route, form, and the dose when the doses make arms)")))
    # the client's own mean profiles, each with the statistic its table states (plan 2026-11-24 §8 feature 5)
    client_means, found = means_of(concentrations)
    problems += found
    if not raw:
        return RoomStudy(study_id=study_id, facts=tuple(study_values), arms=tuple(arms), client_means=tuple(client_means),
                         concentration_unit=unit, problems=(
            Problem(code="NO_CONCENTRATIONS", severity="error", message="no concentration table was read for this study"),
            *problems))
    if not unit:
        problems.append(Problem(code="UNIT_NOT_STATED", severity="error",
                                message="the concentrations' unit is not stated: shown, not sent to the model"))
    by_period = any(s.period for s in raw)

    def occasion(x: Sample) -> str:
        return f"period:{x.period}" if by_period else f"treatment:{x.treatment}"

    # one sample per subject, occasion and time: the same sample in two files is one, two values for it a conflict
    samples: dict[tuple[str, str, float], Sample] = {}
    for x in raw:
        key = (x.subject, occasion(x), x.time_h)
        first = samples.get(key)
        if first is None:
            samples[key] = x
        elif (first.value, first.blq, first.missing) != (x.value, x.blq, x.missing) and not x.missing:
            if first.missing:
                samples[key] = x
            else:
                problems.append(Problem(code="SAMPLE_CONFLICT", severity="error", where=x.chip, message=(
                    f"subject {x.subject}, {occasion(x).split(':', 1)[1]}, {x.time_h:g} h: {first.text!r} in "
                    f"{first.chip.file if first.chip else '?'} and {x.text!r} in {x.chip.file if x.chip else '?'}")))
    by_profile: dict[tuple[str, str], dict[float, Sample]] = defaultdict(dict)
    for (subject, occ, t), x in samples.items():
        by_profile[(subject, occ)][t] = x
    treatment_of = {key: next((x.treatment for x in got.values() if x.treatment), key[1].split(":", 1)[1] if not by_period else "")
                    for key, got in by_profile.items()}
    # a multiple-dose study (a new delivery, 2026-11-24): its occasions are study days ("Day 1", "Day 7 (steady
    # state)") with no treatment and no sequence written; each day is its own profile, not a replicate of one treatment
    day_labels = {k[1].split(":", 1)[1] for k in by_profile}
    day_role = next((c.role for t in concentrations for r in t.rows[:1] for c in r.cells
                     if c.role in ("period", "treatment") and _DAY.search(c.label)), "")
    multiple_dose = len(day_labels) > 1 and not any(x.sequence for x in raw) and (
        (by_period and not any(x.treatment for x in raw) and (day_role == "period" or all(_DAY.search(d) for d in day_labels)))
        or (not by_period and day_role == "treatment"))           # a "Day" column described as the treatment
    if multiple_dose:
        treatment_of = {key: key[1].split(":", 1)[1] for key in by_profile}
    occasions = sorted({k[1] for k in by_profile}, key=lambda o: (parse_number(o.split(":", 1)[1]) is None,
                                                                  parse_number(o.split(":", 1)[1]) or 0, o))
    periods = [o.split(":", 1)[1] for o in occasions]
    subjects = _sort({k[0] for k in by_profile})
    keys_of: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (subject, occ) in sorted(by_profile):
        keys_of[subject].append((occ, treatment_of[(subject, occ)]))
    crossover = by_period and len(occasions) > 1 or any(len({t for _o, t in v}) > 1 for v in keys_of.values())
    # the times scheduled for each treatment: every time any of its profiles was sampled at (nominal times)
    schedule: dict[str, list[float]] = defaultdict(list)
    for (_s, occ), got in by_profile.items():
        schedule[treatment_of[(_s, occ)]].extend(got)
    schedule = {t: sorted(set(v)) for t, v in schedule.items()}
    times = sorted({t for v in schedule.values() for t in v})

    def profile(subject: str, occ: str) -> dict[float, Sample]:
        return by_profile.get((subject, occ), {})

    def dosed_in(subject: str, occ: str) -> bool:
        return any(not x.missing for x in profile(subject, occ).values())

    def n_missing(subject: str, occ: str) -> int:
        got = profile(subject, occ)
        return sum(1 for t in schedule.get(treatment_of.get((subject, occ), ""), ()) if t not in got or got[t].missing)

    def quantifiable(subject: str, occ: str) -> int:
        return sum(1 for x in profile(subject, occ).values() if x.time_h > 0 and x.value is not None and x.value > 0)

    def has_last(subject: str, occ: str) -> bool:
        last = schedule.get(treatment_of.get((subject, occ), ""), [None])[-1]
        x = profile(subject, occ).get(last) if last is not None else None
        return x is not None and not x.missing

    def expected(subject: str) -> list[str]:
        return occasions if crossover else [o for o, _t in keys_of[subject]]

    label = "period" if by_period else "treatment"
    sets: list[SubjectSet] = []
    excluded: dict[str, str] = {}
    dosed = [s for s in subjects if any(dosed_in(s, o) for o in expected(s))]
    sets.append(SubjectSet(name="dosed", label="Dosed", subjects=tuple(dosed), rule=f"a concentration in at least one {label}"))
    if crossover:
        for o, p in zip(occasions, periods, strict=True):
            sets.append(SubjectSet(name=f"dosed:{p}", label=f"Dosed, {label} {p}",
                                   subjects=tuple(s for s in subjects if dosed_in(s, o)), rule=f"a concentration in {label} {p}"))
    all_occasions = [s for s in dosed if all(dosed_in(s, o) for o in expected(s))]
    # completed: dosed on every occasion the design gives it and sampled through each (at most two scheduled samples
    # missing), and not one the client lists as withdrawn or excluded; the client's own list is compared with it
    sampled = [s for s in all_occasions if all(n_missing(s, o) <= 2 for o in expected(s))]
    listed = _facts(facts, "study.completed_subjects")
    excluded_facts = _facts(facts, "study.excluded_subjects")
    out = {s: f.fact.note or f.fact.value for f in excluded_facts for s in subjects_in(f.fact.value, subjects)}
    unknown = [s for s in out if s not in subjects]
    for f in listed:
        unknown += [s for s in subjects_in(f.fact.value, subjects) if s not in subjects]
    if unknown:
        problems.append(Problem(code="SUBJECTS_NOT_IN_DATA", message=(
            f"the client lists subject{'s' if len(unknown) > 1 else ''} {', '.join(_sort(set(unknown)))}, not in the "
            "concentration data")))
    completed = [s for s in sampled if s not in out]
    rule = (f"dosed in every {label}" if crossover else "dosed") + \
        f", sampled through {'each' if crossover else 'it'} (at most two scheduled samples missing)"
    chips: tuple[Chip, ...] = ()
    if excluded_facts:
        rule += ", and not withdrawn or excluded by the client"
        chips = tuple(f.chip for f in excluded_facts if f.chip)
    for s in all_occasions:
        if s in out:
            excluded[s] = f"the client lists it: {out[s]}"
        elif s not in sampled:
            excluded[s] = f"sampling stopped early in a {label} (withdrawn or dropped out)"
    if listed:
        theirs = set(subjects_in(listed[0].fact.value, subjects))
        for s in _sort(theirs ^ set(completed)):
            problems.append(Problem(code="COMPLETERS_DIFFER", where=listed[0].chip, message=(
                f"subject {s}: the client lists it as completed, the data does not" if s in theirs
                else f"subject {s}: completed by the data, not on the client's list")))
        chips += tuple(f.chip for f in listed if f.chip)
    source = "sponsor" if (listed or excluded_facts) else "calculated"
    for s in dosed:
        if s not in all_occasions:
            excluded.setdefault(s, f"not dosed in every {label}")
    sets.append(SubjectSet(name="completed", label="Completed", subjects=tuple(completed), rule=rule, source=source,
                           sources=chips))
    k = rules.analysis_sets.evaluable_min_quantifiable
    evaluable = [s for s in completed if all(quantifiable(s, o) >= k for o in expected(s))]
    for s in completed:
        if s not in evaluable:
            bad = [o for o in expected(s) if quantifiable(s, o) < k]
            names = ", ".join(o.split(":", 1)[1] for o in bad)
            all_blq = all(quantifiable(s, o) == 0 for o in bad)
            excluded[s] = (f"every sample below the LLOQ in {label} {names}: a possible non-absorber or dosing error"
                           if all_blq else f"fewer than {k} quantifiable concentrations in {label} {names}")
    modeling = evaluable
    sets.append(SubjectSet(name="modeling", label="Proposed modeling set", subjects=tuple(modeling),
                           rule=f"completed, and at least {k} quantifiable concentrations after the dose"
                           + (f" in every {label}" if crossover else "")))
    auc = [s for s in modeling if all(has_last(s, o) for o in expected(s))]
    last = times[-1] if times else 0
    sets.append(SubjectSet(name="auc", label=f"AUC set (complete to {last:g} h)", subjects=tuple(auc),
                           rule="the modeling set with its last scheduled sample present" + (f" in every {label}" if crossover else "")))
    statistical = _facts(facts, "study.statistical_set")
    client_pk, found = _client_pk(pk_tables)
    problems += found
    if statistical:
        sets.append(SubjectSet(name="client_statistical", label="Client's statistical set", source="sponsor",
                               subjects=tuple(s for s in subjects if s in set(subjects_in(statistical[0].fact.value, subjects))),
                               rule="as the client lists it", sources=tuple(f.chip for f in statistical if f.chip)))
    elif client_pk:
        sets.append(SubjectSet(name="client_statistical", label="Client's PK set", source="sponsor",
                               subjects=tuple(s for s in subjects if any(key[0] == s for key in client_pk)),
                               rule="the subjects of the client's PK parameter file"))
    if client_pk and not any(key[0] in subjects for key in client_pk):
        problems.append(Problem(code="PK_ROWS_MATCH_NOTHING", severity="error",
                                message="no subject of the client's PK file is in the concentration data"))
    for f in _facts(facts, "study.n_dosed"):
        if f.number is None:
            continue
        period = _period_named(f"{f.fact.subject} {f.fact.quote}", periods)     # not the agent's note
        ours = next((x for x in sets if x.name == f"dosed:{period}"), None) if period else sets[0]
        if ours is not None and int(f.number) != len(ours.subjects):
            problems.append(Problem(code="DOSED_DIFFERS", where=f.chip, message=(
                f"the client says {f.fact.value} dosed{f' in period {period}' if period else ''}; the concentration data has "
                f"a concentration for {len(ours.subjects)}")))
    first_day = periods[0] if multiple_dose and periods else ""
    if multiple_dose:
        problems.append(Problem(code="MULTIPLE_DOSE", severity="info", message=(
            f"a multiple-dose study: each day ({', '.join(periods)}) is its own profile. After the first day, the AUC over "
            "the sampled interval is the AUC over the dosing interval (AUCτ) when the sampling spans it; AUC to infinity "
            "is not shown for those days (it has no meaning at steady state)")))
    if any(len([o for o, t in v if t == trt]) > 1 for v in keys_of.values() for trt in {t for _o, t in v}):
        problems.append(Problem(code="REPLICATE_DESIGN", severity="info", message=(
            "a subject has the same treatment in more than one period: its profiles of a treatment are averaged before "
            "the arm's mean, and each subject counts once")))

    # mean profiles per arm for every set a person may choose
    treatments = sorted({t for t in treatment_of.values() if t})
    if not treatments:
        # said, not guessed: an arm is never made up from the occasions (a crossover's periods mix treatments)
        problems.append(Problem(code="NO_TREATMENT", message=(
            f"the concentration data names no treatment for its {label}s: each profile's NCA and the subject sets are "
            "shown, but no mean profile or exposure per arm until each profile is tied to its treatment (an SDTM PC "
            "dataset names none: the study's EX dataset gives it, and code reads it)")))
    profiles: list[ArmProfile] = []
    for s_ in sets:
        if s_.name in ("modeling", "completed", "client_statistical", "auc", "dosed"):
            for trt in treatments:
                points, n = _mean_profile(s_.subjects, trt, keys_of, by_profile, schedule.get(trt, times))
                profiles.append(ArmProfile(treatment=trt, analysis_set=s_.name, n_subjects=n, points=tuple(points)))

    # NCA per profile, beside the client's; the client's values reproduced with the settings that explain them
    # (plan 2026-11-24 §8 feature 3: integration, time basis, BLQ rule, λz window; tiers UNVERIFIED)
    rows: list[SubjectNca] = []
    keys: list[tuple[str, str]] = []
    results: dict[tuple[str, str], NcaResult] = {}
    candidates: list[Profile] = []
    profiles_of = Counter(subject for subject, _occ in by_profile)
    for (subject, occ), got in sorted(by_profile.items()):
        ts, cs = _nca_points(list(got.values()))
        if sum(1 for c in cs if c > 0) < 3:
            continue
        res = nca(ts, cs)
        trt = treatment_of[(subject, occ)]
        client = (client_pk.get((subject, occ)) or client_pk.get((subject, f"treatment:{trt}"))
                  or (client_pk.get((subject, "only")) if profiles_of[subject] == 1 else None) or {})
        lin = _linear_auc(ts, cs)
        peak = got.get(res.t_max) if res.t_max is not None else None
        rows.append(SubjectNca(subject=subject, period=occ.split(":", 1)[1], treatment=trt,
                               cmax=res.c_max, tmax=res.t_max, tmax_actual=peak.actual_h if peak else None,
                               auc_t=round(res.auc_last, 6), auc_t_linear=round(lin, 6),
                               auc_inf=None if res.auc_inf is None else round(res.auc_inf, 6),
                               t_half=None if res.t_half is None else round(res.t_half, 6),
                               lambda_z=None if res.lambda_z is None else round(res.lambda_z, 8), client=client))
        keys.append((subject, occ))
        results[(subject, occ)] = res
        candidates.append(Profile(key=(subject, occ), samples=list(got.values()), client=client))
    if client_pk and rows and not any(r.client for r in rows):
        problems.append(Problem(code="PK_ROWS_MATCH_NOTHING", severity="error", message=(
            "the client's PK rows match no profile (by subject and period, or subject and treatment)")))
    lloq_facts = _facts(facts, "study.lloq")
    lloq = lloq_facts[0].number if lloq_facts else None
    repro, outcomes, found = reproduction(candidates, rules, lloq=lloq)
    method = ""
    if found is not None and any("auc_t" in r.client for r in rows):
        method = "linear trapezoidal" if found.integration == "linear" else "linear-up/log-down"
    use_linear = method == "linear trapezoidal"
    cfg = rules.nca.reproduce
    checked: list[SubjectNca] = []
    for row, key in zip(rows, keys, strict=True):
        got = outcomes.get(key)
        if got is None:
            checked.append(row)
            continue
        checked.append(row.model_copy(update={"differences": got.differences, "tiers": got.tiers,
                                              "settings_note": got.note}))
        off = [r for r in ("cmax", "tmax", "auc_t", "auc_inf") if got.tiers.get(r) in ("investigate", "differ")]
        if off:
            problems.append(Problem(code="NCA_DIFFERS", message=(
                f"subject {row.subject}" + (f", {label} {row.period}" if row.period else "") + ": " + "; ".join(
                    f"{_LABEL[r]} ours {_shown(got.values.get(r))} vs the client's {row.client[r]:.4g} "
                    f"({_tier_words(r, got.differences.get(r), got.tiers[r], cfg.pass_percent, cfg.investigate_percent)})"
                    for r in off))))
    if repro is not None:
        problems.append(Problem(code="CLIENT_NCA_METHOD", severity="info", message=repro.summary))
    # exclusions flagged, never deleted (plan 2026-11-24 §8 feature 4): every flagged profile stays in its sets
    problems += exclusion_flags(by_profile=by_profile, treatment_of=treatment_of, results=results, label=label,
                                later_days=set(periods[1:]) if multiple_dose else set(), facts=facts, periods=periods,
                                release=release, rules=rules)

    # exposure per arm: Cmax and Tmax on the modeling set, AUC on the AUC set; each subject once (a replicate's
    # profiles of one treatment averaged within the subject, geometrically for Cmax and AUC); N counts the values
    exposures: list[Exposure] = []
    for trt in treatments:
        for metric, members, stat in (("cmax", modeling, "geometric_mean"), ("auc_t", auc, "geometric_mean"),
                                      ("auc_inf", auc, "geometric_mean"), ("tmax", modeling, "arithmetic_mean"),
                                      ("tmax", modeling, "median")):
            if multiple_dose and metric == "auc_inf" and trt != first_day:
                continue
            ours_v, theirs_v = [], []
            for s in members:
                got = [r for r in checked if r.subject == s and r.treatment == trt]
                vals = [r.auc_t_linear if metric == "auc_t" and use_linear else getattr(r, metric) for r in got]
                vals = [v for v in vals if v is not None]
                theirs = [r.client[metric] for r in got if metric in r.client]
                if vals:
                    ours_v.append(_geomean(vals) if stat == "geometric_mean" else statistics.fmean(vals))
                if theirs:
                    theirs_v.append(_geomean(theirs) if stat == "geometric_mean" else statistics.fmean(theirs))
            agg = {"geometric_mean": _geomean, "median": lambda xs: statistics.median(xs) if xs else None,
                   "arithmetic_mean": lambda xs: statistics.fmean(xs) if xs else None}[stat]
            value = agg([v for v in ours_v if v is not None])
            client = agg(theirs_v) if theirs_v and len(theirs_v) == len(ours_v) else None
            exposures.append(Exposure(treatment=trt, analysis_set="auc" if members is auc else "modeling",
                                      n=len([v for v in ours_v if v is not None]), metric=metric, statistic=stat,
                                      value=None if value is None else round(value, 4),
                                      unit=("h" if metric == "tmax" else (unit if metric == "cmax" else f"{unit}·h")),
                                      client=None if client is None else round(client, 4),
                                      difference_percent=_pct(value, client)))
    # each code the documents define, as the data writes it ("Treatment R" is R: a new delivery, 2026-11-24, left both
    # arms without their product); a code no treatment of the data matches is said
    arms = list(arms)
    if treatments and not multiple_dose:
        by_key = {_code_key(t): t for t in treatments}
        for i, arm in enumerate(arms):
            if arm.treatment in treatments:
                continue
            match = by_key.get(_code_key(arm.treatment))
            if match:
                arms[i] = arm.model_copy(update={"treatment": match})
            else:
                problems.append(Problem(code="ARM_MATCHES_NO_TREATMENT", message=(
                    f"the documents define treatment {arm.treatment!r} ({arm.meaning}); the data's treatments are "
                    f"{', '.join(treatments)}: which one is it?")))
    return RoomStudy(study_id=study_id, facts=tuple(study_values), arms=tuple(arms), periods=tuple(periods),
                     times_h=tuple(times), sets=tuple(sets), excluded={s: r for s, r in excluded.items() if r},
                     profiles=tuple(profiles), nca=tuple(checked), exposures=tuple(exposures), nca_method_client=method,
                     nca_reproduction=repro, client_means=tuple(client_means), concentration_unit=unit, lloq=lloq,
                     problems=tuple(problems))
