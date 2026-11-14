"""The value-level answer key (plan 2026-11-12 G1, contracts §8.1 and §13): what the scientist's analysts read in a
delivery, one row per value, as a workbook the scorer (`value_score`) and the two-key comparison (`key_compare`) load.

The key is a person's reading of the files, written by people who did not build the pipeline (decision 8: the
scientist owns it, a trained analyst fills it, a second analyst verifies it independently). It names no anchor: the
scorer joins a key row and a value by what the value is about (study, arm, analyte, matrix, subject, product, batch,
vessel, period, conditions, field, time in minutes), never by where code says it found it.

Sheets (row 1 holds the column names, in any order):
    Header     one row: schema (value-key/2), delivery, analyst, date, status (draft, verified, adjudicated)
    Key        one row per expected value: file, where (the sheet's name, or the page's position in a PDF: "12",
               "p. 12", a range "2-3"), table, study, arm, analyte, matrix, subject, [product, batch, vessel, period,
               occasion, sequence, conditions], field, time, time_unit, value, unit, [statistic, spread, spread_kind,
               n], note. `field` is the ledger's vocabulary (`modeler_intake.fields`); `value` as written: a number,
               a BLQ form (BLQ, <0.5), a missing token (NS) or the text of a name or a choice; `conditions` the
               name=value pairs that tell two runs or intervals apart (names from fields.CONDITION_FIELDS), joined by
               ";". The bracketed columns are optional. The join uses the labels up to period and the conditions
               (§13); occasion, sequence, statistic, spread, spread_kind and n are checked on the value paired with
               the row when the row states them (`ATTRIBUTE_COLUMNS`).
    Studies    optional: study, names (other spellings, ";"-separated), then one column per routing tag (population,
               special_population, route, food_state, application ...): the totals by tag
    Not data   optional: file, where, table, reason: a table the analysts read as no data
    Read me    optional, ignored: the template's instructions

Every cell is text. A cell that is not (a number, a date, a bool typed into a cell not formatted as text) is refused
with its cell named, so 0123, 001, 12.40 and 1:30 are never re-typed by a loader; the template formats every column
as text. What the loader refuses is the key's shape (a sheet, a column, a field or a condition it does not know); a
row it reads but whose value or time the scorer cannot use is kept and listed by the scorer, never dropped.

The key never lives in the repository: it names the client's files (docs/evaluations/value-key-runbook.md).
`key_from_truth` writes the key of the synthetic files (`modeler_intake.synthetic`), for tests only.
"""

from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import BaseModel, ConfigDict

from modeler_intake.document_reading import name_key
from modeler_intake.fields import CONDITION_FIELDS, known_unit, read_choice
from modeler_intake.fields import field as field_def
from modeler_intake.grid import read_workbook_bytes
from modeler_intake.recipe import DEFAULT_BELOW_LLOQ_TOKENS
from modeler_intake.synthetic import SyntheticFile
from pbpk_domain.units import UnitError, minutes_per

SCHEMA = "value-key/2"
STATUSES = ("draft", "verified", "adjudicated")
HEADER_COLUMNS = ("schema", "delivery", "analyst", "date", "status")
KEY_COLUMNS = ("file", "where", "table", "study", "arm", "analyte", "matrix", "subject", "product", "batch", "vessel",
               "period", "occasion", "sequence", "conditions", "field", "time", "time_unit", "value", "unit", "statistic",
               "spread", "spread_kind", "n", "note")
# §13's five columns after subject, and the attributes D0 checks beside the join (occasion, sequence, statistic ...)
OPTIONAL_KEY_COLUMNS = ("product", "batch", "vessel", "period", "occasion", "sequence", "conditions", "statistic",
                        "spread", "spread_kind", "n")
ATTRIBUTE_COLUMNS = ("statistic", "spread", "spread_kind", "n", "occasion", "sequence")
ROUTING_TAGS = ("population", "special_population", "route", "food_state", "application")
STUDIES_COLUMNS = ("study", "names", *ROUTING_TAGS)
NOT_DATA_COLUMNS = ("file", "where", "table", "reason")
README_SHEET = "Read me"
SHEETS = ("Header", "Key", "Studies", "Not data")
TEMPLATE_ROWS = 2000                     # the rows of the template formatted as text, beyond the column style
LABEL_COLUMNS = ("study", "arm", "analyte", "matrix", "subject", "product", "batch", "vessel", "period")
CODE_LABELS = ("subject", "vessel", "period", "occasion", "sequence")     # codes, not names: punctuation counts

