"""The source model: one parse of a client file, structure kept (docs/plans/2026-11-12-intake-contracts.md §4.2).

A file is parsed once (D2) into a `SourceDocument`: its sheets with every non-empty cell (value, text, type, number
format, merge origin), its PDF pages with words, ruled tables and boxes, its Word body in order, its figures, and the
regions located in it (tables, prose, figures, unruled tables) with whatever lies outside them. Every value is later
read from a `RegionGrid`, the same for a sheet range, a PDF table and a Word table, and anchored (§4.1).

"A number" is `has_number` throughout: a cell that holds a digit must be accounted for, whether or not it is a bare
number (`is_numeric_text`). "12.3 (4.5)", "12.3 ± 4.5", "0.95 (0.88-1.03)", "12.3*", "12.3 ng/mL" and "1 234.5" are
not bare numbers, but they hold numbers: a mapped table accounts for them (a value with its cell form, a label, a
constant ...) or they are silent loss.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from modeler_intake.anchors import AnchorError, Box, SheetCell, anchor_text, format_locator
from modeler_intake.fields import DocumentRole, TableKind

FileFormat = Literal["xlsx", "xlsm", "xls", "csv", "tsv", "docx", "pdf", "text", "markdown", "json", "zip", "image", "other"]
DocState = Literal["read", "partly_read", "unsupported", "unreadable"]
CellType = Literal["number", "text", "bool", "date", "empty"]

# A bare number: an optional comparator and sign, then digits with at most one decimal mark, or thousands groups of
# exactly three digits before an optional decimal part ("1,234.5", "1.234,5"), an optional exponent and percent sign.
# Contracts §4.2 wrote the groups as ([.,]\d+)*, which also takes a date ("15.01.2024") or a version ("1.2.3").
NUMERIC_TEXT: re.Pattern[str] = re.compile(
    r"^[<>≤≥]?\s*[-+]?(\d{1,3}([.,]\d{3})+([.,]\d+)?|\d+([.,]\d+)?|[.,]\d+)([eE][-+]?\d+)?\s*%?$")
_DIGIT = re.compile(r"\d")


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("−", "-")


def is_numeric_text(text: str) -> bool:
    """Whether a text is a BARE number (after NFKC, U+2212 read as "-", outer spaces aside): "12.5", "<0.5", "1,234.5",
    "-3e-2", "55 %". Used to type a cell and for the header band's "#" (§6.2), nothing else."""
    return NUMERIC_TEXT.fullmatch(_nfkc(text).strip()) is not None


def has_number(text: str) -> bool:
    """Whether a text holds a digit after NFKC: the one definition of "a cell with a number" for locating regions,
    `Region.numeric_cells`, `CellUse.numeric` and silent loss."""
    return _DIGIT.search(_nfkc(text)) is not None


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ContainerRef(_B):          # the ZIP a document came out of
    sha256: str
    name: str
    member: str


class Finding(_B):
    code: str
    location: str
    message: str
    severity: Literal["error", "warn", "info"] = "error"


class SheetCellValue(_B):
    """One non-empty cell of a sheet (sheets are sparse)."""

    row: int
    column: int
    value: float | int | str | bool | None
    # exactly: a number cell -> the shortest round-trip form of the stored value (repr; an integer without ".0": 12.4037,
    # 12.4, 3), never the formatted display ("12.40" under 0.00) nor the % scaling; a date -> ISO 8601; a bool ->
    # "TRUE"/"FALSE"; a text cell -> its text as stored. A row's `verbatim` is this text; check_anchors compares it.
    text: str
    type: CellType
    number_format: str = ""
    merged_from: str | None = None   # a merged range's copy: the origin's A1; the value is copied, as grid.py does


class Sheet(_B):
    name: str
    index: int
    max_row: int
    max_column: int
    hidden: bool = False
    cells: tuple[SheetCellValue, ...]


class Word(_B):
    index: int
    text: str
    box: Box


class TableCell(_B):
    row: int
    column: int
    text: str
    box: Box | None = None
    row_span: int = 1
    col_span: int = 1


