"""What the table mapper (an LLM) is shown of a table: everything but the numbers of its body (contracts §4.4, §6.2).

Redaction, exactly (`redact_cell`): each maximal run of digits (after NFKC) becomes "#", separators kept, the result cut
at 40 characters: "12.5" -> "#.#", "12,5" -> "#,#", "1.234,5" -> "#.#,#", "<0.5" -> "<#.#", "S01" -> "S#", "2 h" ->
"# h", "BLQ" -> "BLQ". It applies to every body cell, every `distinct_texts` entry, every cell of the header band that
writes a value (`reading.value_like`: a bare number, and also "12.3 (4.5)", "12.3 ng/mL", "12.3*", "0.5 h"; times
across the top are read by code through `time_row`) and every finding message returned to the model. Header words and
the context lines are verbatim: "50 mg" in a title is read by code through a `Cite`, never copied by the model, and a
context line holds only text that belongs to no table region.

The invariant, tested on the band `header_band` actually chooses: no digit of a body cell is in the payload.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from modeler_intake.mapping.fingerprint import header_band
from modeler_intake.mapping.reading import value_like
from modeler_intake.mapping_spec import ColumnProfile, ContextLine, RedactedTable
from modeler_intake.source_model import DocumentRole, Finding, Region, RegionGrid, is_numeric_text

CELL_CHARS = 40
LINE_CHARS = 200
MESSAGE_CHARS = 200                  # a finding message: redacted like a cell, bounded longer (see redact_findings)
DISTINCT = 12
FIRST_BODY_ROWS, LAST_BODY_ROWS = 5, 3


def _digits(text: str) -> str:
    return re.sub(r"\d+", "#", unicodedata.normalize("NFKC", text))


def redact_cell(text: str) -> str:
    """Every maximal run of digits (after NFKC) as "#", separators kept; cut at 40 characters."""
    return _digits(text)[:CELL_CHARS]


def _line(cells) -> str:
    return " | ".join(c.text for c in cells)[:LINE_CHARS]


def redact(grid: RegionGrid, region: Region, *, file_name: str, document_role: DocumentRole) -> RedactedTable:
    """The table as the mapper sees it: its context lines verbatim, its header band (a cell that writes a value
    redacted), the first 5 and last 3 body rows redacted, and a profile of every column over all body rows."""
    band = header_band(grid)
    context = [ContextLine(near="caption", line=i, text=_line((cell,))) for i, cell in enumerate(grid.caption, start=1)]
    context += [ContextLine(near="above", line=i, text=_line(cells)) for i, cells in enumerate(grid.above, start=1)]
    context += [ContextLine(near="below", line=i, text=_line(cells)) for i, cells in enumerate(grid.below, start=1)]
    columns = range(1, grid.n_cols + 1)
    header = tuple(tuple(redact_cell(t) if value_like(t := grid.cell(row, c).text) else t for c in columns)
                   for row in range(1, band + 1))
    body_all = list(range(band + 1, grid.n_rows + 1))
    shown = body_all if len(body_all) <= FIRST_BODY_ROWS + LAST_BODY_ROWS else \
        body_all[:FIRST_BODY_ROWS] + body_all[-LAST_BODY_ROWS:]
    body = tuple(tuple(redact_cell(grid.cell(row, c).text) for c in columns) for row in shown)
    profile = []
    for c in columns:
        numbers = texts = empty = 0
        distinct: list[str] = []
        for row in body_all:
            text = grid.cell(row, c).text.strip()
            if not text:
                empty += 1
            elif is_numeric_text(text):
                numbers += 1
            else:
                texts += 1
                redacted = redact_cell(text)
                if redacted not in distinct and len(distinct) < DISTINCT:
                    distinct.append(redacted)
        profile.append(ColumnProfile(column=c, numbers=numbers, texts=texts, empty=empty, distinct_texts=tuple(distinct)))
    return RedactedTable(region_id=grid.region_id, file_name=file_name, document_role=document_role,
                         kind_by_rule=region.table_kind, n_rows=grid.n_rows, n_cols=grid.n_cols, context=tuple(context),
                         header_rows=band, header=header, body_rows=tuple(shown), body=body, profile=tuple(profile))


def redact_findings(findings: Sequence[Finding]) -> str:
    """"REJECTED: ..." with every finding: its code, where it stands in the spec (`Finding.location`, the spec's own
    indices and field names, which the model wrote) and its message redacted digit by digit, as a cell is (a message
    may quote a cited cell). A message is bounded at 200 characters, not at a cell's 40, so that it still says what to
    fix (a reading of the contract reported by D3: the 40-character cut is a cell's)."""
    lines = [f"- {f.code} at {f.location[:80]}: {_digits(f.message)[:MESSAGE_CHARS]}" for f in findings]
    return "REJECTED: fix these and propose again:\n" + "\n".join(lines)
