"""Score a delivery value by value against the analysts' key (plan 2026-11-12 G1, contracts §8.1 and §13).

Two adapters give the values code read, as `Extracted`: `from_ledger` (the new pipeline: the ledger's active values,
derived spread facts left out) and `from_stores` (the baseline: today's datasets, the points of sheets read and
waiting for a person, dissolution rows and records, and study facts). `score` compares them with a key
(`value_key.ValueKey`); `timings` and `coverage_totals` add the time per delivery and stage (G7) and the coverage
numbers (G2); `render` writes the report.

The join, never on the anchor: (study, arm, analyte, matrix, subject, product, batch, vessel, period, conditions,
field, time in minutes). Names compare by `document_reading.name_key`, codes (subject, vessel, period) by
`value_key.code_key` (punctuation counts: 1-01 is not 10-1), a study also by the other names its row of the key's
Studies sheet lists. The stores adapter has no arm (the arm is part of today's study id), so for it (`fold_arm`, which
the command sets for `--source stores` only) a key's (study, arm) also matches the study id name_key(study + arm).
Inside one join group key rows and values pair as multisets:
1. equal values with equal units first (`found`), so each repeat of the same value counts once; then values within
   the tolerance asked for (`found`, counted as found by tolerance);
2. then `found_rounded`: a value read from a workbook number cell (method `cell`, not a delimited file's text) whose
   stored number equals the key once rounded to the key's written decimals, half-even or half away from zero (decision
   R's nearest workable form, §11.30: 12.4037 under a 0.00 format shows 12.40, which the analyst writes; a
   spreadsheet shows 12.25 under 0.0 as 12.3, rounding a tie away from zero);
3. then a value that matches but in another unit (`wrong_unit`), then the rest in key-row order (`wrong_value`);
4. what is left: a key row is `missing`, except a missing token's (NS), which expects no value and is `found` (how
   "absent", counted apart); a value is `unexpected` when the key covers its place (a file and sheet or page of a key
   row or a Not data row; a value with no sheet or page: its file) and restates nothing (a `link.*` fact joins files,
   an `lloq` fact at a "<0.5" cell with that cell's LLOQ restates it: the analysts do not write either), otherwise it
   is outside the key (counted only).
Each step pairs, over all the group's open rows, a value of the row's own file that restates nothing first, then one
of another file, then values that restate; among those, the value whose attributes agree with the row's.

Beside the join, the attributes a key row states (occasion, sequence, statistic, spread, spread_kind, n) are checked
on the value paired with it and counted apart (`attributes_differ`): a mean with the wrong SD or n, an SE taken for an
SD, a geometric mean for an arithmetic one, Day 1 for Day 14. The join itself is §13's. Two diagnostics change no
verdict: `labels_differ`, a missing row whose value was read with the same study, subject, field, time and value but a
label the value or the row leaves empty (today's stores keep labels another way than the key), and `places_unread`, a
key's sheet or page where no value of that file was read (a typo, a page not read).

Values compare exactly on the written decimal (Decimal: 12.40 equals 12.4); `tolerance` (relative, off by default)
applies to every value but a digitized one, `digitized_tolerance` to digitized values. A BLQ form expects a censored
value (and its LLOQ when the key writes "<0.5"), ">x" a value above the range at x, a missing token no value; a name
or a choice compares as `value_key.text_key` reads it. Units compare through the table of the field's class
(`fields.known_unit`), else as case-folded text: nothing is converted. A key row the scorer cannot use (no value, a
value that is no form of a number, a time that is not a number or has no known unit) is listed, never dropped. There
is no pass threshold here: G1 sets the target after the baseline.

The default report is what leaves the server: counts, field names, verdicts, methods and anchors only (a sheet's
name in an anchor is replaced by its number in the report, `s:#1` for the first sheet of that file it names, since a
sheet is often named after a study), a study by the number of the first key row naming it, a routing tag's value only when it is a word of the
field's vocabulary, a value's id only when it is a ledger id (`tx-...#i`, `f-n`; any other, which may be built from
labels, by its number in the report). It holds no value, no label, no file name and no analyst. `with_values` adds
them, to read on the server only. The command checks the hash chains of the intake logs first and refuses to score a
broken one unless `--accept-broken-chain` is given; the report then says so at its top.

    uv run python -m modeler_project.value_score --root R --project P [--tenant T] --key K.xlsx [--source ledger|stores]
        [--tolerance X] [--digitized-tolerance X] [--compare K2.xlsx] [--template OUT.xlsx] [--with-values] [--json]
        [--out F] [--accept-broken-chain]
Read-only: nothing is written in the root.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from modeler_intake.anchors import (
    ID_PATTERNS,
    AnchorError,
    FigureRef,
    PdfCell,
    PdfSpan,
    SheetCell,
    format_locator,
    parse_anchor,
)
from modeler_intake.document_reading import name_key
from modeler_intake.fields import read_choice
from modeler_intake.source_model import number_text
from modeler_project.client_data import submissions
from modeler_project.dataset_register import datasets
from modeler_project.evidence import EvidenceState
from modeler_project.intake_records import CoverageSummary, RunRecord
from modeler_project.intake_store import IntakeStore
from modeler_project.key_compare import compare, render_comparison
from modeler_project.ledger_view import LedgerView, is_spread_fact
from modeler_project.reading_queue import ReadingQueue
from modeler_project.sheet_intake import drafts
from modeler_project.store import FileProjectStore
from modeler_project.value_key import (
    ATTRIBUTE_COLUMNS,
    LABEL_COLUMNS,
    KeyRow,
    Mark,
    Reading,
    ValueKey,
    ValueKeyError,
    clean,
    conditions_key,
    file_key,
    format_conditions,
    key_marks,
    label_key,
    load_key,
    norm_text,
    parse_conditions,
    read_value,
    split_conditions,
    spread_kind_key,
    statistic_key,
    study_groups,
    template_workbook,
    time_minutes,
    to_decimal,
    unit_key,
    where_places,
)
from modeler_project.workspace import Workspace
from pbpk_domain.units import UnitError, minutes_per

SCORE_SCHEMA = "value-score/1"
Verdict = Literal["found", "found_rounded", "wrong_value", "wrong_unit", "missing", "unexpected"]
VERDICTS: tuple[Verdict, ...] = ("found", "found_rounded", "wrong_value", "wrong_unit", "missing", "unexpected")
NO_STUDY = "(no study)"
NOT_IN_KEY = "(not in the key)"
NOT_STATED = "(not stated)"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_WORKBOOK_SUFFIXES = (".xlsx", ".xlsm", ".xls")
_LOGS = ("files", "runs", "mappings", "facts", "entities", "review")       # the intake's hash-chained logs
_SUMMARY_FIELDS = ("regions", "regions_mapped", "regions_excluded", "regions_unread", "numeric_cells", "cells_used",
                   "cells_excluded", "cells_silent", "silent_loss", "outside_items", "outside_numeric", "values_unassigned",
                   "anchors_unresolved")


class Extracted(BaseModel):
    """One value code read, as the scorer compares it. `value` is the number as code read it (its shortest round-trip
    text) or the text of a name or a choice, None for no value; `verbatim` the cell or sentence as written."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    study: str
    arm: str
    analyte: str
    matrix: str
    subject: str
    product: str = ""                     # §13: the key's five optional columns, defaulted
    batch: str = ""
    vessel: str = ""
    period: str = ""
    occasion: str = ""                    # checked beside the join, as the key's attribute columns
    sequence: str = ""
    conditions: str = ""                  # name=value pairs joined by ";" (value_key.format_conditions)
    field: str
    time_min: float | None
    value: str | None
    verbatim: str
    censored: bool
    lloq: str | None
    unit: str | None
    method: str
    anchor: str | None
    id: str
    uloq: str | None = None               # ">x" read: value None, uloq x (contracts §6.2)
    lloq_unit: str | None = None
    statistic: str = ""                   # the attributes checked beside the join (value_key.ATTRIBUTE_COLUMNS)
    spread: str | None = None
    spread_kind: str = ""
    n: str | None = None


# --- the values code read --------------------------------------------------------------------------------------------


def _value_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return number_text(value)
    return str(value)


def _minutes(time: float | None, unit: str | None) -> float | None:
    """A time in minutes; None with no time, and with a unit that is not known (the value then joins no timed row)."""
    if time is None or not unit:
        return None
    try:
        return round(time * minutes_per(unit), 6)
    except UnitError:
        return None


def _file_names(store: IntakeStore) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in store.files.entries("file"):
        names.setdefault(str(line.body.get("sha256", "")), str(line.body.get("name", "")))
    return names


