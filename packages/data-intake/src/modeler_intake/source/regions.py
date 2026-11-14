"""Regions: where the tables, prose and figures of a parsed file stand, and the grid a mapping reads (contracts §4.2, §6.1).

Locating a sheet (the rules of §6.1, no LLM; "a number" is `has_number` throughout):
- Blocks of non-empty cells separated by an empty row or an empty column, cut recursively (rows first, then columns).
  ONE empty row inside a block does not split it when the rows on both sides span the same columns (two or more: a
  line of text in one cell spans none) and the row after it holds a number (a Mean / SD / N group set off by a blank
  row): the join is noted in `Region.notes`. A row after the gap that holds no number (a caption or a new header)
  starts a new block.
  A row that holds one cell only (a merged cell counts once: a title merged across tables side by side, or wider than
  its table) fills no column: the columns are cut on the other rows, and its cells go with the column they stand in.
- In a block, the rows at its top that hold a single text cell (a merged cell counts once) are the caption (a title
  merged across tables side by side is the caption of each: its origin's, and its leftmost copy over the other); the rows
  below them are the table. A table with at least 2 rows and 2 cells holding a number is a `table` region, its
  columns the block's. Every other block is no region.
- Context: the non-empty cells in the 3 rows above the caption (or the table) and the 3 rows below the table, within
  the table's columns, that belong to no region. Each such cell is the context of ONE region (the nearer; on a tie the
  table it stands below), so a grid's context lines are exactly the outside items that name its region.
- Every non-empty cell in no region (context cells too) is an `OutsideItem`; a merged copy is never listed or counted.

`region_grid` builds the grid of one table region from the stored document alone (sheet, PDF and Word), with its
caption and context lines; `paragraphs` gives a prose region's paragraphs; `as_workbook_grid` hands today's
`grid.WorkbookGrid` to the legacy readers from the same parse.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from itertools import pairwise

from openpyxl.utils import column_index_from_string, get_column_letter

from modeler_intake.anchors import (
    Box,
    DocxCell,
    DocxSpan,
    PdfCell,
    PdfSpan,
    SheetCell,
    TextSpan,
    format_locator,
    parse_locator,
)
from modeler_intake.grid import Cell, SheetGrid, WorkbookGrid, cell_ref
from modeler_intake.mapping_spec import ProseParagraph
from modeler_intake.source_model import (
    GridCell,
    OutsideItem,
    Page,
    PageTable,
    Region,
    RegionGrid,
    Sheet,
    SheetCellValue,
    SourceDocument,
    Word,
    has_number,
    is_numeric_text,
)

CONTEXT_ROWS = 3           # rows above the caption and below the table read as its context (a reading parameter)
OUTSIDE_TEXT = 200         # an outside item carries at most this many characters
LINE_TOLERANCE = 3.0       # PDF words whose tops differ by at most this many points stand on one line

_A1 = re.compile(r"([A-Z]{1,3})([1-9][0-9]*)")
_SHEET_RANGE = re.compile(r"s:'((?:[^']|'')+)'!([A-Z]{1,3}[1-9][0-9]*):([A-Z]{1,3}[1-9][0-9]*)")
_PDF_TABLE = re.compile(r"p:([1-9][0-9]*)/t:([1-9][0-9]*)")
_WORD_SPAN = re.compile(r"p:([1-9][0-9]*)/w:([1-9][0-9]*)-([1-9][0-9]*)")
_DOCX_TABLE = re.compile(r"d:t:([1-9][0-9]*)")
_PARAGRAPHS = re.compile(r"(d:p|x:l):([1-9][0-9]*)-([1-9][0-9]*)")


# --- ids and places ------------------------------------------------------------------------------------------------


def region_id(where: str, file_sha256: str) -> str:
    """A sheet, Word, text, prose or figure region's id: "rg-" + sha256(where + "|" + file sha256)[:10] (§4.2)."""
    return "rg-" + hashlib.sha256(f"{where}|{file_sha256}".encode()).hexdigest()[:10]


def pdf_table_region_id(page: int, box: Box, first_row: Sequence[str], file_sha256: str) -> str:
    """A PDF table's region id (§4.2): its first part's page, its box rounded to whole points and its first row's
    non-empty texts joined by single spaces, so a parser that finds one more table on a page renumbers no region."""
    x0, top, x1, bottom = (round(v) for v in box)
    row = " ".join(t for t in first_row if t)
    return "rg-" + hashlib.sha256(f"p:{page}/box:{x0},{top},{x1},{bottom}/{row}|{file_sha256}".encode()).hexdigest()[:10]