# The BLQ words today's readers know (recipe.DEFAULT_BELOW_LLOQ_TOKENS); "<x" states the LLOQ x
_BLQ = frozenset(t.upper() for t in DEFAULT_BELOW_LLOQ_TOKENS) | frozenset(("<LOQ", "LOQ", "<LOD", "BLOD"))
_MARKS = "*†‡§#"                          # footnote marks after a number ("12.3*")
_NUMBER = re.compile(r"[-+]?(\d+([.,]\d+)*|[.,]\d+)([eE][-+]?\d+)?")
_SPACED = re.compile(r"[-+]?\d{1,3}( \d{3})+([.,]\d+)?")                  # 1 234.5, 1 234,5 (NBSP, thin space: NFKC)
_AMBIGUOUS = re.compile(r"[-+]?[1-9]\d{0,2}[.,]\d{3}")                    # 1,234 and 1.234: a group or a decimal mark
_PAGES = re.compile(r"(?:pages?|pp?\.?)?\s*(.+)", re.IGNORECASE)
_PAGE_PART = re.compile(r"(\d+)(?:\s*(?:-|–|—|to)\s*(\d+))?", re.IGNORECASE)
_MOST_PAGES = 1000                       # a page range longer than this is not read as pages
_CONDITION_SPLIT = re.compile(r";(?=\s*[A-Za-z_][A-Za-z0-9_]*\s*=)")     # only before the next name=: "pH 6.8" stays
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―"})
Mark = Literal["point", "comma"]


class ValueKeyError(ValueError):
    """The key is not as the loader reads it; the message names the sheet and the cell."""


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KeyRow(_B):
    row: int                              # the Key sheet's row number
    file: str
    where: str                            # the sheet's name, or the page's position in the PDF (a range: "2-3")
    table: str
    study: str
    arm: str
    analyte: str
    matrix: str
    subject: str
    product: str = ""                     # §13: the five optional columns after subject
    batch: str = ""
    vessel: str = ""
    period: str = ""
    occasion: str = ""                    # checked beside the join (ATTRIBUTE_COLUMNS)
    sequence: str = ""
    conditions: str = ""                  # name=value pairs joined by ";"
    field: str
    time: str
    time_unit: str
    value: str                            # as written
    unit: str
    statistic: str = ""                   # checked beside the join: individual, arithmetic_mean, geometric_mean ...
    spread: str = ""                      # as written (SD, SE or CV% value)
    spread_kind: str = ""                 # SD, SE, CV% ...
    n: str = ""                           # the n of a mean
    note: str


class ValueKey(_B):
    schema_id: str
    delivery: str
    analyst: str
    date: str
    status: str
    rows: tuple[KeyRow, ...]
    studies: tuple[dict[str, str], ...]   # study, names, a tag per column, and "row" (the Studies sheet's row number)
    not_data: tuple[dict[str, str], ...]  # file, where, table, reason, and "row"


# --- loading -------------------------------------------------------------------------------------------------------


def _cell(sheet: str, row: int, column: int) -> str:
    return f"{sheet}!{get_column_letter(column)}{row}"


def _text_cells(grid: Any, sheet: str) -> dict[tuple[int, int], str]:
    """Every non-empty cell of a sheet as text; a cell that is not text is refused with its cell named."""
    out: dict[tuple[int, int], str] = {}
    for (row, column), cell in grid.cells.items():
        value = cell.value
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not isinstance(value, str):
            raise ValueKeyError(f"{_cell(sheet, row, column)}: {value!r} is not text; every key cell is text (format the "
                                "column as text, as the template does, so that 001, 0123, 12.40 and 1:30 stay as written)")
        out[(row, column)] = value.strip()
    return out