class PageTable(_B):
    index: int
    box: Box | None
    n_rows: int
    n_cols: int
    cells: tuple[TableCell, ...]
    engine: str


class Page(_B):
    number: int
    width: float
    height: float
    rotation: int = 0
    needs_ocr: bool = False
    n_chars: int
    words: tuple[Word, ...]
    tables: tuple[PageTable, ...]
    n_images: int = 0


class Paragraph(_B):
    index: int
    text: str
    style: str = ""


class BodyItem(_B):
    kind: Literal["paragraph", "table"]
    paragraph: Paragraph | None = None
    table: PageTable | None = None


class Figure(_B):
    index: int
    page: int | None = None
    box: Box | None = None
    name: str = ""
    width: int = 0
    height: int = 0


class RegionPart(_B):            # one page's piece of a continued table
    page: int
    table: int
    n_rows: int
    header_rows_repeated: int = 0
    caption: str = ""            # that part's own caption, as written


class Region(_B):
    # sheet, Word, text: "rg-" + sha256(where + "|" + file sha256)[:10]; a PDF table: "rg-" + sha256("p:<first page>
    # /box:<its box rounded to whole points>/" + <its first row's text> + "|" + file sha256)[:10], so a parser that finds
    # one more table on a page does not renumber the others' regions
    id: str
    kind: Literal["table", "prose", "figure", "table_like_text"]
    where: str                              # a `range` of §4.1 (a continued PDF table: its first part)
    parts: tuple[RegionPart, ...] = ()
    caption: str = ""
    caption_locator: str | None = None
    table_kind: TableKind = "unknown"
    kind_evidence: str = ""                 # by rule: the locator and words that decided it
    n_rows: int = 0
    n_cols: int = 0
    numeric_cells: int = 0                  # cells with has_number; a merged copy is not counted (its origin is, once)
    notes: tuple[str, ...] = ()             # e.g. "rows 9-11 joined across empty row 8"


class OutsideItem(_B):           # content in no region: a locator and at most 200 characters
    where: str
    text: str
    numeric: bool                          # has_number(text)
    furniture: bool = False                # page furniture: a page number, or a line repeated at the same place on most pages
    region: str | None = None              # a line of that region's context (RegionGrid.above / below), which a constant may cite


class SourceDocument(_B):
    # read by its alias or its name: a body dumped without by_alias reads back too (canonical() writes the alias)
    model_config = ConfigDict(frozen=True, extra="forbid", validate_by_name=True)

    schema_id: Literal["source/1"] = Field(default="source/1", alias="schema")
    file_sha256: str
    name: str
    size_bytes: int
    format: FileFormat
    parser: str
    parser_version: str
    container: ContainerRef | None = None
    state: DocState
    reason: str = ""                        # required for partly_read, unsupported, unreadable
    role: DocumentRole = "other"
    role_evidence: str = ""
    encoding: str | None = None
    delimiter: str | None = None
    sheets: tuple[Sheet, ...] = ()
    pages: tuple[Page, ...] = ()
    body: tuple[BodyItem, ...] = ()
    figures: tuple[Figure, ...] = ()
    regions: tuple[Region, ...] = ()
    outside: tuple[OutsideItem, ...] = ()
    members: tuple[str, ...] = ()           # ZIP: member paths; each member is its own document
    warnings: tuple[str, ...] = ()


# --- the grid a mapping reads --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GridCell:
    """One cell of a grid. `type` "number" with an int or float `value` is a STORED number (a workbook cell): taken as
    it is (§6.2). `type` "number" with a str `value` is a bare number written as text (a PDF, Word or delimited cell,
    typed with `is_numeric_text` as D2 types it): like every str value it is read under the region's decimal
    convention and counts as a text cell for `decimal_convention`. Only `isinstance(value, int | float)` (not a bool)
    says a number is stored."""

    text: str
    value: float | int | str | bool | None
    type: CellType
    locator: str                            # locator text (§4.1) of this cell; "" for a cell the region does not hold
    number_format: str = ""
    # a merged copy: the ORIGIN's locator. It may serve as a header or label, is never a value, is never counted (the
    # origin is counted once, where it stands)
    merged_from: str | None = None


