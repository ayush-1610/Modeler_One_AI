"""Write sheets of the reading evaluation set (modeler_intake.reading_eval) as the .xlsx files a client would send:
software test data for the browser flows, never observed data.

    uv run python reading_eval_workbook.py <out dir> <case name> [<case name> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

from modeler_intake.reading_eval import CASES, workbook_bytes

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name in sys.argv[2:]:
    case = next(c for c in CASES if c.name == name)
    (out / case.file).write_bytes(workbook_bytes(case))
