"""Delimited text files (`.csv`, `.tsv`) read as one sheet named after the file stem (contracts §6.1).

Encoding, by the standard library only: a byte-order mark (UTF-8, UTF-16, UTF-32), else UTF-8, else cp1252 with a
warning; NUL bytes outside a UTF-16/32 file mean binary content (`unreadable`). Delimiter among `,` `;` tab `|`, over
the first 50 non-empty lines: the one whose rows have the most consistent column count; on a tie, the one that leaves
the fewest cells holding another of the four that are not bare numbers, first in the lines holding a digit, then in
all (split on `,`, the `;` line "0,5;12,3" leaves "5;12": a decimal comma cut in two; split on `;`, its cells "0,5"
and "12,3" are bare numbers); then the wider split.
A tie that remains is read with `csv.Sniffer`'s answer, never with `,` while another delimiter ties (cutting at a
decimal comma would change numbers; not cutting changes none), and named in a `DELIMITER_AMBIGUOUS` warning. Every cell
keeps its text as written; a bare number (`is_numeric_text`) is typed "number" with its text as value (a number written
as text: the mapping reads it under the region's decimal convention, §6.2).
"""

from __future__ import annotations

import codecs
import csv
import io
from collections import Counter
from pathlib import PurePath

from modeler_intake.source_model import Sheet, SheetCellValue, is_numeric_text

DELIMITERS = (",", ";", "\t", "|")
SNIFF_LINES = 50
_BOMS = ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"), (codecs.BOM_UTF8, "utf-8-sig"),
         (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))


class NotText(ValueError):
    """The bytes are not text in any encoding read here."""


def decode(data: bytes) -> tuple[str, str, tuple[str, ...]]:
    """(text, encoding, warnings): a BOM's encoding, else UTF-8, else cp1252 (warned); NotText for binary content."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding, ()
            except UnicodeDecodeError as exc:
                raise NotText(f"the file starts with a {encoding} byte-order mark but is not {encoding}: {exc}") from exc
    if b"\x00" in data:
        raise NotText("binary content (NUL bytes) in a text file")
    try:
        return data.decode("utf-8"), "utf-8", ()
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise NotText(f"neither UTF-8 nor cp1252 text: {exc}") from exc
    return text, "cp1252", ("ENCODING_GUESSED: not UTF-8; read as cp1252 (Windows Western European)",)


def lines_of(text: str) -> list[str]:
    """The text's lines (\\r\\n, \\r or \\n), the empty piece after a final line break dropped."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _score(sample: str, delimiter: str) -> tuple[int, int, int, int]:
    """(lines with the modal column count, minus the cells holding another delimiter that are not bare numbers in the
    lines holding a digit, the same over every line, that count) when the count is above 1; (0, 0, 0, 1) when the
    delimiter never splits a line. A digit makes a line data whatever the split (a header such as "Zeit, h" holds a
    comma with no number to cut)."""
    rows = [row for row in csv.reader(io.StringIO(sample), delimiter=delimiter) if any(c.strip() for c in row)]
    if not rows:
        return 0, 0, 0, 1
    width, lines = Counter(len(row) for row in rows).most_common(1)[0]
    if width < 2:
        return 0, 0, 0, 1
    others = [d for d in DELIMITERS if d != delimiter]

    def mixed(row: list[str]) -> int:
        return sum(1 for cell in row if any(d in cell for d in others) and not is_numeric_text(cell))

    in_data = sum(mixed(row) for row in rows if any(ch.isdigit() for cell in row for ch in cell))
    return lines, -in_data, -sum(mixed(row) for row in rows), width


def sniff_delimiter(text: str) -> tuple[str, tuple[str, ...]]:
    """(the delimiter of a delimited text, warnings): see the module docstring."""
    sample = "\n".join([line for line in lines_of(text) if line.strip()][:SNIFF_LINES])
    scores = {d: _score(sample, d) for d in DELIMITERS}
    best = max(scores.values())
    tied = [d for d in DELIMITERS if scores[d] == best]
    if len(tied) == 1 or best[0] == 0:
        return tied[0], ()
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters="".join(DELIMITERS)).delimiter
    except csv.Error:
        sniffed = None
    allowed = [d for d in tied if d != ","]
    chosen = sniffed if sniffed in allowed else allowed[0]
    named = " and ".join(repr(d) for d in tied)
    return chosen, (f"DELIMITER_AMBIGUOUS: {named} split the lines equally well; read with {chosen!r}",)


def read_delimited(data: bytes, filename: str) -> tuple[Sheet, str, str, tuple[str, ...]]:
    """(the one sheet, encoding, delimiter, warnings); NotText for binary content."""
    text, encoding, warnings = decode(data)
    delimiter, ambiguous = sniff_delimiter(text)
    warnings += ambiguous
    name = sheet_name(filename)
    cells = []
    max_row = max_column = 0
    for r, row in enumerate(csv.reader(io.StringIO("\n".join(lines_of(text))), delimiter=delimiter), start=1):
        max_row = r
        max_column = max(max_column, len(row))
        for c, raw in enumerate(row, start=1):
            if raw == "":
                continue
            cells.append(SheetCellValue(row=r, column=c, value=raw, text=raw,
                                        type="number" if is_numeric_text(raw) else "text"))
    return Sheet(name=name, index=1, max_row=max_row, max_column=max_column, cells=tuple(cells)), encoding, delimiter, warnings


def sheet_name(filename: str) -> str:
    """The sheet of a delimited file is named after its stem (a control character, which no locator can hold, is
    written "_"; an empty stem is "Sheet1")."""
    stem = PurePath(filename.replace("\\", "/")).stem
    clean = "".join("_" if ord(ch) < 32 or ord(ch) == 127 else ch for ch in stem)
    return clean or "Sheet1"
