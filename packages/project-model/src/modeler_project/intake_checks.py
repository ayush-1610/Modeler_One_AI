"""Validity checks of a subject's values (plan G5 and §7.7, contracts §6.4): each failure a typed `CheckResult`.

Every check reads the subject's active values from one `LedgerReader` (a study's, a product's or the compound's) and
returns `CheckResult`s with the rule it applied. A check's severity is the rules file's (`checks.severity` of
`intake_rules.yaml`, UNVERIFIED): `fail` blocks the subject until fixed, overridden by a scientist (`Override`: who,
when, why) or, for `REQUIRED_ITEM_UNDISPOSED` and `CONFLICT_OPEN`, settled by a `RequirementDisposition` or a `Choice`;
`warn` and `info` are shown and block nothing. Every threshold comes from the rules file (`checks.*`,
`ledger.time_resolution_min`, `landing.*`, `routing.population_covariates`) or from an existing one
(`datasets.NCA_TOLERANCE`, `pbpk_domain.dissolution.load_rules()`); none is written here. A code the rules file does not
list is not run.

A check's id is `"ck-" + sha256(code, subject, sorted value ids, detail)[:12]` (`result_id`): the same while nothing
changes, another when its values change, so an override names exactly what it cleared. A check about something
missing (a dose, a landing field, a time reference, a dissolution method) names no value, but its detail key holds a
digest of the ids of the values it judged (`judged`): new data for the same subject gives a new id, so an override
made for one delivery never clears the check for values it was not given for.

A message states the finding, its labels (study, arm, analyte, matrix, product, batch, run conditions, units, field
names) and nothing read from or counted over the subject's values: no value, spread, LLOQ, count of BLQ or other
values, and no number computed from them (an NCA). The values are named by id in `values`, the rule by its key in
`rule`, so the review shows the numbers through the ids and a blinded study's withholding (contracts §8.10) covers
the checks too.

Nothing is changed or refused here: a unit outside its table is reported (`UNIT_NOT_IN_TABLES`, only for a field whose
class has a table) and kept as written; a unit of a class with no table is reported `UNIT_NOT_CHECKED` (info). A unit's
class is its field's (`fields.unit_class`), never guessed from the unit text.

A profile is a study's concentration values of one (arm, analyte, matrix), the matrix read as its choice and, for a
value with no matrix label, the study's single stated matrix; a series is one line of a profile (its subject, period,
sequence, occasion, statistic and conditions).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from itertools import pairwise
from typing import Any, Literal

from modeler_intake.anchors import sha256_of
from modeler_intake.document_reading import name_key
from modeler_intake.fields import CONDITION_FIELDS, MASS_UNITS, known_unit, read_choice, unit_class, unit_table
from modeler_project.datasets import NCA_TOLERANCE
from modeler_project.intake_records import CheckResult, MappingEntry, RequirementStatus
from modeler_project.intake_rules import IntakeRules
from modeler_project.intake_rules import rules as load_rules
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import ValueState
from modeler_project.ledger_view import LedgerReader, in_subject, is_spread_fact
from modeler_project.study_routing import (
    SubjectType,
    matrix_choice,
    stated,
    study_matrix,
    study_tags,
    subject_values,
    tag_values,
)
from pbpk_domain.dissolution import ProfileKey
from pbpk_domain.dissolution import load_rules as dissolution_rules
from pbpk_domain.nca import nca
from pbpk_domain.units import UnitError, is_molar, minutes_per, umol_per_l_per

# Every code this module checks: exactly the codes of the rules file's `checks.severity` (a test holds them equal)
CHECKS: tuple[str, ...] = (
    # fail
    "ONE_LLOQ_PER_PROFILE", "BLQ_WITHOUT_LLOQ", "LLOQ_UNIT_DIFFERS", "DUPLICATE_TIME", "UNIT_MISSING", "UNIT_NOT_IN_TABLES",
    "MATRIX_NOT_PLASMA", "ANALYTE_MISSING", "MATRIX_MISSING", "DOSE_MISSING", "INFUSION_TIME_MISSING",
    "LANDING_FIELD_MISSING", "STATISTIC_MISSING", "SPREAD_KIND_MISSING", "TIME_REFERENCE_UNSTATED", "NEGATIVE_VALUE",
    "ABOVE_RANGE", "DISSOLUTION_METHOD_INCOMPLETE", "DISSOLUTION_OUT_OF_RANGE", "CONFLICT_OPEN",
    "REQUIRED_ITEM_UNDISPOSED", "MAPPING_NOT_APPROVED", "MW_INCONSISTENT",
    # warn
    "SPREAD_NOT_CONVERTED", "GEOMETRIC_SPREAD_VERBATIM", "N_MISSING", "NCA_MISMATCH", "DOSE_BASIS_UNSTATED",
    "DOSE_NOT_MULTIPLE_OF_STRENGTH", "CROSSOVER_PERIOD_MISSING", "DISSOLUTION_LOT_NOT_CLINICAL",
    "DISSOLUTION_RUNS_NOT_KEYED", "COMPOSITION_SUM", "TIMES_NOT_INCREASING", "EXCRETION_NOT_LANDED",
    "OCCASIONS_NOT_LANDED", "ZERO_AFTER_QUANTIFIABLE", "POPULATION_COVARIATE_MISSING", "MARKED_VALUE",
    # info
    "ANALYTE_NOT_PARENT", "BLQ_PRESENT", "DUPLICATE_TABLE_AND_PLOT", "UNIT_NOT_CHECKED",
)
# Checks a person settles with another record than an override (§6.4, §11.22): a disposition, a choice
SETTLED_BY_RECORD = ("REQUIRED_ITEM_UNDISPOSED", "CONFLICT_OPEN")
_SEVERITY_ORDER = ("fail", "warn", "info")
CONCENTRATION = "concentration"
DISSOLVED = "percent_dissolved"
_TABLE_METHODS = ("cell", "pdf_table", "docx_table")
# The StudyRecord fields the landing needs (contracts §6.4): the formulation only for an oral study
LANDING_FIELDS = ("n", "dose", "route", "intended_use")
# A field whose own name carries its unit (fields.FIELDS: weight_mean_kg, strength_mg, infusion_time_min,
# percent_dissolved ...) needs no unit written beside its value
_UNIT_IN_NAME = re.compile(r"_(?:kg|cm|um|mg|g|h|min|ml|c|kcal)$|^percent_")
_MARK = re.compile(r"\d\s*[*†‡]")                          # a footnote mark on a number ("12.3*")
# An AUC unit as concentration × time: "ng*h/mL", "ng/mL*h", "h*ng/mL", "µg·h/L" (the time token one of the time table's)
_TIME = r"(?:s|sec|min|minutes?|h|hrs?|hours?|d|days?)"
_AUC_UNIT = re.compile(rf"^\s*(?:(?P<t1>{_TIME})\s*[*·×]\s*(?P<c1>.+)|(?P<a>[^*·×]+?)\s*[*·×]\s*(?P<t2>{_TIME})\s*(?P<b>/.*)?)$",
                       re.IGNORECASE)
_TOTAL = re.compile(r"^total\b", re.IGNORECASE)            # the total row of a composition table


def result_id(code: str, subject: str, values: Iterable[str], detail: str = "") -> str:
    """A check's id: `"ck-" + sha256(code, subject, sorted value ids, detail key)[:12]`, stable while nothing changes."""
    return "ck-" + sha256_of([code, subject, sorted(values), detail])[:12]