def from_ledger(ws: Workspace) -> list[Extracted]:
    """The ledger's active values (`LedgerView`), proposed or confirmed, each with the labels of its entity; a derived
    spread fact is not a value of its own and is left out (`ledger_view.is_spread_fact`)."""
    view = LedgerView(ws)
    names = _file_names(view.store)

    def label(entity_id: str | None) -> str:
        found = view.entity(entity_id) if entity_id else None
        return found.label if found is not None else ""

    out = []
    for v in view.values():
        if is_spread_fact(v):
            continue
        e = v.entity
        out.append(Extracted(
            file=names.get(v.file_sha256 or "", ""), study=label(e.study), arm=label(e.arm), analyte=label(e.analyte),
            matrix=e.matrix or "", subject=e.subject or "", product=label(e.product), batch=label(e.batch),
            vessel=e.vessel or "", period=e.period or "", occasion=e.occasion or "", sequence=e.sequence or "",
            conditions=format_conditions(sorted(v.conditions.items())), field=v.field,
            time_min=_minutes(v.time, v.time_unit), value=_value_text(v.value), verbatim=v.verbatim, censored=v.censored,
            lloq=_value_text(v.lloq), unit=v.unit, method=v.method, anchor=v.anchor, id=v.id, uloq=_value_text(v.uloq),
            lloq_unit=v.lloq_unit, statistic=v.statistic or "", spread=_value_text(v.spread),
            spread_kind=v.spread_kind or "", n=_value_text(v.n_at)))
    return out


# today's study-record and fact names -> the ledger's field (and the unit the stored number is in)
_RECORD_FIELDS = {"dose_mg": "dose", "n": "n", "route": "route", "food_state": "food_state", "formulation": "formulation",
                  "design": "design", "infusion_time_min": "infusion_time_min", "lloq": "lloq",
                  "population_type": "population", "reference": "reference", "crossover": "crossover",
                  "dosing_interval_h": "dosing_interval_h", "n_doses": "n_doses",
                  "special_population": "special_population", "meal_type": "meal_type"}
_FACT_FIELDS = {"dose_mg": "dose", "n": "n", "age_mean": "age_mean", "age_min": "age_min", "age_max": "age_max",
                "weight_mean": "weight_mean_kg", "height_mean": "height_mean_cm", "females": "n_female",
                "female_percent": "percent_female", "ethnicity": "ethnicity", "lloq": "lloq", "route": "route",
                "food_state": "food_state", "formulation": "formulation", "design": "design"}
_DISSOLUTION_CONDITIONS = ("apparatus", "rpm", "medium", "ph", "volume_ml", "temperature_c", "surfactant")
_EXTRACTION_METHOD = {"CELL": "cell", "FIGURE_DIGITIZED": "digitized", "MANUAL": "person", "OSP_SNAPSHOT": "person"}


def _spread(errors: Sequence[Any] | None, kind: str | None, i: int) -> dict[str, Any]:
    """The i-th spread of a stored series, as Extracted's attributes."""
    if not errors or not kind or kind == "none" or i >= len(errors) or errors[i] is None:
        return {}
    return {"spread": _value_text(errors[i]), "spread_kind": str(kind)}


def _variability(text: str) -> dict[str, Any]:
    """A reported PK parameter's variability as today's stores keep it ("18.2 CV%"): its number and kind."""
    number, _sep, kind = (text or "").strip().partition(" ")
    return {"spread": number, "spread_kind": kind.strip()} if to_decimal(number, "point") is not None else {}


def _table_method(file: str) -> str:
    suffix = PurePosixPath(file).suffix.lower()
    return {".pdf": "pdf_table", ".docx": "docx_table"}.get(suffix, "cell")


def from_stores(ws: Workspace) -> list[Extracted]:
    """The baseline: what today's pipeline stores, as values. Client datasets not rejected (their series points, their
    reported PK parameters and the facts of their study record), the points of sheets read and waiting for a person,
    the template's dissolution rows and the dissolution records of mapped sheets, and the files' study facts. Today's
    stores keep no anchor per value and no arm (it is part of the study id): `anchor` is None and `arm` "". Each
    study-record fact is listed once per file, study and value."""
    subs = submissions(ws)
    name_of = {str(s.get("sha256", "")): str(s.get("file", "")) for s in subs}
    out: list[Extracted] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(**values: Any) -> None:
        defaults = dict(study="", arm="", subject="", analyte="", matrix="", time_min=None, censored=False, lloq=None,
                        unit=None, anchor=None, verbatim=values.get("value") or "")
        out.append(Extracted(**{**defaults, **values}))

    def fact(file: str, study: str, field: str, value: Any, unit: str | None, method: str, id: str) -> None:
        text = _value_text(value)
        if text is None or (file, name_key(study), field, text) in seen:
            return
        seen.add((file, name_key(study), field, text))
        add(file=file, study=study, field=field, value=text, unit=unit, method=method, id=id)

    for d in datasets(ws):
        if d.provider != "CLIENT" or d.state is EvidenceState.REJECTED:
            continue
        file = name_of.get(d.source.doc_sha256 or "", "")
        study = str(d.study.get("study_id", ""))
        method = _table_method(file) if d.extraction == "TABLE" else _EXTRACTION_METHOD.get(d.extraction, "cell")
        lloq = _value_text(d.study.get("lloq"))
        for s in d.series:
            subject = s.name if s.statistic == "individual" else ""
            for i, (t, v) in enumerate(zip(s.times, s.values, strict=False)):
                add(file=file, study=study, analyte=d.analyte, matrix=d.matrix, subject=subject, field="concentration",
                    time_min=_minutes(t, d.time_unit), value=_value_text(v), verbatim=_value_text(v) or "BLQ",
                    censored=v is None, lloq=lloq if v is None else None, unit=d.unit, method=method,
                    id=f"{d.id}/{s.name}#{i}", statistic=s.statistic, n=_value_text(s.n),
                    **_spread(s.error, s.error_kind, i))
        for r in d.reported:
            add(file=file, study=study, analyte=d.analyte, matrix=d.matrix, field=f"pk.{r.parameter}",
                value=_value_text(r.value), unit=r.unit, method=method, id=f"{d.id}/pk.{r.parameter}",
                statistic=r.statistic, **_variability(r.variability))
        for key, field in _RECORD_FIELDS.items():
            value = d.study.get(key)
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                value = "yes" if value else "no"
            unit = ("mg/kg" if d.study.get("dose_per_kg") else "mg") if key == "dose_mg" else \
                (d.study.get("lloq_unit") or d.unit) if key == "lloq" else None
            fact(file, study, field, value, unit, method, f"{d.id}/{key}")

    for w in drafts(ws):
        points = w.get("points") or {}
        if not points.get("series"):
            continue
        sub = next((s for s in subs if s.get("id") == w["sid"]), {})
        constants = ((sub.get("readings") or {}).get(w["sheet"], {}).get("form") or {}).get("constants") or {}
        lloq = _value_text((points.get("study") or {}).get("lloq"))
        for s in points["series"]:
            subject = s.get("name", "") if s.get("statistic") == "individual" else ""
            for i, (t, v) in enumerate(zip(s.get("times", []), s.get("values", []), strict=False)):
                add(file=w["file"], study=w["study_id"], analyte=str(constants.get("analyte", "")),
                    matrix=str(constants.get("matrix", "")), subject=subject, field="concentration",
                    time_min=_minutes(t, points.get("time_unit")), value=_value_text(v),
                    verbatim=_value_text(v) or "BLQ", censored=v is None, lloq=lloq if v is None else None,
                    unit=points.get("unit"), method="cell", id=f"{w['sid']}/{w['sheet']}/{s.get('name', '')}#{i}",
                    statistic=str(s.get("statistic") or ""), n=_value_text(s.get("n")),
                    **_spread(s.get("error"), s.get("error_kind"), i))

    for sub in subs:
        file = str(sub.get("file", ""))
        for row in sub.get("dissolution", []):
            values = row.get("values") or {}
            conditions = format_conditions([(c, _value_text(values[c]) or "") for c in _DISSOLUTION_CONDITIONS
                                            if values.get(c) not in (None, "")])
            time_min = _minutes(values.get("time"), values.get("time_unit"))
            for column in [c for c in values if re.fullmatch(r"vessel_\d+", c)] + ["mean"]:
                if values.get(column) is None:
                    continue
                add(file=file, product=str(values.get("product") or ""), batch=str(values.get("batch") or ""),
                    vessel=column if column != "mean" else "", conditions=conditions, field="percent_dissolved",
                    time_min=time_min, value=_value_text(values[column]), method="cell",
                    id=f"{sub.get('id')}/dissolution/{row.get('row')}/{column}",
                    statistic="individual" if column != "mean" else "arithmetic_mean")
        for i, record in enumerate(sub.get("dissolution_records", [])):
            conditions = format_conditions([(c, _value_text(record[c]) or "") for c in _DISSOLUTION_CONDITIONS
                                            if record.get(c) not in (None, "")])
            add(file=file, product=str(record.get("product") or ""), batch=str(record.get("batch") or ""),
                vessel=str(record.get("vessel") or ""), conditions=conditions, field="percent_dissolved",
                time_min=_minutes(record.get("time"), record.get("time_unit")),
                value=_value_text(record.get("percent_dissolved")), method="cell", id=f"{sub.get('id')}/record/{i}",
                statistic="individual" if record.get("vessel") else str(record.get("statistic") or ""))
        for i, f in enumerate(sub.get("study_facts", [])):
            sets = f.get("sets") or {}
            method = "cell" if f.get("locator") else "prose"
            for key, value in sets.items():
                field = _FACT_FIELDS.get(key)
                if field is None:
                    continue
                unit = ("mg/kg" if sets.get("dose_per_kg") else "mg") if key == "dose_mg" else \
                    (sets.get("lloq_unit") or None) if key == "lloq" else None
                fact(file, str(f.get("study_id", "")), field, value, unit, method, f"{sub.get('id')}/fact/{i}/{key}")
    return out