def _table(grid: Any, sheet: str, known: Sequence[str], required: Sequence[str], *,
           extra: bool = False) -> tuple[dict[str, int], list[tuple[int, dict[str, str]]]]:
    """A sheet as (column name -> column, [(row number, {column name: text})]) for its non-empty rows below row 1."""
    cells = _text_cells(grid, sheet)
    columns: dict[str, int] = {}
    for (row, column), text in sorted(cells.items()):
        if row != 1:
            continue
        name = text.strip().lower().rstrip("*").strip()
        if name in columns:
            raise ValueKeyError(f"{_cell(sheet, 1, column)}: the column {name!r} is named twice")
        if name not in known and not extra:
            raise ValueKeyError(f"{_cell(sheet, 1, column)}: unknown column {text!r}; the {sheet} sheet has "
                                f"{', '.join(known)}")
        if name == "row":
            raise ValueKeyError(f"{_cell(sheet, 1, column)}: 'row' is not a column name")
        columns[name] = column
    missing = [c for c in required if c not in columns]
    if missing:
        raise ValueKeyError(f"{sheet}!1: the column{'s' if len(missing) > 1 else ''} {', '.join(missing)} "
                            f"{'are' if len(missing) > 1 else 'is'} missing")
    unnamed = sorted({column for (row, column) in cells if row > 1} - set(columns.values()))
    if unnamed:
        first = min(row for (row, column) in cells if column == unnamed[0] and row > 1)
        raise ValueKeyError(f"{_cell(sheet, first, unnamed[0])}: a cell under no column name")
    rows = []
    for row in sorted({r for (r, _c) in cells if r > 1}):
        rows.append((row, {name: cells.get((row, column), "") for name, column in columns.items()}))
    return columns, rows


def split_conditions(text: str) -> list[str]:
    """A conditions text cut into its name=value parts: at a ";" followed by the next name and "=", so a value that
    holds a ";" ("medium=phosphate buffer; pH 6.8;ph=6.8") stays whole."""
    return [part for part in _CONDITION_SPLIT.split(text or "") if part.strip()]


def parse_conditions(text: str) -> dict[str, str]:
    """The name=value pairs of a `conditions` cell (";"-separated, any order, `split_conditions`); ValueError for a
    name not in fields.CONDITION_FIELDS or a pair without "="."""
    out: dict[str, str] = {}
    for part in split_conditions(text):
        if not part.strip():
            continue
        name, sep, value = part.partition("=")
        name = name.strip().lower()
        if not sep or not name:
            raise ValueError(f"{part.strip()!r} is not name=value")
        if name not in CONDITION_FIELDS:
            raise ValueError(f"unknown condition {name!r}: one of {', '.join(CONDITION_FIELDS)}")
        if name in out:
            raise ValueError(f"the condition {name!r} is given twice")
        out[name] = value.strip()
    return out


def format_conditions(conditions: Mapping[str, str] | Iterable[tuple[str, str]]) -> str:
    """Conditions as a key cell writes them: name=value pairs joined by ";"."""
    pairs = conditions.items() if isinstance(conditions, Mapping) else conditions
    return ";".join(f"{name}={value}" for name, value in pairs)


def load_key(data: bytes, filename: str) -> ValueKey:
    """Read a key workbook (`modeler_intake.grid.read_workbook_bytes`). ValueKeyError names the sheet and cell of the
    first thing it cannot read: a cell that is not text, a sheet or column it does not know, an unknown field or
    condition, a schema other than value-key/2, a status other than draft, verified or adjudicated."""
    suffix = Path(filename).suffix.lower()
    if suffix in (".yaml", ".yml"):
        raise ValueKeyError(f"{filename}: a YAML key is the v1 key (files, studies, dissolution): score it with "
                            "modeler_project.delivery_report; a value key is a workbook (the template: --template)")
    try:
        book = read_workbook_bytes(data, filename)
    except Exception as exc:                 # openpyxl and xlrd raise many types for a file that is not a workbook
        raise ValueKeyError(f"{filename}: not a readable workbook ({type(exc).__name__}: {exc})") from exc
    unknown = [name for name in book.sheets if name not in SHEETS and name != README_SHEET]
    if unknown:
        raise ValueKeyError(f"{filename}: unknown sheet {unknown[0]!r}; a key has the sheets {', '.join(SHEETS)} "
                            f"(and {README_SHEET!r})")
    for needed in ("Header", "Key"):
        if needed not in book.sheets:
            raise ValueKeyError(f"{filename}: the sheet {needed!r} is missing")

    _columns, header_rows = _table(book.sheets["Header"], "Header", HEADER_COLUMNS, HEADER_COLUMNS)
    if len(header_rows) != 1 or header_rows[0][0] != 2:
        raise ValueKeyError("Header!2: the header is one row, row 2")
    header = header_rows[0][1]
    if header["schema"] != SCHEMA:
        raise ValueKeyError(f"Header!2: schema {header['schema']!r}; this loader reads {SCHEMA}")
    if header["status"] not in STATUSES:
        raise ValueKeyError(f"Header!2: status {header['status']!r}; one of {', '.join(STATUSES)}")

    columns, key_rows = _table(book.sheets["Key"], "Key", KEY_COLUMNS,
                               [c for c in KEY_COLUMNS if c not in OPTIONAL_KEY_COLUMNS])
    rows = []
    for number, values in key_rows:
        field = values["field"]
        if field_def(field) is None:
            where = _cell("Key", number, columns["field"])
            raise ValueKeyError(f"{where}: unknown field {field!r}" if field else f"{where}: the field is empty")
        if values.get("conditions"):
            try:
                parse_conditions(values["conditions"])
            except ValueError as exc:
                raise ValueKeyError(f"{_cell('Key', number, columns['conditions'])}: {exc}") from exc
        rows.append(KeyRow(row=number, **{name: values.get(name, "") for name in KEY_COLUMNS}))

    studies: list[dict[str, str]] = []
    if "Studies" in book.sheets:
        columns, study_rows = _table(book.sheets["Studies"], "Studies", STUDIES_COLUMNS, ("study",), extra=True)
        for number, values in study_rows:
            if not values["study"]:
                raise ValueKeyError(f"{_cell('Studies', number, columns['study'])}: the study is empty")
            studies.append({**values, "row": str(number)})
    not_data: list[dict[str, str]] = []
    if "Not data" in book.sheets:
        _columns, nd_rows = _table(book.sheets["Not data"], "Not data", NOT_DATA_COLUMNS, NOT_DATA_COLUMNS)
        not_data = [{**values, "row": str(number)} for number, values in nd_rows]
    return ValueKey(schema_id=header["schema"], delivery=header["delivery"], analyst=header["analyst"],
                    date=header["date"], status=header["status"], rows=tuple(rows), studies=tuple(studies),
                    not_data=tuple(not_data))


