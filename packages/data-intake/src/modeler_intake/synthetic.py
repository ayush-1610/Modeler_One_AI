"""Shared synthetic client files with their truth (docs/plans/2026-11-12-intake-contracts.md §10).

Every build tests against the same files without needing another build's code: each builder returns the file's bytes
with its tables (where they stand, their cell texts, their context lines and the approved v2 spec that reads them
exactly) and its values (each with the true locator of its cell). Every number is made up; the drug is
`Exampleamide`. The files are built in memory and deterministically (the same bytes on every call, whatever the
clock: an Office file's core dates are fixed after the library writes them).

L2: the PDF is written here by hand, as content-stream operators (text and ruling lines, Helvetica, latin-1, the
technique of `modeler_project.delivery_eval.synthetic_pdf`, which this module does not import).

Conventions of the truth, which the builds that read it rely on:
- `TruthValue.value` is the value as written: a cell's text for a plain cell ("12.1", "BLQ", "<0.5", ">1000", "NS",
  "12.3*", "12,5"), and the part code reads for a cell or line that holds more ("31.2" of "31.2 (4.1)", "50" of
  "Study 230-23, 50 mg, fasted"). The cell's or line's own text is in `TruthTable.rows`, `caption`, `above`, `below`.
- `TruthValue.locator` is a locator text (§4.1), not an anchor: the parser version is the reader's. A constant's
  locator is the context line (or the region's cell, such as a header) it is read from; a prose fact's is the span of
  its number (or word) itself.
- A value with `table == ""` is a prose fact: only the A4-prose stage (a model) reads it, so a run with agents off
  does not find it.
- A table's constants are values too: every constant that is neither a condition nor a label (§4.4 ExtractedConstant,
  §6.3: "non-condition, non-label constants -> scalar facts") has a TruthValue at the line or cell it is read from.
  That includes the constants that name the table's entities (study_id, treatment, analyte, product, batch): each is
  a scalar fact whose value is the name as code reads it ("230-23" of "Study 230-23, 50 mg, fasted"), its entity the
  table's study and the entity it names. A label constant (matrix) and a condition constant (medium, ph) are not
  values: they sit on every row's entity and conditions.
- `TruthValue.locators` names every cell a value is read with, by role: time, unit, spread, n, lloq, each condition,
  and each label of its own row (study, arm, product, batch, analyte, subject, period, vessel ...; "parameter" for the
  label cell of a key_value table).
- `TruthTable.rows` holds the region's cells as written ("" for an empty cell and for the covered cells of a merged
  range); `merges` names the merged ranges: a sheet's in A1 form ("B2:G2"), a Word table's in its own row and column
  numbers ("r1c2:r1c3"). A workbook number cell's text is the shortest round-trip form of its stored value (§4.2).
- Context lines (`caption`, `above`, `below`): a sheet table's caption is the single-cell text rows directly above it;
  its other context lines are the non-empty rows among the 3 sheet rows above the caption and the 3 below the table,
  read within the table's columns. A PDF table's caption is the line directly above its first part (the caption of a
  continued part belongs to that part: `RegionPart.caption`); a Word table's is the paragraph directly above it.
- PDF word numbers are those of `pdfplumber`'s `extract_words()` with its defaults, in its order, 1-based per page.
  Word paragraphs are numbered over the body's paragraphs (`python-docx` `Document.paragraphs`), 1-based; tables
  over the body's tables. A delimited file's sheet is named after the file's stem.
- `SyntheticFile.outside` lists the locators of the items that hold a number and lie outside every region and every
  region's context (page furniture excluded); `prose` lists the prose lines in reading order. In a workbook, every
  cell with a number is in a truth table, in a truth table's context, in `outside` or in `furniture`.
- `SyntheticFile.furniture` lists the cells with a number that are the template's own text (the README's id line and
  instructions, `client_template.README`): located, marked furniture, never an outside number.
- A PDF table region's id hashes "p:<first page>/box:<x0>,<top>,<x1>,<bottom>/<first row>": its first part's box
  rounded to whole points, and its first row's non-empty cell texts joined by single spaces (pdfplumber's own
  `find_tables()` box and `extract()` give the same id).

The TruthValue fields after `occasion` are additions to §10 (named in the contract code's report): a value's
statistic, spread, spread kind and n, its product, batch, vessel and period labels, its actual time, and the locator
of every cell it is read with (time, unit, labels, spread, n, LLOQ, conditions), which `intake_fixtures.write_truth`
writes into the ledger as §4.5 says.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import struct
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter, range_boundaries

from modeler_intake.anchors import DocxCell, DocxSpan, PdfCell, PdfSpan, SheetCell, format_locator
from modeler_intake.client_template import README, build_template
from modeler_intake.fields import TableKind
from modeler_intake.mapping_spec import Cite, ColumnMap, Constant, KeyMap, MappingSpec, RowRule
from modeler_intake.source_model import FileFormat, GridCell, RegionGrid, has_number, is_numeric_text, number_text

DRUG = "Exampleamide"
METABOLITE = "Exampleamide-M1"
TRUTH_PARSER_VERSION = "1.0+truth"      # the parser version of truth_grid's anchors: identities, never D2's version
_FIXED = datetime(2026, 1, 1, tzinfo=UTC)
_FIXED_TEXT = _FIXED.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
_CORE_DATES = re.compile(rb"(<dcterms:(created|modified)\b[^>]*>)[^<]*(</dcterms:\2>)")
# The parser name of each format, as the truth's anchors write it (intake_fixtures uses the same table)
PARSERS = {"xlsx": "workbook", "xlsm": "workbook", "xls": "workbook", "csv": "delimited", "tsv": "delimited",
           "docx": "docx", "pdf": "pdfplumber", "text": "text", "markdown": "text", "json": "text"}


@dataclass(frozen=True)
class TruthTable:
    id: str
    kind: TableKind
    where: str                                         # a `range` of §4.1 (a continued PDF table: its first part)
    rows: tuple[tuple[str, ...], ...]                  # cell texts as written, "" empty
    header_rows: int
    spec: MappingSpec                                  # the approved v2 spec that reads it exactly
    merges: tuple[str, ...] = ()
    pages: tuple[int, ...] = ()
    caption: tuple[str, ...] = ()                      # its context lines
    above: tuple[str, ...] = ()
    below: tuple[str, ...] = ()


@dataclass(frozen=True)
class TruthValue:
    table: str
    field: str
    study: str
    arm: str
    analyte: str
    matrix: str
    subject: str
    time: str
    time_unit: str
    value: str                                         # as written (BLQ, <0.5, NS included)
    unit: str
    locator: str
    conditions: tuple[tuple[str, str], ...] = ()
    occasion: str = ""
    # additions (see the module docstring)
    statistic: str = ""
    spread: str = ""
    spread_kind: str = ""
    n: str = ""
    product: str = ""
    batch: str = ""
    vessel: str = ""
    period: str = ""
    time_actual: str = ""
    locators: tuple[tuple[str, str], ...] = ()       # role -> locator: time, unit, the labels, spread, n, lloq, conditions


@dataclass(frozen=True)
class SyntheticFile:
    name: str
    data: bytes
    format: FileFormat
    tables: tuple[TruthTable, ...]
    values: tuple[TruthValue, ...]
    outside: tuple[str, ...] = ()
    prose: tuple[str, ...] = ()
    notes: str = ""
    furniture: tuple[str, ...] = ()


# --- small helpers -------------------------------------------------------------------------------------------------


def _text(value: object) -> str:
    """A cell's text as §4.2 writes it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return number_text(value)
    return str(value)


def _sheet_cell(sheet: str, row: int, column: int) -> str:
    return format_locator(SheetCell(sheet=sheet, cell=f"{get_column_letter(column)}{row}"))


def _stable_zip(data: bytes) -> bytes:
    """The same archive with fixed member dates and fixed core dates (openpyxl stamps docProps/core.xml's `modified`
    with the clock when it saves, whatever the workbook says), so that a file built twice has the same bytes."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            fixed = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            fixed.compress_type = zipfile.ZIP_DEFLATED
            fixed.external_attr = info.external_attr
            content = source.read(info.filename)
            if info.filename == "docProps/core.xml":
                content = _CORE_DATES.sub(rb"\g<1>" + _FIXED_TEXT + rb"\g<3>", content)
            target.writestr(fixed, content)
    return out.getvalue()


def _save(wb: Workbook) -> bytes:
    wb.properties.created = _FIXED.replace(tzinfo=None)
    wb.properties.modified = _FIXED.replace(tzinfo=None)
    buffer = io.BytesIO()
    wb.save(buffer)
    return _stable_zip(buffer.getvalue())


def _put(ws, row: int, column: int, value: object, number_format: str | None = None) -> None:
    if value is None or value == "":
        return
    cell = ws.cell(row=row, column=column, value=value)
    if number_format:
        cell.number_format = number_format


@dataclass
class _Grid:
    """A table being written on a sheet: its cells as Python values, from its top-left (row0, col0)."""

    sheet: str
    row0: int
    col0: int
    cells: list[list[object]]
    formats: dict[tuple[int, int], str] = field(default_factory=dict)       # (row, column) of the region -> format

    def at(self, row: int, column: int) -> str:
        """The locator of a cell of the region (1-based in its own coordinates)."""
        return _sheet_cell(self.sheet, self.row0 + row - 1, self.col0 + column - 1)

    def write(self, ws) -> None:
        for r, values in enumerate(self.cells, start=1):
            for c, value in enumerate(values, start=1):
                _put(ws, self.row0 + r - 1, self.col0 + c - 1, value, self.formats.get((r, c)))

    def rows(self) -> tuple[tuple[str, ...], ...]:
        width = max(len(r) for r in self.cells)
        return tuple(tuple(_text(r[c]) if c < len(r) else "" for c in range(width)) for r in self.cells)

    def where(self) -> str:
        width = max(len(r) for r in self.cells)
        first = f"{get_column_letter(self.col0)}{self.row0}"
        last = f"{get_column_letter(self.col0 + width - 1)}{self.row0 + len(self.cells) - 1}"
        return "s:'" + self.sheet.replace("'", "''") + f"'!{first}:{last}"


def _caption(sheet: str, row: int, column: int = 1) -> str:
    return _sheet_cell(sheet, row, column)


def _naming(table: str, at: str, *, study: str = "", arm: str = "", analyte: str = "", product: str = "", batch: str = "",
            analyte_at: str | None = None) -> list[TruthValue]:
    """The constants that name a table's entities, each a scalar fact at the line (or cell) it is read from: study_id
    (and treatment, the arm) when a study is given, the analyte, the product and its batch. Each fact's entity is the
    table's study and the entity it names."""
    blank = dict(table=table, study=study, arm="", analyte="", matrix="", subject="", time="", time_unit="", unit="")
    in_study = (("study", at),) if study else ()
    out = []
    if study:
        out.append(TruthValue(**blank, field="study_id", value=study, locator=at, locators=in_study))
    if arm:
        out.append(TruthValue(**{**blank, "arm": arm}, field="treatment", value=arm, locator=at,
                              locators=(*in_study, ("arm", at))))
    if analyte:
        where = analyte_at or at
        out.append(TruthValue(**{**blank, "analyte": analyte}, field="analyte", value=analyte, locator=where,
                              locators=(*in_study, ("analyte", where))))
    if product:
        out.append(TruthValue(**blank, field="product", value=product, locator=at, product=product,
                              locators=(("product", at),)))
    if batch:
        out.append(TruthValue(**blank, field="batch", value=batch, locator=at, product=product, batch=batch,
                              locators=(("product", at), ("batch", at))))
    return out


