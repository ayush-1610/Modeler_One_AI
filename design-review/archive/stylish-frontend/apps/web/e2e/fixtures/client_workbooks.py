"""Writes the two workbooks the client-data e2e flow uploads: a filled client-data template and a raw workbook.

Software test data (made-up numbers): it proves the read path, never a model. Usage: client_workbooks.py <out_dir>
"""

import io
import math
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook

from modeler_intake.client_template import build_template

out = Path(sys.argv[1])
wb = load_workbook(io.BytesIO(build_template()))
header = [c.value.rstrip("*") for c in wb["Studies"][1]]
study = {"study_id": "CL-01", "design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": 10,
         "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml"}
wb["Studies"].append([study.get(h) for h in header])
for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0), (8, "BLQ")):
    wb["PK_Summary"].append(["CL-01", None, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"])
wb["PK_Summary"].append(["CL-01", None, 12, "h", "arithmetic_mean", "1,2", None, None, 12, "ng/ml"])  # refused: decimal comma
for product, role, t50 in (("Test 10 mg", "TEST", 18.0), ("Brand 10 mg", "RLD", 20.0)):
    for t in (5, 10, 15, 20, 30, 45, 60):
        fraction = 1 - math.exp(-math.log(2) * (t / t50) ** 1.3)
        wb["Dissolution"].append([product, role, 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37, None, t, "min",
                                  *[round(100 * fraction + d, 2) for d in (-1.5, -1.2, -0.9, -0.6, -0.3, 0, 0, 0.3, 0.6, 0.9, 1.2, 1.5)]])
wb.save(out / "client-template-filled.xlsx")

raw = Workbook()
sheet = raw.active
sheet.title = "Diss pH 6.8"
for row in (["Time (min)", "Vessel 1", "Vessel 2", "% dissolved mean"], [15, 61, 63, 62], [30, 88, 90, 89]):
    sheet.append(row)
raw.create_sheet("Notes").append(["Shipped with the courier on 1 September"])
raw.save(out / "client-raw.xlsx")