def judged(values: Iterable[str]) -> str:
    """A digest of the ids of the values a check judged, for the detail key of a check that names no value: its id
    changes when those values change (new data reopens a check an override cleared)."""
    return sha256_of(sorted(set(values)))[:12]


def sort_results(results: Iterable[CheckResult]) -> list[CheckResult]:
    """Check results failures first, then in the order of CHECKS, one per id."""
    order = {code: i for i, code in enumerate(CHECKS)}
    return sorted({r.id: r for r in results}.values(),
                  key=lambda r: (_SEVERITY_ORDER.index(r.severity), order.get(r.code, len(order)), r.id))


def run_checks(reader: LedgerReader, *, subject_type: Literal["study", "product", "compound"], subject: str,
               requirements: Sequence[RequirementStatus] = (), mol_weight: float | None = None,
               parent_names: Collection[str] = (), rules: IntakeRules | None = None) -> tuple[CheckResult, ...]:
    """Every check of the rules file for one subject, failures first. `requirements` are the subject's requirement
    statuses (for `REQUIRED_ITEM_UNDISPOSED`); `mol_weight` the compound's (for `MW_INCONSISTENT` and the NCA's unit
    conversion); `parent_names` the drug's name and synonyms (the rules file's `landing.parent_words` are added)."""
    rules = rules or load_rules()
    ctx = _Context.make(reader, subject_type, subject, requirements, mol_weight, parent_names, rules)
    for check in _GENERIC + _BY_SUBJECT[subject_type]:
        check(ctx)
    return tuple(sort_results(ctx.results))


def required_item_checks(reader: LedgerReader, *, subject_type: Literal["study", "product", "compound"], subject: str,
                         requirements: Sequence[RequirementStatus], rules: IntakeRules | None = None) -> tuple[CheckResult, ...]:
    """`REQUIRED_ITEM_UNDISPOSED` alone, as `run_checks` gives it: one result per missing REQUIRED item that applies
    to the subject. The scorecard adds these itself, so a missing required item blocks whether or not the caller
    passed the requirements to `run_checks`."""
    rules = rules or load_rules()
    if subject_type in ("study", "product"):
        entity = reader.entity(subject)
        subject = entity.id if entity is not None else subject
    return tuple(_required_items(reader, subject_type, subject, requirements, _severities(rules)))


# --- the context -------------------------------------------------------------------------------------------------------


Key = tuple[str | None, str | None, str | None]          # a profile: (arm, analyte, matrix)


@dataclass
class _Context:
    reader: LedgerReader
    subject_type: SubjectType
    subject: str
    rules: IntakeRules
    severity: dict[str, str]
    values: list[ValueState]                 # active, spread facts left out
    spreads: list[ValueState]                # the derived spread facts
    requirements: Sequence[RequirementStatus]
    mol_weight: float | None
    parents: set[str]
    matrix: str | None                       # the study's single stated matrix
    results: list[CheckResult] = field(default_factory=list)

    @classmethod
    def make(cls, reader: LedgerReader, subject_type: SubjectType, subject: str,
             requirements: Sequence[RequirementStatus], mol_weight: float | None, parent_names: Collection[str],
             rules: IntakeRules) -> _Context:
        if subject_type in ("study", "product"):
            entity = reader.entity(subject)
            subject = entity.id if entity is not None else subject
        every = subject_values(reader, subject_type, subject, spread_facts=True)
        values = [v for v in every if not is_spread_fact(v)]
        severity = _severities(rules)
        parents = {name_key(w) for w in (*rules.landing.parent_words, *parent_names)}
        return cls(reader=reader, subject_type=subject_type, subject=subject, rules=rules, severity=severity,
                   values=values, spreads=[v for v in every if is_spread_fact(v)], requirements=requirements,
                   mol_weight=mol_weight if mol_weight and mol_weight > 0 else None, parents=parents,
                   matrix=study_matrix(values) if subject_type == "study" else None)

    def add(self, code: str, values: Iterable[str], message: str, *, detail: str = "",
            rule: str = "checks.severity") -> None:
        level = self.severity.get(code)
        if level is None:                    # the rules file does not list it: not run
            return
        ids = tuple(sorted(set(values)))
        self.results.append(CheckResult(id=result_id(code, self.subject, ids, detail), code=code, severity=level,  # type: ignore[arg-type]
                                        subject_type=self.subject_type, subject=self.subject, message=message,
                                        values=ids, rule=rule))

    def label(self, entity_id: str | None, default: str = "") -> str:
        if entity_id is None:
            return default
        entity = self.reader.entity(entity_id)
        return entity.label if entity is not None else entity_id

    def of(self, *names: str) -> list[ValueState]:
        return [v for v in self.values if v.field in names]

    def matrix_of(self, value: ValueState) -> str | None:
        return matrix_choice(value.entity.matrix) or self.matrix

    def profiles(self) -> dict[Key, list[ValueState]]:
        out: dict[Key, list[ValueState]] = {}
        for value in self.of(CONCENTRATION):
            out.setdefault((value.entity.arm, value.entity.analyte, self.matrix_of(value)), []).append(value)
        return out

    def describe(self, key: Key) -> str:
        arm, analyte, matrix = key
        bits = [f"analyte {self.label(analyte, 'not stated')}", f"matrix {matrix or 'not stated'}"]
        if arm is not None:
            bits.insert(0, f"arm {self.label(arm)}")
        return ", ".join(bits)

    def fits(self, value: ValueState, key: Key) -> bool:
        """Whether a study-level value (an LLOQ, a dose) fits a profile: equal where both state the part."""
        arm, analyte, matrix = key
        parts = ((value.entity.arm, arm), (value.entity.analyte, analyte), (self.matrix_of(value), matrix))
        return all(a is None or b is None or a == b for a, b in parts)