# --- the messy workbook --------------------------------------------------------------------------------------------

_TIMES = (0, 0.5, 1, 2, 4, 8)
_FASTING = {
    "001": ("BLQ", 12.1, 30.4, 25.2, 14.8, 5.1),
    "002": ("BLQ", 10.5, 28.2, 27.9, 15.3, 4.4),
    "003": ("<0.5", 13.9, "12.3*", 22.6, 13.4, "BLQ"),
    "004": ("BLQ", 15.2, ">1000", 30.1, 16.7, 6.2),
    "005": ("BLQ", "NS", 33.5, 26.4, 12.9, 3.8),
    "006": ("BLQ", 10.3, 29.6, 24.3, 14.1, 5.5),
}
_FASTING_SUMMARY = (("Mean", ("BLQ", 12.4037, 30.38, 26.03, 14.47, 4.96)), ("SD", ("", 1.92, 2.21, 2.85, 1.42, 0.83)),
                    ("N", (6, 5, 4, 6, 6, 5)), ("CV%", ("", 15.5, 7.3, 10.9, 9.8, 16.7)))
_FED = {
    "101": ("BLQ", 5.2, 18.4, 35.6, 22.1, 8.3),
    "102": ("BLQ", 4.8, 16.9, 33.2, 20.5, 7.9),
    "103": ("BLQ", 6.1, 20.2, 38.1, 24.8, 9.4),
    "104": ("<0.5", 3.9, 15.5, 31.7, 19.6, 7.1),
    "105": ("BLQ", 5.5, 19.1, 36.4, 23.3, 8.8),
    "106": ("BLQ", 4.4, 17.7, 34.9, 21.4, 8.1),
}
_FED_SUMMARY = (("Mean", ("BLQ", 4.98, 17.97, 34.98, 21.95, 8.27)), ("SD", ("", 0.77, 1.71, 2.35, 1.86, 0.74)),
                ("N", (6, 6, 6, 6, 6, 6)), ("CV%", ("", 15.5, 9.5, 6.7, 8.5, 8.9)))
_CONC_HEADER = f"{DRUG} plasma concentration (ng/mL) by time after dose (h)"

INDIVIDUAL_SPEC = MappingSpec(
    kind="pk_individual", layout="wide_times", header_rows=2, first_data_row=3, time_row=2, field="concentration",
    time_unit="h", time_unit_cite=Cite(row=1, column=2), value_unit="ng/mL", value_unit_cite=Cite(row=1, column=2),
    statistic="individual", below_lloq_tokens=("BLQ",), missing_tokens=("NS",),
    columns=(ColumnMap(column=1, role="subject"), *(ColumnMap(column=c, role="value") for c in range(2, 8))),
    row_rules=(RowRule(column=1, pattern="mean", role="arithmetic_mean"),
               RowRule(column=1, pattern="sd", role="spread", spread_kind="SD"),
               RowRule(column=1, pattern="n", role="n"),
               RowRule(column=1, pattern="cv ?%", role="exclude", reason="CV% restates the SD and the mean")),
    lloq=Cite(near="below", line=1),
    constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+),"),
               Constant(field="dose", cite=Cite(near="caption", line=1)),
               Constant(field="food_state", cite=Cite(near="caption", line=1)),
               Constant(field="analyte", cite=Cite(row=1, column=2), pattern=r"^(\S+) plasma"),
               Constant(field="matrix", cite=Cite(row=1, column=2))))


def _individual_sheet(ws, table_id: str, *, study: str, dose: str, food: str, subjects: dict[str, tuple],
                      summary: tuple, mean_format: tuple[int, str] | None = None) -> tuple[TruthTable, list[TruthValue]]:
    """A title line, an individual table (merged two-row header, subjects down, times across), a Mean / SD / N / CV%
    group set off by one empty row, and an LLOQ footnote one empty row below the table."""
    sheet = ws.title
    title = f"Study {study}, {dose} mg, {food}"
    _put(ws, 1, 1, title)
    cells: list[list[object]] = [["Subject", _CONC_HEADER, "", "", "", "", ""], ["", *_TIMES]]
    cells += [[label, *row] for label, row in subjects.items()]
    cells.append(["", "", "", "", "", "", ""])
    cells += [[label, *row] for label, row in summary]
    grid = _Grid(sheet, 2, 1, cells)
    if mean_format is not None:
        grid.formats[(4 + len(subjects), 1 + mean_format[0])] = mean_format[1]
    grid.write(ws)
    ws.merge_cells("A2:A3")
    ws.merge_cells("B2:G2")
    last = 2 + len(cells) - 1
    footnote = "LLOQ = 0.5 ng/mL"
    _put(ws, last + 2, 1, footnote)
    title_at, header_at, lloq_at = _caption(sheet, 1), grid.at(1, 2), _caption(sheet, last + 2)
    labels = (("study", title_at), ("analyte", header_at), ("matrix", header_at))
    table = TruthTable(id=table_id, kind="pk_individual", where=grid.where(), rows=grid.rows(), header_rows=2,
                       spec=INDIVIDUAL_SPEC, merges=("A2:A3", "B2:G2"), caption=(title,), below=(footnote,))
    common = dict(table=table_id, field="concentration", study=study, arm="", analyte=DRUG, matrix="plasma",
                  time_unit="h", unit="ng/mL")
    values: list[TruthValue] = []
    for r, (label, row) in enumerate(subjects.items(), start=3):
        for c, raw in enumerate(row, start=2):
            text = _text(raw)
            lloq = (("lloq", grid.at(r, c)),) if text.startswith("<") else (("lloq", lloq_at),) if text == "BLQ" else ()
            values.append(TruthValue(**common, subject=label, time=_text(_TIMES[c - 2]), value=text, locator=grid.at(r, c),
                                     statistic="individual",
                                     locators=(("time", grid.at(2, c)), ("unit", header_at), ("subject", grid.at(r, 1)),
                                               *labels, *lloq)))
    mean_row = 3 + len(subjects) + 1
    means, sds, ns = summary[0][1], summary[1][1], summary[2][1]
    for c in range(2, 8):
        text = _text(means[c - 2])
        spread = _text(sds[c - 2])
        lloq = (("lloq", lloq_at),) if text == "BLQ" else ()
        values.append(TruthValue(
            **common, subject="", time=_text(_TIMES[c - 2]), value=text, locator=grid.at(mean_row, c),
            statistic="arithmetic_mean", spread=spread, spread_kind="SD" if spread else "", n=_text(ns[c - 2]),
            locators=(("time", grid.at(2, c)), ("unit", header_at), *labels,
                      *((("spread", grid.at(mean_row + 1, c)),) if spread else ()), ("n", grid.at(mean_row + 2, c)),
                      *lloq)))
    values += [
        TruthValue(table=table_id, field="dose", study=study, arm="", analyte="", matrix="", subject="", time="",
                   time_unit="", value=dose, unit="mg", locator=title_at, locators=(("study", title_at),)),
        TruthValue(table=table_id, field="food_state", study=study, arm="", analyte="", matrix="", subject="", time="",
                   time_unit="", value=food, unit="", locator=title_at, locators=(("study", title_at),)),
        TruthValue(table=table_id, field="lloq", study=study, arm="", analyte=DRUG, matrix="plasma", subject="", time="",
                   time_unit="", value="0.5", unit="ng/mL", locator=lloq_at, locators=labels),
        *_naming(table_id, title_at, study=study, analyte=DRUG, analyte_at=header_at),
    ]
    return table, values


METABOLITE_SPEC = MappingSpec(
    kind="pk_summary", layout="wide_series", header_rows=1, first_data_row=2, field="concentration",
    time_unit="h", time_unit_cite=Cite(row=1, column=1), value_unit="ng/mL", value_unit_cite=Cite(near="caption", line=1),
    statistic="arithmetic_mean", below_lloq_tokens=("BLQ",),
    columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value", statistic="arithmetic_mean"),
             ColumnMap(column=3, role="spread", spread_kind="SE", of=2), ColumnMap(column=4, role="n", of=2)),
    lloq=Cite(near="below", line=1),
    constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+):"),
               Constant(field="analyte", cite=Cite(near="caption", line=1), pattern=r": (\S+) plasma"),
               Constant(field="matrix", cite=Cite(near="caption", line=1))))


def _metabolite_table(ws, row0: int) -> tuple[TruthTable, list[TruthValue]]:
    """A caption and a summary table (mean, SE and n per time) of the metabolite, its LLOQ in a footnote."""
    sheet = ws.title
    caption = f"Table 2. Study 230-23: {METABOLITE} plasma concentrations (ng/mL), mean, SE and n"
    _put(ws, row0, 1, caption)
    rows = ((0, "BLQ", "", 6), (0.5, 1.12, 0.21, 6), (1, 2.35, 0.41, 6), (2, 3.1, 0.38, 5), (4, 2.21, 0.29, 6),
            (8, 0.95, 0.17, 4))
    grid = _Grid(sheet, row0 + 1, 1, [["Time (h)", "Mean", "SE", "n"], *[list(r) for r in rows]])
    grid.write(ws)
    footnote = "LLOQ = 0.2 ng/mL"
    lloq_row = row0 + 1 + len(rows) + 2
    _put(ws, lloq_row, 1, footnote)
    caption_at, lloq_at = _caption(sheet, row0), _caption(sheet, lloq_row)
    labels = (("study", caption_at), ("analyte", caption_at), ("matrix", caption_at))
    table = TruthTable(id="fasting-metabolite", kind="pk_summary", where=grid.where(), rows=grid.rows(), header_rows=1,
                       spec=METABOLITE_SPEC, caption=(caption,), below=(footnote,))
    values = []
    for r, (time, mean, se, n) in enumerate(rows, start=2):
        text = _text(mean)
        values.append(TruthValue(
            table=table.id, field="concentration", study="230-23", arm="", analyte=METABOLITE, matrix="plasma", subject="",
            time=_text(time), time_unit="h", value=text, unit="ng/mL", locator=grid.at(r, 2), statistic="arithmetic_mean",
            spread=_text(se), spread_kind="SE" if se != "" else "", n=_text(n),
            locators=(("time", grid.at(r, 1)), ("unit", caption_at), *labels,
                      *((("spread", grid.at(r, 3)),) if se != "" else ()), ("n", grid.at(r, 4)),
                      *((("lloq", lloq_at),) if text == "BLQ" else ()))))
    values.append(TruthValue(table=table.id, field="lloq", study="230-23", arm="", analyte=METABOLITE, matrix="plasma",
                             subject="", time="", time_unit="", value="0.2", unit="ng/mL", locator=lloq_at, locators=labels))
    values += _naming(table.id, caption_at, study="230-23", analyte=METABOLITE)
    return table, values


