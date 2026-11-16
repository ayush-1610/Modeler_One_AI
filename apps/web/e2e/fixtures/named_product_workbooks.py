"""Writes a filled client-data template for a study that names its product in its own file (final review round 6, round 5's
skeptic's probe B): `named.xlsx`, one tablet study CL-02 whose Studies row names product Test 10 mg (role TEST) with its
mean profile, and the dissolution of Brand 10 mg only (the reference product, a curve with a Weibull fit). No dissolution
of Test 10 mg is given.

Software test data (made-up numbers): it proves the page's path, never a model. Usage: named_product_workbooks.py <out_dir>
"""

import io
import math
import sys
from pathlib import Path

from openpyxl import load_workbook

from modeler_intake.client_template import build_template

out = Path(sys.argv[1])
wb = load_workbook(io.BytesIO(build_template()))
header = [c.value.rstrip("*") for c in wb["Studies"][1]]
row = {"study_id": "CL-02", "design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": 10, "dose_unit": "mg",
       "formulation": "ir_tablet", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml", "product": "Test 10 mg",
       "product_role": "TEST"}
wb["Studies"].append([row.get(h) for h in header])
for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0)):
    wb["PK_Summary"].append(["CL-02", None, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"])
for t in (5, 10, 15, 20, 30, 45, 60):
    fraction = 1 - math.exp(-math.log(2) * (t / 20.0) ** 1.3)
    wb["Dissolution"].append(["Brand 10 mg", "RLD", 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37, None, t, "min",
                              *[round(100 * fraction + d, 2) for d in (-1.5, -1.2, -0.9, -0.6, -0.3, 0, 0, 0.3, 0.6, 0.9, 1.2, 1.5)]])
wb.save(out / "named.xlsx")