def a1(row: int, column: int) -> str:
    return f"{get_column_letter(column)}{row}"


def a1_place(text: str) -> tuple[int, int]:
    """(row, column) of an A1 reference."""
    match = _A1.fullmatch(text)
    if match is None:
        raise ValueError(f"not an A1 cell: {text!r}")
    return int(match.group(2)), column_index_from_string(match.group(1))


def sheet_locator(sheet: str, row: int, column: int) -> str:
    return format_locator(SheetCell(sheet=sheet, cell=a1(row, column)))


def sheet_range(sheet: str, r0: int, c0: int, r1: int, c1: int) -> str:
    return sheet_locator(sheet, r0, c0) + ":" + a1(r1, c1)


def parse_sheet_range(where: str) -> tuple[str, int, int, int, int]:
    """(sheet, first row, first column, last row, last column) of a sheet range."""
    match = _SHEET_RANGE.fullmatch(where)
    if match is None:
        raise ValueError(f"not a sheet range: {where!r}")
    (r0, c0), (r1, c1) = a1_place(match.group(2)), a1_place(match.group(3))
    return match.group(1).replace("''", "'"), r0, c0, r1, c1


def round_box(box: Iterable[float]) -> Box:
    """A box with 2 decimals, as a locator writes it (a stored box and its locator agree)."""
    x0, top, x1, bottom = (round(float(v), 2) + 0.0 for v in box)
    return (x0, top, x1, bottom)


def union_box(boxes: Iterable[Box]) -> Box:
    found = list(boxes)
    return round_box((min(b[0] for b in found), min(b[1] for b in found), max(b[2] for b in found),
                      max(b[3] for b in found)))


def word_span(page: int, words: Sequence[Word]) -> str:
    """The span locator of consecutive words of one page."""
    return format_locator(PdfSpan(page=page, first_word=words[0].index, last_word=words[-1].index,
                                  box=union_box(w.box for w in words)))


def clip(text: str) -> str:
    return text if len(text) <= OUTSIDE_TEXT else text[:OUTSIDE_TEXT]


# --- locating sheets -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _SheetCells:
    """One sheet's cells by place: every stored cell, which of them are filled (text not blank), and each merged
    copy's origin."""

    sheet: Sheet
    cells: Mapping[tuple[int, int], SheetCellValue]
    origin: Mapping[tuple[int, int], tuple[int, int]]          # a merged copy -> its origin; an origin -> itself

    @classmethod
    def of(cls, sheet: Sheet) -> _SheetCells:
        cells = {(c.row, c.column): c for c in sheet.cells}
        origin = {place: a1_place(c.merged_from) if c.merged_from else place for place, c in cells.items()}
        return cls(sheet, cells, origin)

    def filled(self) -> list[tuple[int, int]]:
        return [place for place, c in self.cells.items() if c.text.strip()]

    def is_copy(self, place: tuple[int, int]) -> bool:
        return self.origin.get(place, place) != place

    def holds_number(self, place: tuple[int, int]) -> bool:
        cell = self.cells.get(place)
        return cell is not None and not self.is_copy(place) and has_number(cell.text)


def _runs(values: Sequence[int], joined: Iterable[int] = ()) -> list[list[int]]:
    """Consecutive values grouped; a value in `joined` bridges a gap of one."""
    bridge = set(joined)
    out: list[list[int]] = []
    for value in values:
        if out and (value == out[-1][-1] + 1 or (value == out[-1][-1] + 2 and value - 1 in bridge)):
            out[-1].append(value)
        else:
            out.append([value])
    return out