# --- writing -------------------------------------------------------------------------------------------------------

_README = (
    "The value key: what the analysts read in a delivery, one Key row per value (plan G1, decision 8).",
    "",
    "Every cell is text (the columns are formatted as text): write values exactly as the file writes them (001, 12.40).",
    "A number with one separator and three digits after it (1,234 or 1.234) is settled by the other numbers of its",
    "table (a decimal point or a decimal comma written there); when none settles it, write 1234 or 1.234.",
    "Header: schema value-key/2; the delivery; the analyst; the date; status draft, verified or adjudicated.",
    "Key, one row per value:",
    "  file: the file's name; where: the sheet's name, or the page of a PDF as the viewer counts it (1 = the first",
    "  page), not the number printed on the page; for a table continued over pages, each value's own page (empty: the",
    "  whole file; a range such as 2-3 names every page in it); table: its caption or your name for it.",
    "  study, arm, analyte, matrix, subject, product, batch, vessel, period, occasion, sequence: as the file names them",
    "  (empty: not stated).",
    "  conditions: what tells two runs or intervals apart, as name=value pairs joined by ';' (medium=0.1 N HCl;ph=1.2;",
    "  interval_start_h=0;interval_end_h=4). Names: " + ", ".join(CONDITION_FIELDS) + ".",
    "  field: the ledger's field (concentration, percent_dissolved, dose, lloq, n, pk.Cmax, phys.logp ...).",
    "  time and time_unit: the nominal time and its unit (min, h, day), for a value that has one.",
    "  value: as written: a number, BLQ or <0.5, a missing token such as NS, or the text of a name or a choice.",
    "  unit: as written; statistic (individual, arithmetic_mean, geometric_mean, median), spread, spread_kind (SD, SE,",
    "  CV% ...) and n: as the file states them for that value (empty: not stated); note: anything for the scientist.",
    "Studies (optional): study, names (other spellings, ';'-separated), and the routing tags of each study.",
    "Not data (optional): file, where, table, reason: a table that holds no data.",
    "Never put a key in the repository: it names the client's files.",
)


def _sheet(wb: Workbook, title: str, columns: Sequence[str], rows: Sequence[Sequence[str]], *, formatted: int) -> None:
    ws = wb.create_sheet(title)
    for column, name in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=column, value=name)
        cell.font = Font(bold=True)
        letter = cell.column_letter
        ws.column_dimensions[letter].number_format = "@"
        ws.column_dimensions[letter].width = max(10, len(name) + 4)
    for r, values in enumerate(rows, start=2):
        for column, text in enumerate(values, start=1):
            if text == "":
                continue
            cell = ws.cell(row=r, column=column, value=text)
            cell.data_type = "s"             # never a formula, whatever the text starts with
            cell.number_format = "@"
    for r in range(len(rows) + 2, formatted + 2):
        for column in range(1, len(columns) + 1):
            ws.cell(row=r, column=column).number_format = "@"
    ws.freeze_panes = "A2"