def _severities(rules: IntakeRules) -> dict[str, str]:
    return {code: level for level in _SEVERITY_ORDER for code in rules.checks.severity.get(level, ())}  # type: ignore[call-overload]


def _detail(key: Key | tuple[Any, ...]) -> str:
    return "|".join("" if part is None else str(part) for part in key)


def _number(value: ValueState) -> float | None:
    if isinstance(value.value, bool) or not isinstance(value.value, int | float):
        return None
    return float(value.value)


def _minutes(value: ValueState) -> float | None:
    if value.time is None or not value.time_unit:
        return None
    try:
        return value.time * minutes_per(value.time_unit)
    except UnitError:
        return None


def _series_key(ctx: _Context, value: ValueState) -> tuple[Any, ...]:
    e = value.entity
    return (value.field, e.arm, e.product, e.batch, e.analyte, ctx.matrix_of(value), e.subject, e.period, e.sequence,
            e.occasion, e.vessel, value.statistic, tuple(sorted(value.conditions.items())))


def _series(ctx: _Context, *names: str) -> dict[tuple[Any, ...], list[ValueState]]:
    out: dict[tuple[Any, ...], list[ValueState]] = {}
    for value in ctx.of(*names):
        out.setdefault(_series_key(ctx, value), []).append(value)
    return out


def _unit_key(field_name: str, unit: str | None) -> str:
    """A unit's canonical spelling in its field's table, else the unit as written (case and spacing aside)."""
    if not unit or not unit.strip():
        return ""
    known = known_unit(field_name, unit)
    return known if known is not None else " ".join(unit.lower().split())


# --- LLOQ ------------------------------------------------------------------------------------------------------------


def _lloqs(ctx: _Context, key: Key, values: Sequence[ValueState]) -> list[tuple[float, str, str]]:
    """Every LLOQ of a profile, as (number, canonical unit, value id): a value's own (a "<0.5" cell, a cited LLOQ
    line) and each `lloq` fact of the study that fits the profile; an LLOQ with no unit takes the profile's."""
    units = [_unit_key(CONCENTRATION, v.unit) for v in values if v.unit]
    profile_unit = max(sorted(set(units)), key=units.count) if units else ""
    out = [(v.lloq, _unit_key(CONCENTRATION, v.lloq_unit) or profile_unit, v.id) for v in values if v.lloq is not None]
    for fact in ctx.of("lloq"):
        number = _number(fact)
        if number is not None and ctx.fits(fact, key):
            out.append((number, _unit_key("lloq", fact.unit) or profile_unit, fact.id))
    return out


def _one_lloq_per_profile(ctx: _Context) -> None:
    for key, values in ctx.profiles().items():
        lloqs = _lloqs(ctx, key, values)
        distinct = sorted({(n, u) for n, u, _ in lloqs})
        if len(distinct) > 1:
            ctx.add("ONE_LLOQ_PER_PROFILE", (i for _, _, i in lloqs), f"{ctx.describe(key)}: the profile states more "
                    "than one LLOQ; PK-Sim takes one per observed dataset", detail=_detail(key))


def _blq_without_lloq(ctx: _Context) -> None:
    for key, values in ctx.profiles().items():
        censored = [v for v in values if v.censored and v.lloq is None]
        if censored and not any(_number(f) is not None and ctx.fits(f, key) for f in ctx.of("lloq")):
            ctx.add("BLQ_WITHOUT_LLOQ", (v.id for v in censored), f"{ctx.describe(key)}: values below the LLOQ, and "
                    "no LLOQ is stated", detail=_detail(key))


def _lloq_unit_differs(ctx: _Context) -> None:
    for key, values in ctx.profiles().items():
        units = {_unit_key(CONCENTRATION, v.unit) for v in values if v.unit and not v.censored}
        if not units:
            continue
        odd = [(n, u, i) for n, u, i in _lloqs(ctx, key, values) if u and u not in units]
        if odd:
            ctx.add("LLOQ_UNIT_DIFFERS", (i for _, _, i in odd), f"{ctx.describe(key)}: an LLOQ in "
                    f"{', '.join(sorted({u for _, u, _ in odd}))} beside values in {', '.join(sorted(units))}; "
                    "nothing is converted", detail=_detail(key))


# --- profiles ----------------------------------------------------------------------------------------------------------


def _duplicate_time(ctx: _Context) -> None:
    """Two times of one series are one time when they are at most `ledger.time_resolution_min` apart, measured from
    the first time of their cluster (no chaining): the comparator the ledger's conflicts use for the same key (D4's
    `ledger.find_conflicts`, mirrored here because D5 may not import a D4 helper)."""
    resolution = ctx.rules.ledger.time_resolution_min
    names = (CONCENTRATION,) if ctx.subject_type == "study" else (DISSOLVED,)
    for key, values in _series(ctx, *names).items():
        timed = sorted(((m, v) for v in values if (m := _minutes(v)) is not None), key=lambda p: (p[0], p[1].id))
        clusters: list[list[tuple[float, ValueState]]] = []
        for minutes, value in timed:
            if clusters and abs(minutes - clusters[-1][0][0]) <= resolution:
                clusters[-1].append((minutes, value))
            else:
                clusters.append([(minutes, value)])
        same = {v.id for cluster in clusters if len(cluster) > 1 for _, v in cluster}
        if same:
            ctx.add("DUPLICATE_TIME", same, f"{key[0]}: values of one series at one time (within the time resolution)",
                    detail=_detail(key), rule="ledger.time_resolution_min")


def _times_not_increasing(ctx: _Context) -> None:
    names = (CONCENTRATION,) if ctx.subject_type == "study" else (DISSOLVED,)
    groups: dict[tuple[Any, ...], list[ValueState]] = {}
    for value in ctx.of(*names):                         # in the order they were written, per file
        groups.setdefault((value.file_sha256, *_series_key(ctx, value)), []).append(value)
    for key, values in groups.items():
        timed = [(m, v) for v in values if (m := _minutes(v)) is not None]
        back = [vb.id for (a, _), (b, vb) in pairwise(timed) if b < a]
        if back:
            ctx.add("TIMES_NOT_INCREASING", back, f"{key[1]}: times go back in the order written", detail=_detail(key))