def _dissolution_spec(*, summary: bool) -> MappingSpec:
    caption1, caption2 = Cite(near="caption", line=1), Cite(near="caption", line=2)
    constants = (Constant(field="product", cite=caption1, pattern=r"^(.+), batch"),
                 Constant(field="batch", cite=caption1, pattern=r"batch (\S+) \("),
                 Constant(field="medium", cite=caption2, pattern=r"Medium: (.+) pH"),
                 Constant(field="ph", cite=caption2))
    if summary:
        columns = (ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value", statistic="arithmetic_mean"),
                   ColumnMap(column=3, role="spread", spread_kind="SD", of=2), ColumnMap(column=4, role="n", of=2))
    else:
        columns = (ColumnMap(column=1, role="time"),
                   *(ColumnMap(column=c, role="value", series=Cite(row=1, column=c), series_role="vessel") for c in range(2, 8)))
    return MappingSpec(kind="dissolution", layout="wide_series", header_rows=1, first_data_row=2, field="percent_dissolved",
                       time_unit="min", time_unit_cite=Cite(row=1, column=1), value_unit="%", value_unit_cite=caption1,
                       statistic="arithmetic_mean" if summary else "individual", columns=columns, constants=constants)


_PRODUCT = f"{DRUG} IR tablet"
_DISSOLUTION_TIMES = (5, 10, 15, 30, 45, 60)
_VESSELS = ((21.3, 19.8, 23.1, 20.6, 22.4, 18.9), (45.2, 43.7, 47.9, 44.1, 46.3, 42.8), (66.4, 64.9, 68.2, 65.3, 67.1, 63.7),
            (85.7, 84.2, 87.3, 85.1, 86.4, 83.9), (93.1, 92.4, 94.6, 92.8, 93.9, 91.7), (97.4, 96.8, 98.3, 97.1, 97.9, 96.2))
_DISSOLUTION_SUMMARY = ((12.4, 2.1, 12), (28.7, 3.4, 12), (44.9, 3.9, 12), (71.3, 4.2, 12), (86.5, 3.1, 12), (94.2, 2.4, 12))


def _dissolution_sheet(ws) -> tuple[list[TruthTable], list[TruthValue]]:
    """Two blocks side by side: one batch in two media, one with vessels (pH 1.2), one as mean, SD and n = 12 (pH 6.8)."""
    sheet = ws.title
    tables, values = [], []
    for col0, medium, ph, summary in ((1, "HCl buffer", "1.2", False), (9, "phosphate buffer", "6.8", True)):
        caption1 = f"{_PRODUCT}, batch L2301 (% dissolved)"
        caption2 = f"Medium: {medium} pH {ph}"
        _put(ws, 1, col0, caption1)
        _put(ws, 2, col0, caption2)
        if summary:
            cells = [["Time (min)", "Mean", "SD", "n"], *[[t, *row] for t, row in zip(_DISSOLUTION_TIMES, _DISSOLUTION_SUMMARY,
                                                                                      strict=True)]]
        else:
            cells = [["Time (min)", *(f"Vessel {k}" for k in range(1, 7))],
                     *[[t, *row] for t, row in zip(_DISSOLUTION_TIMES, _VESSELS, strict=True)]]
        grid = _Grid(sheet, 3, col0, cells)
        grid.write(ws)
        at1, at2 = _caption(sheet, 1, col0), _caption(sheet, 2, col0)
        table_id = "dissolution-summary" if summary else "dissolution-vessels"
        tables.append(TruthTable(id=table_id, kind="dissolution", where=grid.where(), rows=grid.rows(), header_rows=1,
                                 spec=_dissolution_spec(summary=summary), caption=(caption1, caption2)))
        conditions = (("medium", medium), ("ph", ph))
        context = (("unit", at1), ("product", at1), ("batch", at1), ("medium", at2), ("ph", at2))
        common = dict(table=table_id, field="percent_dissolved", study="", arm="", analyte="", matrix="", subject="",
                      time_unit="min", unit="%", conditions=conditions, product=_PRODUCT, batch="L2301")
        for r, row in enumerate(cells[1:], start=2):
            if summary:
                values.append(TruthValue(**common, time=_text(row[0]), value=_text(row[1]), locator=grid.at(r, 2),
                                         statistic="arithmetic_mean", spread=_text(row[2]), spread_kind="SD", n=_text(row[3]),
                                         locators=(("time", grid.at(r, 1)), *context, ("spread", grid.at(r, 3)),
                                                   ("n", grid.at(r, 4)))))
                continue
            for c in range(2, 8):
                values.append(TruthValue(**common, time=_text(row[0]), value=_text(row[c - 1]), locator=grid.at(r, c),
                                         statistic="individual", vessel=f"Vessel {c - 1}",
                                         locators=(("time", grid.at(r, 1)), *context, ("vessel", grid.at(1, c)))))
        values += _naming(table_id, at1, product=_PRODUCT, batch="L2301")
    return tables, values


SUMMARY_SPEC = MappingSpec(
    kind="pk_parameters", layout="key_value", header_rows=1, first_data_row=2, statistic="arithmetic_mean",
    columns=(ColumnMap(column=1, role="parameter"), ColumnMap(column=2, role="unit"),
             ColumnMap(column=3, role="value", cell_form="value (spread)", spread_kind="SD", statistic="arithmetic_mean")),
    keys=(KeyMap(pattern="cmax", field="pk.Cmax"), KeyMap(pattern="auc_last", field="pk.AUC_last"),
          KeyMap(pattern="t_half", field="pk.t_half")),
    constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+) \("),
               Constant(field="analyte", cite=Cite(near="caption", line=1), pattern=r": (\S+) plasma"),
               Constant(field="matrix", cite=Cite(near="caption", line=1))))


def _summary_sheet(ws) -> tuple[TruthTable, list[TruthValue], str]:
    """A "mean (SD)" table of PK parameters, and a note with a number far below it (an outside number)."""
    sheet = ws.title
    caption = f"Study 230-23 (fasted): {DRUG} plasma PK parameters, mean (SD)"
    _put(ws, 1, 1, caption)
    rows = (("Cmax", "ng/mL", "31.2", "4.1"), ("AUC_last", "ng*h/mL", "152.4", "20.3"), ("t_half", "h", "3.1", "0.6"))
    grid = _Grid(sheet, 2, 1, [["Parameter", "Unit", "Mean (SD)"], *[[p, u, f"{m} ({s})"] for p, u, m, s in rows]])
    grid.write(ws)
    note_row = 10
    _put(ws, note_row, 1, "Note: 3 samples were re-assayed on day 14")
    at = _caption(sheet, 1)
    table = TruthTable(id="summary-parameters", kind="pk_parameters", where=grid.where(), rows=grid.rows(), header_rows=1,
                       spec=SUMMARY_SPEC, caption=(caption,))
    values = [TruthValue(table=table.id, field=f"pk.{p}", study="230-23", arm="", analyte=DRUG, matrix="plasma", subject="",
                         time="", time_unit="", value=m, unit=u, locator=grid.at(r, 3), statistic="arithmetic_mean",
                         spread=s, spread_kind="SD",
                         locators=(("unit", grid.at(r, 2)), ("spread", grid.at(r, 3)), ("parameter", grid.at(r, 1)),
                                   ("study", at), ("analyte", at), ("matrix", at)))
              for r, (p, u, m, s) in enumerate(rows, start=2)]
    values += _naming(table.id, at, study="230-23", analyte=DRUG)
    return table, values, _caption(sheet, note_row)


URINE_SPEC = MappingSpec(
    kind="excretion", layout="long", header_rows=1, first_data_row=2, field="excretion.amount",
    columns=(ColumnMap(column=1, role="condition", condition="interval_start_h"),
             ColumnMap(column=2, role="condition", condition="interval_end_h"),
             ColumnMap(column=3, role="value", unit="mg", unit_cite=Cite(row=1, column=3)),
             ColumnMap(column=4, role="ignore", reason="the fraction of the dose restates the amount over the 50 mg dose")),
    constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+):"),
               Constant(field="analyte", cite=Cite(near="caption", line=1), pattern=r": (\S+) urine"),
               Constant(field="matrix", cite=Cite(near="caption", line=1))))


def _urine_sheet(ws) -> tuple[TruthTable, list[TruthValue]]:
    """The 230-23 study's urine excretion by interval (plasma and urine of one study); a fraction column under 0.0%."""
    sheet = ws.title
    caption = f"Study 230-23: {DRUG} urine excretion (mg) by collection interval"
    _put(ws, 1, 1, caption)
    rows = ((0, 4, 2.1, 0.042), (4, 8, 1.6, 0.032), (8, 12, 0.9, 0.018), (12, 24, 0.7, 0.014))
    grid = _Grid(sheet, 2, 1, [["Interval start (h)", "Interval end (h)", "Amount (mg)", "Fraction of dose"],
                               *[list(r) for r in rows]])
    for r in range(2, 2 + len(rows)):
        grid.formats[(r, 4)] = "0.0%"
    grid.write(ws)
    at = _caption(sheet, 1)
    table = TruthTable(id="urine-excretion", kind="excretion", where=grid.where(), rows=grid.rows(), header_rows=1,
                       spec=URINE_SPEC, caption=(caption,))
    values = [TruthValue(table=table.id, field="excretion.amount", study="230-23", arm="", analyte=DRUG, matrix="urine",
                         subject="", time="", time_unit="", value=_text(amount), unit="mg", locator=grid.at(r, 3),
                         conditions=(("interval_start_h", _text(start)), ("interval_end_h", _text(end))),
                         locators=(("unit", grid.at(1, 3)), ("interval_start_h", grid.at(r, 1)),
                                   ("interval_end_h", grid.at(r, 2)), ("study", at), ("analyte", at), ("matrix", at)))
              for r, (start, end, amount, _fraction) in enumerate(rows, start=2)]
    values += _naming(table.id, at, study="230-23", analyte=DRUG)
    return table, values


PRODUCT_SPEC = MappingSpec(
    kind="product_batch", layout="long", header_rows=1, first_data_row=2,
    columns=(ColumnMap(column=1, role="product"), ColumnMap(column=2, role="value", field="product_role"),
             ColumnMap(column=3, role="value", field="dosage_form"),
             ColumnMap(column=4, role="value", field="strength_mg", unit="mg", unit_cite=Cite(row=1, column=4)),
             ColumnMap(column=5, role="batch"), ColumnMap(column=6, role="value", field="release"),
             ColumnMap(column=7, role="value", field="particle_size_d50_um", unit="µm", unit_cite=Cite(row=1, column=7)),
             ColumnMap(column=8, role="value", field="polymorph")))


def _product_sheet(ws) -> tuple[TruthTable, list[TruthValue]]:
    """A text-heavy product and batch table: strengths, lots, release, particle sizes."""
    sheet = ws.title
    header = ["Product", "Role", "Dosage form", "Strength (mg)", "Batch", "Release", "Particle size d50 (µm)", "Polymorph"]
    rows = ((_PRODUCT, "TEST", "film-coated tablet", 50, "L2301", "immediate release", 12.5, "Form I"),
            ("Comparamide tablet", "RLD", "film-coated tablet", 50, "R7745", "immediate release", 14.2, "Form I"))
    grid = _Grid(sheet, 1, 1, [header, *[list(r) for r in rows]])
    grid.write(ws)
    table = TruthTable(id="product-batches", kind="product_batch", where=grid.where(), rows=grid.rows(), header_rows=1,
                       spec=PRODUCT_SPEC)
    values = []
    for r, row in enumerate(rows, start=2):
        labels = (("product", grid.at(r, 1)), ("batch", grid.at(r, 5)))
        for c, name, unit in ((2, "product_role", ""), (3, "dosage_form", ""), (4, "strength_mg", "mg"), (6, "release", ""),
                              (7, "particle_size_d50_um", "µm"), (8, "polymorph", "")):
            values.append(TruthValue(table=table.id, field=name, study="", arm="", analyte="", matrix="", subject="", time="",
                                     time_unit="", value=_text(row[c - 1]), unit=unit, locator=grid.at(r, c),
                                     product=str(row[0]), batch=str(row[4]),
                                     locators=(*labels, *((("unit", grid.at(1, c)),) if unit else ()))))
    return table, values


