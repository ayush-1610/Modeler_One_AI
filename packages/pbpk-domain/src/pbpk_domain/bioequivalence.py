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


@dataclass(frozen=True)
class StudyBeResult:
    """Average bioequivalence of a clinical study from its subjects' values: the GMR and its CI (fractions), the
    residual variance of the log values (`mse`, the within-subject variance σw² of a crossover), its degrees of freedom
    and the design the analysis took."""

    geometric_mean_ratio: float
    ci_lower: float
    ci_upper: float
    n: int
    n_by_group: tuple[int, ...]
    mse: float
    df: int
    design: str                       # "2x2 crossover", "paired" (sequences not known) or "parallel"
    confidence: float
    limits: tuple[float, float]

    @property
    def passes(self) -> bool:
        return self.ci_lower >= self.limits[0] and self.ci_upper <= self.limits[1]

    @property
    def cv(self) -> float:
        """The CV of the residual variance: within-subject (CVw) for a crossover, between-subject for a parallel study."""
        return float(np.sqrt(np.expm1(self.mse)))


def _checked(*arrays: np.ndarray, minimum: int = 2) -> None:
    for a in arrays:
        if a.ndim != 1 or a.size < minimum:
            raise ValueError(f"at least {minimum} subjects are required in each group")
        if not (np.all(np.isfinite(a)) and np.all(a > 0)):
            raise ValueError("exposure values must be positive and finite; exclude subjects explicitly before analysis")


def crossover_be(test: Sequence[float], reference: Sequence[float], sequences: Sequence[str] | None = None,
                 confidence: float = 0.90, limits: tuple[float, float] = STANDARD_LIMITS) -> StudyBeResult:
    """A clinical crossover's average bioequivalence from each subject's test and reference value (the same order).

    With two sequences (TR and RT, each subject's `sequences` entry): the standard 2×2 analysis, equal to the ANOVA of
    log values with sequence, subject within sequence, period and treatment. The treatment difference is the mean of
    the two sequences' mean log differences (period effects cancel); MSE is their pooled within-sequence variance over
    2, with n − 2 degrees of freedom; the CI's standard error is √(MSE/2 · (1/n₁ + 1/n₂)). With one sequence or none
    given: the paired form (period effects not removed, n − 1 degrees of freedom), as for a virtual crossover."""
    t, r = np.asarray(test, dtype=float), np.asarray(reference, dtype=float)
    if t.shape != r.shape:
        raise ValueError("test and reference need one value per subject each")
    _checked(t, r)
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1)")
    d = np.log(t) - np.log(r)
    groups = [d[np.asarray(sequences) == k] for k in dict.fromkeys(sequences)] if sequences is not None else [d]
    if len(groups) == 2 and all(g.size >= 1 for g in groups) and d.size >= 3:
        estimate = float(np.mean([g.mean() for g in groups]))
        df = int(d.size - 2)
        mse = float(sum(((g - g.mean()) ** 2).sum() for g in groups) / df / 2)
        se = float(np.sqrt(mse / 2 * sum(1 / g.size for g in groups)))
        design, sizes = "2x2 crossover", tuple(int(g.size) for g in groups)
    elif len(groups) <= 1 or sequences is None:
        estimate, df = float(d.mean()), int(d.size - 1)
        mse = float(d.var(ddof=1) / 2)
        se = float(d.std(ddof=1) / np.sqrt(d.size))
        design, sizes = "paired", (int(d.size),)
    else:
        raise ValueError(f"a 2x2 analysis takes two sequences, not {len(groups)}")
    q = float(stats.t.ppf(1 - (1 - confidence) / 2, df))
    return StudyBeResult(geometric_mean_ratio=float(np.exp(estimate)), ci_lower=float(np.exp(estimate - q * se)),
                         ci_upper=float(np.exp(estimate + q * se)), n=int(d.size), n_by_group=sizes, mse=mse, df=df,
                         design=design, confidence=confidence, limits=limits)


def parallel_be(test: Sequence[float], reference: Sequence[float], confidence: float = 0.90,
                limits: tuple[float, float] = STANDARD_LIMITS) -> StudyBeResult:
    """A parallel study's average bioequivalence: the difference of the groups' mean log values, the pooled variance,
    nT + nR − 2 degrees of freedom (equal variances assumed, as the standard analysis does)."""
    t, r = np.log(np.asarray(test, dtype=float)), np.log(np.asarray(reference, dtype=float))
    _checked(np.exp(t), np.exp(r))
    df = int(t.size + r.size - 2)
    mse = float((((t - t.mean()) ** 2).sum() + ((r - r.mean()) ** 2).sum()) / df)
    se = float(np.sqrt(mse * (1 / t.size + 1 / r.size)))
    estimate = float(t.mean() - r.mean())
    q = float(stats.t.ppf(1 - (1 - confidence) / 2, df))
    return StudyBeResult(geometric_mean_ratio=float(np.exp(estimate)), ci_lower=float(np.exp(estimate - q * se)),
                         ci_upper=float(np.exp(estimate + q * se)), n=int(t.size + r.size),
                         n_by_group=(int(t.size), int(r.size)), mse=mse, df=df, design="parallel", confidence=confidence,
                         limits=limits)


def be_zone(mse: float, n: int, confidence: float = 0.90,
            limits: tuple[float, float] = STANDARD_LIMITS) -> tuple[float, float] | None:
    """The GMRs a balanced 2×2 crossover of `n` subjects with within-subject variance `mse` (σw²) concludes
    bioequivalent: GMR · exp(±t·√(2σw²/n)) inside the limits, t on n − 2 degrees of freedom. None when no GMR does
    (the CI alone is wider than the limits)."""
    if n < 3 or mse < 0:
        raise ValueError("a zone needs at least 3 subjects and a variance")
    h = float(stats.t.ppf(1 - (1 - confidence) / 2, n - 2) * np.sqrt(2 * mse / n))
    low, high = limits[0] * float(np.exp(h)), limits[1] * float(np.exp(-h))
    return (low, high) if low <= high else None


def probability_of_success(trials: Iterable[BioequivalenceResult]) -> float:
    results = list(trials)
    if not results:
        raise ValueError("no trials")
    return sum(r.passes for r in results) / len(results)