def _matrix_not_plasma(ctx: _Context) -> None:
    flagged = {name_key(m) for m in ctx.rules.landing.matrix_as_plasma_with_warning}
    for key, values in ctx.profiles().items():
        if key[2] is not None and name_key(key[2]) in flagged:
            ctx.add("MATRIX_NOT_PLASMA", (v.id for v in values), f"{ctx.describe(key)}: measured in {key[2]}, which "
                    "the landing would treat as plasma", detail=_detail(key),
                    rule="landing.matrix_as_plasma_with_warning")


def _analyte_missing(ctx: _Context) -> None:
    for key, values in ctx.profiles().items():
        if key[1] is None:
            ctx.add("ANALYTE_MISSING", (v.id for v in values), f"{ctx.describe(key)}: concentrations name no analyte",
                    detail=_detail(key))


def _matrix_missing(ctx: _Context) -> None:
    for key, values in ctx.profiles().items():
        if key[2] is None:
            ctx.add("MATRIX_MISSING", (v.id for v in values), f"{ctx.describe(key)}: concentrations name no matrix, "
                    "and the study states no single matrix", detail=_detail(key))


def _statistic_missing(ctx: _Context) -> None:
    by_field: dict[str, list[str]] = {}
    for value in ctx.of(CONCENTRATION, DISSOLVED):
        individual = value.entity.subject or (value.field == DISSOLVED and value.entity.vessel)
        if value.statistic is None and not individual and stated(value):
            by_field.setdefault(value.field, []).append(value.id)
    for name, ids in by_field.items():
        ctx.add("STATISTIC_MISSING", ids, f"{name}: values with no statistic and no subject: neither an individual "
                "nor a summary value lands", detail=name)


def _spread_kind_missing(ctx: _Context) -> None:
    by_field: dict[str, list[str]] = {}
    for value in ctx.values:
        if value.spread is not None and not value.spread_kind:
            by_field.setdefault(value.field, []).append(value.id)
    for name, ids in by_field.items():
        ctx.add("SPREAD_KIND_MISSING", ids, f"{name}: spreads of unknown kind (SD, SE, CV% ...): none lands",
                detail=name)


def _negative_value(ctx: _Context) -> None:
    by_field: dict[str, list[str]] = {}
    for value in ctx.of(CONCENTRATION, "lloq"):
        number = _number(value)
        if number is not None and number < 0:
            by_field.setdefault(value.field, []).append(value.id)
    for name, ids in by_field.items():
        ctx.add("NEGATIVE_VALUE", ids, f"{name}: negative values (an observed dataset refuses them)", detail=name)


def _above_range(ctx: _Context) -> None:
    by_field: dict[str, list[str]] = {}
    for value in ctx.values:
        if value.uloq is not None and value.value is None:
            by_field.setdefault(value.field, []).append(value.id)
    for name, ids in by_field.items():
        ctx.add("ABOVE_RANGE", ids, f"{name}: values above the range (written \">x\"): no number is kept", detail=name)


def _occasions_not_landed(ctx: _Context) -> None:
    for key, values in ctx.profiles().items():
        occasions = sorted({v.entity.occasion for v in values if v.entity.occasion})
        if len(occasions) > 1:
            ctx.add("OCCASIONS_NOT_LANDED", (), f"{ctx.describe(key)}: several occasions ({', '.join(occasions)}); such "
                    "a profile is held back at the landing", detail=_detail(key))


def _zero_after_quantifiable(ctx: _Context) -> None:
    for key, values in _series(ctx, CONCENTRATION).items():
        seen = False
        zeros = []
        for _, value in sorted(((m, v) for v in values if (m := _minutes(v)) is not None), key=lambda p: p[0]):
            number = _number(value)
            if number is None or value.censored:
                continue
            if number > 0:
                seen = True
            elif number == 0 and seen:
                zeros.append(value.id)
        if zeros:
            ctx.add("ZERO_AFTER_QUANTIFIABLE", zeros, "zeros after a quantifiable value: a BLQ written as zero?",
                    detail=_detail(key))


def _crossover_period_missing(ctx: _Context) -> None:
    if "yes" not in {v.value if v.value == "yes" else read_choice("crossover", str(v.value))
                     for v in ctx.of("crossover") if v.value is not None}:
        return
    for key, values in ctx.profiles().items():
        missing = [v.id for v in values if v.entity.subject and not v.entity.period]
        if missing:
            ctx.add("CROSSOVER_PERIOD_MISSING", missing, f"{ctx.describe(key)}: a crossover study's individual values "
                    "name no period", detail=_detail(key))


def _excretion_not_landed(ctx: _Context) -> None:
    excreted = [v.id for v in ctx.values if v.field.startswith("excretion.")]
    if excreted:
        ctx.add("EXCRETION_NOT_LANDED", excreted, "excretion values are kept in the ledger; no dataset is made from "
                "them (the interval, cumulative and dose-basis choices are the SME's)")


def _analyte_not_parent(ctx: _Context) -> None:
    roles = {v.entity.analyte: read_choice("analyte_role", str(v.value)) for v in ctx.of("analyte_role")
             if v.value is not None and v.entity.analyte}
    for key in ctx.profiles():
        analyte = key[1]
        if analyte is None or roles.get(analyte) == "parent" or name_key(ctx.label(analyte)) in ctx.parents:
            continue
        ctx.add("ANALYTE_NOT_PARENT", (), f"{ctx.describe(key)}: not the parent drug; it is carried as its own analyte",
                detail=_detail(key), rule="landing.parent_words")


def _blq_present(ctx: _Context) -> None:
    for key, values in ctx.profiles().items():
        censored = [v.id for v in values if v.censored]
        if censored:
            ctx.add("BLQ_PRESENT", censored, f"{ctx.describe(key)}: values below the LLOQ; the BLQ rule is "
                    f"{ctx.rules.landing.blq_rule!r} ({ctx.rules.status})", detail=_detail(key), rule="landing.blq_rule")


def _duplicate_table_and_plot(ctx: _Context) -> None:
    for key, values in ctx.profiles().items():
        digitized = [v.id for v in values if v.method == "digitized"]
        if digitized and any(v.method in _TABLE_METHODS for v in values):
            ctx.add("DUPLICATE_TABLE_AND_PLOT", digitized, f"{ctx.describe(key)}: the profile is read from a table and "
                    "digitized from a plot; the table wins", detail=_detail(key))


# --- spreads, n, NCA -------------------------------------------------------------------------------------------------


