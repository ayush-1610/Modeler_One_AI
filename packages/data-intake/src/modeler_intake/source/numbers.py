"""Apple Numbers (`.numbers`, plan 2026-11-26 §7 phase 2): each table of each sheet read as one sheet.

A Numbers document holds sheets, and each sheet one or more tables (a concentration table and its summary side by
side, for instance). Each table becomes a sheet named "<sheet>" when its sheet has one table, else
"<sheet> · <table>". A cell keeps the value Numbers stores: a number in its shortest round-trip form (not the display
format), a text as stored, a date or a duration in ISO 8601, a boolean as TRUE / FALSE. A formula keeps its result.

The reader is numbers-parser (the owner's decision D5, 2026-11-26); it reads from a path, so the bytes go to a
temporary file that is removed at once.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import tempfile
from typing import Any

from modeler_intake.source_model import Sheet, SheetCellValue


def _cell(row: int, column: int, value: Any) -> SheetCellValue | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, bool):
        return SheetCellValue(row=row, column=column, value=value, text="TRUE" if value else "FALSE", type="bool")
    if isinstance(value, int | float):
        number = int(value) if isinstance(value, float) and value.is_integer() and abs(value) < 1e15 else value
        return SheetCellValue(row=row, column=column, value=number, text=repr(number), type="number")
    if isinstance(value, dt.datetime | dt.date):
        return SheetCellValue(row=row, column=column, value=value.isoformat(), text=value.isoformat(), type="date")
    if isinstance(value, dt.timedelta):
        text = str(value)
        return SheetCellValue(row=row, column=column, value=text, text=text, type="text")
    text = str(value)
    if not text.strip():
        return None
    return SheetCellValue(row=row, column=column, value=text, text=text, type="text")


def read_numbers(data: bytes) -> tuple[tuple[Sheet, ...], tuple[str, ...]]:
    """(sheets, warnings) of a Numbers document: one sheet per table. Raises the library's exception for a file it
    cannot read (the caller makes the document `unreadable`)."""
    from numbers_parser import Document

    handle, path = tempfile.mkstemp(suffix=".numbers")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        document = Document(path)
        sheets: list[Sheet] = []
        for sheet in document.sheets:
            tables = list(sheet.tables)
            for table in tables:
                cells: list[SheetCellValue] = []
                for r, row in enumerate(table.rows(values_only=True), start=1):
                    for c, value in enumerate(row, start=1):
                        got = _cell(r, c, value)
                        if got is not None:
                            cells.append(got)
                name = sheet.name if len(tables) == 1 else f"{sheet.name} · {table.name}"
                sheets.append(Sheet(name=name, index=len(sheets) + 1, max_row=table.num_rows, max_column=table.num_cols,
                                    cells=tuple(cells)))
    finally:
        os.unlink(path)
    return tuple(sheets), ()
