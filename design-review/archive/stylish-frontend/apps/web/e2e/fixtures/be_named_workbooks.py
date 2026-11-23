"""Writes filled client-data templates of the common bioequivalence shape (final review round 7, round 6's named-product
skeptic): the Test product's study names Test 10 mg, the Reference product's names Brand 10 mg, and only Brand 10 mg (the
reference, a curve with a Weibull fit) has a dissolution profile.

- `two.xlsx`: two tablet studies, CL-01 (Brand 10 mg, RLD) and CL-02 (Test 10 mg, TEST);
- `crossover.xlsx`: one crossover tablet study CL-02 with a Test arm (Test 10 mg) and a Reference arm (Brand 10 mg);
- `solid-label.xlsx`: one tablet study CL-04 whose product is "Test 10 mg tablet" (solid by its name, so the delivery
  asks for its release itself), with no dissolution at all.

Software test data (made-up numbers): it proves the page's path, never a model. Usage: be_named_workbooks.py <out_dir>
"""

import io
import math
import sys
from pathlib import Path

from openpyxl import load_workbook

from modeler_intake.client_template import build_template

out = Path(sys.argv[1])


def workbook(rows: list[tuple[str, str | None, str, str]], dissolution: str | None, name: str) -> None:
    """Each (study, treatment, product, role) a tablet study or arm with its mean profile, and `dissolution`'s curve."""
    wb = load_workbook(io.BytesIO(build_template()))
    header = [c.value.rstrip("*") for c in wb["Studies"][1]]
    for study, treatment, product, role in rows:
        row = {"study_id": study, "treatment": treatment, "design": "SD", "crossover": "yes" if treatment else None,
               "population": "healthy", "n": 12, "route": "oral", "dose": 10, "dose_unit": "mg", "formulation": "ir_tablet",
               "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml", "product": product, "product_role": role}
        wb["Studies"].append([row.get(h) for h in header])
        for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0)):
            wb["PK_Summary"].append([study, treatment, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"])
    if dissolution:
        for t in (5, 10, 15, 20, 30, 45, 60):
            fraction = 1 - math.exp(-math.log(2) * (t / 20.0) ** 1.3)
            wb["Dissolution"].append([dissolution, "RLD", 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37, None, t, "min",
                                      *[round(100 * fraction + d, 2) for d in (-1.5, -1.2, -0.9, -0.6, -0.3, 0, 0, 0.3, 0.6, 0.9, 1.2, 1.5)]])
    wb.save(out / name)


workbook([("CL-01", None, "Brand 10 mg", "RLD"), ("CL-02", None, "Test 10 mg", "TEST")], "Brand 10 mg", "two.xlsx")
workbook([("CL-02", "Test", "Test 10 mg", "TEST"), ("CL-02", "Reference", "Brand 10 mg", "RLD")], "Brand 10 mg", "crossover.xlsx")
workbook([("CL-04", None, "Test 10 mg tablet", "TEST")], None, "solid-label.xlsx")