def _spreads(ctx: _Context) -> None:
    """GEOMETRIC_SPREAD_VERBATIM and SPREAD_NOT_CONVERTED: a (statistic, spread kind) pair `landing.spreads_landed` does
    not land (beside a geometric mean, or any other), and a spread `landing.sd_from` converts that cannot be: an SE with
    no n at its point or in its series (and no derived SD), a CV% with no mean."""
    derived = {source for s in ctx.spreads for source in s.derived_from}
    series = _series(ctx, CONCENTRATION)
    landed = ctx.rules.landing.spreads_landed
    found: dict[tuple[str, str, str], list[str]] = {}
    for values in series.values():
        series_n = any(v.n_at for v in values)
        for value in values:
            statistic, kind = value.statistic, value.spread_kind
            if value.spread is None or not kind or not statistic:
                continue
            if kind not in landed.get(statistic, {}):
                code = "GEOMETRIC_SPREAD_VERBATIM" if statistic == "geometric_mean" else "SPREAD_NOT_CONVERTED"
                found.setdefault((code, "landing.spreads_landed", f"{statistic}|{kind}"), []).append(value.id)
            elif kind in ctx.rules.landing.sd_from.get(statistic, ()) and value.id not in derived:
                convertible = (value.n_at or series_n) if kind == "SE" else value.value is not None
                if not convertible:
                    found.setdefault(("SPREAD_NOT_CONVERTED", "landing.sd_from", f"{statistic}|{kind}"),
                                     []).append(value.id)
    for (code, rule, detail), ids in found.items():
        statistic, kind = detail.split("|")
        why = ("lands no error and stays in the ledger as written" if rule == "landing.spreads_landed"
               else "cannot be converted to an SD (no n)" if kind == "SE" else "cannot be converted to an SD")
        ctx.add(code, ids, f"{kind} values beside a {statistic.replace('_', ' ')}: {why}", detail=detail, rule=rule)


def _n_missing(ctx: _Context) -> None:
    names = (CONCENTRATION,) if ctx.subject_type == "study" else (DISSOLVED,)
    n_facts = [v for v in ctx.of("n") if _number(v) is not None]
    for key, values in _series(ctx, *names).items():
        statistic = key[11]
        if statistic in (None, "individual") or any(v.n_at for v in values):
            continue
        arm = key[1]
        if any(f.entity.arm in (None, arm) for f in n_facts):
            continue
        ctx.add("N_MISSING", (), f"{key[0]}: a {statistic.replace('_', ' ')} series with no n, at its points or for "
                "its arm", detail=_detail(key))


# The parts of `_series_key` a reported PK parameter and the mean series it reports must agree on, where both state
# them: arm, product, batch, analyte, matrix, subject, period, sequence, occasion
_REPORT_PARTS = (1, 2, 3, 4, 5, 6, 7, 8, 9)


def _reports(ctx: _Context, rep: ValueState, key: tuple[Any, ...]) -> bool:
    """Whether a mean series (its `_series_key`) is the one a reported PK parameter can be about: the same statistic
    (any summary statistic when the report states none), and its arm, product, batch, analyte, matrix, subject,
    period, sequence, occasion and conditions equal to the report's wherever both state them."""
    if key[11] in (None, "individual") or (rep.statistic is not None and key[11] != rep.statistic):
        return False
    mine = _series_key(ctx, rep)
    if not all(mine[i] is None or key[i] is None or mine[i] == key[i] for i in _REPORT_PARTS):
        return False
    theirs = dict(key[12])
    return all(theirs.get(name, value) == value for name, value in rep.conditions.items())


def _nca_mismatch(ctx: _Context) -> None:
    """A reported Cmax or AUC_last against the NCA of the one mean series it reports (`_reports`). A report that
    several series fit (test and reference in one arm, two periods, and the report names neither) is not compared
    and says so; one that no series fits (another statistic, no mean profile) is not compared."""
    reported = ctx.of("pk.Cmax", "pk.AUC_last")
    if not reported:
        return
    series = _series(ctx, CONCENTRATION)
    for rep in reported:
        number = _number(rep)
        if number is None or number <= 0:
            continue
        parameter = rep.field.removeprefix("pk.")
        fitting = [(k, vs) for k, vs in series.items() if _reports(ctx, rep, k)]
        if len(fitting) > 1:
            ctx.add("NCA_MISMATCH", (rep.id,), f"reported {parameter}: several mean profiles fit it (they differ in "
                    "arm, product, batch, period or occasion, and the report does not say which); it is not compared",
                    detail=f"{rep.field}|{rep.id}|several|{judged(v.id for _, vs in fitting for v in vs)}",
                    rule="datasets.NCA_TOLERANCE")
            continue
        if not fitting:
            continue
        key, chosen = fitting[0]
        points = sorted(((m, n, v) for v in chosen if (m := _minutes(v)) is not None and (n := _number(v)) is not None),
                        key=lambda p: (p[0], p[1]))
        if len(points) < 3:
            continue
        result = nca([m for m, _, _ in points], [n for _, n, _ in points])
        unit = next((v.unit for _, _, v in points if v.unit), None)
        ours = result.c_max if parameter == "Cmax" else result.auc_last
        factor = _factor(rep.unit, unit, ctx.mol_weight, auc=parameter == "AUC_last")
        profile = (key[1], key[4], key[5])
        ids = (rep.id, *(v.id for _, _, v in points))
        detail = f"{_detail(key)}|{rep.field}|{rep.id}"
        if factor is None:
            ctx.add("NCA_MISMATCH", ids, f"{ctx.describe(profile)}: reported {parameter} in {rep.unit!r} cannot be "
                    f"compared with the profile in {unit!r}", detail=detail, rule="datasets.NCA_TOLERANCE")
            continue
        theirs = number * factor                    # in the profile's units (an AUC: its concentration unit x min)
        if ours > 0 and abs(ours - theirs) / theirs > NCA_TOLERANCE:
            ctx.add("NCA_MISMATCH", ids, f"{ctx.describe(profile)}: the reported {parameter} and the NCA of its mean "
                    "profile differ by more than the tolerance", detail=detail, rule="datasets.NCA_TOLERANCE")