# --- the score -------------------------------------------------------------------------------------------------------

JoinKey = tuple[Any, ...]


def _code_number(text: str | None) -> Decimal | None:
    """A number code wrote (`number_text`: a decimal point, never a group separator)."""
    return to_decimal(text, "point") if text else None


def _found_reading(e: Extracted) -> Reading:
    """What code read, as the key's readings are compared: a censored value is BLQ (with its LLOQ), a value None with
    a `uloq` is above the range at it, any other value None is "no value"."""
    if e.censored:
        return Reading("blq", _code_number(e.lloq))
    if e.value is None:
        return Reading("above", _code_number(e.uloq)) if e.uloq is not None else Reading("missing")
    return read_value(e.field, e.value, "point")


def _rounds(e: Extracted) -> bool:
    """Whether a value is a workbook number cell's stored value (decision R): method cell, and an anchor that is not a
    delimited file's; with no anchor (today's stores) or one that does not parse, a workbook's file name (.xlsx, .xlsm,
    .xls)."""
    if e.method != "cell":
        return False
    try:
        parser = parse_anchor(e.anchor).parser if e.anchor else None
    except AnchorError:
        parser = None
    if parser is not None:
        return parser != "delimited"
    return PurePosixPath(e.file.replace("\\", "/")).suffix.lower() in _WORKBOOK_SUFFIXES


def _rounded_equal(found: Decimal, key: Decimal) -> bool:
    """Whether a stored number equals the key's once rounded to the key's written decimals, half-even (the contract's
    text) or half away from zero (how a spreadsheet's number format shows a tie: 12.25 under 0.0 is 12.3)."""
    try:
        quantum = Decimal(1).scaleb(key.as_tuple().exponent)      # type: ignore[arg-type]
        return any(found.quantize(quantum, rounding=mode) == key for mode in (ROUND_HALF_EVEN, ROUND_HALF_UP))
    except InvalidOperation:
        return False


def _match(k: Reading, f: Reading, e: Extracted, tolerance: float, digitized_tolerance: float
           ) -> Literal["exact", "tolerance", "rounded"] | None:
    """How a value meets the key's value, units aside: exactly, within the tolerance asked for, after rounding, or not."""
    if k.kind != f.kind:
        return None
    if k.kind == "text":
        return "exact" if k.text == f.text else None
    if k.kind == "missing":
        return "exact"
    if k.kind in ("blq", "above"):
        return "exact" if k.number is None or k.number == f.number else None
    if k.number is None or f.number is None:
        return None
    if k.number == f.number:
        return "exact"
    tol = digitized_tolerance if e.method == "digitized" else tolerance
    if tol > 0 and abs(f.number - k.number) <= Decimal(repr(tol)) * abs(k.number):
        return "tolerance"
    if _rounds(e) and _rounded_equal(f.number, k.number):
        return "rounded"
    return None


def _unit_ok(r: KeyRow, reading: Reading, e: Extracted) -> bool:
    """Whether a value's unit is the key row's (through the field's unit table): for a "<0.5" row, the LLOQ's unit
    when the value states one."""
    unit = e.lloq_unit if reading.kind == "blq" and reading.number is not None and e.lloq_unit else e.unit
    return unit_key(r.field, r.unit) == unit_key(r.field, unit)


def _attribute_diffs(r: KeyRow, e: Extracted, mark: Mark | None) -> tuple[str, ...]:
    """The attributes a key row states (value_key.ATTRIBUTE_COLUMNS) that the value paired with it does not have:
    statistic and spread_kind by their names (statistic_key, spread_kind_key), spread by its number (exact, or
    rounded for a workbook cell, as a value is), n as a whole number, occasion and sequence as codes. An attribute the
    row leaves empty is not checked."""
    out = []
    for name in ATTRIBUTE_COLUMNS:
        stated = clean(getattr(r, name))
        if not stated:
            continue
        found = getattr(e, name) or ""
        if name == "statistic":
            same = statistic_key(stated) == statistic_key(found)
        elif name == "spread_kind":
            same = spread_kind_key(stated) == spread_kind_key(found)
        elif name in ("spread", "n"):
            k, f = to_decimal(stated, mark), _code_number(found)
            same = k is not None and f is not None and (k == f or (name == "spread" and _rounds(e) and _rounded_equal(f, k)))
        else:
            same = label_key(name, stated) == label_key(name, found)
        if not same:
            out.append(name)
    return tuple(out)


def _place(e: Extracted) -> tuple[str, str] | None:
    """The sheet or page a value's anchor names; None for a Word or text file, or a value with no anchor."""
    if not e.anchor:
        return None
    try:
        locator = parse_anchor(e.anchor).locator
    except AnchorError:
        return None
    if isinstance(locator, SheetCell):
        return ("sheet", norm_text(locator.sheet))
    if isinstance(locator, PdfCell | PdfSpan) or (isinstance(locator, FigureRef) and locator.page is not None):
        return ("page", str(locator.page))
    return None


def _conditions(text: str) -> dict[str, str]:
    """A conditions text as name -> value: the key's (checked at load), or a value's as the ledger wrote it."""
    try:
        return parse_conditions(text)
    except ValueError:
        pairs = (part.partition("=") for part in split_conditions(text))
        return {name.strip().lower(): value.strip() for name, _sep, value in pairs}


def _file_keys(name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((file_key(name), file_key(PurePosixPath(name.replace("\\", "/")).name))))


class _Coverage:
    """The places a key covers: per file, the sheets and pages its Key and Not data rows name (or the whole file)."""

    def __init__(self, key: ValueKey):
        self.places: dict[str, set[tuple[str, str]]] = {}
        self.whole: set[str] = set()
        for file, where in [(r.file, r.where) for r in key.rows] + [(n.get("file", ""), n.get("where", ""))
                                                                     for n in key.not_data]:
            if not clean(file):
                continue
            for name in _file_keys(file):
                places = where_places(where)
                if places:
                    self.places.setdefault(name, set()).update(places)
                else:
                    self.whole.add(name)

    def covers(self, e: Extracted) -> bool:
        names = [n for n in _file_keys(e.file) if n in self.whole or n in self.places] if e.file else []
        if not names:
            return False
        place = _place(e)
        return place is None or any(n in self.whole or place in self.places.get(n, set()) for n in names)


def _lloqs_at(extracted: Sequence[Extracted]) -> dict[str, list[tuple[Decimal, str | None]]]:
    """The LLOQ and its unit of each censored value that states one, by its anchor ("<0.5" read at a cell)."""
    out: dict[str, list[tuple[Decimal, str | None]]] = {}
    for e in extracted:
        lloq = _code_number(e.lloq)
        if e.censored and e.anchor and lloq is not None:
            out.setdefault(e.anchor, []).append((lloq, e.lloq_unit or e.unit))
    return out


def _restates(e: Extracted, lloqs_at: dict[str, list[tuple[Decimal, str | None]]]) -> bool:
    """Whether a value only restates what the ledger links or what another value holds, so that the analysts do not
    write it: a `link.*` fact (it joins a file to a study another file named), or an `lloq` fact anchored at a censored
    value's own cell with that value's LLOQ and unit (a "<0.5" token's LLOQ, which the key's "<0.5" row already
    checks; a different number there is an ordinary value). Never unexpected; scored when a key row names it."""
    if e.field.startswith("link."):
        return True
    if e.field != "lloq" or not e.anchor or e.anchor not in lloqs_at:
        return False
    number = _code_number(e.value)
    return number is not None and any(
        number == lloq and (not unit or not e.unit or unit_key("lloq", unit) == unit_key("lloq", e.unit))
        for lloq, unit in lloqs_at[e.anchor])