def messy_workbook() -> SyntheticFile:
    """Sheet "Fasting": a title line, an individual table with a merged two-row header (BLQ, <0.5, >1000, NS, "12.3*"),
    Mean / SD / N / CV% rows set off by one empty row (a computed mean stored as 12.4037 under 0.00), an LLOQ footnote;
    then empty rows, a caption and a second (summary, SE, n per time) table of the metabolite. Sheet "Fed": the same
    layout under another title. Sheet "Dissolution": two blocks side by side, one batch in two media (pH 1.2 with
    vessels, pH 6.8 as mean, SD and n = 12). Sheet "Summary": a "mean (SD)" table and a note with a number that belongs
    to no region and no region's context (an outside number). Sheet "Urine": the 230-23 study's urine excretion by
    interval. Sheet "Product": a text-heavy product and batch table. Sheet "Notes": hidden, text only."""
    wb = Workbook()
    fasting = wb.active
    fasting.title = "Fasting"
    tables: list[TruthTable] = []
    values: list[TruthValue] = []
    table, found = _individual_sheet(fasting, "fasting-individual", study="230-23", dose="50", food="fasted",
                                     subjects=_FASTING, summary=_FASTING_SUMMARY, mean_format=(2, "0.00"))
    tables.append(table)
    values += found
    table, found = _metabolite_table(fasting, 20)
    tables.append(table)
    values += found
    table, found = _individual_sheet(wb.create_sheet("Fed"), "fed-individual", study="231-24", dose="100", food="fed",
                                     subjects=_FED, summary=_FED_SUMMARY)
    tables.append(table)
    values += found
    more, found = _dissolution_sheet(wb.create_sheet("Dissolution"))
    tables += more
    values += found
    table, found, note = _summary_sheet(wb.create_sheet("Summary"))
    tables.append(table)
    values += found
    table, found = _urine_sheet(wb.create_sheet("Urine"))
    tables.append(table)
    values += found
    table, found = _product_sheet(wb.create_sheet("Product"))
    tables.append(table)
    values += found
    hidden = wb.create_sheet("Notes")
    hidden["A1"] = "Working notes, not for review"
    hidden.sheet_state = "hidden"
    return SyntheticFile(name="messy-delivery.xlsx", data=_save(wb), format="xlsx", tables=tuple(tables),
                         values=tuple(values), outside=(note,),
                         notes="hidden sheet: Notes (text only); the Fasting mean at 0.5 h is stored as 12.4037 under 0.00; "
                               "the Urine fraction column is formatted 0.0% and ignored by its spec")


# --- PDF: written by hand ------------------------------------------------------------------------------------------

_PAGE_W, _PAGE_H = 612.0, 792.0
_CHAR = 0.5                    # an approximate glyph width (em): boxes are carried for the viewer, never compared


@dataclass(frozen=True)
class _Text:
    x: float
    top: float
    text: str
    size: float = 10.0


@dataclass(frozen=True)
class _Table:
    x: float
    top: float
    widths: tuple[float, ...]
    rows: tuple[tuple[str, ...], ...]
    size: float = 9.0
    row_height: float = 16.0

    def box(self, row: int | None = None, column: int | None = None) -> tuple[float, float, float, float]:
        """The table's box, or a cell's (1-based)."""
        if row is None or column is None:
            return (self.x, self.top, self.x + sum(self.widths), self.top + len(self.rows) * self.row_height)
        x0 = self.x + sum(self.widths[: column - 1])
        top = self.top + (row - 1) * self.row_height
        return (x0, top, x0 + self.widths[column - 1], top + self.row_height)

    def texts(self) -> list[_Text]:
        out = []
        for r, row in enumerate(self.rows, start=1):
            for c, text in enumerate(row, start=1):
                if text:
                    x0, top, _x1, _bottom = self.box(r, c)
                    out.append(_Text(x0 + 4, top + 3.5, text, self.size))
        return out


@dataclass(frozen=True)
class _Page:
    texts: tuple[_Text, ...] = ()
    tables: tuple[_Table, ...] = ()
    image: bool = False


def _words(page: _Page) -> list[tuple[_Text, int, str, tuple[float, float, float, float]]]:
    """Every word of a page in pdfplumber's order (lines top to bottom, words left to right): (its text item, its
    position in the item, the word, an approximate box)."""
    found = []
    for item in (*page.texts, *(t for table in page.tables for t in table.texts())):
        offset = 0
        for position, word in enumerate(item.text.split(" ")):
            if word:
                x0 = item.x + offset * _CHAR * item.size
                found.append((item, position, word, (x0, item.top, x0 + len(word) * _CHAR * item.size, item.top + item.size)))
            offset += len(word) + 1
    return sorted(found, key=lambda w: (round(w[3][1], 1), w[3][0]))


def _span(page_number: int, page: _Page, item: _Text, first: int = 0, last: int | None = None) -> str:
    """The locator of words `first`..`last` (0-based positions in the item; all by default) of one text item."""
    words = _words(page)
    numbered = [(i, w) for i, w in enumerate(words, start=1) if w[0] == item]
    last = len(numbered) - 1 if last is None else last
    (i0, w0), (i1, w1) = numbered[first], numbered[last]
    box = (w0[3][0], min(w0[3][1], w1[3][1]), w1[3][2], max(w0[3][3], w1[3][3]))
    return format_locator(PdfSpan(page=page_number, first_word=i0, last_word=i1, box=box))


def _word_span(page_number: int, page: _Page, item: _Text, word: str) -> str:
    """The locator of the one word of an item that starts with `word`."""
    positions = [i for i, w in enumerate(w for w in item.text.split(" ") if w) if w.startswith(word)]
    (position,) = positions
    return _span(page_number, page, item, position, position)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf(pages: Sequence[_Page]) -> bytes:
    """A PDF of these pages: text in Helvetica (WinAnsi), ruling lines for the tables, an 8-bit gray image."""
    objects: list[bytes] = []
    kids = []
    image_obj = 4 + 2 * len(pages)
    for i, page in enumerate(pages):
        page_obj, content_obj = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_obj} 0 R")
        ops = []
        for table in page.tables:
            x0, top, x1, bottom = table.box()
            ops.append("0.5 w")
            for r in range(len(table.rows) + 1):
                y = _PAGE_H - (top + r * table.row_height)
                ops.append(f"{x0:.2f} {y:.2f} m {x1:.2f} {y:.2f} l S")
            x = x0
            for width in (0.0, *table.widths):
                x += width
                ops.append(f"{x:.2f} {_PAGE_H - top:.2f} m {x:.2f} {_PAGE_H - bottom:.2f} l S")
        for item in (*page.texts, *(t for table in page.tables for t in table.texts())):
            baseline = _PAGE_H - (item.top + 0.8 * item.size)
            ops.append(f"BT /F1 {item.size:g} Tf {item.x:.2f} {baseline:.2f} Td ({_escape(item.text)}) Tj ET")
        resources = "/Font << /F1 3 0 R >>"
        if page.image:
            ops.append("q 400 0 0 500 106 146 cm /Im1 Do Q")
            resources += f" /XObject << /Im1 {image_obj} 0 R >>"
        stream = "\n".join(ops).encode("latin-1")
        objects.append(f"{page_obj} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_W:g} {_PAGE_H:g}] "
                       f"/Resources << {resources} >> /Contents {content_obj} 0 R >> endobj\n".encode())
        objects.append(f"{content_obj} 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n")
    pixels = bytes(((x * 7 + y * 13) % 200) + 40 for y in range(32) for x in range(32))
    objects.append(f"{image_obj} 0 obj << /Type /XObject /Subtype /Image /Width 32 /Height 32 /ColorSpace /DeviceGray "
                   f"/BitsPerComponent 8 /Length {len(pixels)} >> stream\n".encode() + pixels + b"\nendstream endobj\n")
    head = [b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            f"2 0 obj << /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >> endobj\n".encode(),
            b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n"]
    body, offsets = b"%PDF-1.4\n", []
    for obj in head + objects:
        offsets.append(len(body))
        body += obj
    xref = len(body)
    body += f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    return body + f"trailer << /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def _footer(number: int, total: int) -> _Text:
    return _Text(280, 760, f"Page {number} of {total}", 9)


@dataclass(frozen=True)
class _PdfTruth:
    """Where one truth table stands in a laid-out PDF: its parts (page, table index on the page, table, repeated header
    rows dropped), its caption line and its line below."""

    parts: tuple[tuple[int, int, _Table, int], ...]
    caption: tuple[int, _Text] | None
    below: tuple[int, _Text] | None


_T5_HEADER = ("Subject", "Time (h)", "Concentration (ng/mL)")
_T5 = {"201": ("BLQ", "18.2", "25.6", "19.4", "9.7", "3.1"), "202": ("BLQ", "16.5", "23.9", "18.8", "8.9", "2.7"),
       "203": ("BLQ", "20.1", "27.3", "21.2", "10.4", "BLQ")}
_T5_TIMES = ("0", "1", "2", "4", "8", "12")
_COHORT_HEADER = ("Time (h)", "Mean (ng/mL)", "SD (ng/mL)", "N")
_COHORT_TIMES = ("0.5", "1", "2", "4", "8", "12")
_COHORTS = (("Cohort 1", "10", ("3.2", "5.8", "7.1", "5.2", "2.4", "0.9"), ("0.8", "1.2", "1.5", "1.1", "0.6", "0.3"),
             ("8", "8", "8", "8", "8", "7")),
            ("Cohort 2", "30", ("9.8", "17.5", "21.6", "15.9", "7.3", "2.8"), ("2.1", "3.6", "4.4", "3.2", "1.7", "0.7"),
             ("8", "8", "8", "8", "8", "8")))
_SYNOPSIS = ("Study 230-23 was a single-dose, open-label study in healthy volunteers.",
             f"{DRUG} was given as a single oral dose of 50 mg.",
             "The study enrolled 24 healthy subjects.",
             "All subjects were dosed in the fasted state.")
_UNRULED = (("Parameter", "Cohort 1", "Cohort 2"), ("Cmax (ng/mL)", "7.4", "22.3"), ("AUC (ng*h/mL)", "41.2", "128.6"),
            ("t1/2 (h)", "3.3", "3.5"))


@lru_cache(maxsize=2)
def _report_layout(unruled_table: bool) -> tuple[tuple[_Page, ...], dict[str, _PdfTruth]]:
    total = 6 if unruled_table else 5
    pages: list[_Page] = []
    tables: dict[str, _PdfTruth] = {}
    # page 1: the synopsis
    pages.append(_Page(texts=(_Text(56, 60, "Clinical Study Report Synopsis", 14),
                              *(_Text(56, 100 + 16 * i, line) for i, line in enumerate(_SYNOPSIS)), _footer(1, total))))
    # pages 2-3: Table 5, continued
    rows = [(subject, time, value) for subject, row in _T5.items() for time, value in zip(_T5_TIMES, row, strict=True)]
    widths = (70.0, 70.0, 130.0)
    first = _Table(56, 90, widths, (_T5_HEADER, *rows[:12]))
    second = _Table(56, 90, widths, (_T5_HEADER, *rows[12:]))
    caption = _Text(56, 70, f"Table 5. Study 230-25: {DRUG} plasma concentrations by subject")
    continued = _Text(56, 70, f"Table 5. Study 230-25: {DRUG} plasma concentrations by subject (continued)")
    footnote = _Text(56, 220, "BLQ: below the lower limit of quantification (0.5 ng/mL).")
    pages.append(_Page(texts=(caption, _footer(2, total)), tables=(first,)))
    pages.append(_Page(texts=(continued, footnote, _footer(3, total)), tables=(second,)))
    tables["report-table5"] = _PdfTruth(parts=((2, 1, first, 0), (3, 1, second, 1)), caption=(2, caption), below=(3, footnote))
    # pages 4-5: Table 6 and Table 7, the same header under different captions
    for k, (cohort, dose, means, sds, ns) in enumerate(_COHORTS):
        table = _Table(56, 90, (60.0, 90.0, 90.0, 40.0),
                       (_COHORT_HEADER, *zip(_COHORT_TIMES, means, sds, ns, strict=True)))
        title = _Text(56, 70, f"Table {6 + k}. Study 230-26, {cohort} ({dose} mg): {DRUG} plasma concentrations, mean (SD)")
        pages.append(_Page(texts=(title, _footer(4 + k, total)), tables=(table,)))
        tables[f"report-table{6 + k}"] = _PdfTruth(parts=((4 + k, 1, table, 0),), caption=(4 + k, title), below=None)
    # page 6: an unruled table (located as table_like_text, not gridded)
    if unruled_table:
        lines = [_Text(56, 70, f"Table 8. Study 230-26: {DRUG} PK parameters by cohort")]
        for i, row in enumerate(_UNRULED):
            lines += [_Text(x, 100 + 16 * i, text) for x, text in zip((56, 220, 320), row, strict=True)]
        pages.append(_Page(texts=(*lines, _footer(6, total))))
    return tuple(pages), tables


COHORT_SPEC = MappingSpec(
    kind="pk_summary", layout="wide_series", header_rows=1, first_data_row=2, field="concentration",
    time_unit="h", time_unit_cite=Cite(row=1, column=1), value_unit="ng/mL", value_unit_cite=Cite(row=1, column=2),
    statistic="arithmetic_mean",
    columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value", statistic="arithmetic_mean"),
             ColumnMap(column=3, role="spread", spread_kind="SD", of=2), ColumnMap(column=4, role="n", of=2)),
    constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+),"),
               Constant(field="treatment", cite=Cite(near="caption", line=1), pattern=r", (Cohort \d+) \("),
               Constant(field="dose", cite=Cite(near="caption", line=1)),
               Constant(field="analyte", cite=Cite(near="caption", line=1), pattern=r": (\S+) plasma"),
               Constant(field="matrix", cite=Cite(near="caption", line=1))))