def _cut(index: _SheetCells, cells: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """The blocks of a set of filled cells: cut at empty rows (one empty row joined by the rule), then at empty
    columns, recursively, until no cut is left. A row that holds one cell only, a merged cell counting once (a title
    merged across tables side by side, or wider than its table, or standing over the empty column between them), fills
    no column: the columns are cut on the other rows, and its cells go with the column they stand in (an origin over an
    empty column is a block of its own; a copy there goes with none)."""
    done: list[list[tuple[int, int]]] = []
    todo = [cells]
    while todo:
        part = todo.pop()
        by_row: dict[int, list[int]] = {}
        for r, c in part:
            by_row.setdefault(r, []).append(c)
        rows = sorted(by_row)
        joined = []
        for prev, row in pairwise(rows):
            span = (min(by_row[prev]), max(by_row[prev]))
            if row == prev + 2 and span[1] > span[0] and span == (min(by_row[row]), max(by_row[row])) \
                    and any(index.holds_number((row, c)) for c in by_row[row]):
                joined.append(prev + 1)
        row_runs = _runs(rows, joined)
        if len(row_runs) > 1:
            todo.extend([(r, c) for r in run for c in by_row[r]] for run in row_runs)
            continue
        alone = {r for r in rows if len({index.origin.get((r, c), (r, c)) for c in by_row[r]}) == 1}
        frame = [p for p in part if p[0] not in alone] or part
        column_runs = _runs(sorted({c for _r, c in frame}))
        if len(column_runs) > 1:
            blocks = [[p for p in part if run[0] <= p[1] <= run[-1]] for run in column_runs]
            placed = {p for block in blocks for p in block}
            left = [p for p in part if p not in placed and not index.is_copy(p)]   # an origin over an empty column
            todo.extend(blocks + ([left] if left else []))
            continue
        done.append(part)
    return done


@dataclass(frozen=True)
class _SheetTable:
    caption_rows: tuple[int, ...]
    r0: int
    c0: int
    r1: int
    c1: int
    caption_cells: tuple[tuple[int, int], ...]

    @property
    def top(self) -> int:
        return self.caption_rows[0] if self.caption_rows else self.r0


def _table_of(index: _SheetCells, block: list[tuple[int, int]]) -> _SheetTable | None:
    """The table a block holds (its caption rows apart), or None when it holds none."""
    r0, r1 = min(r for r, _c in block), max(r for r, _c in block)
    c0, c1 = min(c for _r, c in block), max(c for _r, c in block)
    by_row: dict[int, list[tuple[int, int]]] = {}
    for place in block:
        by_row.setdefault(place[0], []).append(place)
    caption_rows, caption_cells = [], []
    for row in range(r0, r1 + 1):
        origins = {index.origin.get(p, p) for p in by_row.get(row, ())}
        if len(origins) != 1:
            break
        (origin,) = origins
        cell = index.cells.get(origin)
        if cell is None or cell.type != "text" or origin[0] != row:
            break
        caption_rows.append(row)
        caption_cells.append(_in_block(origin, sorted(by_row[row]), c0, c1))
    top = r0 + len(caption_rows)
    body = [p for p in block if p[0] >= top]
    if r1 - top + 1 < 2 or sum(1 for p in body if index.holds_number(p)) < 2:
        return None
    return _SheetTable(tuple(caption_rows), top, c0, r1, c1, tuple(caption_cells))


def _in_block(origin: tuple[int, int], places: Sequence[tuple[int, int]], c0: int, c1: int) -> tuple[int, int]:
    """A caption's cell within a block's columns: its origin, or (a title merged across tables side by side, its
    origin over the other table) its leftmost copy over this block."""
    if c0 <= origin[1] <= c1:
        return origin
    return next((p for p in places if c0 <= p[1] <= c1), origin)


def locate_sheets(sheets: Sequence[Sheet], file_sha256: str) -> tuple[tuple[Region, ...], tuple[OutsideItem, ...]]:
    """The table regions of every sheet and the cells outside them (see the module docstring)."""
    regions: list[Region] = []
    outside: list[OutsideItem] = []
    for sheet in sheets:
        found, items = _locate_sheet(sheet, file_sha256)
        regions += found
        outside += items
    return tuple(regions), tuple(outside)


def _locate_sheet(sheet: Sheet, file_sha256: str) -> tuple[list[Region], list[OutsideItem]]:
    index = _SheetCells.of(sheet)
    filled = index.filled()
    if not filled:
        return [], []
    tables = [t for block in _cut(index, filled) if (t := _table_of(index, block)) is not None]
    tables.sort(key=lambda t: (t.top, t.c0))
    held: set[tuple[int, int]] = set()
    for t in tables:
        held |= {p for p in filled if t.r0 <= p[0] <= t.r1 and t.c0 <= p[1] <= t.c1}
        held |= {p for p in filled if index.origin.get(p, p) in t.caption_cells}
    ids = [region_id(sheet_range(sheet.name, t.r0, t.c0, t.r1, t.c1), file_sha256) for t in tables]
    regions = []
    for t, rid in zip(tables, ids, strict=True):
        body = [p for p in filled if t.r0 <= p[0] <= t.r1 and t.c0 <= p[1] <= t.c1]
        caption = "\n".join(index.cells[p].text for p in t.caption_cells)
        regions.append(Region(
            id=rid, kind="table", where=sheet_range(sheet.name, t.r0, t.c0, t.r1, t.c1), caption=caption,
            caption_locator=sheet_locator(sheet.name, *t.caption_cells[0]) if t.caption_cells else None,
            n_rows=t.r1 - t.r0 + 1, n_cols=t.c1 - t.c0 + 1,
            numeric_cells=sum(1 for p in body if index.holds_number(p)), notes=_joins(t, body)))
    outside = []
    for place in sorted(p for p in filled if p not in held and not index.is_copy(p)):
        cell = index.cells[place]
        outside.append(OutsideItem(where=sheet_locator(sheet.name, *place), text=clip(cell.text),
                                   numeric=has_number(cell.text), region=_context_of(place, tables, ids)))
    return regions, outside


def _joins(table: _SheetTable, body: Sequence[tuple[int, int]]) -> tuple[str, ...]:
    rows = {r for r, _c in body}
    gaps = [r for r in range(table.r0, table.r1 + 1) if r not in rows]
    notes = []
    for k, gap in enumerate(gaps):
        end = (gaps[k + 1] - 1) if k + 1 < len(gaps) else table.r1
        notes.append(f"rows {gap + 1}-{end} joined across empty row {gap}")
    return tuple(notes)


def _context_of(place: tuple[int, int], tables: Sequence[_SheetTable], ids: Sequence[str]) -> str | None:
    """The region whose context window holds this cell: the nearer one; on a tie the one it stands below."""
    row, column = place
    best: tuple[int, int, str] | None = None
    for t, rid in zip(tables, ids, strict=True):
        if not t.c0 <= column <= t.c1:
            continue
        if t.top - CONTEXT_ROWS <= row < t.top:
            rank = (t.top - row, 1, rid)
        elif t.r1 < row <= t.r1 + CONTEXT_ROWS:
            rank = (row - t.r1, 0, rid)
        else:
            continue
        if best is None or rank[:2] < best[:2]:
            best = rank
    return best[2] if best else None


# --- the grid of a region ------------------------------------------------------------------------------------------


def _region(doc: SourceDocument, region_id_: str) -> Region:
    for region in doc.regions:
        if region.id == region_id_:
            return region
    raise KeyError(f"no region {region_id_!r} in {doc.name}")


def region_grid(doc: SourceDocument, region_id: str) -> RegionGrid:
    """The grid of one table region with its context (caption, lines above and below); KeyError for an unknown region,
    ValueError for a region that is not a table (prose, an unruled table, a figure)."""
    region = _region(doc, region_id)
    if region.kind != "table":
        raise ValueError(f"region {region_id} of {doc.name} is {region.kind}, not a table")
    if region.where.startswith("s:"):
        return _sheet_grid(doc, region)
    if region.where.startswith("p:"):
        return _pdf_grid(doc, region)
    return _docx_grid(doc, region)


def _sheet_of(doc: SourceDocument, name: str) -> Sheet:
    for sheet in doc.sheets:
        if sheet.name == name:
            return sheet
    raise KeyError(f"no sheet {name!r} in {doc.name}")


def _grid_cell(sheet: str, cell: SheetCellValue) -> GridCell:
    origin = sheet_locator(sheet, *a1_place(cell.merged_from)) if cell.merged_from else None
    return GridCell(text=cell.text, value=cell.value, type=cell.type, locator=sheet_locator(sheet, cell.row, cell.column),
                    number_format=cell.number_format, merged_from=origin)


def _sheet_grid(doc: SourceDocument, region: Region) -> RegionGrid:
    name, r0, c0, r1, c1 = parse_sheet_range(region.where)
    sheet = _sheet_of(doc, name)
    index = _SheetCells.of(sheet)
    cells = {(c.row - r0 + 1, c.column - c0 + 1): _grid_cell(name, c) for c in sheet.cells
             if r0 <= c.row <= r1 and c0 <= c.column <= c1 and c.text.strip()}
    caption = []
    if region.caption_locator:
        first = a1_place(parse_locator(region.caption_locator).cell)[0]
        for row in range(first, r0):
            places = sorted(p for p in index.cells if p[0] == row and c0 <= p[1] <= c1 and index.cells[p].text.strip())
            origins = sorted({index.origin.get(p, p) for p in places})
            caption += [_grid_cell(name, index.cells[_in_block(o, places, c0, c1)]) for o in origins[:1]]
    above: dict[int, list[GridCell]] = {}
    below: dict[int, list[GridCell]] = {}
    for item in doc.outside:
        if item.region != region.id:
            continue
        locator = parse_locator(item.where)
        row, column = a1_place(locator.cell)
        target = above if row < r0 else below
        target.setdefault(row, []).append(_grid_cell(name, index.cells[(row, column)]))
    return RegionGrid(
        file_sha256=doc.file_sha256, parser=doc.parser, parser_version=doc.parser_version, region_id=region.id,
        n_rows=r1 - r0 + 1, n_cols=c1 - c0 + 1, cells=cells, caption=tuple(caption),
        above=tuple(tuple(above[r]) for r in sorted(above, reverse=True)),
        below=tuple(tuple(below[r]) for r in sorted(below)))


def table_cells(table: PageTable) -> dict[tuple[int, int], tuple[str, str | None]]:
    """Every place of a page table's grid -> (text, the origin's (row, column) as "r,c" for a covered place)."""
    out: dict[tuple[int, int], tuple[str, str | None]] = {}
    for cell in table.cells:
        out[(cell.row, cell.column)] = (cell.text, None)
        for r in range(cell.row, cell.row + cell.row_span):
            for c in range(cell.column, cell.column + cell.col_span):
                if (r, c) != (cell.row, cell.column):
                    out[(r, c)] = (cell.text, f"{cell.row},{cell.column}")
    return out


def _text_cell(text: str, locator: str, merged_from: str | None = None) -> GridCell:
    return GridCell(text=text, value=text, type="number" if is_numeric_text(text) else "text", locator=locator,
                    merged_from=merged_from)


def _line(text: str, locator: str) -> GridCell:
    return GridCell(text=text, value=text, type="text", locator=locator)


def page_of(doc: SourceDocument, number: int) -> Page:
    if 1 <= number <= len(doc.pages) and doc.pages[number - 1].number == number:
        return doc.pages[number - 1]
    raise KeyError(f"no page {number} in {doc.name}")


def span_words(page: Page, first: int, last: int) -> list[Word]:
    """Words first..last (1-based, inclusive) of a page."""
    if not 1 <= first <= last <= len(page.words):
        raise KeyError(f"no words {first}-{last} on page {page.number}")
    return list(page.words[first - 1:last])


def span_line(doc: SourceDocument, locator: str) -> GridCell:
    """A PDF context line (a word span) as one grid cell, its text the words joined by single spaces."""
    span = parse_locator(locator)
    page = page_of(doc, span.page)
    words = span_words(page, span.first_word, span.last_word)
    return _line(" ".join(w.text for w in words), word_span(page.number, words))


def lines_of_words(words: Sequence[Word]) -> list[list[Word]]:
    """Consecutive words cut into the lines they stand on (a word whose top differs from its line's first word by
    more than LINE_TOLERANCE points starts a new line)."""
    out: list[list[Word]] = []
    for word in words:
        if out and abs(word.box[1] - out[-1][0].box[1]) <= LINE_TOLERANCE:
            out[-1].append(word)
        else:
            out.append([word])
    return out


def span_lines(doc: SourceDocument, locator: str) -> tuple[GridCell, ...]:
    """A PDF caption (a word span, wrapped over lines or not) as one grid cell per line."""
    span = parse_locator(locator)
    page = page_of(doc, span.page)
    return tuple(_line(" ".join(w.text for w in line), word_span(page.number, line))
                 for line in lines_of_words(span_words(page, span.first_word, span.last_word)))


def _pdf_grid(doc: SourceDocument, region: Region) -> RegionGrid:
    cells: dict[tuple[int, int], GridCell] = {}
    row0 = 0
    for part in region.parts:
        table = page_of(doc, part.page).tables[part.table - 1]
        fallback = table.box or (0.0, 0.0, 0.0, 0.0)          # an engine's cell with no box: its table's
        boxes = {(c.row, c.column): c.box or fallback for c in table.cells}
        for (r, c), (text, origin) in sorted(table_cells(table).items()):
            if r <= part.header_rows_repeated or not text.strip():
                continue
            if origin is None:
                box = boxes[(r, c)]
            else:
                o_row, o_col = (int(v) for v in origin.split(","))
                box = boxes[(o_row, o_col)]
            locator = format_locator(PdfCell(page=part.page, table=part.table, row=r, column=c, box=box))
            merged = None
            if origin is not None:
                o_row, o_col = (int(v) for v in origin.split(","))
                merged = format_locator(PdfCell(page=part.page, table=part.table, row=o_row, column=o_col,
                                                box=boxes[(o_row, o_col)]))
            cells[(row0 + r - part.header_rows_repeated, c)] = _text_cell(text, locator, merged)
        row0 += table.n_rows - part.header_rows_repeated
    caption = span_lines(doc, region.caption_locator) if region.caption_locator else ()
    first = region.parts[0]
    first_top = page_of(doc, first.page).tables[first.table - 1].box
    above, below = [], []
    for item in doc.outside:
        if item.region != region.id:
            continue
        span = parse_locator(item.where)
        line = span_line(doc, item.where)
        if span.page == first.page and first_top is not None and span.box[3] <= first_top[1] + 1:
            above.append((span.box[1], line))
        else:
            below.append((span.page, span.box[1], line))
    return RegionGrid(
        file_sha256=doc.file_sha256, parser=doc.parser, parser_version=doc.parser_version, region_id=region.id,
        n_rows=region.n_rows, n_cols=region.n_cols, cells=cells, caption=caption,
        above=tuple((g,) for _top, g in sorted(above, key=lambda a: -a[0])),
        below=tuple((g,) for _p, _top, g in sorted(below, key=lambda b: (b[0], b[1]))))


def body_table(doc: SourceDocument, number: int) -> PageTable:
    """The Word body's table `number` (1-based)."""
    tables = [item.table for item in doc.body if item.kind == "table" and item.table is not None]
    if not 1 <= number <= len(tables):
        raise KeyError(f"no table {number} in {doc.name}")
    return tables[number - 1]


def body_paragraph(doc: SourceDocument, number: int) -> str:
    """The text of the Word body's (or a text file's) paragraph `number` (1-based)."""
    for item in doc.body:
        if item.kind == "paragraph" and item.paragraph is not None and item.paragraph.index == number:
            return item.paragraph.text
    raise KeyError(f"no paragraph {number} in {doc.name}")


def _docx_grid(doc: SourceDocument, region: Region) -> RegionGrid:
    match = _DOCX_TABLE.fullmatch(region.where)
    if match is None:
        raise ValueError(f"not a Word table: {region.where!r}")
    number = int(match.group(1))
    table = body_table(doc, number)
    cells = {}
    for (r, c), (text, origin) in table_cells(table).items():
        if not text.strip():
            continue
        merged = None
        if origin is not None:
            o_row, o_col = (int(v) for v in origin.split(","))
            merged = format_locator(DocxCell(table=number, row=o_row, column=o_col))
        cells[(r, c)] = _text_cell(text, format_locator(DocxCell(table=number, row=r, column=c)), merged)

    def paragraph_line(locator: str) -> GridCell:
        span = parse_locator(locator)
        return _line(body_paragraph(doc, span.paragraph)[span.start:span.end], locator)

    caption = (paragraph_line(region.caption_locator),) if region.caption_locator else ()
    caption_at = parse_locator(region.caption_locator).paragraph if region.caption_locator else None
    above, below = [], []
    position = _table_position(doc, number)
    for item in doc.outside:
        if item.region == region.id and item.where.startswith("d:p:"):
            span = parse_locator(item.where)
            (above if span.paragraph < (caption_at or position) else below).append((span.paragraph, paragraph_line(item.where)))
    return RegionGrid(
        file_sha256=doc.file_sha256, parser=doc.parser, parser_version=doc.parser_version, region_id=region.id,
        n_rows=table.n_rows, n_cols=table.n_cols, cells=cells, caption=caption,
        above=tuple((g,) for _n, g in sorted(above, key=lambda a: -a[0])),
        below=tuple((g,) for _n, g in sorted(below, key=lambda b: b[0])))


def _table_position(doc: SourceDocument, number: int) -> int:
    """The number the next paragraph after Word table `number` would have (to tell lines above from lines below)."""
    tables, last_paragraph = 0, 0
    for item in doc.body:
        if item.kind == "paragraph" and item.paragraph is not None:
            last_paragraph = item.paragraph.index
        elif item.kind == "table":
            tables += 1
            if tables == number:
                return last_paragraph + 1
    return last_paragraph + 1


# --- prose -----------------------------------------------------------------------------------------------------------


def paragraphs(doc: SourceDocument, region_id: str) -> list[ProseParagraph]:
    """The paragraphs of a prose region, in order, each with the heading above it (where a study or arm label may
    stand); KeyError for an unknown region, ValueError for a region that is not prose. A PDF paragraph's text is its
    words joined by single spaces (so a character offset in it counts words); a Word paragraph's is its text; a text
    file's paragraph is one line."""
    region = _region(doc, region_id)
    if region.kind != "prose":
        raise ValueError(f"region {region_id} of {doc.name} is {region.kind}, not prose")
    if region.where.startswith("p:"):
        from modeler_intake.source.pdf import region_paragraphs

        return region_paragraphs(doc, region)
    match = _PARAGRAPHS.fullmatch(region.where)
    if match is None:
        raise ValueError(f"not a paragraph range: {region.where!r}")
    first, last = int(match.group(2)), int(match.group(3))
    textual = match.group(1) == "x:l"
    out = []
    heading, heading_at = "", None
    for item in doc.body:
        para = item.paragraph
        if item.kind != "paragraph" or para is None:
            continue
        if para.index > last:
            break
        is_heading = heading_style(para.style) and bool(para.text.strip())
        if para.index >= first and para.text.strip():
            out.append(ProseParagraph(index=para.index, text=para.text, locator=f"{match.group(1)}:{para.index}-{para.index}",
                                      heading="" if is_heading else heading,
                                      heading_locator=None if is_heading else heading_at))
        if is_heading:
            span = (TextSpan(line=para.index, start=0, end=len(para.text)) if textual
                    else DocxSpan(paragraph=para.index, start=0, end=len(para.text)))
            heading, heading_at = para.text, format_locator(span)      # as written: offsets in it are the span's
    return out


def heading_style(style: str) -> bool:
    """A Word paragraph style (or a text file's "markdown" marker) that makes a paragraph a heading."""
    return bool(re.match(r"(?i)(heading|title)\b", style)) or style == "markdown-heading"


# --- today's grid from the same parse --------------------------------------------------------------------------------


def _legacy_value(cell: SheetCellValue) -> object:
    """A cell's value as the legacy grid holds it: a date, time or duration as the datetime, time or timedelta again."""
    if cell.type == "date" and isinstance(cell.value, str):
        for read in (datetime.fromisoformat, time.fromisoformat):
            try:
                return read(cell.value)
            except ValueError:
                continue
        from modeler_intake.source.workbook import parse_duration

        duration = parse_duration(cell.value)
        if duration is not None:
            return duration
    return cell.value


def as_workbook_grid(doc: SourceDocument) -> WorkbookGrid:
    """Today's `grid.WorkbookGrid` from the same parse (a workbook or delimited document): the same values (a date as a
    datetime again) and merged copies, so the legacy readers (`sheet_form.suggest`, `triage`) need no second parse.
    One difference: an .xls cell holding an error is its text ("#DIV/0!"), as an .xlsx one is in both readers, where
    `grid.read_workbook_bytes` leaves the .xls one out. ValueError for a document with no sheets."""
    if doc.format not in ("xlsx", "xlsm", "xls", "csv", "tsv"):
        raise ValueError(f"{doc.name} is {doc.format}: only a workbook or delimited file has sheets")
    sheets: dict[str, SheetGrid] = {}
    for sheet in doc.sheets:
        grid = SheetGrid(name=sheet.name, max_row=sheet.max_row, max_column=sheet.max_column)
        for cell in sheet.cells:
            origin = cell_ref(sheet.name, *a1_place(cell.merged_from)) if cell.merged_from else None
            grid.cells[(cell.row, cell.column)] = Cell(sheet.name, cell.row, cell.column, _legacy_value(cell),
                                                       merged_from=origin)
        sheets[sheet.name] = grid
    return WorkbookGrid(doc.name, doc.file_sha256, sheets)
