"""Writes two filled client-data templates for the formulation lever's edges (final review round 5): `study-only.xlsx`, one
tablet study CL-01 and its mean profile, no product and no dissolution; `plateau.xlsx`, the dissolution of product Tab 10
that plateaus below complete release (read as a table: no Weibull fit can be its release).

Software test data (made-up numbers): it proves the page's path, never a model. Usage: study_only_workbooks.py <out_dir>
"""

import io
import sys
from pathlib import Path

from openpyxl import load_workbook

from modeler_intake.client_template import build_template

out = Path(sys.argv[1])

study = load_workbook(io.BytesIO(build_template()))
header = [c.value.rstrip("*") for c in study["Studies"][1]]
row = {"study_id": "CL-01", "design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": 10, "dose_unit": "mg",
       "formulation": "ir_tablet", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml"}
study["Studies"].append([row.get(h) for h in header])
for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0)):
    study["PK_Summary"].append(["CL-01", None, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"])
study.save(out / "study-only.xlsx")

plateau = load_workbook(io.BytesIO(build_template()))
for t, mean in ((5, 12.0), (10, 25.0), (15, 36.0), (20, 44.0), (30, 52.0), (45, 56.0), (60, 57.0)):
    plateau["Dissolution"].append(["Tab 10", "TEST", 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37, None, t, "min",
                                   *[round(mean + d, 2) for d in (-1.5, -1.2, -0.9, -0.6, -0.3, 0, 0, 0.3, 0.6, 0.9, 1.2, 1.5)]])
plateau.save(out / "plateau.xlsx")
