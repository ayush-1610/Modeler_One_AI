"""Deterministic non-compartmental analysis of a concentration-time profile (task T-18).

Used to reduce observed clinical data and simulated profiles to the PK parameters the acceptance gate
compares: Cmax, tmax, AUC to the last measured time (linear-up / log-down trapezoidal), the terminal
half-life from a log-linear fit of the tail, and AUC extrapolated to infinity. The method is fixed and
deterministic so the same profile always yields the same parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class NcaResult:
    c_max: float
    t_max: float
    t_last: float
    c_last: float
    auc_last: float           # AUC from the first time to the last, linear-up/log-down
    lambda_z: float | None    # terminal elimination rate constant (1/time)
    t_half: float | None      # ln(2) / lambda_z
    auc_inf: float | None     # auc_last + c_last / lambda_z
    n_terminal_points: int    # points used for the terminal slope


def _clean(times: list[float], concs: list[float]) -> tuple[list[float], list[float]]:
    pairs = sorted((float(t), float(c)) for t, c in zip(times, concs, strict=True))
    ts = [t for t, _ in pairs]
    cs = [c for _, c in pairs]
    if len(ts) < 2:
        raise ValueError("NCA needs at least two time points")
    return ts, cs


def auc_linup_logdown(times: list[float], concs: list[float]) -> float:
    """Trapezoidal AUC: linear on rising (or zero) segments, log on falling segments (positive values)."""
    ts, cs = _clean(times, concs)
    total = 0.0
    for i in range(len(ts) - 1):
        dt = ts[i + 1] - ts[i]
        c0, c1 = cs[i], cs[i + 1]
        if dt <= 0:
            continue
        if c1 < c0 and c0 > 0 and c1 > 0:  # falling, both positive -> log trapezoid
            total += dt * (c0 - c1) / math.log(c0 / c1)
        else:  # rising, flat, or a zero endpoint -> linear trapezoid
            total += dt * (c0 + c1) / 2.0
    return total


# Two regressions whose adjusted R^2 differ by less than this are equally good; the one with more points is taken
# (the "best fit" lambda_z rule of standard NCA software).
ADJ_R2_TOLERANCE = 1e-4


def terminal_slope(times: list[float], concs: list[float], *, min_points: int = 3) -> tuple[float, int] | None:
    """Terminal elimination rate from a log-linear regression over the trailing points after Cmax, choosing the
    number of points (>= min_points) with the best adjusted R^2 (ties within ADJ_R2_TOLERANCE go to more points).

    Trailing points that do not fall below the point before them are left out of the regression (they stay in
    AUClast): a terminal phase declines, and a flat or repeated tail is an assay-limit or digitisation artefact
    that would otherwise read as a near-zero elimination rate (the OSP Boulton 2013 IV dataset ends 4.48e-5,
    4.48e-5 and gave a 275 h half-life for a drug eliminated with a half-life near 12 h)."""
    ts, cs = _clean(times, concs)
    points = [(t, c) for t, c in zip(ts, cs, strict=True) if c > 0]
    if not points:
        return None
    i_max = max(range(len(points)), key=lambda i: points[i][1])
    tail = points[i_max + 1:]
    while len(tail) >= 2 and tail[-1][1] >= tail[-2][1]:
        tail.pop()
    if len(tail) < min_points:
        return None
    best: tuple[float, float, int] | None = None  # (adj_r2, lambda_z, n)
    for n in range(min_points, len(tail) + 1):
        fit = _loglinear(tail[-n:])
        if fit is None or fit[0] <= 0:  # need a declining tail (positive elimination rate)
            continue
        lambda_z, adj_r2 = fit
        if best is None or adj_r2 > best[0] - ADJ_R2_TOLERANCE:
            best = (max(adj_r2, best[0]) if best else adj_r2, lambda_z, n)
    if best is None:
        return None
    return best[1], best[2]


def _loglinear(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Regress ln(c) on t; return (lambda_z = -slope, adjusted R^2), or None if degenerate."""
    n = len(points)
    xs = [t for t, _ in points]
    ys = [math.log(c) for _, c in points]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    intercept = my - slope * mx
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys, strict=True))
    ss_tot = sum((y - my) ** 2 for y in ys)
    if ss_tot == 0 or n <= 2:
        r2 = 1.0 if ss_res == 0 else 0.0
    else:
        r2 = 1.0 - ss_res / ss_tot
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / (n - 2) if n > 2 else r2
    return -slope, adj_r2


def nca(times: list[float], concs: list[float], *, terminal_min_points: int = 3) -> NcaResult:
    """Compute the NCA parameters of one profile. AUCinf/t-half are None when no declining tail is found."""
    ts, cs = _clean(times, concs)
    i_max = max(range(len(cs)), key=lambda i: cs[i])
    auc_last = auc_linup_logdown(ts, cs)
    slope = terminal_slope(ts, cs, min_points=terminal_min_points)
    lambda_z = t_half = auc_inf = None
    n_terminal = 0
    if slope is not None:
        lambda_z, n_terminal = slope
        t_half = math.log(2) / lambda_z
        auc_inf = auc_last + cs[-1] / lambda_z
    return NcaResult(
        c_max=cs[i_max], t_max=ts[i_max], t_last=ts[-1], c_last=cs[-1],
        auc_last=auc_last, lambda_z=lambda_z, t_half=t_half, auc_inf=auc_inf, n_terminal_points=n_terminal,
    )