TABLE5_SPEC = MappingSpec(
    kind="pk_individual", layout="long", header_rows=1, first_data_row=2, field="concentration", statistic="individual",
    time_unit="h", time_unit_cite=Cite(row=1, column=2), value_unit="ng/mL", value_unit_cite=Cite(row=1, column=3),
    below_lloq_tokens=("BLQ",), lloq=Cite(near="below", line=1),
    columns=(ColumnMap(column=1, role="subject"), ColumnMap(column=2, role="time"), ColumnMap(column=3, role="value")),
    constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+):"),
               Constant(field="analyte", cite=Cite(near="caption", line=1), pattern=r": (\S+) plasma"),
               Constant(field="matrix", cite=Cite(near="caption", line=1))))


def _pdf_cell(page: int, index: int, table: _Table, row: int, column: int) -> str:
    return format_locator(PdfCell(page=page, table=index, row=row, column=column, box=table.box(row, column)))


def _pdf_grid_cells(truth: _PdfTruth) -> list[list[tuple[str, str]]]:
    """The joined grid of a PDF truth table: (text, locator) per cell, repeated headers dropped."""
    grid: list[list[tuple[str, str]]] = []
    for page, index, table, repeated in truth.parts:
        for r in range(repeated + 1, len(table.rows) + 1):
            grid.append([(text, _pdf_cell(page, index, table, r, c)) for c, text in enumerate(table.rows[r - 1], start=1)])
    return grid


def pdf_report(*, unruled_table: bool = True) -> SyntheticFile:
    """Page 1: a synopsis in sentences (study 230-23, the workbook's study label: the cross-file link is exercised);
    pages 2-3: "Table 5" continued, its title repeated "(continued)" and its header repeated; page 3: a footnote with
    the LLOQ; pages 4-5: "Table 6, Cohort 1 (10 mg)" and "Table 7, Cohort 2 (30 mg)" with the same header, one per
    page; page 6: an unruled table (`unruled_table=False` leaves page 6 out, for a delivery with no silent loss); a page
    number on every page."""
    pages, layout = _report_layout(unruled_table)
    tables: list[TruthTable] = []
    values: list[TruthValue] = []
    page1 = pages[0]
    lines = page1.texts[1:5]
    study_at = _word_span(1, page1, lines[0], "230-23")
    for line, name, word, unit in ((lines[1], "dose", "50", "mg"), (lines[2], "n", "24", ""), (lines[3], "food_state", "fasted", "")):
        values.append(TruthValue(table="", field=name, study="230-23", arm="", analyte="", matrix="", subject="", time="",
                                 time_unit="", value=word, unit=unit, locator=_word_span(1, page1, line, word),
                                 locators=(("study", study_at),)))
    # Table 5
    truth = layout["report-table5"]
    cells = _pdf_grid_cells(truth)
    caption_at = _span(truth.caption[0], pages[truth.caption[0] - 1], truth.caption[1])
    below_at = _span(truth.below[0], pages[truth.below[0] - 1], truth.below[1])
    labels = (("study", caption_at), ("analyte", caption_at), ("matrix", caption_at))
    tables.append(TruthTable(id="report-table5", kind="pk_individual", where="p:2/t:1",
                             rows=tuple(tuple(t for t, _l in row) for row in cells), header_rows=1, spec=TABLE5_SPEC,
                             pages=(2, 3), caption=(truth.caption[1].text,), below=(truth.below[1].text,)))
    for row in cells[1:]:
        (subject, subject_at), (time, time_at), (value, value_at) = row
        values.append(TruthValue(table="report-table5", field="concentration", study="230-25", arm="", analyte=DRUG,
                                 matrix="plasma", subject=subject, time=time, time_unit="h", value=value, unit="ng/mL",
                                 locator=value_at, statistic="individual",
                                 locators=(("time", time_at), ("unit", cells[0][2][1]), ("subject", subject_at), *labels,
                                           *((("lloq", below_at),) if value == "BLQ" else ()))))
    values.append(TruthValue(table="report-table5", field="lloq", study="230-25", arm="", analyte=DRUG, matrix="plasma",
                             subject="", time="", time_unit="", value="0.5", unit="ng/mL", locator=below_at, locators=labels))
    values += _naming("report-table5", caption_at, study="230-25", analyte=DRUG)
    # Tables 6 and 7
    for k, (cohort, dose, *_rest) in enumerate(_COHORTS):
        table_id = f"report-table{6 + k}"
        truth = layout[table_id]
        cells = _pdf_grid_cells(truth)
        page = truth.caption[0]
        caption_at = _span(page, pages[page - 1], truth.caption[1])
        labels = (("study", caption_at), ("arm", caption_at), ("analyte", caption_at), ("matrix", caption_at))
        tables.append(TruthTable(id=table_id, kind="pk_summary", where=f"p:{page}/t:1",
                                 rows=tuple(tuple(t for t, _l in row) for row in cells), header_rows=1, spec=COHORT_SPEC,
                                 pages=(page,), caption=(truth.caption[1].text,)))
        for row in cells[1:]:
            (time, time_at), (mean, mean_at), (sd, sd_at), (n, n_at) = row
            values.append(TruthValue(table=table_id, field="concentration", study="230-26", arm=cohort, analyte=DRUG,
                                     matrix="plasma", subject="", time=time, time_unit="h", value=mean, unit="ng/mL",
                                     locator=mean_at, statistic="arithmetic_mean", spread=sd, spread_kind="SD", n=n,
                                     locators=(("time", time_at), ("unit", cells[0][1][1]), ("spread", sd_at), ("n", n_at),
                                               *labels)))
        values.append(TruthValue(table=table_id, field="dose", study="230-26", arm=cohort, analyte="", matrix="", subject="",
                                 time="", time_unit="", value=dose, unit="mg", locator=caption_at,
                                 locators=(("study", caption_at), ("arm", caption_at))))
        values += _naming(table_id, caption_at, study="230-26", arm=cohort, analyte=DRUG)
    notes = ("page 1: the synopsis (prose); page 3: the footnote below Table 5's second part; "
             + ("page 6: an unruled table (table_like_text: " + " / ".join(" | ".join(r) for r in _UNRULED) + "); "
                if unruled_table else "")
             + "a page number at the foot of every page (furniture)")
    return SyntheticFile(name="study-report.pdf", data=_report_bytes(unruled_table), format="pdf", tables=tuple(tables),
                         values=tuple(values),
                         prose=("Clinical Study Report Synopsis", *_SYNOPSIS), notes=notes)


def scanned_pdf() -> SyntheticFile:
    """One text page, one page that is only an image (it needs OCR: no text layer)."""
    pages = (_Page(texts=(_Text(56, 60, f"Certificate of analysis: {DRUG} IR tablet"),
                          _Text(56, 80, "The scanned certificate follows on the next page."))),
             _Page(image=True))
    return SyntheticFile(name="scanned.pdf", data=_pdf(pages), format="pdf", tables=(), values=(),
                         prose=(f"Certificate of analysis: {DRUG} IR tablet", "The scanned certificate follows on the next page."),
                         notes="page 2 is only an image: no text layer, it needs OCR")


# --- Word ----------------------------------------------------------------------------------------------------------


def _png(width: int = 16, height: int = 16) -> bytes:
    """A small gray PNG, written by hand."""
    raw = b"".join(b"\x00" + bytes((x * 9 + y * 5) % 256 for x in range(width)) for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# The n is in its own sentence: §6.2's check wants exactly one number in the clause that states a field with no unit
# class, and "230-27" is a number too
_WORD_DESIGN = ("Study 230-27 was a randomised, two-way crossover study. It enrolled 18 healthy volunteers.",
                f"Each subject received a single oral dose of 20 mg {DRUG} under fasted conditions.")
_WORD_CAPTION = f"Table 1. Study 230-27: {DRUG} plasma concentrations after 20 mg, mean (SD)"
_WORD_ROWS = (("0.5", "8.1", "1.9"), ("1", "14.6", "3.1"), ("2", "17.9", "3.8"), ("4", "13.2", "2.9"), ("8", "6.1", "1.4"),
              ("12", "2.2", "0.6"))
WORD_SPEC = MappingSpec(
    kind="pk_summary", layout="wide_series", header_rows=2, first_data_row=3, field="concentration",
    time_unit="h", time_unit_cite=Cite(row=1, column=1), value_unit="ng/mL", value_unit_cite=Cite(row=1, column=2),
    statistic="arithmetic_mean",
    columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value", statistic="arithmetic_mean"),
             ColumnMap(column=3, role="spread", spread_kind="SD", of=2)),
    constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+):"),
               Constant(field="dose", cite=Cite(near="caption", line=1)),
               Constant(field="analyte", cite=Cite(near="caption", line=1), pattern=r": (\S+) plasma"),
               Constant(field="matrix", cite=Cite(near="caption", line=1))))


