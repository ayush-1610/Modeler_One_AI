"""Writes two client-data templates that give one study two doses and two subject counts (plan 2026-11-03 §3.5): the
contradiction the Clinical studies card flags. Software test data (made-up numbers), never a model.
Usage: conflict_workbooks.py <out_dir>
"""

import io
import sys
from pathlib import Path

from openpyxl import load_workbook

from modeler_intake.client_template import build_template

out = Path(sys.argv[1])
for name, dose, n in (("EX-101_protocol_PK.xlsx", 10, 14), ("EX-101_PK_sheet.xlsx", 5, 12)):
    wb = load_workbook(io.BytesIO(build_template()))
    header = [c.value.rstrip("*") for c in wb["Studies"][1]]
    study = {"study_id": "EX-101", "design": "SD", "population": "healthy", "n": n, "route": "oral", "dose": dose,
             "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml"}
    wb["Studies"].append([study.get(h) for h in header])
    for t, v in ((0.5, 18.0), (1, 42.0), (2, 31.0), (4, 13.0), (8, 4.2)):
        wb["PK_Summary"].append(["EX-101", None, t, "h", "arithmetic_mean", v, None, None, n, "ng/ml"])
    wb.save(out / name)