def write_key(header: Mapping[str, str], rows: Sequence[Mapping[str, str]], studies: Sequence[Mapping[str, str]] = (),
              not_data: Sequence[Mapping[str, str]] = (), *, formatted: int = 0) -> bytes:
    """A key workbook from its parts, every cell written as text: the header's five values, the Key rows, the Studies
    rows (a tag the standard columns lack gets its own column) and the Not data rows (each a mapping of column name to
    text; a column left out is empty; "row" is never written). `formatted`: how many rows below the last are formatted
    as text for an analyst to fill."""
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Header", HEADER_COLUMNS, [[header.get(c, "") for c in HEADER_COLUMNS]], formatted=1)
    status = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=False)
    wb["Header"].add_data_validation(status)
    status.add("E2")
    _sheet(wb, "Key", KEY_COLUMNS, [[r.get(c, "") for c in KEY_COLUMNS] for r in rows], formatted=formatted)
    tags = [*STUDIES_COLUMNS, *dict.fromkeys(c for s in studies for c in s if c not in STUDIES_COLUMNS and c != "row")]
    _sheet(wb, "Studies", tags, [[s.get(c, "") for c in tags] for s in studies], formatted=min(formatted, 200))
    _sheet(wb, "Not data", NOT_DATA_COLUMNS, [[n.get(c, "") for c in NOT_DATA_COLUMNS] for n in not_data],
           formatted=min(formatted, 200))
    readme = wb.create_sheet(README_SHEET)
    for r, line in enumerate(_README, start=1):
        if line:
            readme.cell(row=r, column=1, value=line).data_type = "s"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def template_workbook() -> bytes:
    """The empty key: the four sheets with their columns, every column formatted as text, the schema written and the
    status a draft, and a Read me sheet."""
    return write_key({"schema": SCHEMA, "status": "draft"}, (), formatted=TEMPLATE_ROWS)


def _where(locator: str) -> str:
    """A key's `where` for a truth locator or range: the sheet's name, the page number, or "" (a Word or text file)."""
    match = re.match(r"s:'((?:[^']|'')*)'!", locator)
    if match:
        return match.group(1).replace("''", "'")
    match = re.match(r"p:(\d+)/", locator)
    return match.group(1) if match else ""


def key_from_truth(files: Sequence[SyntheticFile], *, analyst: str = "test") -> bytes:
    """The key of the synthetic files' truth (tests only): one Key row per truth value, with its file, where, table,
    labels, conditions, field, time, value and unit as written, and a Not data row per not_data truth table."""
    rows = []
    not_data = []
    for file in files:
        for value in file.values:
            rows.append({"file": file.name, "where": _where(value.locator), "table": value.table, "study": value.study,
                         "arm": value.arm, "analyte": value.analyte, "matrix": value.matrix, "subject": value.subject,
                         "product": value.product, "batch": value.batch, "vessel": value.vessel, "period": value.period,
                         "occasion": value.occasion, "conditions": format_conditions(value.conditions),
                         "field": value.field, "time": value.time, "time_unit": value.time_unit if value.time else "",
                         "value": value.value, "unit": value.unit, "statistic": value.statistic, "spread": value.spread,
                         "spread_kind": value.spread_kind, "n": value.n, "note": ""})
        for table in file.tables:
            if table.kind == "not_data":
                not_data.append({"file": file.name, "where": _where(table.where), "table": table.id,
                                 "reason": table.spec.not_data_reason or "not data"})
    header = {"schema": SCHEMA, "delivery": "synthetic", "analyst": analyst, "date": "2026-01-01", "status": "verified"}
    return write_key(header, rows, (), not_data)


# --- reading a key's text the way the scorer compares it -------------------------------------------------------------


def clean(text: str) -> str:
    """NFKC, U+2212 as "-", outer whitespace off."""
    return unicodedata.normalize("NFKC", text or "").replace("−", "-").strip()


def norm_text(text: str) -> str:
    """Free text as code compares it: NFC, whitespace collapsed, case aside."""
    return " ".join(unicodedata.normalize("NFC", text or "").split()).casefold()


def _bare(text: str) -> str:
    """A number's text with a trailing footnote mark (12.3*) and a trailing % read past."""
    t = clean(text).rstrip(_MARKS).strip()
    return t[:-1].strip() if t.endswith("%") else t


def separator_ambiguous(text: str) -> bool:
    """Whether a number writes one separator once with three digits after it and a first group of one to three digits
    (1,234 or 1.234): a thousands group or a decimal mark, which only the other numbers of its table can settle (the
    rule of contracts §6.2's parse_cell). 0.125 and 12.5 are not ambiguous."""
    return _AMBIGUOUS.fullmatch(_bare(text)) is not None


