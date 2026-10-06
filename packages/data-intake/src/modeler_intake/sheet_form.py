"""A sheet described in a person's words (the Client data page's form), and the mapping recipe it stands for.

`suggest` fills the form from the sheet the way a person reads it on first sight: where the header and the data are,
whether the sampling times run down a column or across the top, which columns hold the subject and the values, and
the units, dose and LLOQ the sheet states. Each of those it finds is quoted from its cell, so the recipe carries the
evidence a reviewer checks; what the sheet does not state is left blank (or taken from the file name, and said so) for
the person to fill in. Nothing is read until the person checks the form's result and confirms it (plan §10.1 step 4).

`to_proposal` writes the recipe (the data-mapping proposal shape) from the form; `preview_rows` is the grid the form is
shown next to.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field

from modeler_intake.apply import PRE_DOSE, UnparseableValueError, header_time, parse_numeric
from modeler_intake.grid import SheetGrid, as_text
from modeler_intake.recipe import DEFAULT_BELOW_LLOQ_TOKENS, Statistic

Kind = Literal["concentration_time", "dissolution"]
Layout = Literal["times_down", "times_across"]
SCAN_ROWS = 40          # rows looked at to find the header and the data
PREVIEW_ROWS = 30
PREVIEW_COLUMNS = 40

_CONC_UNIT = re.compile(r"(?<![a-z])(pg|ng|µg|μg|ug|mcg|mg|g|fmol|pmol|nmol|µmol|μmol|umol|mmol)\s*/\s*(ml|l|dl)(?![a-z])",
                        re.IGNORECASE)
_TIME_UNIT = re.compile(r"(?<![a-z])(hours?|hrs?|h|minutes?|mins?|min)(?![a-z])", re.IGNORECASE)
_TIME_HEADER = re.compile(r"\btime\b|\bhours?\b|\bhrs?\b|\bnominal\b|\bsampling\b|\bmin(?:utes?)?\b|^t$|\(h\)|\(hr?s?\)|\(min\)",
                          re.IGNORECASE)
_SUBJECT = re.compile(r"\bsubj(?:ect)?s?\b|\bvolunteer|\bpatient|\bsubject\s*(?:no|id|number)|^id$|^no\.?$|\bs\.? ?no\b",
                      re.IGNORECASE)
_VESSEL = re.compile(r"\bvessel|\bunit\s*\d|^v\s*\d+$|^\d{1,2}$|\bjar\b|\btablet\s*\d", re.IGNORECASE)
_PERIOD = re.compile(r"\bperiod\b|\bpd\b", re.IGNORECASE)
_SUMMARY = re.compile(r"\bmean\b|\bavg\b|\baverage\b|\bsd\b|\bs\.d\.|\bstd\b|\bcv\b|%\s*cv|\brsd\b|\bmin\b\.?$|\bmax\b|\bmedian\b",
                      re.IGNORECASE)
_SUMMARY_ROW = re.compile(r"^(arith\w*\.? ?mean|geo\w*\.? ?mean|mean|average|sd|s\.d\.|std\.?( ?dev\.?)?|cv ?%?|% ?cv|rsd|min|"
                          r"max|median|n|sum|total)\b", re.IGNORECASE)
_SD = re.compile(r"^\s*(sd|s\.d\.|std\.?(\s*dev\.?)?|standard deviation)\s*$", re.IGNORECASE)
_N = re.compile(r"^\s*(n|no\. of subjects|number of subjects)\s*$", re.IGNORECASE)
_CONC_HEADER = re.compile(r"conc|ng/ml|µg/ml|ug/ml|ng/l|nmol|plasma|serum|value|result|dissolved|release", re.IGNORECASE)
_LLOQ = re.compile(r"(?:lloq|lower limit of quantification|below|blq\s*[:=<]?|bql\s*[:=<]?)\D{0,25}?(\d+(?:\.\d+)?)\s*"
                   r"(pg|ng|µg|ug)\s*/\s*(ml|l)", re.IGNORECASE)
_DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)
_PH = re.compile(r"\bph\s*[:=]?\s*(\d{1,2}(?:\.\d+)?)", re.IGNORECASE)
_RPM = re.compile(r"(\d{2,3})\s*rpm\b", re.IGNORECASE)
_VOLUME = re.compile(r"(\d{3,4})\s*ml\b", re.IGNORECASE)
_BATCH = re.compile(r"\b(?:batch|lot)\s*(?:no\.?|number|#|:)?\s*[:#]?\s*([A-Za-z0-9](?:[A-Za-z0-9/_-]|\.(?=[A-Za-z0-9]))+)",
                    re.IGNORECASE)
_APPARATUS = re.compile(r"usp\s*(?:apparatus\s*)?(?:type\s*)?(i{1,3}|iv|[1-4])\b|\bpaddle\b|\bbasket\b", re.IGNORECASE)
_MEDIUM = re.compile(r"(0\.1\s*n\s*hcl|hcl|acetate|phosphate|citrate|fassif|fessif|fassgf|sgf|sif|water|buffer)", re.IGNORECASE)
_STUDY_ID = re.compile(r"\b([A-Z]{0,4}\d{2,4}(?:[-/]\d{2,4})+)\b", re.IGNORECASE)
_TEST = re.compile(r"\btest\b", re.IGNORECASE)
_REFERENCE = re.compile(r"\breference\b|\bref\b|\brld\b|\binnovator\b|\bbrand\b", re.IGNORECASE)
_FED = re.compile(r"\bfed\b", re.IGNORECASE)
_FASTED = re.compile(r"\bfast(?:ed|ing)?\b", re.IGNORECASE)
_IV = re.compile(r"\biv\b|intravenous|infusion", re.IGNORECASE)
_MR = re.compile(r"\b(er|xr|sr|cr|pr|mr|extended|prolonged|sustained|controlled|modified)\b", re.IGNORECASE)


class Evidence(BaseModel):
    cell: str
    quote: str
    supports: str
    field: str = ""        # what the quote stands for in the form (value_unit, time_unit, lloq, or a constant's key) …
    value: str = ""        # … and the value it supports: the quote is kept only while the form still says that


class SheetForm(BaseModel):
    """What a person tells the page about one sheet. Columns are letters; rows are the sheet's own row numbers."""

    sheet: str
    kind: Kind = "concentration_time"
    layout: Layout = "times_down"
    header_row: int = Field(default=1, ge=0, description="The row with the column headers (times across: the times)")
    first_data_row: int = Field(default=2, ge=1)
    last_data_row: int | None = Field(default=None, ge=1)
    time_column: str | None = None
    subject_column: str | None = None
    group_column: str | None = None          # e.g. the period, when one subject has several rows
    value_columns: list[str] = Field(default_factory=list)
    sd_column: str | None = None
    n_column: str | None = None
    time_unit: str = "h"
    value_unit: str = "ng/ml"
    statistic: Statistic = "individual"
    lloq: float | None = Field(default=None, gt=0)
    decimal_comma: bool = False
    below_lloq_tokens: list[str] = Field(default_factory=list)
    missing_tokens: list[str] = Field(default_factory=list)
    constants: dict[str, str] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _texts(grid: SheetGrid, rows: range) -> list[tuple[str, str]]:
    out = []
    for row in rows:
        for column in range(1, grid.max_column + 1):
            cell = grid.cell(row, column)
            text = as_text(cell.value)
            if text and cell.merged_from is None:
                out.append((cell.ref, text))
    return out


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    try:
        parse_numeric(value, below_lloq_tokens=DEFAULT_BELOW_LLOQ_TOKENS)
        return as_text(value) != ""
    except UnparseableValueError:
        return False