def _same_file(row: KeyRow, e: Extracted) -> bool:
    return bool(row.file) and bool(set(_file_keys(row.file)) & set(_file_keys(e.file)))


def _pair(members: Sequence[tuple[KeyRow, Reading, float | None]], candidates: Sequence[int], used: list[bool],
          extracted: Sequence[Extracted], readings: Sequence[Reading], restating: Sequence[bool], tolerance: float,
          digitized_tolerance: float, marks: dict[int, Mark | None]) -> dict[int, tuple[str, str, int | None]]:
    """Pair one join group's key rows with its values as multisets (the module docstring's steps 1 to 4): key row ->
    (verdict, how, the index of its value). Each step runs over all the open rows four times: values of the row's own
    file that restate nothing, then of another file, then restating values of the row's file, then of another; a row
    takes, of those, the value whose attributes agree with it most. Marks the values it takes in `used`."""
    out: dict[int, tuple[str, str, int | None]] = {}
    open_rows = list(members)

    def tier(r: KeyRow, i: int) -> int:
        return 2 * restating[i] + (not _same_file(r, extracted[i]))

    def take(test: Callable[[KeyRow, Reading, int], str | None], verdict: str) -> None:
        for wanted in range(4):
            for member in list(open_rows):
                r, reading, _minutes = member
                hits = [(i, how) for i in candidates
                        if not used[i] and tier(r, i) == wanted and (how := test(r, reading, i)) is not None]
                if not hits:
                    continue
                i, how = min(hits, key=lambda hit: len(_attribute_diffs(r, extracted[hit[0]], marks.get(r.row))))
                used[i] = True
                open_rows.remove(member)
                out[r.row] = (verdict, how, i)

    def matching(wanted: str) -> Callable[[KeyRow, Reading, int], str | None]:
        def test(r: KeyRow, reading: Reading, i: int) -> str | None:
            how = _match(reading, readings[i], extracted[i], tolerance, digitized_tolerance)
            return how if how == wanted and _unit_ok(r, reading, extracted[i]) else None
        return test

    def other_unit(r: KeyRow, reading: Reading, i: int) -> str | None:
        how = _match(reading, readings[i], extracted[i], tolerance, digitized_tolerance)
        return "unit" if how is not None and not _unit_ok(r, reading, extracted[i]) else None

    take(matching("exact"), "found")
    take(matching("tolerance"), "found")
    take(matching("rounded"), "found_rounded")
    take(other_unit, "wrong_unit")
    take(lambda r, reading, i: "value", "wrong_value")
    for r, reading, _minutes in open_rows:
        # a missing token (NS) expects no value: nothing read is what the key says
        out[r.row] = ("found", "absent", None) if reading.kind == "missing" else ("missing", "", None)
    return out


def _counts() -> dict[str, int]:
    return {v: 0 for v in VERDICTS}


def score(key: ValueKey, extracted: Sequence[Extracted], *, tolerance: float = 0.0,
          digitized_tolerance: float = 0.0, fold_arm: bool = False) -> dict[str, Any]:
    """Score the values code read against the key (see the module docstring): per key row its verdict, the value it
    was paired with and the attributes that differ; the values unexpected; the key rows the scorer cannot use; the
    two diagnostics (labels_differ, places_unread); totals by field, by study, by each Studies tag, by method and by
    attribute. `fold_arm`: also match a key's (study, arm) against the study id name_key(study + arm), for today's
    stores, which keep the arm in the study id. Plain data, for JSON or `render`."""
    for name, value in (("tolerance", tolerance), ("digitized_tolerance", digitized_tolerance)):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} is a relative tolerance, 0 or more: {value!r}")
    groups_of = study_groups(key)
    marks = key_marks(key.rows)

    def study_key(label: str) -> str:
        return groups_of.get(name_key(label), name_key(label))

    def labels(source: Any) -> tuple[str, ...]:
        return tuple(study_key(source.study) if col == "study" else label_key(col, getattr(source, col))
                     for col in LABEL_COLUMNS)

    def join(source: Any, time_min: float | None) -> JoinKey:
        return (*labels(source), conditions_key(_conditions(source.conditions)), source.field, time_min)

    # the key's studies: a display label (the Studies sheet's spelling, else the first key row's) and its first row
    study_label: dict[str, str] = {}
    study_row: dict[str, int] = {}
    for s in key.studies:
        study_label.setdefault(study_key(s["study"]), s["study"])
    for r in key.rows:
        if clean(r.study):
            sk = study_key(r.study)
            study_label.setdefault(sk, r.study)
            study_row.setdefault(sk, r.row)
    tags = [t for t in (key.studies[0] if key.studies else {}) if t not in ("study", "names", "row")]
    tag_of: dict[str, dict[str, str]] = {study_key(s["study"]): s for s in key.studies}

    # usable key rows, grouped by their join key in key-row order
    unusable: list[dict[str, Any]] = []
    groups: dict[JoinKey, list[tuple[KeyRow, Reading, float | None]]] = {}
    alt_of: dict[JoinKey, JoinKey | None] = {}
    for r in key.rows:
        reading = read_value(r.field, r.value, marks[r.row])
        if reading.kind == "empty":
            unusable.append({"row": r.row, "field": r.field, "reason": "the value is empty"})
            continue
        if reading.kind == "unreadable":
            unusable.append({"row": r.row, "field": r.field,
                             "reason": "the value is not a number, a BLQ form, an above-range form or a missing token"})
            continue
        if reading.kind == "ambiguous":
            unusable.append({"row": r.row, "field": r.field,
                             "reason": "the value's separator is ambiguous (1,234 or 1.234) and no other number of its "
                                       "table settles it: write it without a thousands separator"})
            continue
        try:
            minutes = time_minutes(r.time, r.time_unit, marks[r.row])
        except ValueError as exc:
            unusable.append({"row": r.row, "field": r.field, "reason": str(exc)})
            continue
        primary = join(r, minutes)
        groups.setdefault(primary, []).append((r, reading, minutes))
        if fold_arm and clean(r.arm) and primary not in alt_of:
            alt_of[primary] = (study_key(r.study + r.arm), "", *primary[2:])
        alt_of.setdefault(primary, None)

    index: dict[JoinKey, list[int]] = {}
    for i, e in enumerate(extracted):
        index.setdefault(join(e, e.time_min), []).append(i)
    readings = [_found_reading(e) for e in extracted]
    lloqs_at = _lloqs_at(extracted)
    restating = [_restates(e, lloqs_at) for e in extracted]
    used = [False] * len(extracted)
    rows_out: list[dict[str, Any]] = []
    verdict_of: dict[int, tuple[str, str, int | None]] = {}     # key row -> (verdict, how, extracted index)

    for primary, members in groups.items():
        alt = alt_of.get(primary)
        candidates = list(dict.fromkeys(index.get(primary, []) + (index.get(alt, []) if alt else [])))
        verdict_of.update(_pair(members, candidates, used, extracted, readings, restating, tolerance,
                                digitized_tolerance, marks))

    labels_differ = _labels_differ(groups, verdict_of, extracted, readings, used, restating, study_key,
                                   tolerance=tolerance, digitized_tolerance=digitized_tolerance, fold_arm=fold_arm)
    coverage = _Coverage(key)
    unexpected: list[int] = []
    outside = 0
    for i, e in enumerate(extracted):
        if used[i]:
            continue
        if coverage.covers(e) and not restating[i]:
            unexpected.append(i)
        else:
            outside += 1

    # totals
    totals = {**_counts(), "found_by_tolerance": 0, "found_absent": 0}
    by_field: dict[str, dict[str, int]] = {}
    by_study: dict[str, dict[str, int]] = {}
    by_method: dict[str, dict[str, int]] = {}
    by_tag: dict[str, dict[str, dict[str, int]]] = {t: {} for t in tags}
    by_attribute = dict.fromkeys(ATTRIBUTE_COLUMNS, 0)

    def count(verdict: str, field: str, study: str, method: str) -> None:
        totals[verdict] += 1
        for table, name in ((by_field, field), (by_study, study), (by_method, method)):
            table.setdefault(name, _counts())[verdict] += 1
        for tag in tags:
            value = clean(tag_of[study].get(tag, "")) if study in tag_of else ""
            by_tag[tag].setdefault(value or NOT_STATED, _counts())[verdict] += 1

    def found_part(i: int) -> dict[str, Any]:
        e = extracted[i]
        return {"id": e.id, "value": e.value, "verbatim": e.verbatim, "unit": e.unit, "censored": e.censored,
                "lloq": e.lloq, "uloq": e.uloq, "method": e.method, "anchor": e.anchor, "file": e.file,
                "labels": {c: getattr(e, c) for c in (*LABEL_COLUMNS, "conditions")}, "time_min": e.time_min,
                "attributes": {c: getattr(e, c) for c in ATTRIBUTE_COLUMNS if getattr(e, c) not in ("", None)}}

    usable = {r.row for members in groups.values() for r, _reading, _m in members}
    attributes_differ = 0
    for r in key.rows:
        if r.row not in usable:
            continue
        verdict, how, i = verdict_of[r.row]
        sk = study_key(r.study) if clean(r.study) else ""
        count(verdict, r.field, sk or NO_STUDY, extracted[i].method if i is not None else "(none)")
        if how == "tolerance":
            totals["found_by_tolerance"] += 1
        if how == "absent":
            totals["found_absent"] += 1
        differ = _attribute_diffs(r, extracted[i], marks[r.row]) if i is not None else ()
        for name in differ:
            by_attribute[name] += 1
        attributes_differ += bool(differ)
        rows_out.append({
            "row": r.row, "verdict": verdict, "how": how, "field": r.field, "study": sk,
            "attributes_differ": list(differ),
            "expected": {"value": r.value, "unit": r.unit, "time": r.time, "time_unit": r.time_unit, "file": r.file,
                         "where": r.where, "table": r.table,
                         "labels": {c: getattr(r, c) for c in (*LABEL_COLUMNS, "conditions")},
                         "attributes": {c: getattr(r, c) for c in ATTRIBUTE_COLUMNS if getattr(r, c)}},
            "found": found_part(i) if i is not None else None})
    unexpected_out = []
    for i in unexpected:
        e = extracted[i]
        sk = study_key(e.study) if clean(e.study) else ""
        bucket = sk if sk in study_label else (NOT_IN_KEY if sk else NO_STUDY)
        count("unexpected", e.field, bucket, e.method)
        unexpected_out.append({"field": e.field, "study": bucket, **found_part(i)})
    labels_out = [{"row": r.row, "field": r.field, "study": study_key(r.study) if clean(r.study) else "",
                   "labels": names, "found": found_part(i)} for r, i, names in labels_differ]
    places_unread = _places_unread(key, extracted)

    totals.update(key_rows=len(key.rows), unusable=len(unusable), scored=len(usable), extracted=len(extracted),
                  outside_key=outside, errors=totals["wrong_value"] + totals["wrong_unit"] + totals["unexpected"],
                  omissions=totals["missing"], attributes_differ=attributes_differ, labels_differ=len(labels_out),
                  places_unread=len(places_unread))
    tag_rows: dict[str, dict[str, int]] = {}
    for tag in tags:
        for s in key.studies:
            value = clean(s.get(tag, ""))
            if value:
                tag_rows.setdefault(tag, {}).setdefault(value, int(s["row"]))
    return {
        "schema": SCORE_SCHEMA,
        "key": {"schema": key.schema_id, "delivery": key.delivery, "analyst": key.analyst, "date": key.date,
                "status": key.status, "rows": len(key.rows), "not_data": len(key.not_data)},
        "options": {"tolerance": tolerance, "digitized_tolerance": digitized_tolerance, "fold_arm": fold_arm},
        "totals": totals,
        "by_field": dict(sorted(by_field.items())),
        "by_study": dict(sorted(by_study.items(), key=lambda item: (item[0] in (NO_STUDY, NOT_IN_KEY),
                                                                   study_row.get(item[0], 0), item[0]))),
        "by_tag": by_tag,
        "by_method": dict(sorted(by_method.items())),
        "by_attribute": by_attribute,
        "studies": {sk: {"label": study_label.get(sk, ""), "row": study_row.get(sk)} for sk in study_label},
        "tag_rows": tag_rows,
        "rows": rows_out,
        "unexpected": unexpected_out,
        "unusable": unusable,
        "labels_differ": labels_out,
        "places_unread": places_unread,
    }


