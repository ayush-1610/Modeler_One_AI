"""Model evaluation metrics (F-202).

Pairs with a non-finite or non-positive value cannot enter log-scale metrics. They are excluded
and counted, never dropped silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# Relative slack so that a prediction exactly on a fold boundary is not lost to float rounding.
_BOUNDARY_RTOL = 1e-12


@dataclass(frozen=True)
class MetricResult:
    value: float
    n: int
    n_excluded: int


def _valid_pairs(predicted: Sequence[float], observed: Sequence[float]) -> tuple[np.ndarray, np.ndarray, int]:
    pred = np.asarray(predicted, dtype=float)
    obs = np.asarray(observed, dtype=float)
    if pred.shape != obs.shape:
        raise ValueError(f"predicted and observed differ in shape: {pred.shape} vs {obs.shape}")
    keep = np.isfinite(pred) & np.isfinite(obs) & (pred > 0) & (obs > 0)
    if not keep.any():
        raise ValueError("no pair with positive, finite predicted and observed values")
    return pred[keep], obs[keep], int((~keep).sum())


def fold_errors(predicted: Sequence[float], observed: Sequence[float]) -> np.ndarray:
    pred, obs, _ = _valid_pairs(predicted, observed)
    return pred / obs


def gmfe(predicted: Sequence[float], observed: Sequence[float]) -> MetricResult:
    """Geometric mean fold error: 10 ** mean(|log10(pred / obs)|)."""
    pred, obs, excluded = _valid_pairs(predicted, observed)
    value = float(10 ** np.mean(np.abs(np.log10(pred / obs))))
    return MetricResult(value=value, n=int(pred.size), n_excluded=excluded)


def fraction_within_fold(predicted: Sequence[float], observed: Sequence[float], fold: float = 2.0) -> MetricResult:
    """Fraction of pairs with 1/fold <= pred/obs <= fold (inclusive)."""
    if fold < 1:
        raise ValueError("fold must be >= 1")
    pred, obs, excluded = _valid_pairs(predicted, observed)
    ratio = pred / obs
    within = (ratio >= (1 / fold) * (1 - _BOUNDARY_RTOL)) & (ratio <= fold * (1 + _BOUNDARY_RTOL))
    return MetricResult(value=float(within.mean()), n=int(pred.size), n_excluded=excluded)


def guest_limits(observed_ratio: float, delta: float = 2.0) -> tuple[float, float]:
    """Acceptance range for a predicted DDI ratio (Guest et al., Drug Metab Dispos 2011).

    Limit = (delta * (r - 1) + 1) / r with r = R_obs, or 1 / R_obs for ratios below 1.
    The prediction is acceptable if R_obs / Limit <= R_pred <= R_obs * Limit.
    delta = 2 is the default; confirm the convention for each template (architecture pack Q6).
    """
    if observed_ratio <= 0:
        raise ValueError("observed ratio must be > 0")
    if delta < 1:
        raise ValueError("delta must be >= 1")
    r = observed_ratio if observed_ratio >= 1 else 1 / observed_ratio
    limit = (delta * (r - 1) + 1) / r
    return observed_ratio / limit, observed_ratio * limit


def within_guest_limits(predicted_ratio: float, observed_ratio: float, delta: float = 2.0) -> bool:
    lower, upper = guest_limits(observed_ratio, delta)
    return lower * (1 - _BOUNDARY_RTOL) <= predicted_ratio <= upper * (1 + _BOUNDARY_RTOL)