def _is_time_header(value: Any, unit: str) -> bool:
    try:
        return header_time(value, unit) is not None
    except UnparseableValueError:
        return False


def _data_columns(grid: SheetGrid, first: int, last: int) -> list[int]:
    return [c for c in range(1, grid.max_column + 1) if any(grid.cell(r, c).value not in (None, "") for r in range(first, last + 1))]


def _last_data_row(grid: SheetGrid, first: int) -> tuple[int, str]:
    """The last row of the block of numbers, and the label of the summary row that ended it (Mean, SD …), if one did."""
    last = first
    for row in range(first, grid.max_row + 1):
        values = [grid.cell(row, c).value for c in range(1, grid.max_column + 1)]
        filled = [v for v in values if v not in (None, "")]
        if not filled:
            break
        label = as_text(filled[0])
        if row > first and _SUMMARY_ROW.match(label):
            return last, label
        if row > first and sum(_is_number(v) for v in filled) * 2 < len(filled):
            break
        last = row
    return last, ""


_HEADER_WORD = re.compile(r"subj|volunteer|patient|pre-?\s?dos|\btime\b|vessel|period|sequence|treatment", re.IGNORECASE)


def _first_data_row(grid: SheetGrid) -> int | None:
    """The first row of the block of numbers. A row of sampling times is a header, not data: it names its rows
    (Subject, Pre-dose …), or leaves the label column empty where the rows below have one."""
    for row in range(1, min(grid.max_row, SCAN_ROWS) + 1):
        values = [grid.cell(row, c).value for c in range(1, grid.max_column + 1)]
        filled = [v for v in values if v not in (None, "")]
        numbers = [v for v in filled if _is_number(v)]
        if len(numbers) < 2 or len(numbers) * 2 < len(filled):
            continue
        if any(isinstance(v, str) and not _is_number(v) and _HEADER_WORD.search(v) for v in filled):
            continue
        first_column = next(c for c in range(1, grid.max_column + 1) if grid.cell(row, c).value not in (None, ""))
        if first_column > 1 and grid.cell(row + 1, first_column - 1).value not in (None, ""):
            continue
        return row
    return None


