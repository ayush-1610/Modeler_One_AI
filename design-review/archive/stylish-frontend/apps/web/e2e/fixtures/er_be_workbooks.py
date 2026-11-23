"""Writes workbooks laid out the way CROs and labs send them, for the guided client-data flow (T-47).

A BE study per arm with the sampling times across the top, BLQ / NS cells and Mean / SD rows under the subjects;
dissolution of a test and a reference ER tablet with one column per vessel; published mean IV data with SD and N.
Software test data (made-up numbers): it proves the read path, never a model. Usage: er_be_workbooks.py <out_dir>
"""

import math
import sys
from pathlib import Path

from openpyxl import Workbook

out = Path(sys.argv[1])
TIMES = ["Pre-dose", "1.00", "2.00", "4.00", "6.00", "8.00", "12.00", "24.00", "36.00", "48.00", "72.00"]


def curve(t: float, scale: float) -> float:
    return round(scale * (math.exp(-0.06 * t) - math.exp(-0.35 * t)), 2)


for arm, scale in (("Reference", 160.0), ("Test", 150.0)):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append([f"Study 230-23: plasma concentrations of desvenlafaxine (ng/mL), {arm}, 50 mg, fasting"])
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
    wb.save(out / f"230-23 Fasting {arm}.xlsx")

for name, label, t50 in (("Test", "Desvenlafaxine ER Tablets 50 mg (Test)", 5.0), ("RLD", "Reference product 50 mg (RLD)", 5.5)):
    wb = Workbook()
    ws = wb.active
    ws.title = "pH 6.8"
    ws.append([f"Dissolution of {label}, Batch No. B{t50:g}01, USP II (paddle), 50 rpm, 900 mL phosphate buffer pH 6.8"])
    ws.append(["Time (hr)", *(f"Vessel {i}" for i in range(1, 13)), "Mean", "SD", "%CV"])
    for t in (1, 2, 4, 6, 8, 12, 16, 20):
        base = 100 * (1 - math.exp(-math.log(2) * (t / t50) ** 1.2))
        vessels = [round(base + d, 2) for d in (-1.5, -1.2, -0.9, -0.6, -0.3, 0, 0, 0.3, 0.6, 0.9, 1.2, 1.5)]
        ws.append([t, *vessels, round(base, 2), 0.9, 1.0])
    wb.save(out / f"Dissolution {name} pH 6.8.xlsx")

wb = Workbook()
ws = wb.active
ws.title = "Fig 1"
ws.append(["Time (h)", "Mean concentration (ng/mL)", "SD", "N"])
for t, v in ((1, 60.0), (3, 150.0), (5, 210.0), (8, 140.0), (12, 90.0), (24, 30.0), (48, 4.0)):
    ws.append([t, v, round(v / 5, 1), 14])
wb.save(out / "Nichols2012 IV 50 mg 5 h infusion.xlsx")
