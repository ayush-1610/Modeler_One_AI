"""Spread conversion, versioned (docs/plans/2026-11-12-intake-contracts.md §4.8).

The ledger's derived SD and the profile a campaign is given call these same two functions, so the number a reviewer
sees beside its inputs is the number the campaign gets. Nothing is converted for a geometric mean or a median: that
is the landing's rule (intake_rules.yaml, `landing.sd_from`), not this module's.

The two error types PK-Sim's observed data take are typed here once. Both are harvested, not invented: they occur as
`AuxiliaryType` in services/engine-worker/golden/fixtures/*.json (GeometricStdDev in Midazolam and Rifampicin,
ArithmeticStdDev in most), and tests/test_spread.py asserts it. fit_spec, units, profile_landing,
campaign_activities and the intake rules loader import them; run_pi.R accepts these two only.
"""

from __future__ import annotations

import math

VERSION = "spread-1"

ARITHMETIC_SD = "ArithmeticStdDev"
GEOMETRIC_SD = "GeometricStdDev"
ERROR_TYPES = (ARITHMETIC_SD, GEOMETRIC_SD)


def sd_from_se(se: float, n: int) -> float:
    """The SD of a mean from its standard error and the number of values it is the mean of: SE × √n."""
    if n < 1:
        raise ValueError(f"an SD needs n >= 1 (got {n})")
    return se * math.sqrt(n)


def sd_from_cv_percent(cv_percent: float, mean: float) -> float:
    """The SD of an arithmetic mean from its coefficient of variation in percent: CV% × mean / 100."""
    return cv_percent * mean / 100