def _find(grid: SheetGrid, rows: range, pattern: re.Pattern[str]) -> tuple[str, re.Match[str]] | None:
    for ref, text in _texts(grid, rows):
        match = pattern.search(_norm(text))
        if match:
            return ref, match
    return None


def preview_rows(grid: SheetGrid) -> list[list[str]]:
    """The first rows of the sheet as text, for the page to show next to the form."""
    columns = min(grid.max_column, PREVIEW_COLUMNS)
    return [[as_text(grid.cell(r, c).value) for c in range(1, columns + 1)] for r in range(1, min(grid.max_row, PREVIEW_ROWS) + 1)]


def suggest(grid: SheetGrid, *, category: str = "", filename: str = "", drug: str = "",
            products: list[dict[str, str]] | None = None) -> tuple[SheetForm, list[str]]:
    """A first filling of the form, and what was found (or not) in words. Never a reading: a person checks it."""
    notes: list[str] = []
    names = f"{filename} {grid.name}"
    first = _first_data_row(grid)
    if first is None:
        return SheetForm(sheet=grid.name), [("No block of numbers found in the first rows: this sheet may not hold data "
                                              "(keep it as a document, or set the rows by hand).")]
    header = next((r for r in range(first - 1, 0, -1) if not grid.row_is_empty(r)), 0)
    last, summary = _last_data_row(grid, first)
    columns = _data_columns(grid, first, last)
    head = {c: as_text(grid.cell(header, c).value) if header else "" for c in columns}
    header_region = range(1, first)
    kind: Kind = "dissolution" if (category == "DISSOLUTION" or re.search(r"dissol|% ?released|vessel", " ".join(
        t for _r, t in _texts(grid, header_region)) + " " + names, re.IGNORECASE)) else "concentration_time"

    # times across the top: three or more header cells that are sampling times, and no time column
    time_header = any(_TIME_HEADER.search(head[c]) for c in columns)
    across = [] if time_header else [c for c in columns if header and (
        _is_time_header(grid.cell(header, c).value, "h") or _is_time_header(grid.cell(header, c).value, "min"))]
    form = SheetForm(sheet=grid.name, kind=kind, header_row=header, first_data_row=first)
    letter = get_column_letter
    if len(across) >= 3:
        form.layout = "times_across"
        form.value_columns = [letter(c) for c in across]
        left = [c for c in columns if c < across[0]]
        subject = next((c for c in left if _SUBJECT.search(head[c])), None) or (left[0] if left else None)
        period = next((c for c in left if c != subject and _PERIOD.search(head[c])), None)
        form.subject_column = letter(subject) if subject else None
        form.group_column = letter(period) if period else None
        notes.append(f"Times run across row {header} ({letter(across[0])}–{letter(across[-1])}); one row per "
                     f"{'vessel' if kind == 'dissolution' else 'subject'}, rows {first}–{last}.")
        if any(as_text(grid.cell(header, c).value).lower() in PRE_DOSE for c in across):
            notes.append("A pre-dose column is read as time 0.")
    else:
        time = next((c for c in columns if _TIME_HEADER.search(head[c])), None) or next(
            (c for c in columns if all(_is_number(grid.cell(r, c).value) for r in range(first, last + 1))), None)
        if time is None:
            notes.append("No time column found: choose it.")
        form.time_column = letter(time) if time else None
        subject = next((c for c in columns if c != time and _SUBJECT.search(head[c])), None)
        form.subject_column = letter(subject) if subject else None
        sd = next((c for c in columns if _SD.match(head[c])), None)
        n = next((c for c in columns if _N.match(head[c])), None)
        rest = [c for c in columns if c not in (time, subject, sd, n)]
        if kind == "dissolution":
            vessels = [c for c in rest if _VESSEL.search(head[c]) and not _SUMMARY.search(head[c])]
            values = vessels or [c for c in rest if re.search(r"\bmean\b|\bavg\b|\baverage\b", head[c], re.IGNORECASE)][:1]
            if not vessels and values:
                notes.append("No vessel columns found: the mean is read as one profile (f2 needs the 12 vessels).")
        else:
            named = [c for c in rest if _CONC_HEADER.search(head[c])]
            values = named or [c for c in rest if all(_is_number(grid.cell(r, c).value) or grid.cell(r, c).value in (None, "")
                                                       for r in range(first, last + 1))]
            if not subject and len(values) == 1 and re.search(r"\bmean\b|\bavg\b|\baverage\b", head[values[0]], re.IGNORECASE):
                form.statistic = "arithmetic_mean"
            if re.search(r"geo", " ".join(head[c] for c in values), re.IGNORECASE):
                form.statistic = "geometric_mean"
            if form.statistic != "individual":
                form.sd_column = letter(sd) if sd else None
                form.n_column = letter(n) if n else None
        form.value_columns = [letter(c) for c in values]
        if form.time_column:
            notes.append(f"Time in column {form.time_column}, values in {', '.join(form.value_columns) or 'no column yet'}, "
                         f"rows {first}–{last}.")
    form.last_data_row = last if last < grid.max_row and not grid.row_is_empty(last + 1) else None
    if summary:
        notes.append(f"Row {last + 1} ({summary}) and below are summary rows: not read.")

    # units and LLOQ, quoted from the header (or the notes under the table)
    evidence: list[Evidence] = []
    everything = range(1, min(grid.max_row, 200) + 1)
    if kind == "dissolution":
        form.value_unit = "%"
        found = _find(grid, header_region, re.compile(r"%"))
        if found:
            evidence.append(Evidence(cell=found[0], quote="%", supports="value unit %", field="value_unit", value="%"))
    else:
        found = _find(grid, header_region, _CONC_UNIT) or _find(grid, everything, _CONC_UNIT)
        if found:
            form.value_unit = found[1].group(0).replace(" ", "")
            evidence.append(Evidence(cell=found[0], quote=found[1].group(0), supports=f"value unit {form.value_unit}",
                                     field="value_unit", value=form.value_unit))
        else:
            notes.append("The concentration unit is not written in the sheet: choose it (ng/mL assumed until you do).")
    time_cells = [form.time_column] if form.time_column else []
    unit_found = None
    for ref, text in _texts(grid, header_region):
        column = re.sub(r"\d", "", ref.split("!")[-1])
        if (time_cells and column in time_cells) or (form.layout == "times_across" and _TIME_HEADER.search(text)):
            m = _TIME_UNIT.search(_norm(text).replace("(", " ").replace(")", " "))
            if m:
                unit_found = (ref, m)
                break
    if unit_found is None and form.layout == "times_across":
        for column in form.value_columns:
            cell = grid.cell(header, column)
            m = _TIME_UNIT.search(as_text(cell.value))
            if isinstance(cell.value, str) and m:
                unit_found = (cell.ref, m)
                break
    if unit_found:
        word = unit_found[1].group(1).lower()
        form.time_unit = "min" if word.startswith("min") else "h"
        evidence.append(Evidence(cell=unit_found[0], quote=unit_found[1].group(1), supports=f"time unit {form.time_unit}",
                                 field="time_unit", value=form.time_unit))
    else:
        form.time_unit = "min" if kind == "dissolution" else "h"
        notes.append(f"The time unit is not written in the sheet: check it ({form.time_unit} assumed).")
    if kind == "concentration_time":
        lloq = _find(grid, everything, _LLOQ)
        if lloq:
            form.lloq = float(lloq[1].group(1))
            evidence.append(Evidence(cell=lloq[0], quote=lloq[1].group(0).strip(), supports=f"LLOQ {form.lloq:g}",
                                     field="lloq", value=f"{form.lloq:g}"))

    # what the data cells say besides numbers
    tokens = sorted({as_text(grid.cell(r, c).value) for r in range(first, last + 1) for c in
                     [*map(_col_index, form.value_columns)] if isinstance(grid.cell(r, c).value, str)
                     and not _is_plain_number(as_text(grid.cell(r, c).value))})
    blq = {t.upper() for t in DEFAULT_BELOW_LLOQ_TOKENS}
    form.below_lloq_tokens = [t for t in tokens if t.upper() in blq or t.startswith("<")]
    other = [t for t in tokens if t not in form.below_lloq_tokens]
    if form.below_lloq_tokens and form.lloq is None and kind == "concentration_time":
        notes.append(f"Cells say {', '.join(repr(t) for t in form.below_lloq_tokens[:4])}: enter the LLOQ (it is not in the sheet).")
    if other:
        notes.append(f"Cells say {', '.join(repr(t) for t in other[:6])}: mark them as 'no sample' or correct the file.")

    _constants(form, grid, header_region, names, drug=drug, products=products or [], evidence=evidence, notes=notes)
    form.evidence = evidence
    return form, notes


