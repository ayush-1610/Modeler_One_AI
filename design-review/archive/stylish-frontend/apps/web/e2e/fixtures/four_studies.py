"""A filled client-data template with four studies, each with a mean profile (software test data), for the one-by-one
review of a delivery with many studies (build C, plan 2026-11-05 §3.2).

    uv run python four_studies.py <dir>
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from openpyxl import load_workbook

from modeler_intake.client_template import build_template

book = load_workbook(io.BytesIO(build_template()))
header = [c.value.rstrip("*") for c in book["Studies"][1]]
for k, (study, dose) in enumerate((("CL-1", 10), ("CL-2", 20), ("CL-3", 40), ("CL-4", 80)), start=1):
    row = {"study_id": study, "design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": dose,
           "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted"}
    book["Studies"].append([row.get(h) for h in header])
    for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0), (8, 3.1)):
        book["PK_Summary"].append([study, None, t, "h", "arithmetic_mean", round(v * k, 2), None, None, 12, "ng/ml"])
out = Path(sys.argv[1]) / "four-studies.xlsx"
book.save(out)
print(out)
