"""Spreadsheets as grids of cells that keep their sheet!A1 reference.

Merged cells: every cell in a merged range carries the top-left value and remembers where it came from,
so a header like "Concentration (ng/mL)" spanning three columns applies to all three.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

CellValue = str | float | int | bool | datetime | date | None


def cell_ref(sheet: str, row: int, column: int) -> str:
    return f"{sheet}!{get_column_letter(column)}{row}"


@dataclass(frozen=True)
class Cell:
    sheet: str
    row: int
    column: int
    value: CellValue
    merged_from: str | None = None

    @property
    def ref(self) -> str:
        return cell_ref(self.sheet, self.row, self.column)


@dataclass
class SheetGrid:
    name: str
    max_row: int
    max_column: int
    cells: dict[tuple[int, int], Cell] = field(default_factory=dict)

    def cell(self, row: int, column: int | str) -> Cell:
        col = column_index_from_string(column) if isinstance(column, str) else column
        return self.cells.get((row, col)) or Cell(self.name, row, col, None)

    def row_is_empty(self, row: int) -> bool:
        return all(self.cell(row, c).value in (None, "") for c in range(1, self.max_column + 1))

    def preview(self, max_rows: int = 40, max_columns: int = 20) -> str:
        """Compact text view with row numbers and column letters, used when asking AI to propose a mapping."""
        columns = range(1, min(self.max_column, max_columns) + 1)
        lines = ["row\t" + "\t".join(get_column_letter(c) for c in columns)]
        for row in range(1, min(self.max_row, max_rows) + 1):
            values = ["" if self.cell(row, c).value is None else str(self.cell(row, c).value) for c in columns]
            lines.append(f"{row}\t" + "\t".join(values))
        return "\n".join(lines)


@dataclass
class WorkbookGrid:
    file_name: str
    sha256: str
    sheets: dict[str, SheetGrid]

    def sheet(self, name: str) -> SheetGrid:
        if name not in self.sheets:
            raise KeyError(f"sheet {name!r} not found; available: {', '.join(self.sheets)}")
        return self.sheets[name]

    def header_fingerprint(self, sheet: str, header_rows: int) -> str:
        """Fingerprint of a sheet's header region (text cells only), used to recognise a known file layout."""
        grid = self.sheet(sheet)
        parts = [sheet]
        for row in range(1, header_rows + 1):
            for column in range(1, grid.max_column + 1):
                value = grid.cell(row, column).value
                if isinstance(value, str) and value.strip():
                    parts.append(f"{row}:{column}:{value.strip().lower()}")
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _load_xlsx(path: Path, sha256: str) -> WorkbookGrid:
    workbook = load_workbook(path, data_only=True)
    sheets: dict[str, SheetGrid] = {}
    for ws in workbook.worksheets:
        grid = SheetGrid(name=ws.title, max_row=ws.max_row, max_column=ws.max_column)
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None:
                    grid.cells[(c.row, c.column)] = Cell(ws.title, c.row, c.column, c.value)
        for merged in ws.merged_cells.ranges:
            origin = grid.cells.get((merged.min_row, merged.min_col))
            if origin is None:
                continue
            for r in range(merged.min_row, merged.max_row + 1):
                for col in range(merged.min_col, merged.max_col + 1):
                    if (r, col) != (merged.min_row, merged.min_col):
                        grid.cells[(r, col)] = Cell(ws.title, r, col, origin.value, merged_from=origin.ref)
        sheets[ws.title] = grid
    return WorkbookGrid(getattr(path, "name", "workbook.xlsx"), sha256, sheets)


def _xls_value(book, cell) -> Any:
    """A legacy .xls cell's value as openpyxl would give it: a number, text, a bool, a datetime; None when empty."""
    import xlrd

    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return None
    if cell.ctype == xlrd.XL_CELL_DATE:
        return xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
        return int(cell.value)
    return cell.value


def _load_xls(data: bytes, name: str, sha256: str) -> WorkbookGrid:
    """A legacy Excel 97–2003 workbook (`xlrd`, owner-approved 2026-10-09) as the same grid as an .xlsx: cell values,
    their sheet!A1 references, and merged ranges carried to every cell they cover."""
    import xlrd
    from xlrd.compdoc import CompDocError

    try:
        book = xlrd.open_workbook(file_contents=data, formatting_info=True)
    except (xlrd.XLRDError, CompDocError) as exc:  # not a workbook, or a damaged compound file
        raise ValueError(f"the .xls workbook could not be read: {exc}") from exc
    sheets: dict[str, SheetGrid] = {}
    for ws in book.sheets():
        grid = SheetGrid(name=ws.name, max_row=ws.nrows, max_column=ws.ncols)
        for r in range(ws.nrows):
            for c in range(ws.ncols):
                value = _xls_value(book, ws.cell(r, c))
                if value is not None:
                    grid.cells[(r + 1, c + 1)] = Cell(ws.name, r + 1, c + 1, value)
        for r_lo, r_hi, c_lo, c_hi in ws.merged_cells:   # half-open, 0-based
            origin = grid.cells.get((r_lo + 1, c_lo + 1))
            if origin is None:
                continue
            for r in range(r_lo + 1, r_hi + 1):
                for c in range(c_lo + 1, c_hi + 1):
                    if (r, c) != (r_lo + 1, c_lo + 1):
                        grid.cells[(r, c)] = Cell(ws.name, r, c, origin.value, merged_from=origin.ref)
        sheets[ws.name] = grid
    return WorkbookGrid(name, sha256, sheets)


def _load_csv(path: Path, sha256: str) -> WorkbookGrid:
    name = path.stem
    grid = SheetGrid(name=name, max_row=0, max_column=0)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for r, row in enumerate(csv.reader(handle), start=1):
            grid.max_row = r
            grid.max_column = max(grid.max_column, len(row))
            for c, value in enumerate(row, start=1):
                if value != "":
                    grid.cells[(r, c)] = Cell(name, r, c, value)
    return WorkbookGrid(path.name, sha256, {name: grid})


def read_workbook_bytes(data: bytes, filename: str) -> WorkbookGrid:
    """The same grid from bytes held in memory (an upload): no temporary file."""
    import io

    sha256 = hashlib.sha256(data).hexdigest()
    suffix = Path(filename).suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        grid = _load_xlsx(io.BytesIO(data), sha256)  # type: ignore[arg-type]
        return WorkbookGrid(Path(filename).name, sha256, grid.sheets)
    if suffix == ".xls":
        return _load_xls(data, Path(filename).name, sha256)
    if suffix == ".csv":
        name = Path(filename).stem
        sheet = SheetGrid(name=name, max_row=0, max_column=0)
        for r, row in enumerate(csv.reader(io.StringIO(data.decode("utf-8-sig"))), start=1):
            sheet.max_row = r
            sheet.max_column = max(sheet.max_column, len(row))
            for c, value in enumerate(row, start=1):
                if value != "":
                    sheet.cells[(r, c)] = Cell(name, r, c, value)
        return WorkbookGrid(Path(filename).name, sha256, {name: sheet})
    raise ValueError(f"unsupported spreadsheet type {suffix!r}: use .xlsx, .xlsm, .xls or .csv")


def read_workbook(path: Path, sha256: str) -> WorkbookGrid:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return _load_xlsx(path, sha256)
    if suffix == ".xls":
        return _load_xls(path.read_bytes(), path.name, sha256)
    if suffix == ".csv":
        return _load_csv(path, sha256)
    raise ValueError(f"unsupported spreadsheet type {suffix!r}: use .xlsx, .xlsm, .xls or .csv")


def as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()
