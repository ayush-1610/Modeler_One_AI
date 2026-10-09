"""Compare PK-Sim's Weibull release curve (weibull_check.R) with the platform's equation (pbpk_domain.dissolution).

    uv run --frozen --package pbpk-domain python compare_weibull.py <work dir>

The OSP Dapagliflozin "IC tablet (Chang 2015)" is t50 30 min, shape 0.6, lag 0 (golden/fixtures). Acceptance (plan
harvest rule): the platform's fraction is within 1 % (0.01 of the dose) of PK-Sim's at every time point. Writes
weibull_result.json; exits 1 when the curves disagree, so the qualification gate fails and nothing is confirmed.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

from pbpk_domain.dissolution import EQUATION, FUNCTION_VERSION, weibull_fraction

T50_MIN, SHAPE, LAG_MIN = 30.0, 0.6, 0.0
TOLERANCE = 0.01


def main(work: Path) -> int:
    rows = list(csv.DictReader((work / "weibull_curve.csv").open(encoding="utf-8")))
    t = np.array([float(r["time_min"]) for r in rows])
    engine = np.array([float(r["fraction"]) for r in rows])
    ours = weibull_fraction(t, T50_MIN, SHAPE, LAG_MIN)
    deviation = float(np.max(np.abs(ours - engine)))
    worst = float(t[int(np.argmax(np.abs(ours - engine)))])
    result = {"formulation": "OSP Dapagliflozin IC tablet (Chang 2015)", "t50_min": T50_MIN, "shape": SHAPE,
              "lag_min": LAG_MIN, "quantity": rows[0]["path"], "points": len(rows), "max_abs_deviation": deviation,
              "at_min": worst, "tolerance": TOLERANCE, "equation": EQUATION, "function_version": FUNCTION_VERSION,
              "passed": deviation <= TOLERANCE}
    (work / "weibull_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