_RELAXED = ("arm", "analyte", "matrix", "product", "batch", "vessel", "period")


def _labels_differ(groups: dict[JoinKey, list[tuple[KeyRow, Reading, float | None]]],
                   verdict_of: dict[int, tuple[str, str, int | None]], extracted: Sequence[Extracted],
                   readings: Sequence[Reading], used: Sequence[bool], restating: Sequence[bool],
                   study_key: Callable[[str], str], *, tolerance: float, digitized_tolerance: float,
                   fold_arm: bool) -> list[tuple[KeyRow, int, list[str]]]:
    """The diagnostic `labels_differ` (it changes no verdict): each missing key row, in key-row order, with a value no
    row took that has its field, time, subject and value (in its unit), and its study (also folded with the arm when
    `fold_arm`), arm, analyte, matrix, product, batch, vessel, period and conditions each equal or left empty on one
    side; the labels left empty on one side are listed. Today's stores keep labels another way than the key's
    convention (a dose with no analyte, a PK parameter with its dataset's analyte): these rows are that, not a value
    the pipeline lost."""
    free: dict[tuple[str, float | None, str], list[int]] = {}
    for i, e in enumerate(extracted):
        if not used[i] and not restating[i]:
            free.setdefault((e.field, e.time_min, label_key("subject", e.subject)), []).append(i)
    taken: set[int] = set()
    out: list[tuple[KeyRow, int, list[str]]] = []
    for members in groups.values():
        for r, reading, minutes in members:
            if verdict_of[r.row][0] != "missing":
                continue
            for i in free.get((r.field, minutes, label_key("subject", r.subject)), []):
                e = extracted[i]
                if i in taken:
                    continue
                names = _loose(r, e, study_key, fold_arm)
                if names is None:
                    continue
                how = _match(reading, readings[i], e, tolerance, digitized_tolerance)
                if how is None or not _unit_ok(r, reading, e):
                    continue
                taken.add(i)
                out.append((r, i, names))
                break
    out.sort(key=lambda item: item[0].row)
    return out


def _loose(r: KeyRow, e: Extracted, study_key: Callable[[str], str], fold_arm: bool) -> list[str] | None:
    """The labels a key row and a value state on one side only, or None when a label both state differs. With
    `fold_arm`, a value whose study id is the row's study and arm folded together has the row's study and arm."""
    folded = fold_arm and clean(r.arm) and not clean(e.arm) and study_key(r.study + r.arm) == study_key(e.study)
    pairs: list[tuple[Any, Any, str]] = [] if folded else [(study_key(r.study), study_key(e.study), "study")]
    pairs += [(label_key(name, getattr(r, name)), label_key(name, getattr(e, name)), name)
              for name in (_RELAXED[1:] if folded else _RELAXED)]
    pairs.append((conditions_key(_conditions(r.conditions)), conditions_key(_conditions(e.conditions)), "conditions"))
    names: list[str] = []
    for a, b, name in pairs:
        if a and b and a != b:
            return None
        if bool(a) != bool(b):
            names.append(name)
    return names


def _places_unread(key: ValueKey, extracted: Sequence[Extracted]) -> list[dict[str, Any]]:
    """The diagnostic `places_unread`: a key's sheet or page (its rows' `where`) where no value of that file was read,
    while values of the file were read in other sheets or pages (a misspelt sheet, a page not read, a printed page
    number written for the PDF's own). A file with no anchored value (today's stores) is not judged."""
    read: dict[str, set[tuple[str, str]]] = {}
    for e in extracted:
        place = _place(e)
        if place is not None and e.file:
            for name in _file_keys(e.file):
                read.setdefault(name, set()).add(place)
    groups: dict[tuple[tuple[str, ...], str], list[KeyRow]] = {}
    for r in key.rows:
        if clean(r.file) and where_places(r.where):
            groups.setdefault((_file_keys(r.file), norm_text(r.where)), []).append(r)
    out = []
    for (names, _where), rows in groups.items():
        seen = set().union(*(read.get(n, set()) for n in names))
        if seen and not seen & set(where_places(rows[0].where)):
            out.append({"first_row": rows[0].row, "rows": len(rows), "file": rows[0].file, "where": rows[0].where})
    return out


# --- time and coverage ---------------------------------------------------------------------------------------------


def _ts(text: str | None) -> datetime | None:
    """An ISO timestamp (a store's "...Z" or the reading queue's "+00:00"); a naive one is read as UTC."""
    if not text:
        return None
    try:
        found = datetime.fromisoformat(text)
    except ValueError:
        return None
    return found if found.tzinfo is not None else found.replace(tzinfo=UTC)


def _seconds(start: str | None, end: str | None) -> float | None:
    a, b = _ts(start), _ts(end)
    return round((b - a).total_seconds(), 3) if a is not None and b is not None else None


def _latest_runs(store: IntakeStore) -> dict[str, RunRecord]:
    """Each run's latest line (its state), in the order the runs were queued."""
    runs: dict[str, RunRecord] = {}
    for line in store.runs.entries():
        try:
            run = RunRecord.model_validate(line.body)
        except ValidationError:                  # a line of another kind (the log is the runner's): not a run state
            continue
        runs[run.run_id] = run
    return runs


