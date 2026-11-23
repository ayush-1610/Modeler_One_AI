"""Writes one workbook that holds two studies, one per sheet, laid out like the 230-23 BE arms of er_be_workbooks.py.

Sheet1 is titled "Study 230-23 … Reference …" (a study the delivery names, with the Reference arm's subjects and periods),
Sheet2 "Study 777-01 …" (a study no file names yet): To do's link table must let each table go to its own place, and refuse
Sheet1's table the arm that already holds those subjects. Software test data (made-up numbers): it proves the link path,
never a model. Usage: two_studies_workbook.py <out_dir>
"""

import math
import sys
from pathlib import Path

from openpyxl import Workbook

out = Path(sys.argv[1])
TIMES = ["Pre-dose", "1.00", "2.00", "4.00", "6.00", "8.00", "12.00", "24.00", "36.00", "48.00", "72.00"]


def curve(t: float, scale: float) -> float:
    return round(scale * (math.exp(-0.06 * t) - math.exp(-0.35 * t)), 2)


wb = Workbook()
for n, (study, scale) in enumerate((("230-23", 160.0), ("777-01", 140.0))):
    ws = wb.active if n == 0 else wb.create_sheet()
    ws.title = f"Sheet{n + 1}"
    ws.append([f"Study {study}: plasma concentrations of desvenlafaxine (ng/mL), Reference, 50 mg, fasting"])
    ws.append([])
    ws.append(["Time (hr)"])
    ws.append(["Subject No.", "Period", *TIMES])
    for i in range(1, 7):
        row = ["BLQ", *(curve(float(t), scale * (0.85 + 0.05 * i)) for t in TIMES[1:])]
        if i == 3:
            row[8] = "NS"
        ws.append([f"{i:03d}", "I" if i % 2 else "II", *row])
    ws.append(["Mean", None, None, *(1.0 for _ in TIMES[1:])])
    ws.append(["SD", None, None, *(0.1 for _ in TIMES[1:])])
    ws.append([])
    ws.append(["BLQ = below the lower limit of quantification (0.50 ng/mL); NS = no sample"])
wb.save(out / "two-studies-one-workbook.xlsx")