def _docx_span(paragraph: int, text: str, word: str | None = None) -> str:
    if word is None:
        return format_locator(DocxSpan(paragraph=paragraph, start=0, end=len(text)))
    start = re.search(rf"(?<!\S){re.escape(word)}", text).start()
    return format_locator(DocxSpan(paragraph=paragraph, start=start, end=start + len(word)))


def word_report() -> SyntheticFile:
    """Design sentences under a heading, a table with a merged header (a line break inside a header cell) under its
    caption paragraph, and an image."""
    import docx

    doc = docx.Document()
    doc.core_properties.created = _FIXED
    doc.core_properties.modified = _FIXED
    doc.add_heading("Study design", level=1)
    for sentence in _WORD_DESIGN:
        doc.add_paragraph(sentence)
    doc.add_paragraph(_WORD_CAPTION)
    table = doc.add_table(rows=2 + len(_WORD_ROWS), cols=3)
    table.cell(0, 0).merge(table.cell(1, 0)).text = "Time (h)"
    table.cell(0, 1).merge(table.cell(0, 2)).text = f"{DRUG} plasma concentration (ng/mL)"
    table.cell(1, 1).text = "Mean\n(arithmetic)"
    table.cell(1, 2).text = "SD"
    for r, row in enumerate(_WORD_ROWS, start=2):
        for c, text in enumerate(row):
            table.cell(r, c).text = text
    doc.add_picture(io.BytesIO(_png()))
    buffer = io.BytesIO()
    doc.save(buffer)
    rows = (("Time (h)", f"{DRUG} plasma concentration (ng/mL)", ""), ("", "Mean\n(arithmetic)", "SD"), *_WORD_ROWS)

    def at(r: int, c: int) -> str:
        return format_locator(DocxCell(table=1, row=r, column=c))

    caption_at = _docx_span(4, _WORD_CAPTION)
    labels = (("study", caption_at), ("analyte", caption_at), ("matrix", caption_at))
    truth = TruthTable(id="word-table1", kind="pk_summary", where="d:t:1", rows=rows, header_rows=2, spec=WORD_SPEC,
                       merges=("r1c1:r2c1", "r1c2:r1c3"), caption=(_WORD_CAPTION,))
    values = [TruthValue(table=truth.id, field="concentration", study="230-27", arm="", analyte=DRUG, matrix="plasma",
                         subject="", time=time, time_unit="h", value=mean, unit="ng/mL", locator=at(r, 2),
                         statistic="arithmetic_mean", spread=sd, spread_kind="SD",
                         locators=(("time", at(r, 1)), ("unit", at(1, 2)), ("spread", at(r, 3)), *labels))
              for r, (time, mean, sd) in enumerate(_WORD_ROWS, start=3)]
    values.append(TruthValue(table=truth.id, field="dose", study="230-27", arm="", analyte="", matrix="", subject="", time="",
                             time_unit="", value="20", unit="mg", locator=caption_at, locators=(("study", caption_at),)))
    values += _naming(truth.id, caption_at, study="230-27", analyte=DRUG)
    study_at = _docx_span(2, _WORD_DESIGN[0], "230-27")
    values += [
        TruthValue(table="", field="n", study="230-27", arm="", analyte="", matrix="", subject="", time="", time_unit="",
                   value="18", unit="", locator=_docx_span(2, _WORD_DESIGN[0], "18"), locators=(("study", study_at),)),
        # the dose's paragraph names no study: no label span (a label is read in the fact's paragraph or its heading
        # only, §6.2 (5)); the ledger gives it the file's one study (§6.3)
        TruthValue(table="", field="dose", study="230-27", arm="", analyte="", matrix="", subject="", time="", time_unit="",
                   value="20", unit="mg", locator=_docx_span(3, _WORD_DESIGN[1], "20"), locators=()),
    ]
    return SyntheticFile(name="design-report.docx", data=_stable_zip(buffer.getvalue()), format="docx", tables=(truth,),
                         values=tuple(values), prose=("Study design", *_WORD_DESIGN),
                         notes="paragraphs: 1 heading, 2-3 design, 4 the table's caption, 5 the image (a figure)")


# --- delimited and zipped ------------------------------------------------------------------------------------------

_CSV_ROWS = (("301", "0", "BLQ"), ("301", "0.5", "12.5"), ("301", "1", "30.1"), ("301", "2", "22.4"),
             ("302", "0", "BLQ"), ("302", "0.5", "10.8"), ("302", "1", "27.6"), ("302", "2", "20.9"))
DELIMITED_SPEC = MappingSpec(
    kind="pk_individual", layout="long", header_rows=1, first_data_row=2, field="concentration", statistic="individual",
    time_unit="h", time_unit_cite=Cite(row=1, column=2), value_unit="µg/L", value_unit_cite=Cite(row=1, column=3),
    below_lloq_tokens=("BLQ",),
    columns=(ColumnMap(column=1, role="subject"), ColumnMap(column=2, role="time"), ColumnMap(column=3, role="value")),
    constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+) \("),
               Constant(field="analyte", cite=Cite(near="caption", line=1), pattern=r": (\S+) plasma"),
               Constant(field="matrix", cite=Cite(near="caption", line=1))))


def delimited(sep: str = ";", decimal_comma: bool = True, encoding: str = "cp1252") -> SyntheticFile:
    """A delimited concentration listing under a title line (µ in the unit, so the encoding matters)."""
    suffix = "tsv" if sep == "\t" else "csv"
    name = f"concentrations.{suffix}"
    sheet = "concentrations"
    caption = f"Study 230-28 (fasted): {DRUG} plasma concentrations"
    header = ("Subject", "Time (h)", "Concentration (µg/L)")

    def written(text: str) -> str:
        return text.replace(".", ",") if decimal_comma else text

    body = tuple((s, written(t), written(v)) for s, t, v in _CSV_ROWS)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=sep, lineterminator="\r\n")
    writer.writerow((caption,))
    writer.writerow(header)
    writer.writerows(body)
    data = out.getvalue().encode(encoding)
    grid = _Grid(sheet, 2, 1, [list(header), *[list(r) for r in body]])
    at = _caption(sheet, 1)
    labels = (("study", at), ("analyte", at), ("matrix", at))
    table = TruthTable(id="delimited-listing", kind="pk_individual", where=grid.where(), rows=grid.rows(), header_rows=1,
                       spec=DELIMITED_SPEC, caption=(caption,))
    values = tuple(TruthValue(table=table.id, field="concentration", study="230-28", arm="", analyte=DRUG, matrix="plasma",
                              subject=s, time=t, time_unit="h", value=v, unit="µg/L", locator=grid.at(r, 3),
                              statistic="individual",
                              locators=(("time", grid.at(r, 2)), ("unit", grid.at(1, 3)), ("subject", grid.at(r, 1)), *labels))
                   for r, (s, t, v) in enumerate(body, start=2))
    values += tuple(_naming(table.id, at, study="230-28", analyte=DRUG))
    return SyntheticFile(name=name, data=data, format=suffix, tables=(table,), values=values,
                         notes=f"delimiter={sep!r}; encoding={encoding}; decimal={'comma' if decimal_comma else 'point'}")