def timings(ws: Workspace) -> dict[str, Any]:
    """Time per delivery and per stage (G7), from runs.jsonl: the files of each delivery, its runs by state, from the
    first file's arrival to the last run's end, and per stage the seconds summed over the runs, the longest and the
    failures. The baseline, today's pipeline: the reading queue's timestamps (waiting, reading)."""
    store = IntakeStore(ws)
    arrivals: dict[str, list[str]] = {}
    for line in store.files.entries("file"):
        arrivals.setdefault(str(line.body.get("delivery", "")), []).append(str(line.body.get("at", "")))
    deliveries: dict[str, dict[str, Any]] = {}
    for run in _latest_runs(store).values():
        d = deliveries.setdefault(run.delivery, {"files": len(arrivals.get(run.delivery, [])), "runs": 0, "queued": 0,
                                                  "running": 0, "done": 0, "failed": 0, "stages": {}, "_ends": []})
        d["runs"] += 1
        d[run.state] += 1
        if run.finished_at:
            d["_ends"].append(run.finished_at)
        for stage in run.stages:
            s = d["stages"].setdefault(stage.stage, {"seconds": 0.0, "longest": 0.0, "runs": 0, "failed": 0})
            s["seconds"] = round(s["seconds"] + stage.seconds, 3)
            s["longest"] = max(s["longest"], round(stage.seconds, 3))
            s["runs"] += 1
            s["failed"] += 0 if stage.ok else 1
    for delivery, d in deliveries.items():
        ends = sorted(d.pop("_ends"), key=lambda t: _ts(t) or _EPOCH)
        starts = sorted(arrivals.get(delivery, []), key=lambda t: _ts(t) or _EPOCH)
        d["first_arrival"] = starts[0] if starts else None
        d["last_end"] = ends[-1] if ends else None
        d["arrival_to_end_seconds"] = _seconds(d["first_arrival"], d["last_end"]) if not d["queued"] + d["running"] \
            else None
    items = ReadingQueue(ws).items()
    waits = [s for i in items if (s := _seconds(i.added_at, i.started_at)) is not None]
    reads = [s for i in items if (s := _seconds(i.started_at, i.finished_at)) is not None]
    added = sorted((i.added_at for i in items if i.added_at), key=lambda t: _ts(t) or _EPOCH)
    finished = sorted((i.finished_at for i in items if i.finished_at), key=lambda t: _ts(t) or _EPOCH)
    queue = {"items": len(items), "done": sum(1 for i in items if i.state == "done"),
             "failed": sum(1 for i in items if i.state == "failed"),
             "waiting": sum(1 for i in items if i.state in ("queued", "reading")),
             "waiting_seconds": {"total": round(sum(waits), 3), "longest": max(waits, default=0.0)},
             "reading_seconds": {"total": round(sum(reads), 3), "longest": max(reads, default=0.0)},
             "first_added": added[0] if added else None, "last_finished": finished[-1] if finished else None,
             "added_to_finished_seconds": _seconds(added[0], finished[-1]) if added and finished else None}
    return {"deliveries": deliveries, "queue": queue}


def _summary_totals(summaries: Iterable[CoverageSummary]) -> dict[str, int]:
    out = dict.fromkeys(_SUMMARY_FIELDS, 0) | {"needs_ocr_pages": 0}
    for s in summaries:
        for name in _SUMMARY_FIELDS:
            out[name] += getattr(s, name)
        out["needs_ocr_pages"] += len(s.needs_ocr_pages)
    return out


def coverage_totals(ws: Workspace) -> dict[str, Any]:
    """The coverage numbers (G2) of every file of files.jsonl: the current ones (coverage/<sha>.json, recomputed by
    exclusions and assignments) and the snapshot of each file's latest run line ("at run end"), files by state,
    regions, cells and silent loss, summed; the files whose two differ are named by sha256."""
    store = IntakeStore(ws)
    names = _file_names(store)
    latest: dict[str, RunRecord] = {}
    for run in _latest_runs(store).values():
        latest[run.sha256] = run                     # a file's latest run (runs in queue order)
    files = []
    for sha, name in names.items():
        current = store.coverage(sha)
        run = latest.get(sha)
        files.append({"sha256": sha, "name": name, "state": current.summary.state if current else None,
                      "run_state": run.state if run else None,
                      "current": current.summary.model_dump(mode="json") if current else None,
                      "at_run_end": run.coverage.model_dump(mode="json") if run and run.coverage else None})
    by_state: dict[str, int] = {}
    for f in files:
        state = f["state"] or "no coverage"
        by_state[state] = by_state.get(state, 0) + 1
    return {
        "files": len(files), "by_state": dict(sorted(by_state.items())),
        "current": _summary_totals(CoverageSummary.model_validate(f["current"]) for f in files if f["current"]),
        "at_run_end": _summary_totals(CoverageSummary.model_validate(f["at_run_end"]) for f in files if f["at_run_end"]),
        "differs": [f["sha256"] for f in files if f["current"] and f["at_run_end"] and f["current"] != f["at_run_end"]],
        "per_file": files,
    }


# --- the report ------------------------------------------------------------------------------------------------------


def masked_anchor(anchor: str | None, sheets: dict[str, dict[str, int]] | None = None) -> str:
    """An anchor for the report that leaves the server: the file's sha256 (12 hex), the parser and its version, and the
    locator with a sheet's name replaced by its number in this report (`s:#1!C4`: the first sheet of that file the
    report names; a sheet is often named after a study, and a hash of a short name can be guessed). `sheets` keeps the
    numbers of one report (file sha256 -> sheet name -> number); without it every sheet is #1."""
    if not anchor:
        return ""
    try:
        parsed = parse_anchor(anchor)
    except AnchorError:
        return "(not an anchor)"
    locator = parsed.locator
    if isinstance(locator, SheetCell):
        numbers = (sheets if sheets is not None else {}).setdefault(parsed.file_sha256, {})
        text = f"s:#{numbers.setdefault(locator.sheet, len(numbers) + 1)}!{locator.cell}"
    else:
        text = format_locator(locator)
    return f"{parsed.file_sha256[:12]}@{parsed.parser}/{parsed.parser_version}#{text}"


def _vocabulary(tag: str, value: str) -> bool:
    """Whether a routing tag's value is a word of the field's vocabulary (a choice), not the client's text."""
    choice = read_choice(tag, value) if value else None
    return choice is not None and name_key(choice) == name_key(value)


def public_id(value_id: str | None, numbers: dict[str, str]) -> str | None:
    """A value's id for the report that leaves the server: a ledger id as it is (`tx-<16 hex>#i`, a hash of a whole
    extract; `f-<n>`, a line's number), any other (today's stores build theirs from sheet and series names) by its
    number in this report, "value 3" (`numbers` keeps them)."""
    if not value_id:
        return value_id
    if ID_PATTERNS["value"].fullmatch(value_id) or ID_PATTERNS["line"].fullmatch(value_id):
        return value_id
    return numbers.setdefault(value_id, f"value {len(numbers) + 1}")


def public(scored: dict[str, Any]) -> dict[str, Any]:
    """The score with no value, no label, no file name and no analyst: what may leave the server (`--json` without
    `--with-values`). A study is named by its first key row; anchors are masked (`masked_anchor`) and ids withheld
    unless they are ledger ids (`public_id`), with numbers kept across the whole report; a key place is named by its
    first row."""
    studies = scored["studies"]
    sheets: dict[str, dict[str, int]] = {}
    ids: dict[str, str] = {}

    def study_ref(sk: str) -> str:
        if sk in (NO_STUDY, NOT_IN_KEY):
            return sk
        row = studies.get(sk, {}).get("row")
        return f"study of key row {row}" if row is not None else "a study of the Studies sheet only"

    def tag_ref(tag: str, value: str) -> str:
        if value == NOT_STATED or _vocabulary(tag, value):
            return value
        return f"as in Studies row {scored['tag_rows'].get(tag, {}).get(value, '?')}"

    def found(item: dict[str, Any] | None) -> dict[str, Any]:
        item = item or {}
        return {"id": public_id(item.get("id"), ids), "method": item.get("method"),
                "anchor": masked_anchor(item.get("anchor"), sheets)}

    def row(item: dict[str, Any]) -> dict[str, Any]:
        return {"row": item["row"], "verdict": item["verdict"], "how": item["how"], "field": item["field"],
                "study": study_ref(item["study"]) if item["study"] else NO_STUDY,
                "attributes_differ": item.get("attributes_differ", []), **found(item.get("found"))}

    return {
        "schema": scored["schema"],
        "key": {k: scored["key"][k] for k in ("schema", "date", "status", "rows", "not_data")},
        "options": scored["options"], "totals": scored["totals"], "by_field": scored["by_field"],
        "by_study": {study_ref(sk): counts for sk, counts in scored["by_study"].items()},
        "by_tag": {tag: {tag_ref(tag, value): counts for value, counts in values.items()}
                   for tag, values in scored["by_tag"].items()},
        "by_method": scored["by_method"],
        "by_attribute": scored.get("by_attribute", {}),
        "rows": [row(item) for item in scored["rows"]],
        "unexpected": [{"field": u["field"], "study": study_ref(u["study"]), **found(u)} for u in scored["unexpected"]],
        "unusable": [{"row": u["row"], "field": u["field"], "reason": u["reason"]} for u in scored["unusable"]],
        "labels_differ": [{"row": d["row"], "field": d["field"], "study": study_ref(d["study"]) if d["study"] else NO_STUDY,
                           "labels": d["labels"], **found(d["found"])} for d in scored.get("labels_differ", [])],
        "places_unread": [{"first_row": u["first_row"], "rows": u["rows"]} for u in scored.get("places_unread", [])],
        "chain_problems": scored.get("chain_problems", []),
    }