def decimal_mark(text: str) -> Mark | None:
    """The decimal mark a number shows beyond doubt: a single separator that is no thousands group (12.5, 0,125), the
    last of two kinds (1,234.5), the other kind than a repeated group separator (1.234.567: comma), the separator after
    space groups (1 234,5). None: no separator, an ambiguous one (1,234), or not a number."""
    t = _bare(text)
    if t[:1] in "<≤>≥":
        t = t[1:].strip()
    if _SPACED.fullmatch(t):
        return "comma" if "," in t else "point" if "." in t else None
    if not _NUMBER.fullmatch(t) or _AMBIGUOUS.fullmatch(t):
        return None
    mantissa = re.split(r"[eE]", t)[0]
    seps = [c for c in mantissa if c in ".,"]
    if not seps:
        return None
    if len(set(seps)) == 2:
        found: Mark = "point" if seps[-1] == "." else "comma"
    elif len(seps) > 1:
        found = "comma" if seps[0] == "." else "point"
    else:
        found = "point" if seps[0] == "." else "comma"
    return found if to_decimal(t, found) is not None else None


def to_decimal(text: str, mark: Mark | None = None) -> Decimal | None:
    """The number a text writes as a bare number, exactly as written (12.40 keeps its two decimals), or None. Space
    groups (1 234,5, NBSP and thin spaces too) and one kind of separator repeated (1.234.567) group thousands; with two
    kinds the last is the decimal (1,234.5 and 1.234,5); a single separator is the decimal (12,5 is 12.5), except an
    ambiguous one (1,234: `separator_ambiguous`), which `mark` settles (point: 1,234 is 1234 and 1.234 is 1.234;
    comma: the reverse) and which is None without one. A trailing footnote mark (12.3*) and a trailing % are read
    past. Numbers code wrote (`number_text`) are read with mark "point"."""
    t = _bare(text)
    if _SPACED.fullmatch(t):
        t = t.replace(" ", "")
        try:
            return Decimal(t.replace(",", "."))
        except InvalidOperation:
            return None
    if not _NUMBER.fullmatch(t):
        return None
    mantissa, _e, exponent = t.partition("e") if "e" in t else t.partition("E")
    seps = [c for c in mantissa if c in ".,"]
    if len(set(seps)) == 2:
        point = seps[-1]
        other = "," if point == "." else "."
        whole, _sep, _fraction = mantissa.rpartition(point)
        groups = whole.lstrip("+-").split(other)
        if any(len(g) != 3 for g in groups[1:]) or not 1 <= len(groups[0]) <= 3 or point in whole:
            return None
        mantissa = mantissa.replace(other, "").replace(point, ".")
    elif len(seps) == 1:
        if _AMBIGUOUS.fullmatch(mantissa) and not exponent:
            if mark is None:
                return None
            group = (seps[0] == ",") == (mark == "point")
            mantissa = mantissa.replace(seps[0], "" if group else ".")
        else:
            mantissa = mantissa.replace(seps[0], ".")
    elif seps:
        groups = re.split(r"[.,]", mantissa.lstrip("+-"))
        if any(len(g) != 3 for g in groups[1:]) or not 1 <= len(groups[0]) <= 3:
            return None
        mantissa = mantissa.replace(seps[0], "")
    try:
        return Decimal(mantissa + (f"E{exponent}" if exponent else ""))
    except InvalidOperation:
        return None


def key_marks(rows: Sequence[KeyRow]) -> dict[int, Mark | None]:
    """Each key row's decimal mark, from the numbers of its table (the rows of one file, where and table): "point" or
    "comma" when the values, spreads and times written there show one mark and only that one (`decimal_mark`), else
    None. It settles a "1,234" the way the pipeline settles it from its column (contracts §6.2), never by guessing."""
    def group(r: KeyRow) -> tuple[str, str, str]:
        return file_key(r.file), norm_text(r.where), norm_text(r.table)

    seen: dict[tuple[str, str, str], set[str]] = {}
    for r in rows:
        marks = seen.setdefault(group(r), set())
        for text in (r.value, r.spread, r.time):
            found = decimal_mark(text) if text else None
            if found is not None:
                marks.add(found)
    out: dict[int, Mark | None] = {}
    for r in rows:
        marks = seen[group(r)]
        out[r.row] = next(iter(marks)) if len(marks) == 1 else None      # type: ignore[assignment]
    return out


