"""What code left out of a sheet when it read it, and what it changed, cell by cell (plan 2026-11-05 §3.1 step 4:
"cleaned, with a record ... nothing silently").

A reading (`sheet_form.SheetForm`, applied by `apply.apply_recipe`) takes the cells of its table and leaves the rest. This
module names what it left and why, from the sheet and the cells the reading turned into points: the title and notes
above and below the table, empty rows inside it, columns it did not read, cells that say there is no sample, cells
below the LLOQ (kept as such), text that is not a number, and decimal commas read as points. Each line names its cells,
so a person can open them; nothing here changes what is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from openpyxl.utils import column_index_from_string, get_column_letter

from modeler_intake.grid import SheetGrid, as_text
from modeler_intake.sheet_form import SheetForm

Kind = Literal["ignored", "not_read", "no_sample", "below_lloq", "corrected"]
MAX_CELLS = 12          # the cells named on one line (the count says how many there are)


@dataclass(frozen=True)
class CleaningLine:
    kind: Kind
    text: str
    cells: tuple[str, ...] = ()

    def to_content(self) -> dict[str, object]:
        return {"kind": self.kind, "text": self.text, "cells": list(self.cells)}


def _span(rows: list[int]) -> str:
    """Rows as a person reads them: "row 4", "rows 9–11", "rows 6, 8"."""
    if len(rows) == 1:
        return f"row {rows[0]}"
    if rows == list(range(rows[0], rows[-1] + 1)):
        return f"rows {rows[0]}–{rows[-1]}"
    return "rows " + ", ".join(map(str, rows))


def _quote(text: str, limit: int = 70) -> str:
    text = " ".join(text.split())
    return f"“{text if len(text) <= limit else text[: limit - 1] + '…'}”"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _row_texts(grid: SheetGrid, row: int) -> list[tuple[str, str]]:
    return [(grid.cell(row, c).ref, as_text(grid.cell(row, c).value)) for c in range(1, grid.max_column + 1)
            if as_text(grid.cell(row, c).value) and grid.cell(row, c).merged_from is None]


def _last_row(grid: SheetGrid, form: SheetForm) -> int:
    """The table's last row, as the reading takes it (`apply._rows`): the form's, or the first empty row's before."""
    if form.last_data_row is not None:
        return form.last_data_row
    last = form.first_data_row - 1
    for row in range(form.first_data_row, grid.max_row + 1):
        if grid.row_is_empty(row):
            break
        last = row
    return last


