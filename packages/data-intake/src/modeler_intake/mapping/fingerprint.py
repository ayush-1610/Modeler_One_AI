"""The layout fingerprint a cached mapping is looked up by, and the header band the mapper is shown (contracts §6.2).

The fingerprint is the layout's, not the file's: the header band's words (digit runs as "#") at their positions relative
to the region, the column count and the shapes of the first column's labels. It does not depend on the sheet name, on
where the table sits, on the subject numbers, on the sampling times or on the context lines, so the same layout in
another sheet, file or delivery finds its cached spec (which `validate_spec` then re-reads on the new region: a title
that states another study or dose is read as such).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from modeler_intake.mapping.reading import value_like
from modeler_intake.source_model import RegionGrid

MAX_HEADER_ROWS = 4


def header_band(grid: RegionGrid) -> int:
    """The rows above the first row with two or more cells that write a value; at most 4; when no row has two, the
    first row only (a text-heavy product or design table never sends its body as "header").

    A cell writes a value (`reading.value_like`) when it is a bare number or a BLQ-like token, as §6.2 says, and also
    when it is a value written with its spread, interval, mark or unit ("12.3 (4.5)", "12.3 ± 4.5", "0.95 (0.88-1.03)",
    "12.3*", "12.3 ng/mL", "2 h"): a row of such cells is body, so its digits never reach the mapper as "header", and a
    marked value in the first body row does not move the band (reported to the integrator as a reading of §6.2). A
    header row of times or doses written with their unit ("0.5 h", "10 mg") ends the band too, as a header row of bare
    times does: the mapper sees it with its digits as "#", and code reads it through its cites."""
    for row in range(1, grid.n_rows + 1):
        cells = [c for (r, _c), c in grid.cells.items() if r == row and c.merged_from is None]
        if sum(value_like(c.text) for c in cells) >= 2:
            return min(row - 1, MAX_HEADER_ROWS)
    return min(1, grid.n_rows)


def norm(text: str) -> str:
    """NFKC, casefold, whitespace collapsed, every digit run "#"."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", folded).strip())


def layout_fingerprint(grid: RegionGrid) -> str:
    """sha256 of "\\x1f".join(["cols=<n_cols>", "<r>:<c>:<norm(text)>" for the header band's non-empty cells (relative r
    and c), "labels=" + the sorted set of norm(first-column text of each body row that writes no value, as
    `header_band` reads a value: "0.5 h" is a time, not a label), comma-joined])."""
    band = header_band(grid)
    parts = [f"cols={grid.n_cols}"]
    for (row, column), cell in sorted(grid.cells.items()):
        if row <= band and cell.text.strip():
            parts.append(f"{row}:{column}:{norm(cell.text)}")
    labels = sorted({norm(cell.text) for (row, column), cell in grid.cells.items()
                     if row > band and column == 1 and cell.text.strip() and not value_like(cell.text)})
    parts.append("labels=" + ",".join(labels))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