def zipped(*files: SyntheticFile, name: str = "delivery.zip") -> SyntheticFile:
    """A ZIP of these files under their names. Its members' truth stays with the members (each is its own document)."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for member in files:
            archive.writestr(zipfile.ZipInfo(member.name, date_time=(1980, 1, 1, 0, 0, 0)), member.data)
    return SyntheticFile(name=name, data=out.getvalue(), format="zip", tables=(), values=(),
                         notes="members: " + ", ".join(f.name for f in files))


# --- the client-data template, filled ------------------------------------------------------------------------------

_T_STUDY = "EXA-101"
_T_TEST, _T_RLD = f"{DRUG} 10 mg tablet", "Comparamide 10 mg tablet"
_TEMPLATE_ROWS: dict[str, tuple[dict[str, object], ...]] = {
    "Studies": (
        dict(study_id=_T_STUDY, treatment="TEST", reference="CR-101", design="SD", crossover="yes", population="healthy",
             n=12, age_mean=31.5, age_min=21, age_max=45, weight_mean_kg=72.4, percent_female=50, route="oral", dose=10,
             dose_unit="mg", salt_or_base="base", product=_T_TEST, product_role="TEST", formulation="ir_tablet",
             strength_mg=10, batch="B123", food_state="fasted", analyte=DRUG, matrix="plasma", lloq=0.5, lloq_unit="ng/ml",
             intended_use="model_building"),
        dict(study_id=_T_STUDY, treatment="RLD", reference="CR-101", design="SD", crossover="yes", population="healthy",
             n=12, age_mean=31.5, age_min=21, age_max=45, weight_mean_kg=72.4, percent_female=50, route="oral", dose=10,
             dose_unit="mg", salt_or_base="base", product=_T_RLD, product_role="RLD", formulation="ir_tablet",
             strength_mg=10, batch="R456", food_state="fasted", analyte=DRUG, matrix="plasma", lloq=0.5, lloq_unit="ng/ml",
             intended_use="model_building"),
    ),
    "PK_Individual": (
        dict(study_id=_T_STUDY, treatment="TEST", subject_id="001", period=1, nominal_time=0.5, actual_time=0.52,
             time_unit="h", concentration="<0.5", unit="ng/ml", blq_flag="yes"),
        dict(study_id=_T_STUDY, treatment="TEST", subject_id="001", period=1, nominal_time=1, actual_time=1.03,
             time_unit="h", concentration=12.4, unit="ng/ml"),
        dict(study_id=_T_STUDY, treatment="TEST", subject_id="002", period=1, nominal_time=0.5, actual_time=0.55,
             time_unit="h", concentration="BLQ", unit="ng/ml", blq_flag="yes"),
        dict(study_id=_T_STUDY, treatment="TEST", subject_id="002", period=1, nominal_time=1, actual_time=0.98,
             time_unit="h", concentration=10.9, unit="ng/ml"),
    ),
    "PK_Summary": (
        dict(study_id=_T_STUDY, treatment="RLD", time=0.5, time_unit="h", statistic="arithmetic_mean", value=11.8,
             variability=2.3, variability_kind="SD", n=12, unit="ng/ml"),
        dict(study_id=_T_STUDY, treatment="RLD", time=1, time_unit="h", statistic="arithmetic_mean", value=25.1,
             variability=4.6, variability_kind="SD", n=12, unit="ng/ml"),
    ),
    "PK_Parameters": (
        dict(study_id=_T_STUDY, treatment="TEST", parameter="Cmax", statistic="geometric_mean", value=31.4, variability=18.2,
             variability_kind="CV%", unit="ng/ml"),
        dict(study_id=_T_STUDY, treatment="TEST", parameter="AUC_last", statistic="geometric_mean", value=152.7,
             variability=21.5, variability_kind="CV%", unit="ng/ml*h"),
    ),
    "Dissolution": (
        dict(product=_T_TEST, role="TEST", strength_mg=10, batch="B123", apparatus="USP 2 paddle", rpm=50,
             medium="0.1 N HCl", ph=1.2, volume_ml=900, temperature_c=37, time=15, time_unit="min", vessel_1=62.1,
             vessel_2=60.4, vessel_3=63.8),
        dict(product=_T_TEST, role="TEST", strength_mg=10, batch="B123", apparatus="USP 2 paddle", rpm=50,
             medium="0.1 N HCl", ph=1.2, volume_ml=900, temperature_c=37, time=30, time_unit="min", vessel_1=88.4,
             vessel_2=86.9, vessel_3=89.7),
    ),
    "Product": (
        dict(product=_T_TEST, role="TEST", dosage_form="tablet", strength_mg=10, release="IR", particle_size_d10_um=4.1,
             particle_size_d50_um=12.6, particle_size_d90_um=31.8, particle_size_method="laser diffraction",
             polymorph="Form I"),
    ),
    "Physchem_InVitro": (
        dict(parameter="phys.logp", value=2.1, conditions="pH 7.4, 25 °C", method="shake flask, measured",
             report_reference="R-12"),
        dict(parameter="bind.fu", value=0.12, conditions="human plasma", method="equilibrium dialysis",
             report_reference="R-13"),
    ),
    "Urine_Feces": (
        dict(study_id=_T_STUDY, treatment="TEST", matrix="urine", interval_start_h=0, interval_end_h=12, amount=1.8,
             unit="mg", analyte=DRUG),
        dict(study_id=_T_STUDY, treatment="TEST", matrix="urine", interval_start_h=12, interval_end_h=24, amount=0.6,
             unit="mg", analyte=DRUG),
    ),
}
# A template column read as an entity's label (role), a value's unit or an ignored column; every other filled column
# is a value of the field of the same name (Dissolution's and Product's `role` is the field product_role)
_TEMPLATE_LABELS = {"study_id": "study", "treatment": "arm", "subject_id": "subject", "period": "period", "product": "product",
                    "batch": "batch", "analyte": "analyte", "matrix": "matrix"}


def _template_spec(sheet: str, columns: Sequence[str]) -> MappingSpec:
    """The approved spec of one template sheet (its header is row 1)."""
    from modeler_intake.client_template import PK_PARAMETERS

    index = {name: i for i, name in enumerate(columns, start=1)}
    out: list[ColumnMap] = []
    for name, i in index.items():
        if name in _TEMPLATE_LABELS:
            out.append(ColumnMap(column=i, role=_TEMPLATE_LABELS[name]))
        elif name in ("nominal_time", "time"):
            out.append(ColumnMap(column=i, role="time"))
        elif name == "actual_time":
            out.append(ColumnMap(column=i, role="time_actual"))
        elif name == "time_unit":
            out.append(ColumnMap(column=i, role="time_unit"))
        elif name == "blq_flag":
            out.append(ColumnMap(column=i, role="blq_flag", of=index["concentration"]))
        elif name == "statistic":
            out.append(ColumnMap(column=i, role="statistic"))
        elif name in ("variability", "sd"):
            out.append(ColumnMap(column=i, role="spread", of=index["value" if name == "variability" else "mean"],
                                 spread_kind="SD" if name == "sd" else None))
        elif name == "variability_kind":
            out.append(ColumnMap(column=i, role="spread_kind"))
        elif name == "n" and sheet in ("PK_Summary", "Dissolution"):
            out.append(ColumnMap(column=i, role="n", of=index["value" if sheet == "PK_Summary" else "mean"]))
        elif name == "unit":
            out.append(ColumnMap(column=i, role="unit", of=index["amount" if sheet == "Urine_Feces" else
                                                              "value" if "value" in index else "concentration"]))
        elif name == "lloq_unit":
            out.append(ColumnMap(column=i, role="unit", of=index["lloq"]))
        elif name == "dose_unit":
            out.append(ColumnMap(column=i, role="unit", of=index["dose"]))
        elif name == "parameter":
            out.append(ColumnMap(column=i, role="parameter"))
        elif name in ("apparatus", "rpm", "medium", "ph", "volume_ml", "temperature_c", "surfactant", "interval_start_h",
                      "interval_end_h"):
            out.append(ColumnMap(column=i, role="condition", condition=name))
        elif name.startswith("vessel_"):
            out.append(ColumnMap(column=i, role="value", field="percent_dissolved", statistic="individual",
                                 series=Cite(row=1, column=i), series_role="vessel"))
        elif name == "mean":
            out.append(ColumnMap(column=i, role="value", field="percent_dissolved", statistic="arithmetic_mean"))
        elif name == "role":
            out.append(ColumnMap(column=i, role="value", field="product_role"))
        elif name == "amount":
            out.append(ColumnMap(column=i, role="value", field="excretion.amount"))
        elif name == "concentration":
            out.append(ColumnMap(column=i, role="value", field="concentration", statistic="individual"))
        elif name in ("conditions", "method", "report_reference"):
            out.append(ColumnMap(column=i, role="ignore", reason="the measurement's conditions, method and report are kept "
                                                                  "with the source: no condition field holds free text"))
        elif name == "value":
            out.append(ColumnMap(column=i, role="value", field="concentration" if sheet == "PK_Summary" else None))
        else:
            out.append(ColumnMap(column=i, role="value", field=name))
    layout = "key_value" if sheet in ("PK_Parameters", "Physchem_InVitro") else "long"
    keys: tuple[KeyMap, ...] = ()
    if sheet == "PK_Parameters":
        keys = tuple(KeyMap(pattern=re.escape(p), field=f"pk.{p}") for p in PK_PARAMETERS)
    elif sheet == "Physchem_InVitro":
        keys = (KeyMap(pattern=r"phys\.logp", field="phys.logp"), KeyMap(pattern=r"bind\.fu", field="bind.fu"))
    kind = {"Studies": "study_design", "PK_Individual": "pk_individual", "PK_Summary": "pk_summary",
            "PK_Parameters": "pk_parameters", "Dissolution": "dissolution", "Product": "product_batch",
            "Physchem_InVitro": "physchem_invitro", "Urine_Feces": "excretion"}[sheet]
    return MappingSpec(kind=kind, layout=layout, header_rows=1, first_data_row=2, columns=tuple(out), keys=keys,
                       below_lloq_tokens=("BLQ",) if sheet == "PK_Individual" else ())


README_SPEC = MappingSpec(kind="not_data", layout="long", header_rows=1, first_data_row=2,
                          not_data_reason="the template's column guide (sheet, column, required, allowed values, notes): "
                                          "instructions for the client, not data")


def _readme(ws) -> tuple[TruthTable, tuple[str, ...], tuple[str, ...]]:
    """The README sheet: its column guide as a not_data truth table (header "Sheet | Column | ..." to the last row) and
    the locators of the lines above it that hold a number and lie outside the table's context: the outside numbers
    (none in a template filled as shipped), then the template's own text (furniture)."""
    header_row = next(r for r in range(1, ws.max_row + 1) if (ws.cell(r, 1).value, ws.cell(r, 2).value) == ("Sheet", "Column"))
    cells = [[ws.cell(r, c).value for c in range(1, ws.max_column + 1)] for r in range(header_row, ws.max_row + 1)]
    grid = _Grid(ws.title, header_row, 1, cells)
    near = [r for r in range(header_row - 1, header_row - 4, -1)
            if r >= 1 and any(ws.cell(r, c).value is not None for c in range(1, ws.max_column + 1))]
    table = TruthTable(id="template-readme", kind="not_data", where=grid.where(), rows=grid.rows(), header_rows=1,
                       spec=README_SPEC, above=tuple(" | ".join(_text(ws.cell(r, c).value) for c in range(1, ws.max_column + 1)
                                                               if ws.cell(r, c).value is not None) for r in near))
    # the template's own words (its id line and instructions, client_template.README) are furniture, never an outside
    # number; a line the client changed, or anything typed beside them, is
    def own(r: int, c: int) -> bool:
        return c == 1 and r <= len(README) and _text(ws.cell(r, c).value).strip() == README[r - 1].strip()

    numbered = [(r, c) for r in range(1, header_row) if r not in near for c in range(1, ws.max_column + 1)
                if ws.cell(r, c).value is not None and has_number(_text(ws.cell(r, c).value))]
    outside = tuple(_sheet_cell(ws.title, r, c) for r, c in numbered if not own(r, c))
    return table, outside, tuple(_sheet_cell(ws.title, r, c) for r, c in numbered if own(r, c))


def template_workbook() -> SyntheticFile:
    """A filled client-data template (client_template.build_template): every data sheet has rows; the README sheet
    stays as the template writes it (its column guide is a not_data table, its numbered title and instruction lines
    are outside items)."""
    from modeler_intake.client_template import SHEETS

    wb = load_workbook(io.BytesIO(build_template()))
    tables: list[TruthTable] = []
    values: list[TruthValue] = []
    for sheet, records in _TEMPLATE_ROWS.items():
        columns = [c.name for c in SHEETS[sheet]]
        ws = wb[sheet]
        for record in records:
            ws.append([record.get(name) for name in columns])
        width = len(columns)
        header = [_text(ws.cell(1, c).value) for c in range(1, width + 1)]
        grid = _Grid(sheet, 1, 1, [header, *[[record.get(name) for name in columns] for record in records]])
        table = TruthTable(id=f"template-{sheet.lower()}", kind=_template_spec(sheet, columns).kind, where=grid.where(),
                           rows=grid.rows(), header_rows=1, spec=_template_spec(sheet, columns))
        tables.append(table)
        values += _template_values(table, sheet, columns, records, grid)
    readme, outside, furniture = _readme(wb["README"])
    tables.append(readme)
    return SyntheticFile(name="client-data-template.xlsx", data=_save(wb), format="xlsx", tables=tuple(tables),
                         values=tuple(values), outside=outside, furniture=furniture,
                         notes="the README sheet's column guide is a not_data table (no values); its title and "
                               "instruction lines are the template's own text (furniture, never outside numbers); a "
                               "template is confirmed on its legacy "
                               "card (contracts §2). A unit the template states by its column's name or convention "
                               "(strength_mg, % dissolved) is not written in a cell: such a value's unit is \"\"")