def _factor(reported: str | None, unit: str | None, mol_weight: float | None, *, auc: bool) -> float | None:
    """The factor that puts a reported Cmax in the profile's concentration unit, or a reported AUC in (that unit x
    min), as `datasets._nca_check` converts them (between two mass or two molar units the molecular weight cancels);
    an AUC unit is read as concentration x time. None when the two cannot be compared."""
    if not reported or not unit:
        return None
    concentration, time = reported, None
    if auc:
        match = _AUC_UNIT.match(reported)
        if match is None:
            return None
        if match["t1"]:
            time, concentration = match["t1"], match["c1"]
        else:
            time, concentration = match["t2"], match["a"] + (match["b"] or "")
    try:
        mw = mol_weight or (1.0 if is_molar(concentration.strip()) == is_molar(unit) else None)
        factor = umol_per_l_per(concentration.strip(), mw) / umol_per_l_per(unit, mw)
        if time is not None:
            factor *= minutes_per(time.strip())
    except UnitError:
        return None
    return factor


# --- dose and design -----------------------------------------------------------------------------------------------


def _dose_missing(ctx: _Context) -> None:
    doses = [v for v in ctx.of("dose") if _number(v) is not None]
    profiles = ctx.profiles()
    for arm in sorted({key[0] for key in profiles}, key=lambda a: a or ""):
        if not any(d.entity.arm in (None, arm) for d in doses):
            where = f"arm {ctx.label(arm)}" if arm else "the study"
            seen = judged(v.id for key, values in profiles.items() if key[0] == arm for v in values)
            ctx.add("DOSE_MISSING", (), f"no dose is stated for {where}, which has concentrations",
                    detail=f"{arm or ''}|{seen}")


def _infusion_time_missing(ctx: _Context) -> None:
    times = ctx.of("infusion_time_min")
    for value in ctx.of("route"):
        if read_choice("route", str(value.value)) == "iv_infusion" or value.value == "iv_infusion":
            arm = value.entity.arm
            if not any(stated(t) and (arm is None or t.entity.arm in (None, arm)) for t in times):
                where = f"arm {ctx.label(arm)}" if arm else "the study"
                ctx.add("INFUSION_TIME_MISSING", (value.id,), f"{where} is an IV infusion with no infusion time",
                        detail=arm or "")


def _landing_field_missing(ctx: _Context) -> None:
    concentrations = ctx.of(CONCENTRATION)
    if not concentrations:
        return
    have = {v.field for v in ctx.values if stated(v)}
    tags = study_tags(ctx.reader, ctx.subject, brief=None)
    needed = [*LANDING_FIELDS, *(("formulation",) if "oral" in tag_values(tags, "route") else ())]
    seen = judged(v.id for v in concentrations)
    for name in needed:
        if name not in have:
            ctx.add("LANDING_FIELD_MISSING", (), f"the study record needs {name}, which no active value states",
                    detail=f"{name}|{seen}")


def _time_reference_unstated(ctx: _Context) -> None:
    designs = {read_choice("design", str(v.value)) for v in ctx.of("design") if v.value is not None}
    if "MD" not in designs:
        return
    references = _time_references(ctx.reader)
    concentrations = ctx.of(CONCENTRATION)
    if not any(references.get((v.mapping.mapping_id, v.mapping.version)) for v in concentrations if v.mapping):
        ctx.add("TIME_REFERENCE_UNSTATED", (), "a multiple-dose study whose concentration times state no reference "
                "(first dose, last dose, the occasion's dose)",
                detail=judged(v.id for v in (*concentrations, *ctx.of("design"))))


def _time_references(reader: LedgerReader) -> dict[tuple[str, int], str | None]:
    """The time reference each mapping version states (mappings.jsonl, which D5 reads): the ledger's values carry their
    mapping, not its spec. A reader with no store states none."""
    store = getattr(reader, "store", None)
    if not isinstance(store, IntakeStore) or not store.available:
        return {}
    out: dict[tuple[str, int], str | None] = {}
    for line in store.mappings.entries("entry"):
        entry = MappingEntry.model_validate(line.body)
        out[(entry.mapping_id, entry.version)] = entry.spec.time_reference
    return out


def _dose_basis_unstated(ctx: _Context) -> None:
    doses = [v.id for v in ctx.of("dose") if _number(v) is not None]
    if doses and not any(stated(v) for v in ctx.of("salt_or_base")):
        ctx.add("DOSE_BASIS_UNSTATED", doses, "doses with no stated basis (salt or free base)")


def _mg(value: ValueState, field_name: str) -> float | None:
    """A mass in mg: as written in mg, g or µg; a field whose name says mg with no unit; None otherwise (mg/kg)."""
    number = _number(value)
    if number is None:
        return None
    if not value.unit:
        return number if field_name.endswith("_mg") else None
    known = known_unit(field_name, value.unit)
    return number * MASS_UNITS[known] if known in MASS_UNITS else None


def _dose_not_multiple_of_strength(ctx: _Context) -> None:
    tolerance = ctx.rules.checks.dose_multiple_relative_tolerance
    products = {v.entity.product for v in ctx.values if v.entity.product}
    for dose in ctx.of("dose"):
        mg = _mg(dose, "dose")
        candidates = [dose.entity.product] if dose.entity.product else sorted(products) if len(products) == 1 else []
        strengths = [(s, n) for p in candidates if p for s in ctx.reader.values(product=p, field="strength_mg")
                     if (n := _mg(s, "strength_mg"))]
        if mg is None or not strengths:
            continue
        if not any(round(mg / n) >= 1 and abs(mg / n - round(mg / n)) <= tolerance * round(mg / n) for _, n in strengths):
            ctx.add("DOSE_NOT_MULTIPLE_OF_STRENGTH", (dose.id, *(s.id for s, _ in strengths)),
                    "the dose is not a whole number of units of the product's strength", detail=dose.id,
                    rule="checks.dose_multiple_relative_tolerance")


def _population_covariate_missing(ctx: _Context) -> None:
    tags = study_tags(ctx.reader, ctx.subject, brief=None)
    have = {v.field for v in ctx.values if stated(v)}
    for population in tag_values(tags, "special_population"):
        needs = ctx.rules.routing.population_covariates.get(population)
        if needs and not have & set(needs):
            ctx.add("POPULATION_COVARIATE_MISSING", (), f"a {population.replace('_', ' ')} study states none of "
                    f"{', '.join(needs)}", detail=population, rule="routing.population_covariates")


# --- dissolution and composition -----------------------------------------------------------------------------------


def _runs(ctx: _Context) -> dict[tuple[Any, ...], list[ValueState]]:
    out: dict[tuple[Any, ...], list[ValueState]] = {}
    for value in ctx.of(DISSOLVED):
        out.setdefault((value.entity.batch, tuple(sorted(value.conditions.items()))), []).append(value)
    return out


