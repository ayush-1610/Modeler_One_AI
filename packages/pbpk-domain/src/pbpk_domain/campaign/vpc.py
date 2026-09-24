"""Visual predictive check (MS-01 §4 S1/S2 gates, S4 report).

A study's model is simulated across a virtual population built from the study's demographics (n = 100, seed
recorded); the 5th–95th percentile band of plasma concentration over time is compared with the observed points.
At S1 and S2 the gate requires at least 80 % of observed points inside the band (MS-01 S1: "VPC coverage ≥ 80 % of
observed points inside the simulated 5–95 % band of a 100-individual population with the study demographics";
S2: "Gate: as S1"). At S4 the VPC is part of the report ("VPC per study") but the gate is the PK acceptance table,
so a low coverage there is a flagged finding, not a failure.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass

VPC_STAGES = ("S1", "S2", "S4")       # where the VPC is run and reported
VPC_GATE_STAGES = ("S1", "S2")        # where it is part of the gate (MS-01 §4)
VPC_INDIVIDUALS = 100
VPC_MIN_COVERAGE = 0.80
VPC_PERCENTILES = (0.05, 0.5, 0.95)
# When a study reports no age range, its VPC population spans the mean age ± this many years (adults: from 18).
# A MAP default the modeler signs, flagged for SME review like every MS-01 [SME] value.
DEFAULT_AGE_HALF_SPAN_Y = 10.0


@dataclass(frozen=True)
class VpcCoverage:
    study_id: str
    n_points: int
    n_inside: int
    individuals: int

    @property
    def fraction(self) -> float:
        return self.n_inside / self.n_points if self.n_points else 0.0

    @property
    def passes(self) -> bool:
        return self.n_points > 0 and self.fraction >= VPC_MIN_COVERAGE


def age_range(age_years: float, age_min: float | None, age_max: float | None) -> tuple[float, float]:
    """The VPC population's age range: the study's own, else mean ± DEFAULT_AGE_HALF_SPAN_Y (adults from 18)."""
    if age_min is not None and age_max is not None and age_min < age_max:
        return age_min, age_max
    lo = max(18.0, age_years - DEFAULT_AGE_HALF_SPAN_Y) if age_years >= 18 else max(0.0, age_years - 2.0)
    return lo, max(lo + 1.0, age_years + DEFAULT_AGE_HALF_SPAN_Y)


def _interp(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    i = bisect_left(xs, x)
    if i <= 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def coverage(study_id: str, band: dict, observed_times_min: Sequence[float], observed_values: Sequence[float],
             *, lloq: float | None = None) -> VpcCoverage:
    """How many observed points fall inside the band's 5th–95th percentiles (interpolated at each observed time).
    Points below the LLOQ carry no concentration and are not counted."""
    times = list(band["times_min"])
    lo, hi = list(band["percentiles"]["5"]), list(band["percentiles"]["95"])
    inside = total = 0
    for t, v in zip(observed_times_min, observed_values, strict=False):
        if v is None or (lloq is not None and v < lloq) or t < times[0] or t > times[-1]:
            continue
        total += 1
        inside += int(_interp(times, lo, t) <= v <= _interp(times, hi, t))
    return VpcCoverage(study_id=study_id, n_points=total, n_inside=inside, individuals=int(band.get("individuals", 0)))
