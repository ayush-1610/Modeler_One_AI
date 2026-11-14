"""Workbooks read once, cells kept as they are stored (contracts §4.2, §6.1): `.xlsx`/`.xlsm` with openpyxl
(`data_only=True`), `.xls` with xlrd.

Every non-empty cell keeps its value, its text (a number's shortest round-trip form, never its display: 12.4037 under
"0.00" is "12.4037", 0.042 under "0.0%" is "0.042"), its type and its number format ("" for General), so a "55%" cell is
read as 0.55 with its format and the mapping decides. A date, a time of day or a duration (a cell openpyxl reads as a
timedelta, under a format such as "[h]:mm") is typed "date" with its ISO 8601 text ("2024-03-05T00:00:00", "12:30:00",
"P1DT2H"), never a bare number a mapping could take for hours. A merged range's covered cells are copies of the origin (value,
text, type and format) with `merged_from` = the origin's A1, as `grid.py` copies them. Hidden sheets are read and
flagged. A formula with no cached value (a workbook never opened in Excel after a script wrote it) has no value to
read: finding `FORMULA_NO_VALUE`, listed in the document's warnings, and the document is `partly_read`, its reason
naming the cells. A cell holding an error ("#DIV/0!") is a text cell with that text in both formats, named in the
warnings (`CELL_ERROR`).

`grid.read_workbook_bytes` is not used: it drops number formats and hidden state. A test proves both give the same
values and merge copies for the same bytes.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime, time, timedelta
from xml.etree import ElementTree

from modeler_intake.source.regions import a1, sheet_locator
from modeler_intake.source_model import CellType, Sheet, SheetCellValue, number_text

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def typed(value: object) -> tuple[float | int | str | bool | None, str, CellType]:
    """(value, text, type) of a cell value as a library gives it (§4.2's text rules)."""
    if isinstance(value, bool):
        return value, "TRUE" if value else "FALSE", "bool"
    if isinstance(value, int | float):
        return value, number_text(value), "number"
    if isinstance(value, datetime | date | time):
        text = value.isoformat()
        return text, text, "date"
    if isinstance(value, timedelta):
        text = iso_duration(value)
        return text, text, "date"
    text = str(value)
    return text, text, "text"


_DURATION = re.compile(r"(-)?P(?:([0-9]+)D)?(?:T(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+(?:\.[0-9]+)?)S)?)?")


def iso_duration(value: timedelta) -> str:
    """A duration in ISO 8601 ("P1DT2H", "PT30M", "PT0S", "-PT1H30M"); `parse_duration` reads it back exactly."""
    if value < timedelta(0):
        return "-" + iso_duration(-value)
    hours, rest = divmod(value.seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    second = f"{seconds}.{value.microseconds:06d}".rstrip("0") if value.microseconds else str(seconds)
    day = f"{value.days}D" if value.days else ""
    clock = (f"{hours}H" if hours else "") + (f"{minutes}M" if minutes else "") + \
        (f"{second}S" if seconds or value.microseconds else "")
    return "P" + day + ("T" + clock if clock else "") if day or clock else "PT0S"


def parse_duration(text: str) -> timedelta | None:
    """The timedelta of an `iso_duration` text; None for any other text."""
    match = _DURATION.fullmatch(text)
    if match is None or text in ("P", "-P") or text.endswith("T"):
        return None
    sign, days, hours, minutes, seconds = match.groups()
    found = timedelta(days=int(days or 0), hours=int(hours or 0), minutes=int(minutes or 0),
                      seconds=float(seconds or 0))
    return -found if sign else found


def _copies(cells: dict[tuple[int, int], SheetCellValue], merges: list[tuple[int, int, int, int]]) -> None:
    """Every covered cell of a merged range (r0, c0, r1, c1) becomes a copy of its origin, as grid.py does."""
    for r0, c0, r1, c1 in merges:
        origin = cells.get((r0, c0))
        if origin is None:
            continue
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if (r, c) != (r0, c0):
                    cells[(r, c)] = SheetCellValue(row=r, column=c, value=origin.value, text=origin.text, type=origin.type,
                                                   number_format=origin.number_format, merged_from=a1(r0, c0))


def read_xlsx(data: bytes) -> tuple[tuple[Sheet, ...], tuple[str, ...], tuple[str, ...]]:
    """(sheets, warnings, unread) of an .xlsx/.xlsm: the warnings name hidden sheets, cells holding an error and
    formulas with no cached value; `unread` holds the locators of the latter (the document is `partly_read`). Raises
    the library's exception for a file it cannot open (the caller makes it `unreadable`)."""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), data_only=True)
    missing = _formulas_without_value(data)
    sheets, warnings, unread = [], [], []
    for number, ws in enumerate(workbook.worksheets, start=1):
        cells: dict[tuple[int, int], SheetCellValue] = {}
        stored = getattr(ws, "_cells", None)
        found = stored.values() if isinstance(stored, dict) else (c for row in ws.iter_rows() for c in row)
        for cell in found:
            raw = cell.value
            if raw is None or raw == "":
                continue
            value, text, kind = typed(raw)
            if cell.data_type == "e":
                warnings.append(f"CELL_ERROR {_where(ws.title, a1(cell.row, cell.column))}: the cell holds the error {text}")
            number_format = cell.number_format if cell.number_format and cell.number_format != "General" else ""
            cells[(cell.row, cell.column)] = SheetCellValue(row=cell.row, column=cell.column, value=value, text=text,
                                                            type=kind, number_format=number_format)
        _copies(cells, [(m.min_row, m.min_col, m.max_row, m.max_col) for m in ws.merged_cells.ranges])
        hidden = ws.sheet_state != "visible"
        sheets.append(Sheet(name=ws.title, index=number, max_row=ws.max_row, max_column=ws.max_column, hidden=hidden,
                            cells=tuple(cells[k] for k in sorted(cells))))
        if hidden:
            warnings.append(f"HIDDEN_SHEET {_where(ws.title)}: the sheet is hidden ({ws.sheet_state}); it is read like any other")
        for ref in missing.get(ws.title, ()):
            warnings.append(f"FORMULA_NO_VALUE {_where(ws.title, ref)}: a formula with no cached value; nothing to read")
            unread.append(_where(ws.title, ref))
    return tuple(sheets), tuple(warnings), tuple(unread)