def _describe_run(ctx: _Context, run: tuple[Any, ...]) -> str:
    batch, conditions = run
    bits = [f"batch {ctx.label(batch)}"] if batch else []
    bits += [f"{k} {v}" for k, v in conditions]
    return ", ".join(bits) or "a run with no batch or conditions"


def _method_fields(rules: IntakeRules) -> tuple[str, ...]:
    """The dissolution method a run must state: the `conditions` the rules file asks of the dissolution items."""
    return tuple(dict.fromkeys(c for spec in rules.routing.item_fields.values() if DISSOLVED in spec.all
                               for c in spec.conditions))


def _dissolution_method_incomplete(ctx: _Context) -> None:
    needed = _method_fields(ctx.rules)
    for run, values in _runs(ctx).items():
        stated_ = {k for k, v in run[1] if str(v).strip()}
        missing = [c for c in needed if c not in stated_]
        if missing:
            ctx.add("DISSOLUTION_METHOD_INCOMPLETE", (), f"{_describe_run(ctx, run)}: no {', '.join(missing)} stated",
                    detail=f"{_detail(run)}|{judged(v.id for v in values)}", rule="routing.item_fields")


def _dissolution_out_of_range(ctx: _Context) -> None:
    ceiling = dissolution_rules()["profile"]["max_percent"]
    for run, values in _runs(ctx).items():
        out = []
        for value in values:
            number = _number(value)
            if number is None:
                continue
            percent = number * 100 if value.unit and known_unit(DISSOLVED, value.unit) == "" else number
            if percent < 0 or percent > ceiling:
                out.append(value.id)
        if out:
            ctx.add("DISSOLUTION_OUT_OF_RANGE", out, f"{_describe_run(ctx, run)}: values below zero or above the "
                    "ceiling of percent dissolved", detail=_detail(run), rule="dissolution_similarity.profile.max_percent")


def _dissolution_lot_not_clinical(ctx: _Context) -> None:
    clinical = {v.entity.batch for v in ctx.values if v.entity.study and v.entity.batch}
    if not clinical:
        return
    for batch in sorted({v.entity.batch for v in ctx.of(DISSOLVED) if v.entity.batch} - clinical):
        ctx.add("DISSOLUTION_LOT_NOT_CLINICAL", (), f"dissolution of batch {ctx.label(batch)}, which no clinical study "
                f"names (clinical: {', '.join(sorted(ctx.label(b) for b in clinical))})", detail=batch)


# The conditions `pbpk_domain.dissolution.ProfileKey` keys a dissolution profile by (read from the dataclass, never
# retyped); the product and its role are the subject's, the batch is the run's entity
_KEYED = tuple(f.name for f in dataclass_fields(ProfileKey) if f.name in CONDITION_FIELDS)


def _condition_value(text: str) -> object:
    """A condition as the landing compares it: a number as a number ("50" and "50.0" rpm are one), else its name key."""
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return name_key(text)


def _profile_key(run: tuple[Any, ...]) -> tuple[Any, ...]:
    conditions = dict(run[1])
    return (run[0], *(_condition_value(conditions.get(k, "")) for k in _KEYED))


def _unkeyed(run: tuple[Any, ...]) -> dict[str, object]:
    """A run's conditions that `ProfileKey` does not key, each as the landing compares it (`_condition_value`)."""
    return {name: _condition_value(str(value)) for name, value in run[1] if name not in _KEYED}


def _dissolution_runs_not_keyed(ctx: _Context) -> None:
    """Runs whose `ProfileKey` is equal while a condition it does not key (temperature, surfactant ...) differs by
    value. Runs that differ only in how a condition is written ("50" and "50.0" rpm) are one run, not this check."""
    keyed: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
    for run in _runs(ctx):
        keyed.setdefault(_profile_key(run), []).append(run)
    for key, runs in keyed.items():
        others = [_unkeyed(run) for run in runs]
        names = sorted({name for conditions in others for name in conditions})
        differ = [name for name in names if len({repr(conditions.get(name, "")) for conditions in others}) > 1]
        if differ:
            ctx.add("DISSOLUTION_RUNS_NOT_KEYED", (), f"runs share one profile key ({', '.join(_KEYED)}) and differ "
                    f"in {', '.join(differ)}, which it does not key: at the landing one would overwrite the other",
                    detail=_detail(key))


def _composition_sum(ctx: _Context) -> None:
    tolerance = ctx.rules.checks.composition_sum_tolerance_percent
    percent_table = unit_table("percentage") or {}
    groups: dict[str | None, list[ValueState]] = {}
    for value in ctx.of("composition.amount"):
        if _number(value) is not None:
            groups.setdefault(value.entity.batch, []).append(value)
    for batch, values in groups.items():
        percent = all(v.unit and percent_table.get(v.unit.strip().lower()) == "%" for v in values)
        totals = [v for v in values if _TOTAL.match(v.conditions.get("component", "").strip())]
        parts = [v for v in values if v not in totals]
        if percent:
            target, amount = 100.0, sum(_number(v) or 0.0 for v in parts)
        elif len(totals) == 1 and (total := _mg(totals[0], "composition.amount")):
            masses = [_mg(v, "composition.amount") for v in parts]
            if any(m is None for m in masses):
                continue
            target, amount = total, sum(m or 0.0 for m in masses)
        else:
            continue
        if parts and abs(amount - target) / target * 100 > tolerance:
            total = "a hundred percent" if percent else "its total row"
            ctx.add("COMPOSITION_SUM", (v.id for v in values), f"composition{f' of batch {ctx.label(batch)}' if batch else ''} "
                    f"does not sum to {total} within the tolerance", detail=batch or "",
                    rule="checks.composition_sum_tolerance_percent")


# --- units and values ----------------------------------------------------------------------------------------------


def _numeric(value: ValueState) -> bool:
    return value.censored or _number(value) is not None


def _unit_missing(ctx: _Context) -> None:
    by_field: dict[str, list[str]] = {}
    for value in ctx.values:
        if not _numeric(value):
            continue
        if unit_table(unit_class(value.field)) is not None and not (value.unit or "").strip() \
                and not _UNIT_IN_NAME.search(value.field):
            by_field.setdefault(value.field, []).append(value.id)
        if value.time is not None and not (value.time_unit or "").strip():
            by_field.setdefault("time", []).append(value.id)
    for name, ids in by_field.items():
        ctx.add("UNIT_MISSING", ids, f"{name}: values with no unit stated", detail=name)


