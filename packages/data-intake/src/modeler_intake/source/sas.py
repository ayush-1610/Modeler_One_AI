"""SAS datasets (plan 2026-11-26 §7 phase 2): a CRO's `.sas7bdat` or SAS transport (`.xpt`) file read as one sheet.

CROs deliver clinical data as SAS datasets, often in CDISC form (SDTM/ADaM domains such as PC, PP, EX, ADSL). Each
dataset becomes a sheet named after the dataset: line 1 the variable names (USUBJID, PCSTRESN …), line 2 their labels
when the file has any ("Numeric Result/Finding in Standard Units" …), then one line per observation. Every value is
kept as the file stores it: a number in its shortest round-trip form, a text as stored, a SAS date or datetime in ISO
8601. A missing value leaves its cell empty (sheets are sparse).

The reader is pyreadstat (the owner's decision D5, 2026-11-26); it reads from a path, so the bytes go to a temporary
file that is removed at once.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import tempfile
from pathlib import PurePosixPath
from typing import Any

from modeler_intake.source_model import Sheet, SheetCellValue

SUFFIXES = (".sas7bdat", ".xpt")


def _cell(row: int, column: int, value: Any) -> SheetCellValue | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, bool):
        return SheetCellValue(row=row, column=column, value=value, text="TRUE" if value else "FALSE", type="bool")
    if isinstance(value, int | float):
        number = int(value) if isinstance(value, float) and value.is_integer() and abs(value) < 1e15 else value
        return SheetCellValue(row=row, column=column, value=number, text=repr(number), type="number")
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return SheetCellValue(row=row, column=column, value=value.isoformat(), text=value.isoformat(), type="date")
    text = str(value)
    if not text.strip():
        return None
    return SheetCellValue(row=row, column=column, value=text, text=text, type="text")


def read_sas(data: bytes, filename: str) -> tuple[tuple[Sheet, ...], tuple[str, ...]]:
    """(sheets, warnings) of a SAS dataset: one sheet. Raises the library's exception for a file it cannot read (the
    caller makes the document `unreadable`)."""
    import pyreadstat

    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    reader = pyreadstat.read_xport if suffix == ".xpt" else pyreadstat.read_sas7bdat
    handle, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        frame, meta = reader(path, output_format="dict")
    finally:
        os.unlink(path)
    names = list(meta.column_names or frame.keys())
    labels = list(meta.column_labels or [])
    has_labels = any(label and str(label).strip() and str(label).strip() != name for name, label in zip(names, labels, strict=False))
    cells: list[SheetCellValue] = []
    for c, name in enumerate(names, start=1):
        cells.append(SheetCellValue(row=1, column=c, value=name, text=name, type="text"))
        if has_labels and c <= len(labels) and labels[c - 1]:
            label = str(labels[c - 1])
            cells.append(SheetCellValue(row=2, column=c, value=label, text=label, type="text"))
    first = 3 if has_labels else 2
    n_rows = int(meta.number_rows or (len(frame[names[0]]) if names else 0))
    for c, name in enumerate(names, start=1):
        for i, value in enumerate(frame.get(name, ())):
            got = _cell(first + i, c, value)
            if got is not None:
                cells.append(got)
    cells.sort(key=lambda x: (x.row, x.column))
    sheet_name = str(meta.table_name or "").strip() or PurePosixPath(filename.replace("\\", "/")).stem
    warnings = (f"SAS_LABELS: line 2 holds the variables' labels; data start on line {first}",) if has_labels else ()
    return (Sheet(name=sheet_name, index=1, max_row=first - 1 + n_rows, max_column=len(names), cells=tuple(cells)),), warnings