_EMPTY = GridCell(text="", value=None, type="empty", locator="")


@dataclass(frozen=True)
class RegionGrid:
    """One table region as a grid in its own coordinates (row 1, column 1 = the region's top-left): what the mapping
    reads, the same for a sheet range, a PDF table (its parts joined, repeated headers dropped) and a Word table.
    Its context is what a constant may cite: the caption, up to 3 lines directly above it and up to 3 lines directly
    below the region, only lines that belong to no other region (a sheet line: that row's non-empty cells; a PDF or
    Word line: one cell, its span locator).

    A grid compares by value and is not hashable (its cells are a mapping): key a cache by its region id.
    `cells` holds the non-empty cells only. `caption` holds one cell per caption line, in reading order (Cite line 1 is
    the first); `above[0]` is the line directly above (the caption, when there is one, is apart), `below[0]` the line
    directly below the region."""

    file_sha256: str
    parser: str
    parser_version: str
    region_id: str
    n_rows: int
    n_cols: int
    cells: Mapping[tuple[int, int], GridCell]
    caption: tuple[GridCell, ...] = ()
    above: tuple[tuple[GridCell, ...], ...] = ()
    below: tuple[tuple[GridCell, ...], ...] = ()

    def cell(self, row: int, column: int) -> GridCell:
        """The cell at (row, column) of the region; an empty GridCell (locator "") when the region holds none there."""
        return self.cells.get((row, column), _EMPTY)

    def anchor(self, row: int, column: int) -> str:
        """The anchor text of that cell; AnchorError when the region holds no cell there."""
        locator = self.cell(row, column).locator
        if not locator:
            raise AnchorError(f"region {self.region_id} holds no cell at row {row}, column {column}")
        return anchor_text(self.file_sha256, self.parser, self.parser_version, locator)

    def context(self, near: Literal["caption", "above", "below"], line: int) -> tuple[GridCell, ...]:
        """The cells of one context line (line from 1); () when there is no such line."""
        if line < 1:
            return ()
        if near == "caption":
            return (self.caption[line - 1],) if line <= len(self.caption) else ()
        lines = self.above if near == "above" else self.below
        return lines[line - 1] if line <= len(lines) else ()

    def anchor_of(self, locator: str) -> str:
        """The anchor text of a locator of this grid or of its context; AnchorError for any other locator."""
        context = (*self.caption, *(c for line in (*self.above, *self.below) for c in line))
        if not locator or not any(c.locator == locator for c in (*self.cells.values(), *context)):
            raise AnchorError(f"{locator!r} is not a cell of region {self.region_id} or of its context")
        return anchor_text(self.file_sha256, self.parser, self.parser_version, locator)

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[str | float | int | None]], *, region_id: str = "rg-0000000000",
                  first_cell: str | None = None, sheet: str = "T", caption: Sequence[str] = (),
                  above: Sequence[Sequence[str]] = (), below: Sequence[Sequence[str]] = ()) -> RegionGrid:
        """For tests: a grid with sheet-cell locators, typed as a sheet types its cells. The region starts at
        `first_cell` of sheet `sheet`; by default (None) at column A, on the first row below the caption and the
        `above` lines (row len(caption) + len(above) + 1), so a title over a table needs no position. Caption lines
        stand in the rows directly above the region (in reading order), the `above` lines above them (above[0]
        nearest), the `below` lines in the rows directly under the region (below[0] nearest), each from the region's
        first column; an explicit `first_cell` without room for them is a ValueError. None and "" are empty cells; an
        int or float is a stored number (text: its shortest round-trip form); a bool is a bool; a str is a text cell,
        its value as written ("<0.5", "12,5": a sheet stores them as text). The default region id passes
        `check_id("region")`. `synthetic.truth_grid` gives the true cells and locators of every format (a PDF, Word or
        delimited cell that is a bare number is typed "number" there, its value a str)."""
        needed = len(caption) + len(above)
        if first_cell is None:
            col0, row0 = 1, needed + 1
        else:
            match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", first_cell)
            if match is None:
                raise ValueError(f"not an A1 cell: {first_cell!r}")
            col0, row0 = _column_number(match.group(1)), int(match.group(2))
        if row0 <= needed:
            raise ValueError(f"the caption and the lines above need the region to start below row {needed} "
                             f"(first_cell={first_cell!r})")

        def at(row: int, column: int, raw: str | float | None) -> GridCell | None:
            if raw is None or raw == "":
                return None
            locator = format_locator(SheetCell(sheet=sheet, cell=f"{_column_letters(column)}{row}"))
            if isinstance(raw, bool):
                return GridCell(text="TRUE" if raw else "FALSE", value=raw, type="bool", locator=locator)
            if isinstance(raw, int | float):
                return GridCell(text=number_text(raw), value=raw, type="number", locator=locator)
            return GridCell(text=raw, value=raw, type="text", locator=locator)

        cells: dict[tuple[int, int], GridCell] = {}
        for r, values in enumerate(rows, start=1):
            for c, raw in enumerate(values, start=1):
                made = at(row0 + r - 1, col0 + c - 1, raw)
                if made is not None:
                    cells[(r, c)] = made

        def line(row: int, texts: Sequence[str]) -> tuple[GridCell, ...]:
            return tuple(g for c, t in enumerate(texts) if (g := at(row, col0 + c, t)) is not None)

        caption_cells = []
        for i, text in enumerate(caption):
            made = at(row0 - len(caption) + i, col0, text)
            if made is not None:
                caption_cells.append(made)
        top = row0 - len(caption)
        n_rows = len(rows)
        return cls(file_sha256="0" * 64, parser="test", parser_version="1.0", region_id=region_id, n_rows=n_rows,
                   n_cols=max((len(r) for r in rows), default=0), cells=cells, caption=tuple(caption_cells),
                   above=tuple(line(top - 1 - i, texts) for i, texts in enumerate(above)),
                   below=tuple(line(row0 + n_rows + i, texts) for i, texts in enumerate(below)))