def public_coverage(cover: dict[str, Any]) -> dict[str, Any]:
    """`coverage_totals` for the report that leaves the server: per file no name and no reason (free text)."""
    def summary(found: dict[str, Any] | None) -> dict[str, Any] | None:
        return {**found, "reason": ""} if found else found

    return {**cover, "per_file": [{**f, "name": "", "current": summary(f["current"]), "at_run_end": summary(f["at_run_end"])}
                                  for f in cover["per_file"]]}


def _cell(text: Any) -> str:
    return str("" if text is None else text).replace("|", "\\|").replace("\n", " ")


def _code(text: Any) -> str:
    """An anchor or an id in a report cell, in backticks ("" stays empty)."""
    return f"`{text}`" if text else ""


def _table(head: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return lines


def _verdict_table(title: str, name: str, counts: dict[str, dict[str, int]]) -> list[str]:
    if not counts:
        return []
    return ["", f"## {title}", "", *_table([name, *VERDICTS], [[k, *(c[v] for v in VERDICTS)] for k, c in counts.items()])]


def _labels_text(labels: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in labels.items() if v not in ("", None))


def _read(found: dict[str, Any]) -> str:
    """What code read, for the with-values report: the text as written, the number read and the unit."""
    read = found["value"] if found["value"] is not None else "censored" if found["censored"] else "no value"
    time = f" at {found['time_min']:g} min" if found.get("time_min") is not None else ""
    return f"{found['verbatim']} (read {read}) {found['unit'] or ''}".strip() + time


def _tolerance(value: float) -> str:
    return f"relative {value}" if value else "off"


def _attributes_text(attributes: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in attributes.items())


def render(scored: dict[str, Any], *, timings: dict | None = None, coverage: dict | None = None,
           with_values: bool = False) -> str:
    """The score as Markdown. Default: counts, field names, verdicts, methods and masked anchors, a study by its first
    key row; no value, no label, no file name, no analyst (it leaves the server). Every count stands in a table cell
    of its own and every anchor or id in backticks. `with_values`: the expected and the found values, the labels, the
    file names and the full anchors, to read on the server only."""
    shown = scored if with_values else public(scored)
    key = scored["key"]
    totals = scored["totals"]
    options = scored["options"]
    lines = ["# Value score", ""]
    chain = scored.get("chain_problems") or []
    if chain:
        lines += [("**The hash chain of the intake logs is broken: this score is of data edited after it was written, "
                   "not of what the pipeline wrote.**"), "",
                  *_table(["log", "line", "problem"], [[c["log"], c["seq"], c["problem"]] for c in chain]), ""]
    if with_values:
        lines += ["**With values: read on the server only; never send this report.**", ""]
    else:
        lines += ["This report holds no value, no label and no file name: it may leave the server.", ""]
    about = [["date", key["date"]], ["status", key["status"]], ["key rows", key["rows"]],
             ["not-data tables", key["not_data"]], ["source", scored.get("source", "")]]
    if with_values:
        about = [["delivery", key["delivery"]], ["analyst", key["analyst"]], *about]
    lines += _table(["key", ""], about)
    tolerances = (f"Tolerance: {_tolerance(options['tolerance'])}; for digitized values: "
                  f"{_tolerance(options['digitized_tolerance'])}.")
    lines += ["", tolerances, "",
              ("The statistic, spread, spread kind, n, occasion and sequence of a value are checked only where the key "
               "states them (counted apart, as attributes that differ); a key that leaves those columns empty does not "
               "score them."), "", "## Totals", "",
              *_table(["what", "count"], [
                  ["key rows", totals["key_rows"]], ["scored", totals["scored"]],
                  ["not usable (listed below)", totals["unusable"]], ["found", totals["found"]],
                  ["of them by tolerance", totals["found_by_tolerance"]],
                  ["of them a missing token with nothing read", totals["found_absent"]],
                  ["found after rounding", totals["found_rounded"]],
                  ["wrong value", totals["wrong_value"]], ["wrong unit", totals["wrong_unit"]],
                  ["unexpected", totals["unexpected"]], ["errors (wrong value, wrong unit, unexpected)", totals["errors"]],
                  ["omissions (missing)", totals["missing"]],
                  ["paired rows with an attribute that differs", totals["attributes_differ"]],
                  ["missing rows read under other labels (diagnostic)", totals["labels_differ"]],
                  ["key places where nothing was read (diagnostic)", totals["places_unread"]],
                  ["values read", totals["extracted"]], ["values outside the key", totals["outside_key"]]])]
    lines += _verdict_table("By field", "field", shown["by_field"])
    lines += _verdict_table("By study", "study", {(scored["studies"].get(k, {}).get("label") or k) if with_values else k: c
                                                  for k, c in shown["by_study"].items()})
    for tag, values in shown["by_tag"].items():
        lines += _verdict_table(f"By {tag}", tag, values)
    lines += _verdict_table("By method", "method", shown["by_method"])
    if any(shown["by_attribute"].values()):
        lines += ["", "## Attributes that differ", "",
                  *_table(["attribute", "rows"], [[k, n] for k, n in shown["by_attribute"].items() if n])]

    looks = [r for r in shown["rows"] if r["verdict"] != "found" or r["attributes_differ"]]
    if looks:
        lines += ["", "## Key rows to look at", ""]
        if with_values:
            lines += _table(["row", "field", "verdict", "attributes that differ", "expected", "found", "labels", "method",
                             "anchor"], [
                [r["row"], r["field"], r["verdict"], ", ".join(r["attributes_differ"]),
                 f"{r['expected']['value']} {r['expected']['unit']}".strip()
                 + (f" at {r['expected']['time']} {r['expected']['time_unit']}" if r["expected"]["time"] else "")
                 + (f" ({_attributes_text(r['expected']['attributes'])})" if r["expected"]["attributes"] else ""),
                 (_read(r["found"]) + (f" ({_attributes_text(r['found']['attributes'])})" if r["found"]["attributes"]
                                       else "")) if r["found"] else "",
                 _labels_text(r["expected"]["labels"]) + f"; {r['expected']['file']} {r['expected']['where']}",
                 (r["found"] or {}).get("method", ""), _code((r["found"] or {}).get("anchor"))] for r in looks])
        else:
            lines += _table(["row", "field", "study", "verdict", "attributes that differ", "method", "anchor"],
                            [[r["row"], r["field"], r["study"], r["verdict"], ", ".join(r["attributes_differ"]),
                              r["method"] or "", _code(r["anchor"])] for r in looks])
    if shown["unexpected"]:
        lines += ["", "## Values the key does not have (unexpected)", ""]
        if with_values:
            lines += _table(["field", "value", "labels", "file", "method", "anchor"], [
                [u["field"], _read(u), _labels_text(u["labels"]), u["file"], u["method"], _code(u["anchor"])]
                for u in shown["unexpected"]])
        else:
            lines += _table(["field", "study", "method", "anchor"],
                            [[u["field"], u["study"], u["method"], _code(u["anchor"])] for u in shown["unexpected"]])
    if shown["unusable"]:
        lines += ["", "## Key rows the scorer cannot use", "",
                  *_table(["row", "field", "reason"], [[u["row"], u["field"], u["reason"]] for u in shown["unusable"]])]
    if shown["labels_differ"]:
        lines += ["", "## Missing rows whose value was read under other labels (diagnostic)", "",
                  ("Same study, subject, field, time and value; the labels listed are stated on one side only. The "
                   "verdicts stay missing and unexpected (the join is exact on every label)."), ""]
        if with_values:
            lines += _table(["row", "field", "labels on one side only", "found", "found labels", "file"], [
                [d["row"], d["field"], ", ".join(d["labels"]), _read(d["found"]), _labels_text(d["found"]["labels"]),
                 d["found"]["file"]] for d in shown["labels_differ"]])
        else:
            lines += _table(["row", "field", "study", "labels on one side only", "method", "anchor"], [
                [d["row"], d["field"], d["study"], ", ".join(d["labels"]), d["method"] or "", _code(d["anchor"])]
                for d in shown["labels_differ"]])
    if shown["places_unread"]:
        lines += ["", "## Key places where no value of the file was read (diagnostic)", "",
                  ("A misspelt sheet, a page not read, or a page number printed on the page rather than its position in "
                   "the PDF."), ""]
        if with_values:
            lines += _table(["first key row", "rows", "file", "where"],
                            [[u["first_row"], u["rows"], u["file"], u["where"]] for u in shown["places_unread"]])
        else:
            lines += _table(["first key row", "rows"], [[u["first_row"], u["rows"]] for u in shown["places_unread"]])
    if timings is not None:
        lines += _timing_lines(timings)
    if coverage is not None:
        lines += _coverage_lines(coverage, with_values=with_values)
    return "\n".join(lines) + "\n"


def _timing_lines(t: dict[str, Any]) -> list[str]:
    lines = ["", "## Time (G7)", ""]
    if t["deliveries"]:
        lines += _table(["delivery", "files", "runs", "done", "failed", "waiting", "first arrival to last end (s)"],
                        [[_code(name), d["files"], d["runs"], d["done"], d["failed"], d["queued"] + d["running"],
                          d["arrival_to_end_seconds"] if d["arrival_to_end_seconds"] is not None else "not finished"]
                         for name, d in t["deliveries"].items()])
        for name, d in t["deliveries"].items():
            lines += ["", f"Stages of delivery {_code(name)}:", "",
                      *_table(["stage", "seconds", "longest (s)", "runs", "failed"],
                              [[s, v["seconds"], v["longest"], v["runs"], v["failed"]] for s, v in d["stages"].items()])]
    else:
        lines += ["No pipeline run is recorded (runs.jsonl)."]
    q = t["queue"]
    span = q["added_to_finished_seconds"]
    lines += ["", "Baseline, today's reading queue:", "",
              *_table(["items", "done", "failed", "waiting", "waiting (s)", "longest wait (s)", "reading (s)",
                       "longest reading (s)", "first added to last finished (s)"],
                      [[q["items"], q["done"], q["failed"], q["waiting"], q["waiting_seconds"]["total"],
                        q["waiting_seconds"]["longest"], q["reading_seconds"]["total"], q["reading_seconds"]["longest"],
                        span if span is not None else ""]])]
    return lines


def _coverage_lines(c: dict[str, Any], *, with_values: bool) -> list[str]:
    lines = ["", "## Coverage (G2)", "",
             *_table(["files by state", "files"], [[state, n] for state, n in c["by_state"].items()] + [["all", c["files"]]]),
             ""]
    names = list(_SUMMARY_FIELDS) + ["needs_ocr_pages"]
    lines += _table(["count", "current", "at run end"], [[n, c["current"][n], c["at_run_end"][n]] for n in names])
    if c["differs"]:
        lines += ["", "Current coverage differs from the run end (exclusions or assignments since) for: "
                  + ", ".join(_code(s[:12]) for s in c["differs"]) + "."]
    lines += ["", *_table(["file", "state", "run", "silent loss now", "silent loss at run end"], [
        [f["name"] if with_values else _code(f["sha256"][:12]), f["state"] or "no coverage", f["run_state"] or "no run",
         (f["current"] or {}).get("silent_loss", ""), (f["at_run_end"] or {}).get("silent_loss", "")]
        for f in c["per_file"]])]
    return lines


# --- the command -----------------------------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _write(text: str | bytes, out: str | None, root: Path | None) -> int:
    if out is None:
        print(text if isinstance(text, str) else "", end="" if isinstance(text, str) and text.endswith("\n") else "\n")
        return 0
    path = Path(out).expanduser()
    if root is not None and _inside(path, root):
        print(f"{out}: inside the project store; this tool writes nothing there", file=sys.stderr)
        return 2
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    print(f"written to {out}")
    return 0


def chain_problems(ws: Workspace) -> list[dict[str, Any]]:
    """Every break of the intake logs' hash chains (IntakeStore: files, runs, mappings, facts, entities, review), as
    {log, seq, problem}; a torn last line (a write in progress) is listed too. Empty when every chain is whole."""
    store = IntakeStore(ws)
    return [{"log": name, "seq": p.seq, "problem": p.problem} for name in _LOGS for p in getattr(store, name).verify()]


def _load(path: str) -> ValueKey:
    file = Path(path).expanduser()
    return load_key(file.read_bytes(), file.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a delivery value by value against the analysts' key (G1).")
    parser.add_argument("--root", help="the project store root (on the server: ~/modeler-data/read-root)")
    parser.add_argument("--project", help="the project's id")
    parser.add_argument("--tenant", help="the tenant (found from the project when left out)")
    parser.add_argument("--key", help="the value key (a workbook: value-key/2)")
    parser.add_argument("--source", choices=("ledger", "stores"), default="ledger",
                        help="ledger: the new pipeline; stores: today's pipeline (the baseline)")
    parser.add_argument("--tolerance", type=float, default=0.0, help="relative tolerance (off by default)")
    parser.add_argument("--digitized-tolerance", type=float, default=0.0, help="relative tolerance for digitized values")
    parser.add_argument("--compare", help="a second analyst's key: compare it with --key (no project needed)")
    parser.add_argument("--template", help="write the empty key template to this file and stop")
    parser.add_argument("--with-values", action="store_true", help="values, labels and file names: on the server only")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--out", help="write to this file (never inside the root) instead of printing")
    parser.add_argument("--accept-broken-chain", action="store_true",
                        help="score although an intake log's hash chain is broken (the report says so at its top)")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser() if args.root else None

    if args.template:
        if root is not None and _inside(Path(args.template).expanduser(), root):
            print(f"{args.template}: inside the project store; this tool writes nothing there", file=sys.stderr)
            return 2
        Path(args.template).expanduser().write_bytes(template_workbook())
        print(f"template written to {args.template}")
        return 0
    if not args.key:
        print("give --key (the value key), or --template OUT to write an empty one", file=sys.stderr)
        return 2
    try:
        key = _load(args.key)
        second = _load(args.compare) if args.compare else None
    except (ValueKeyError, OSError) as exc:
        print(f"the key: {exc}", file=sys.stderr)
        return 2
    if second is not None:
        result = compare(key, second)
        text = json.dumps(result, indent=1, ensure_ascii=False) if args.json else render_comparison(result)
        return _write(text, args.out, root)

    if root is None or not args.project or not root.is_dir():
        print(f"no project store at {args.root!r}: give --root (on the server, ~/modeler-data/read-root) and --project",
              file=sys.stderr)
        return 2
    tenants = [args.tenant] if args.tenant else [t.name for t in root.iterdir() if (t / "projects" / args.project).is_dir()]
    if len(tenants) != 1 or not (root / tenants[0] / "projects" / args.project).is_dir():
        print(f"project {args.project} is {'in several tenants: give --tenant' if len(tenants) > 1 else 'not in this store'}",
              file=sys.stderr)
        return 2
    ws = Workspace(FileProjectStore(root), tenants[0], args.project)
    chain = chain_problems(ws)
    broken = [c for c in chain if c["problem"] != "torn_tail"]
    if broken and not args.accept_broken_chain:
        print("the hash chain of the intake logs is broken ("
              + ", ".join(f"{c['log']} line {c['seq']}: {c['problem']}" for c in broken)
              + "): the data was changed after it was written; nothing is scored (--accept-broken-chain to score it "
              "all the same, with the break at the top of the report)", file=sys.stderr)
        return 2
    try:
        extracted = from_ledger(ws) if args.source == "ledger" else from_stores(ws)
        scored = score(key, extracted, tolerance=args.tolerance, digitized_tolerance=args.digitized_tolerance,
                       fold_arm=args.source == "stores")
        times, cover = timings(ws), coverage_totals(ws)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    scored["source"] = args.source
    scored["chain_problems"] = chain
    if args.json:
        if args.with_values:
            body = {"score": scored, "timings": times, "coverage": cover}
        else:
            body = {"score": public(scored) | {"source": args.source}, "timings": times,
                    "coverage": public_coverage(cover)}
        text = json.dumps(body, indent=1, ensure_ascii=False)
    else:
        text = render(scored, timings=times, coverage=cover, with_values=args.with_values)
    return _write(text, args.out, root)


if __name__ == "__main__":
    sys.exit(main())
