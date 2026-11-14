"""Plain text, Markdown and JSON read as lines (contracts §6.1: "lines as paragraphs").

Each line is a paragraph numbered from 1 (its locator `x:l:<n>/ch:<start>-<end>`, a range `x:l:<a>-<b>`). Blocks of
non-empty lines are separated by empty lines; consecutive blocks form a `prose` region, a Markdown heading (`#`) starts a
new one, and a block of at least two lines whose share of tokens holding a number reaches `TABLE_LIKE_NUMERIC_SHARE`
is a `table_like_text` region (a table written as text: located, not gridded). A token is a run of characters between
spaces and the pipes of a Markdown table, with a letter or a digit in it (a rule such as "|---|" is none). The encoding
is found as for a delimited file.
"""

from __future__ import annotations

import re

from modeler_intake.source.delimited import decode, lines_of
from modeler_intake.source.regions import region_id
from modeler_intake.source_model import BodyItem, Paragraph, Region, has_number

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_TOKEN_SPLIT = re.compile(r"[\s|]+")


def tokens(line: str) -> list[str]:
    """The tokens of a line: runs between spaces and Markdown pipes that hold a letter or a digit."""
    return [t for t in _TOKEN_SPLIT.split(line) if any(ch.isalnum() for ch in t)]


def numeric_share(tokens: list[str]) -> float:
    return sum(1 for t in tokens if has_number(t)) / len(tokens) if tokens else 0.0


def read_text(data: bytes, file_sha256: str, *, table_like_share: float) -> dict[str, object]:
    """The document fields of a text file: its lines as paragraphs, its regions, its encoding. NotText (from
    `decode`) for binary content."""
    text, encoding, warnings = decode(data)
    lines = lines_of(text)
    body = tuple(BodyItem(kind="paragraph", paragraph=Paragraph(index=n, text=line,
                                                                style="markdown-heading" if _HEADING.match(line) else ""))
                 for n, line in enumerate(lines, start=1))
    blocks: list[list[int]] = []
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if blocks and blocks[-1][-1] == n - 1 and not _HEADING.match(line):
            blocks[-1].append(n)
        else:
            blocks.append([n])
    regions: list[Region] = []
    run: list[int] = []

    def close() -> None:
        if run:
            where = f"x:l:{run[0]}-{run[-1]}"
            found = [t for n in run for t in tokens(lines[n - 1])]
            regions.append(Region(id=region_id(where, file_sha256), kind="prose", where=where, n_rows=len(run),
                                  numeric_cells=sum(1 for t in found if has_number(t))))
            run.clear()

    for block in blocks:
        found = [t for n in block for t in tokens(lines[n - 1])]
        if len(block) >= 2 and numeric_share(found) >= table_like_share:
            close()
            where = f"x:l:{block[0]}-{block[-1]}"
            regions.append(Region(id=region_id(where, file_sha256), kind="table_like_text", where=where, n_rows=len(block),
                                  numeric_cells=sum(1 for t in found if has_number(t))))
            continue
        if _HEADING.match(lines[block[0] - 1]):
            close()
        run.extend(block)
    close()
    return {"state": "read", "encoding": encoding, "body": body, "regions": tuple(regions), "warnings": warnings}