def _col_index(letter: str) -> int:
    from openpyxl.utils import column_index_from_string

    return column_index_from_string(letter)


def _is_plain_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def _constants(form: SheetForm, grid: SheetGrid, header_region: range, names: str, *, drug: str,
               products: list[dict[str, str]], evidence: list[Evidence], notes: list[str]) -> None:
    title = " ".join(t for _r, t in _texts(grid, header_region))
    words = f"{names} {title}"

    def from_cell(pattern: re.Pattern[str], key: str, supports: str, group: int = 1) -> str | None:
        found = _find(grid, header_region, pattern)
        if found:
            value = found[1].group(group)
            evidence.append(Evidence(cell=found[0], quote=found[1].group(0).strip(), supports=f"{supports} {value}",
                                     field=key, value=value))
            return value
        match = pattern.search(names)
        if match:
            notes.append(f"{key} {match.group(group)!r} is taken from the file name: check it.")
            return match.group(group)
        return None

    role = "REF" if _REFERENCE.search(words) else "TEST" if _TEST.search(words) else ""
    if form.kind == "dissolution":
        c = form.constants
        c["role"] = "RLD" if role == "REF" else role
        if c["role"] == "TEST":
            test = next((p["name"] for p in products if p.get("role") == "TEST"), "")
            if test:
                c["product"] = test
        for key, pattern, supports in (("ph", _PH, "pH"), ("rpm", _RPM, "rpm"), ("volume_ml", _VOLUME, "medium volume"),
                                       ("batch", _BATCH, "batch"), ("strength_mg", _DOSE, "strength")):
            value = from_cell(pattern, key, supports)
            if value:
                c[key] = value
        medium = from_cell(_MEDIUM, "medium", "medium")
        if medium:
            c["medium"] = medium
        apparatus = from_cell(_APPARATUS, "apparatus", "apparatus", group=0)
        if apparatus:
            c["apparatus"] = apparatus
        if not c.get("product"):
            notes.append("Name the product as the brief does (and its role) so the plan item and f2 can use this profile.")
        return
    c = form.constants
    study = _STUDY_ID.search(names) or _STUDY_ID.search(title)
    stem = re.match(r"[A-Za-z0-9]+", names.strip())
    base = study.group(1) if study else stem.group(0) if stem else ""
    if base:
        c["study_id"] = base + (f"-{role}" if role else "")
        notes.append(f"Study id {c['study_id']!r} is made from the file name: give each arm its own id.")
    c["analyte"] = drug or "parent"
    matrix = re.search(r"\b(plasma|serum|whole blood|blood|urine)\b", title, re.IGNORECASE)
    c["matrix"] = matrix.group(1).lower() if matrix else "plasma"
    dose = from_cell(_DOSE, "dose", "dose")
    if dose:
        c["dose"] = dose
        c["dose_unit"] = "mg"
    c["route"] = "iv_infusion" if _IV.search(words) else "oral"
    if c["route"] == "iv_infusion":
        c["formulation"] = "solution"
    elif _MR.search(words):
        c["formulation"] = "mr"
    if _FED.search(words):
        c["food_state"] = "fed"
    elif _FASTED.search(words):
        c["food_state"] = "fasted"