@dataclass(frozen=True)
class Reading:
    """A value as code compares it. number: a number; blq: below the LLOQ (`number`: the LLOQ a "<x" form states);
    above: above the range (`number`: the limit); missing: a missing token (no value); text: a name, a choice or free
    text (`text`: its comparison form); empty; unreadable: a numeric field's text that holds a number but is not one
    of these forms ("12.3 (4.5)"); ambiguous: a number whose single separator its table does not settle (1,234)."""

    kind: Literal["number", "blq", "above", "missing", "text", "empty", "unreadable", "ambiguous"]
    number: Decimal | None = None
    text: str = ""


def text_key(field: str, text: str) -> str:
    """A name or a choice as code compares it: a choice by the one it states (fields.read_choice: "immediate release"
    is IR), a name by name_key, free text case and spacing aside."""
    found = field_def(field)
    if found is not None and found.value == "choice":
        choice = read_choice(field, text)
        return name_key(choice if choice is not None else text)
    if found is not None and found.value == "name":
        return name_key(text)
    return norm_text(text)


def read_value(field: str, text: str, mark: Mark | None = None) -> Reading:
    """A value as written, read for its field: a numeric field's number, BLQ form (a BLQ word, "<x"), above-range form
    (">x") or missing token (any text with no digit); any other field's text (`text_key`). `mark` settles an ambiguous
    separator (`to_decimal`); without it a "1,234" reads as ambiguous."""
    t = clean(text)
    if not t:
        return Reading("empty")
    found = field_def(field)
    if found is not None and found.value not in ("number", "integer"):
        return Reading("text", text=text_key(field, t))
    if t.upper() in _BLQ:
        return Reading("blq")
    if t[0] in "<≤>≥":
        rest = t[1:].strip()
        kind: Literal["blq", "above"] = "blq" if t[0] in "<≤" else "above"
        if not any(c.isdigit() for c in rest):
            return Reading(kind)
        number = to_decimal(rest, mark)
        if number is None and separator_ambiguous(rest):
            return Reading("ambiguous")
        return Reading(kind, number) if number is not None else Reading("unreadable")
    number = to_decimal(t, mark)
    if number is not None:
        return Reading("number", number)
    if separator_ambiguous(t):
        return Reading("ambiguous")
    if found is None:
        return Reading("text", text=norm_text(t))
    if not any(c.isdigit() for c in t):
        return Reading("missing", text=norm_text(t))
    return Reading("unreadable")


def readings_equal(a: Reading, b: Reading) -> bool:
    """Whether two readings say the same: the same kind and number (12.40 equals 12.4) and, for text, the same text;
    every missing token is the same "no value"."""
    if a.kind != b.kind:
        return False
    if a.kind == "text":
        return a.text == b.text
    return a.number == b.number


def unit_key(field: str, unit: str | None) -> str:
    """A unit as code compares it: its canonical spelling in the table of the field's class (fields.known_unit, which
    goes through validate.canonical_unit), else its text, case and spacing aside. Nothing is converted."""
    u = clean(unit or "")
    if not u:
        return ""
    known = known_unit(field, u)
    return f"={known}" if known is not None else norm_text(u.replace("μ", "µ"))


def time_minutes(time: str, unit: str, mark: Mark | None = None) -> float | None:
    """A key's time in minutes (pbpk_domain.units.minutes_per); ValueError when the time is not a number, its
    separator is ambiguous (`mark` settles it) or its unit is not known. An empty time is None."""
    t = clean(time)
    if not t:
        return None
    number = to_decimal(t, mark)
    if number is None:
        if separator_ambiguous(t):
            raise ValueError("the time's separator is ambiguous (1,000 or 1.000): write it without a thousands separator")
        raise ValueError("the time is not a number")
    if not clean(unit):
        raise ValueError("the time has no unit")
    try:
        factor = minutes_per(clean(unit))
    except UnitError as exc:
        raise ValueError("the time unit is not known") from exc
    return round(float(number) * factor, 6)


def code_key(text: str) -> str:
    """A code (a subject, vessel, period, occasion or sequence) as the join compares it: case and spacing aside, "_"
    read as a space and every dash as "-", other punctuation kept, so that subjects 1-01 and 10-1 stay two subjects."""
    return " ".join(clean(text).translate(_DASHES).replace("_", " ").split()).casefold()