def unread_reason(unread: tuple[str, ...], limit: int = 5) -> str:
    """The reason of a workbook `partly_read` for its formulas with no cached value (all are in the warnings)."""
    named = ", ".join(unread[:limit])
    more = f" and {len(unread) - limit} more (see the warnings)" if len(unread) > limit else ""
    return (f"formula{'s' if len(unread) > 1 else ''} with no cached value, nothing to read "
            f"(the workbook was not recalculated and saved in Excel): {named}{more}")


def _where(sheet: str, ref: str | None = None) -> str:
    try:
        if ref is None:
            return sheet_locator(sheet, 1, 1).rsplit("!", 1)[0]
        match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", ref)
        return sheet_locator(sheet, int(match.group(2)), _column(match.group(1))) if match else f"{sheet}!{ref}"
    except Exception:  # noqa: BLE001 - a sheet name no locator can hold is named as it is
        return f"{sheet}!{ref or ''}"


def _column(letters: str) -> int:
    number = 0
    for ch in letters:
        number = number * 26 + ord(ch) - 64
    return number


def _formulas_without_value(data: bytes) -> dict[str, list[str]]:
    """Sheet name -> the cells holding a formula with no cached value, read from the sheet XML (openpyxl's
    `data_only=True` gives them as empty). A part that cannot be read is skipped: this only adds findings."""
    out: dict[str, list[str]] = {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        names = set(archive.namelist())
        book = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError, ValueError):
        return out
    targets = {r.get("Id"): r.get("Target", "") for r in rels.iter(f"{_PKG_REL}Relationship")}
    for sheet in book.iter(f"{_MAIN}sheet"):
        target = targets.get(sheet.get(f"{_REL}id"), "")
        part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        if part not in names:
            continue
        xml = archive.read(part)
        if b"<f" not in xml and b":f" not in xml:
            continue
        try:
            for _event, element in ElementTree.iterparse(io.BytesIO(xml)):
                if element.tag != f"{_MAIN}c":
                    continue
                formula = element.find(f"{_MAIN}f")
                cached = element.find(f"{_MAIN}v")
                inline = element.find(f"{_MAIN}is")
                if formula is not None and (cached is None or not (cached.text or "").strip()) and inline is None:
                    out.setdefault(sheet.get("name", ""), []).append(element.get("r", ""))
                element.clear()
        except ElementTree.ParseError:
            continue
    return out


def read_xls(data: bytes) -> tuple[tuple[Sheet, ...], tuple[str, ...], tuple[str, ...]]:
    """(sheets, warnings, unread) of a legacy .xls (xlrd, owner-approved 2026-10-09, as grid.py reads them: a whole
    number as an int, a date as a date) with each cell's number format. A cell holding an error is a text cell with
    the error's text ("#DIV/0!"), as openpyxl gives an .xlsx one, and is named in the warnings; xlrd gives every
    formula's cached value, so `unread` is empty."""
    import xlrd

    book = xlrd.open_workbook(file_contents=data, formatting_info=True)
    sheets, warnings = [], []
    for number, ws in enumerate(book.sheets(), start=1):
        cells: dict[tuple[int, int], SheetCellValue] = {}
        for r in range(ws.nrows):
            for c in range(ws.ncols):
                cell = ws.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_ERROR:
                    text = xlrd.error_text_from_code.get(cell.value, "#ERROR")
                    warnings.append(f"CELL_ERROR {_where(ws.name, a1(r + 1, c + 1))}: the cell holds the error {text}")
                    cells[(r + 1, c + 1)] = SheetCellValue(row=r + 1, column=c + 1, value=text, text=text, type="text",
                                                           number_format=_xls_format(book, cell))
                    continue
                if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    continue
                if cell.ctype == xlrd.XL_CELL_DATE:
                    raw: object = xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    raw = bool(cell.value)
                elif cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
                    raw = int(cell.value)
                else:
                    raw = cell.value
                if raw == "":
                    continue
                value, text, kind = typed(raw)
                cells[(r + 1, c + 1)] = SheetCellValue(row=r + 1, column=c + 1, value=value, text=text, type=kind,
                                                       number_format=_xls_format(book, cell))
        _copies(cells, [(r0 + 1, c0 + 1, r1, c1) for r0, r1, c0, c1 in ws.merged_cells])
        hidden = ws.visibility != 0
        sheets.append(Sheet(name=ws.name, index=number, max_row=ws.nrows, max_column=ws.ncols, hidden=hidden,
                            cells=tuple(cells[k] for k in sorted(cells))))
        if hidden:
            warnings.append(f"HIDDEN_SHEET {_where(ws.name)}: the sheet is hidden; it is read like any other")
    return tuple(sheets), tuple(warnings), ()


def _xls_format(book, cell) -> str:
    try:
        found = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""
    return "" if found in ("", "General") else found