def _template_values(table: TruthTable, sheet: str, columns: Sequence[str], records: Sequence[dict[str, object]],
                     grid: _Grid) -> list[TruthValue]:
    index = {name: i for i, name in enumerate(columns, start=1)}
    unit_of = {"lloq": "lloq_unit", "dose": "dose_unit", "concentration": "unit", "value": "unit", "amount": "unit"}
    skip = {*_TEMPLATE_LABELS, "nominal_time", "time", "actual_time", "time_unit", "blq_flag", "statistic", "variability",
            "variability_kind", "n" if sheet in ("PK_Summary", "Dissolution") else "", "unit", "lloq_unit", "dose_unit",
            "parameter", "conditions", "method", "report_reference", "sd", "apparatus", "rpm", "medium", "ph", "volume_ml",
            "temperature_c", "surfactant", "interval_start_h", "interval_end_h"}
    out = []
    for r, record in enumerate(records, start=2):
        labels = {role: _text(record.get(name)) for name, role in _TEMPLATE_LABELS.items() if record.get(name) is not None}
        label_at = tuple((role, grid.at(r, index[name])) for name, role in _TEMPLATE_LABELS.items()
                         if record.get(name) is not None)
        conditions = tuple((name, _text(record[name])) for name in ("apparatus", "rpm", "medium", "ph", "volume_ml",
                                                                    "temperature_c", "surfactant", "interval_start_h",
                                                                    "interval_end_h") if record.get(name) is not None)
        condition_at = tuple((name, grid.at(r, index[name])) for name, _v in conditions)
        time = _text(record.get("nominal_time", record.get("time")))
        time_name = "nominal_time" if "nominal_time" in index else "time"
        time_at = (("time", grid.at(r, index[time_name])),) if time else ()
        for name in columns:
            raw = record.get(name)
            if raw is None or name in skip:
                continue
            if sheet == "PK_Parameters" and name == "value":
                field_name = f"pk.{record['parameter']}"
            elif sheet == "PK_Summary" and name == "value":
                field_name = "concentration"
            elif sheet == "Physchem_InVitro" and name == "value":
                field_name = str(record["parameter"])
            else:
                field_name = {"role": "product_role", "amount": "excretion.amount", "mean": "percent_dissolved"}.get(
                    name, "percent_dissolved" if name.startswith("vessel_") else name)
            unit = _text(record.get(unit_of.get(name, ""), "")) if name in unit_of else ""
            statistic = ""
            if name == "concentration" or name.startswith("vessel_"):
                statistic = "individual"
            elif "statistic" in index and name == "value":
                statistic = _text(record.get("statistic"))
            spread = _text(record.get("variability")) if name == "value" and record.get("variability") is not None else ""
            extra = []
            if unit and name in unit_of and record.get(unit_of[name]) is not None:
                extra.append(("unit", grid.at(r, index[unit_of[name]])))
            if spread:
                extra.append(("spread", grid.at(r, index["variability"])))
            if name == "value" and "n" in index and record.get("n") is not None:
                extra.append(("n", grid.at(r, index["n"])))
            if name == "value" and "parameter" in index and record.get("parameter") is not None:
                extra.append(("parameter", grid.at(r, index["parameter"])))
            if "actual_time" in index and record.get("actual_time") is not None and name == "concentration":
                extra.append(("time_actual", grid.at(r, index["actual_time"])))
            if name == "concentration" and _text(raw).startswith("<"):
                extra.append(("lloq", grid.at(r, index[name])))
            measured = name in ("concentration", "value", "amount", "mean") or name.startswith("vessel_")
            out.append(TruthValue(
                table=table.id, field=field_name, study=labels.get("study", ""), arm=labels.get("arm", ""),
                analyte=labels.get("analyte", ""), matrix=labels.get("matrix", ""), subject=labels.get("subject", ""),
                time=time if measured else "", time_unit=_text(record.get("time_unit")) if measured and time else "",
                value=_text(raw), unit=unit, locator=grid.at(r, index[name]),
                conditions=conditions if measured else (), statistic=statistic, spread=spread,
                spread_kind=_text(record.get("variability_kind")) if spread else "",
                n=_text(record.get("n")) if name == "value" and sheet == "PK_Summary" else "",
                product=labels.get("product", ""), batch=labels.get("batch", ""),
                vessel=name if name.startswith("vessel_") else "", period=labels.get("period", "") if measured else "",
                time_actual=_text(record.get("actual_time")) if name == "concentration" else "",
                locators=(*(time_at if measured else ()), *label_at, *(condition_at if measured else ()),
                          *((("vessel", grid.at(1, index[name])),) if name.startswith("vessel_") else ()), *extra)))
    return out


def delivery() -> tuple[SyntheticFile, ...]:
    """The set W, D0 and D6 run end to end: the messy workbook, the PDF report without its unruled page (an unruled
    table cannot be mapped: it would be silent loss), the Word report and the delimited listing. Not the scanned PDF
    (it needs OCR) and not the template (it is confirmed on the legacy card)."""
    return (messy_workbook(), pdf_report(unruled_table=False), word_report(), delimited())


# --- the truth as a grid -------------------------------------------------------------------------------------------


def _region_id(where: str, file_sha256: str) -> str:
    return "rg-" + hashlib.sha256(f"{where}|{file_sha256}".encode()).hexdigest()[:10]


def _sheet_truth_grid(file: SyntheticFile, table: TruthTable, sha: str) -> RegionGrid:
    sheet_name, cells_range = re.fullmatch(r"s:'((?:[^']|'')+)'!(.+)", table.where).groups()
    sheet_name = sheet_name.replace("''", "'")
    col0, row0, col1, row1 = range_boundaries(cells_range)
    sheet = None
    if file.format in ("xlsx", "xlsm"):
        sheet = load_workbook(io.BytesIO(file.data), data_only=True)[sheet_name]

    def grid_cell(row: int, column: int) -> GridCell | None:
        locator = _sheet_cell(sheet_name, row, column)
        if sheet is None:
            text = table.rows[row - row0][column - col0] if row0 <= row <= row1 and col0 <= column <= col1 else ""
            return GridCell(text=text, value=text, type="number" if is_numeric_text(text) else "text", locator=locator) \
                if text else None
        cell = sheet.cell(row=row, column=column)
        value = cell.value
        if value is None:
            return None
        number_format = cell.number_format if cell.number_format != "General" else ""
        if isinstance(value, bool):
            return GridCell(text=_text(value), value=value, type="bool", locator=locator, number_format=number_format)
        if isinstance(value, int | float):
            return GridCell(text=_text(value), value=value, type="number", locator=locator, number_format=number_format)
        if isinstance(value, datetime):
            return GridCell(text=value.isoformat(), value=value.isoformat(), type="date", locator=locator)
        return GridCell(text=str(value), value=str(value), type="text", locator=locator, number_format=number_format)

    cells: dict[tuple[int, int], GridCell] = {}
    for row in range(row0, row1 + 1):
        for column in range(col0, col1 + 1):
            made = grid_cell(row, column)
            if made is not None:
                cells[(row - row0 + 1, column - col0 + 1)] = made
    for merge in table.merges:
        m_col0, m_row0, m_col1, m_row1 = range_boundaries(merge)
        origin = cells[(m_row0 - row0 + 1, m_col0 - col0 + 1)]
        for row in range(m_row0, m_row1 + 1):
            for column in range(m_col0, m_col1 + 1):
                if (row, column) != (m_row0, m_col0):
                    cells[(row - row0 + 1, column - col0 + 1)] = GridCell(
                        text=origin.text, value=origin.value, type=origin.type, locator=_sheet_cell(sheet_name, row, column),
                        number_format=origin.number_format, merged_from=origin.locator)
    caption = tuple(GridCell(text=t, value=t, type="text", locator=_sheet_cell(sheet_name, row0 - len(table.caption) + i, col0))
                    for i, t in enumerate(table.caption))

    def lines(rows: Sequence[int]) -> tuple[tuple[GridCell, ...], ...]:
        found = []
        for row in rows:
            if row < 1:
                continue
            line = tuple(c for column in range(col0, col1 + 1) if (c := grid_cell(row, column)) is not None)
            if line:
                found.append(line)
        return tuple(found)

    top = row0 - len(table.caption)
    above = lines(range(top - 1, top - 4, -1)) if sheet is not None else ()
    below = lines(range(row1 + 1, row1 + 4)) if sheet is not None else ()
    return RegionGrid(file_sha256=sha, parser=PARSERS[file.format], parser_version=TRUTH_PARSER_VERSION,
                      region_id=_region_id(table.where, sha), n_rows=row1 - row0 + 1, n_cols=col1 - col0 + 1, cells=cells,
                      caption=caption, above=above, below=below)


@lru_cache(maxsize=2)
def _report_bytes(unruled_table: bool) -> bytes:
    return _pdf(_report_layout(unruled_table)[0])


def _pdf_truth_grid(file: SyntheticFile, table: TruthTable, sha: str) -> RegionGrid:
    variants = [unruled for unruled in (True, False) if _report_bytes(unruled) == file.data]
    if not variants:
        raise ValueError(f"{file.name}: not a file pdf_report() built")
    pages, layout = _report_layout(variants[0])
    truth = layout[table.id]
    cells: dict[tuple[int, int], GridCell] = {}
    for r, row in enumerate(_pdf_grid_cells(truth), start=1):
        for c, (text, locator) in enumerate(row, start=1):
            if text:
                cells[(r, c)] = GridCell(text=text, value=text, type="number" if is_numeric_text(text) else "text",
                                         locator=locator)

    def line(where: tuple[int, _Text] | None) -> GridCell | None:
        if where is None:
            return None
        page, item = where
        return GridCell(text=item.text, value=item.text, type="text", locator=_span(page, pages[page - 1], item))

    caption, below = line(truth.caption), line(truth.below)
    first_page, _index, first_table, _repeated = truth.parts[0]
    x0, top, x1, bottom = (round(v) for v in first_table.box())
    first_row = " ".join(t for t in first_table.rows[0] if t)
    region_id = "rg-" + hashlib.sha256(f"p:{first_page}/box:{x0},{top},{x1},{bottom}/{first_row}|{sha}".encode()).hexdigest()[:10]
    return RegionGrid(file_sha256=sha, parser="pdfplumber", parser_version=TRUTH_PARSER_VERSION, region_id=region_id,
                      n_rows=len(table.rows), n_cols=len(table.rows[0]), cells=cells,
                      caption=(caption,) if caption else (), below=((below,),) if below else ())


def _docx_truth_grid(file: SyntheticFile, table: TruthTable, sha: str) -> RegionGrid:
    number = int(table.where.removeprefix("d:t:"))
    cells: dict[tuple[int, int], GridCell] = {}
    for r, row in enumerate(table.rows, start=1):
        for c, text in enumerate(row, start=1):
            if text:
                cells[(r, c)] = GridCell(text=text, value=text, type="number" if is_numeric_text(text) else "text",
                                         locator=format_locator(DocxCell(table=number, row=r, column=c)))
    for merge in table.merges:
        (r0, c0), (r1, c1) = (tuple(int(n) for n in re.fullmatch(r"r(\d+)c(\d+)", end).groups()) for end in merge.split(":"))
        origin = cells[(r0, c0)]
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if (r, c) != (r0, c0):
                    cells[(r, c)] = GridCell(text=origin.text, value=origin.value, type=origin.type,
                                             locator=format_locator(DocxCell(table=number, row=r, column=c)),
                                             merged_from=origin.locator)
    caption = tuple(GridCell(text=t, value=t, type="text", locator=_docx_span(4, t)) for t in table.caption)
    return RegionGrid(file_sha256=sha, parser="docx", parser_version=TRUTH_PARSER_VERSION,
                      region_id=_region_id(table.where, sha), n_rows=len(table.rows), n_cols=len(table.rows[0]), cells=cells,
                      caption=caption)


def truth_grid(file: SyntheticFile, table_id: str) -> RegionGrid:
    """The table as a grid with every cell's TRUE locator (sheet, PDF or Word) and its context lines: D3, D4 and D5 test
    on it. A workbook's cells carry their stored value, type and number format ("" for General); a merged range's
    covered cells are copies with `merged_from` (the origin's locator). The parser version is TRUTH_PARSER_VERSION.
    The region id is §4.2's: "rg-" + sha256(where + "|" + file sha256)[:10], and for a PDF table
    "rg-" + sha256("p:<first page>/box:<x0>,<top>,<x1>,<bottom>/<first row>|<file sha256>")[:10], the box of its first
    part rounded to whole points and its first row's non-empty texts joined by single spaces."""
    (table,) = [t for t in file.tables if t.id == table_id]
    sha = hashlib.sha256(file.data).hexdigest()
    if file.format == "pdf":
        return _pdf_truth_grid(file, table, sha)
    if file.format == "docx":
        return _docx_truth_grid(file, table, sha)
    return _sheet_truth_grid(file, table, sha)
