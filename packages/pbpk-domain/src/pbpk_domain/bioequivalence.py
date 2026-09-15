"""Virtual bioequivalence statistics (F-304).

Virtual crossover: every virtual subject receives both test and reference, so there are no
period or sequence effects. The analysis is the paired log-difference form of average
bioequivalence. Parallel designs and replicate designs need their own functions.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import stats

STANDARD_LIMITS = (0.80, 1.25)


@dataclass(frozen=True)
class BioequivalenceResult:
    geometric_mean_ratio: float
    ci_lower: float
    ci_upper: float
    n: int
    confidence: float
    limits: tuple[float, float]

    @property
    def passes(self) -> bool:
        return self.ci_lower >= self.limits[0] and self.ci_upper <= self.limits[1]


def paired_crossover_ci(
    test: Sequence[float],
    reference: Sequence[float],
    confidence: float = 0.90,
    limits: tuple[float, float] = STANDARD_LIMITS,
) -> BioequivalenceResult:
    t = np.asarray(test, dtype=float)
    r = np.asarray(reference, dtype=float)
    if t.shape != r.shape or t.ndim != 1:
        raise ValueError("test and reference must be 1-D arrays of equal length (one value per subject)")
    if t.size < 2:
        raise ValueError("at least 2 subjects are required")
    if not (np.all(np.isfinite(t)) and np.all(np.isfinite(r)) and np.all(t > 0) and np.all(r > 0)):
        raise ValueError("exposure values must be positive and finite; exclude subjects explicitly before analysis")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")

    d = np.log(t) - np.log(r)
    n = int(d.size)
    mean = float(d.mean())
    se = float(d.std(ddof=1)) / np.sqrt(n)
    q = float(stats.t.ppf(1 - (1 - confidence) / 2, n - 1))
    return BioequivalenceResult(
        geometric_mean_ratio=float(np.exp(mean)),
        ci_lower=float(np.exp(mean - q * se)),
        ci_upper=float(np.exp(mean + q * se)),
        n=n,
        confidence=confidence,
        limits=limits,
    )


def probability_of_success(trials: Iterable[BioequivalenceResult]) -> float:
    results = list(trials)
    if not results:
        raise ValueError("no trials")
    return sum(r.passes for r in results) / len(results)