def to_proposal(form: SheetForm, grid: SheetGrid) -> dict[str, Any]:
    """The mapping recipe the form stands for (the data-mapping proposal shape, applied and validated by code)."""
    columns: list[dict[str, Any]] = []
    if form.layout == "times_down" and form.time_column:
        columns.append({"column": form.time_column, "role": "time"})
    if form.subject_column:
        columns.append({"column": form.subject_column, "role": "subject_id"})
    if form.group_column:
        columns.append({"column": form.group_column, "role": "group"})
    wide = form.layout == "times_down" and len(form.value_columns) > 1 and not form.subject_column
    for column in form.value_columns:
        label = as_text(grid.cell(form.header_row, column).value) if (wide and form.header_row) else ""
        columns.append({"column": column, "role": "value", **({"series_label": label or column} if wide else {})})
    if form.layout == "times_down":
        for column, role in ((form.sd_column, "sd"), (form.n_column, "n")):
            if column:
                columns.append({"column": column, "role": role})
    evidence = [e.model_dump(include={"cell", "quote", "supports"}) for e in form.evidence if _still_true(e, form)]
    table = {
        "record_type": form.kind, "sheet": form.sheet, "header_rows": form.header_row, "first_data_row": form.first_data_row,
        "last_data_row": form.last_data_row, "columns": columns, "time_unit": form.time_unit, "value_unit": form.value_unit,
        "statistic": form.statistic, "lloq": form.lloq, "below_lloq_tokens": form.below_lloq_tokens,
        "missing_tokens": form.missing_tokens, "decimal_comma": form.decimal_comma,
        "constants": [{"key": k, "value": str(v)} for k, v in form.constants.items() if str(v).strip()],
        "evidence": evidence,
    }
    if form.layout == "times_across":
        table["time_row"] = form.header_row
    return {"tables": [table], "questions_for_reviewer": []}


def _still_true(evidence: Evidence, form: SheetForm) -> bool:
    """A quote found by `suggest` stays only while the form still says what it supports (a changed unit drops it)."""
    if not evidence.field:
        return True
    if evidence.field == "value_unit":
        return evidence.value.lower() == form.value_unit.lower()
    if evidence.field == "time_unit":
        return evidence.value == form.time_unit
    if evidence.field == "lloq":
        return form.lloq is not None and f"{form.lloq:g}" == evidence.value
    return str(form.constants.get(evidence.field, "")).strip() == evidence.value