def label_key(column: str, text: str) -> str:
    """A label as the join compares it: a matrix by the choice it states (fields.read_choice), a code (`CODE_LABELS`:
    subject, vessel, period, occasion, sequence) by `code_key`, every other label (a study, arm, analyte, product or
    batch: a name) by name_key (case, spaces and punctuation aside)."""
    if column == "matrix":
        choice = read_choice("matrix", text) if clean(text) else None
        return name_key(choice if choice is not None else text)
    if column in CODE_LABELS:
        return code_key(text)
    return name_key(text)


_STATISTICS = {"MEAN": "ARITHMETICMEAN", "AM": "ARITHMETICMEAN", "ARITHMETIC": "ARITHMETICMEAN",
               "GEOMEAN": "GEOMETRICMEAN", "GMEAN": "GEOMETRICMEAN", "GM": "GEOMETRICMEAN", "GEOMETRIC": "GEOMETRICMEAN",
               "INDIVIDUALS": "INDIVIDUAL"}
_SPREAD_KINDS = {"SEM": "SE", "STANDARDERROR": "SE", "STANDARDDEVIATION": "SD", "CVPERCENT": "CV", "PERCENTCV": "CV",
                 "GSD": "GEOSD", "GEOMETRICSD": "GEOSD", "GCV": "GEOCV", "GEOMETRICCV": "GEOCV"}


def statistic_key(text: str | None) -> str:
    """A statistic as the attribute check compares it: name_key, with "mean" read as the arithmetic mean and
    "geomean" as the geometric one."""
    key = name_key(text or "")
    return _STATISTICS.get(key, key)


def spread_kind_key(text: str | None) -> str:
    """A spread's kind as the attribute check compares it: name_key (CV% and %CV are one), SEM read as SE."""
    key = name_key(text or "")
    return _SPREAD_KINDS.get(key, key)


def conditions_key(conditions: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """Conditions as the join compares them: sorted by name, a number by its value (1.20 is 1.2), a choice by the one
    it states, other text by name_key."""
    out = []
    for name, value in conditions.items():
        reading = read_value(name, value)
        if reading.kind == "number" and reading.number is not None:
            text = format(reading.number.normalize(), "f")
        elif reading.kind == "text":
            text = reading.text
        else:
            text = name_key(value)
        out.append((name.strip().lower(), text))
    return tuple(sorted(out))


def study_groups(*keys: ValueKey) -> dict[str, str]:
    """name_key -> the canonical key of its study, from the Studies sheets: a study and its other names are one study
    (two rows that share a name are one too). Names no Studies row lists are their own."""
    groups: list[set[str]] = []
    for key in keys:
        for study in key.studies:
            names = {name_key(study.get("study", ""))} | {name_key(n) for n in study.get("names", "").split(";")}
            names.discard("")
            if not names:
                continue
            touching = [g for g in groups if g & names]
            merged = set(names).union(*touching)
            groups = [g for g in groups if not g & names] + [merged]
    out: dict[str, str] = {}
    for group in groups:
        canonical = min(group)
        for name in group:
            out[name] = canonical
    return out


def file_key(name: str) -> str:
    """A file name as a person may type it: NFC, spaces collapsed, case aside."""
    return norm_text(name)


def where_pages(where: str) -> tuple[int, ...]:
    """The pages a `where` names when it reads as pages: "12", "p. 12", "page 12", a range "2-3" or "pp. 2-3" (every
    page in it), a list "2, 5". () when it does not (a sheet's name), or a range runs backwards or over 1000 pages."""
    match = _PAGES.fullmatch(clean(where))
    if not match:
        return ()
    pages: list[int] = []
    for part in re.split(r"\s*[,;]\s*", match.group(1).strip()):
        found = _PAGE_PART.fullmatch(part)
        if not found:
            return ()
        first = int(found.group(1))
        last = int(found.group(2)) if found.group(2) else first
        if first < 1 or last < first or last - first >= _MOST_PAGES:
            return ()
        pages.extend(range(first, last + 1))
    return tuple(dict.fromkeys(pages))


def where_places(where: str) -> tuple[tuple[str, str], ...]:
    """The places a key's `where` names: a sheet by its name and, when it reads as pages (`where_pages`: "12",
    "p. 12", "2-3"), each of those pages. Empty: () (the whole file)."""
    text = clean(where)
    if not text:
        return ()
    return (("sheet", norm_text(text)), *(("page", str(page)) for page in where_pages(text)))


def where_key(where: str) -> tuple[str, Any]:
    """A `where` as two keys compare it: by its pages when it reads as pages ("p. 2" and "2" are one page), else by
    the sheet's name."""
    pages = where_pages(where)
    return ("pages", frozenset(pages)) if pages else ("sheet", norm_text(clean(where)))