def _column_number(letters: str) -> int:
    number = 0
    for ch in letters:
        number = number * 26 + (ord(ch) - 64)
    return number


def _column_letters(number: int) -> str:
    letters = ""
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def number_text(value: float) -> str:
    """A stored number's text (§4.2): its shortest round-trip form, an integer without ".0" (12.4037, 12.4, 3)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value)


# --- engines that may be passed in (none is today) -----------------------------------------------------------------


class PdfTableEngine(Protocol):
    """A second table engine (Docling ...): none is passed today."""

    name: str
    version: str

    def tables(self, data: bytes, page: int) -> Sequence[PageTable]: ...


class OcrEngine(Protocol):
    """None is passed today; a scanned page is reported as needing OCR."""

    name: str
    version: str

    def words(self, data: bytes, page: int) -> Sequence[Word]: ...


# --- what the review shows -----------------------------------------------------------------------------------------


class Resolved(_B):
    text: str
    locator: str
    region_id: str | None
    page: int | None = None
    box: Box | None = None


class ViewCell(_B):
    row: int
    column: int
    text: str
    numeric: bool
    locator: str
    highlighted: bool = False
    role: str | None = None                 # highlighted: "value", "time", "unit", "spread", "n", "lloq" or a label role


class SourceView(_B):
    """What the review shows beside a value (D2 builds it, D6 serves it)."""

    kind: Literal["grid", "text"]
    title: str
    region_id: str | None
    # grid: the region's cells (and its context lines: negative rows above, rows past n_rows below); the value's cell and
    # the cells of its time, unit, labels, spread, n and LLOQ highlighted with their role
    n_rows: int = 0
    n_cols: int = 0
    cells: tuple[ViewCell, ...] = ()
    text: str = ""                          # text: the paragraph and the span in it
    span: tuple[int, int] | None = None
    page: int | None = None                 # PDF: to draw the page
    page_size: tuple[float, float] | None = None
    box: Box | None = None


class AnchorProblem(_B):
    id: str
    anchor: str
    problem: Literal["not_found", "text_differs"]
    found: str = ""