def record(grid: SheetGrid, form: SheetForm, read_cells: set[str], below_lloq_cells: set[str] = frozenset()) -> list[CleaningLine]:
    """What the reading `form` left out of `grid` and what it changed. `read_cells` are the value cells the reading turned
    into points (`SourceRef.cells["value"]`), `below_lloq_cells` those of them read as below the LLOQ."""
    lines: list[CleaningLine] = []
    if not form.value_columns:
        return [CleaningLine("not_read", "Nothing read: code could not tell which columns hold the values.")]
    first, last = form.first_data_row, _last_row(grid, form)
    top = form.header_row if form.header_row else first
    # above the table: the title and notes, read for the study's facts only
    above = [r for r in range(1, top) if _row_texts(grid, r)]
    if above:
        texts = [t for r in above for _ref, t in _row_texts(grid, r)]
        lines.append(CleaningLine("ignored", f"Above the table ({_span(above)}): {_quote(texts[0])}"
                                             f"{f' and {len(texts) - 1} more' if len(texts) > 1 else ''}; read for the "
                                             "study's facts only, not as data.",
                                  tuple(ref for r in above for ref, _t in _row_texts(grid, r))[:MAX_CELLS]))
    # below the table: notes, footnotes, summary rows the reading did not take
    kept_below = {form.mean_row} if form.mean_row else set()
    below = [r for r in range(last + 1, grid.max_row + 1) if r not in kept_below and _row_texts(grid, r)]
    if below:
        texts = [t for r in below for _ref, t in _row_texts(grid, r)]
        lines.append(CleaningLine("ignored", f"Below the table ({_span(below)}): {_quote(texts[0])}"
                                             f"{f' and {len(texts) - 1} more' if len(texts) > 1 else ''}; not data.",
                                  tuple(ref for r in below for ref, _t in _row_texts(grid, r))[:MAX_CELLS]))
    rows = range(first, last + 1)
    empty = [r for r in rows if grid.row_is_empty(r)]
    if empty:
        lines.append(CleaningLine("ignored", f"{_plural(len(empty), 'empty row')} inside the table skipped ({_span(empty)})."))
    # columns of the table the reading did not read
    used = {c for c in (form.time_column, form.subject_column, form.group_column, form.sd_column, form.n_column,
                        form.mean_column, form.mean_sd_column, *form.value_columns) if c}
    used_idx = {column_index_from_string(c) for c in used}
    for column in range(1, grid.max_column + 1):
        if column in used_idx:
            continue
        cells = [grid.cell(r, column) for r in rows if as_text(grid.cell(r, column).value)]
        if not cells:
            continue
        header = as_text(grid.cell(form.header_row, column).value) if form.header_row else ""
        name = f"{get_column_letter(column)}{f' ({_quote(header, 40)})' if header else ''}"
        lines.append(CleaningLine("not_read", f"Column {name} not read: {_plural(len(cells), 'cell')} beside the values.",
                                  tuple(c.ref for c in cells)[:MAX_CELLS]))
    # the value cells, one by one
    missing = {t.strip().upper() for t in form.missing_tokens}
    no_sample: dict[str, list[str]] = {}
    empty_cells: list[str] = []
    not_numbers: list[tuple[str, str]] = []
    commas: list[str] = []
    blq: list[str] = []
    blq_tokens: list[str] = []
    value_rows = [form.mean_row] if form.layout == "times_across" and form.mean_row else []
    for row in [r for r in rows if not grid.row_is_empty(r)] + value_rows:
        for letter in form.value_columns:
            cell = grid.cell(row, letter)
            text = as_text(cell.value)
            if cell.ref in read_cells:
                if cell.ref in below_lloq_cells:
                    blq.append(cell.ref)
                    blq_tokens.append(text)
                elif form.decimal_comma and isinstance(cell.value, str) and "," in text:
                    commas.append(cell.ref)
                continue
            if not text:
                empty_cells.append(cell.ref)
            elif text.upper() in missing:
                no_sample.setdefault(text, []).append(cell.ref)
            else:
                not_numbers.append((cell.ref, text))
    if blq:
        tokens = [_quote(t, 20) for t in dict.fromkeys(blq_tokens) if t][:3]
        written = f" ({', '.join(tokens)})" if tokens else ""
        lines.append(CleaningLine("below_lloq", f"{_plural(len(blq), 'cell')} below the LLOQ{written}: kept as below the "
                                                "LLOQ, not as zero.", tuple(blq)[:MAX_CELLS]))
    for token, refs in sorted(no_sample.items()):
        lines.append(CleaningLine("no_sample", f"{_plural(len(refs), 'cell')} marked {_quote(token)}: no sample.",
                                  tuple(refs)[:MAX_CELLS]))
    if empty_cells:
        lines.append(CleaningLine("no_sample", f"{_plural(len(empty_cells), 'empty value cell')}: no sample.",
                                  tuple(empty_cells)[:MAX_CELLS]))
    if not_numbers:
        shown = ", ".join(_quote(t, 20) for t in dict.fromkeys(t for _r, t in not_numbers))
        lines.append(CleaningLine("ignored", f"{_plural(len(not_numbers), 'value cell')} not read, not numbers: {shown}.",
                                  tuple(r for r, _t in not_numbers)[:MAX_CELLS]))
    if commas:
        lines.append(CleaningLine("corrected", f"{_plural(len(commas), 'number')} written with a decimal comma "
                                               "(12,4) read as 12.4.", tuple(commas)[:MAX_CELLS]))
    return lines