def _unit_not_in_tables(ctx: _Context) -> None:
    found: dict[tuple[str, str], list[str]] = {}
    for value in ctx.values:
        if value.unit and unit_table(unit_class(value.field)) is not None and known_unit(value.field, value.unit) is None:
            found.setdefault((value.field, value.unit), []).append(value.id)
        if value.time is not None and value.time_unit and known_unit("time", value.time_unit) is None:
            found.setdefault(("time", value.time_unit), []).append(value.id)
    for (name, unit), ids in found.items():
        ctx.add("UNIT_NOT_IN_TABLES", ids, f"{name}: values in {unit!r}, which the {unit_class(name)} table does not "
                "hold; kept as written, nothing converted", detail=f"{name}|{unit}")


def _unit_not_checked(ctx: _Context) -> None:
    found: dict[tuple[str, str], list[str]] = {}
    for value in ctx.values:
        if value.unit and value.unit.strip() and unit_table(unit_class(value.field)) is None:
            found.setdefault((value.field, value.unit), []).append(value.id)
    for (name, unit), ids in found.items():
        ctx.add("UNIT_NOT_CHECKED", ids, f"{name}: values in {unit!r}; no unit table exists for this field, so the "
                "unit is kept and not checked", detail=f"{name}|{unit}")


def _marked_value(ctx: _Context) -> None:
    by_field: dict[str, list[str]] = {}
    for value in ctx.values:
        if value.method in _TABLE_METHODS and _MARK.search(value.verbatim):
            by_field.setdefault(value.field, []).append(value.id)
    for name, ids in by_field.items():
        ctx.add("MARKED_VALUE", ids, f"{name}: values carry a footnote mark: read the footnote", detail=name)


def _mapping_not_approved(ctx: _Context) -> None:
    by_mapping: dict[tuple[str, int] | None, list[str]] = {}
    for value in ctx.values:
        if value.level == "new_mapping":
            key = (value.mapping.mapping_id, value.mapping.version) if value.mapping is not None else None
            by_mapping.setdefault(key, []).append(value.id)
    for key, ids in by_mapping.items():
        which = f"mapping {key[0]} v{key[1]}" if key else "a table with no recorded mapping"
        ctx.add("MAPPING_NOT_APPROVED", ids, f"values read by {which}, which no person has approved",
                detail=f"{key[0]}@{key[1]}" if key else "")


def _mw_inconsistent(ctx: _Context) -> None:
    if ctx.mol_weight is None:
        return
    tolerance = ctx.rules.checks.mw_relative_tolerance
    odd = []
    for value in ctx.of("molecular_weight", "phys.mw"):
        number = _number(value)
        if number is None:
            continue
        if value.field == "molecular_weight" and value.entity.analyte is not None \
                and name_key(ctx.label(value.entity.analyte)) not in ctx.parents:
            continue                                     # a metabolite's own weight
        if abs(number - ctx.mol_weight) / ctx.mol_weight > tolerance:
            odd.append(value.id)
    if odd:
        ctx.add("MW_INCONSISTENT", odd, "molecular weights differ from the compound's by more than the tolerance (a "
                "salt form's weight?)", rule="checks.mw_relative_tolerance")


def _conflict_open(ctx: _Context) -> None:
    if ctx.subject_type == "study":
        conflicts = ctx.reader.conflicts(study=ctx.subject)
    elif ctx.subject_type == "product":
        conflicts = ctx.reader.conflicts(product=ctx.subject)
    else:
        conflicts = [c for c in ctx.reader.conflicts() if in_subject(c.entity, c.field, "compound", "compound")]
    for conflict in conflicts:
        ctx.add("CONFLICT_OPEN", conflict.values, f"{conflict.field}: values disagree ({conflict.kind}); a person "
                "chooses one", detail=conflict.id)


def _required_item_undisposed(ctx: _Context) -> None:
    ctx.results.extend(_required_items(ctx.reader, ctx.subject_type, ctx.subject, ctx.requirements, ctx.severity))


def _required_items(reader: LedgerReader, subject_type: str, subject: str, requirements: Sequence[RequirementStatus],
                    severity: dict[str, str]) -> list[CheckResult]:
    """One REQUIRED_ITEM_UNDISPOSED per missing REQUIRED item that applies to the subject (its id from the item's
    req_id alone, so the scorecard finds it from a disposition)."""
    level = severity.get("REQUIRED_ITEM_UNDISPOSED")
    if level is None:                        # the rules file does not list it: not run
        return []
    out = []
    for item in requirements:
        if item.scope != subject_type or item.subject is None:
            continue
        entity = reader.entity(item.subject)
        if (entity.id if entity is not None else item.subject) != subject:
            continue
        if item.status == "missing" and item.criticality == "REQUIRED" and item.applies == "yes":
            out.append(CheckResult(id=result_id("REQUIRED_ITEM_UNDISPOSED", subject, (), item.req_id),
                                   code="REQUIRED_ITEM_UNDISPOSED", severity=level, subject_type=subject_type,  # type: ignore[arg-type]
                                   subject=subject, message=f"{item.req_id} ({item.label}) is missing: send it, or "
                                   "record that it is asked of the client, taken from literature or not needed",
                                   rule="routing.item_scope"))
    return out


_Check = Callable[[_Context], None]
# Run on every subject's values
_GENERIC: tuple[_Check, ...] = (
    _unit_missing, _unit_not_in_tables, _statistic_missing, _spread_kind_missing, _negative_value, _above_range,
    _conflict_open, _required_item_undisposed, _mapping_not_approved, _mw_inconsistent, _marked_value, _unit_not_checked)
_STUDY: tuple[_Check, ...] = (
    _one_lloq_per_profile, _blq_without_lloq, _lloq_unit_differs, _duplicate_time, _matrix_not_plasma, _analyte_missing,
    _matrix_missing, _dose_missing, _infusion_time_missing, _landing_field_missing, _time_reference_unstated, _spreads,
    _n_missing, _nca_mismatch, _dose_basis_unstated, _dose_not_multiple_of_strength, _crossover_period_missing,
    _times_not_increasing, _excretion_not_landed, _occasions_not_landed, _zero_after_quantifiable,
    _population_covariate_missing, _analyte_not_parent, _blq_present, _duplicate_table_and_plot)
_PRODUCT: tuple[_Check, ...] = (
    _duplicate_time, _dissolution_method_incomplete, _dissolution_out_of_range, _n_missing, _dissolution_lot_not_clinical,
    _dissolution_runs_not_keyed, _composition_sum, _times_not_increasing)
_BY_SUBJECT: dict[str, tuple[_Check, ...]] = {"study": _STUDY, "product": _PRODUCT, "compound": ()}
