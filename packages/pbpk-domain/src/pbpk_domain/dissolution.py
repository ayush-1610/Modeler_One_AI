"""In vitro dissolution (plan §10.3, T-48): canonical profiles, checks, f2 and the Weibull release fit.

A canonical profile is one product × role × strength × batch × apparatus × rpm × medium × pH × volume, with its times
(in minutes), per-vessel values, mean, SD, CV and n. Checks and the f2 conditions are ruleset data
(`rulesets/dissolution_similarity.yaml`, UNVERIFIED). f2 is computed only when its conditions hold; otherwise the
reason is reported. The release fit is a deterministic least-squares fit of the Weibull function in PK-Sim's own
parameterization (`Dissolution time (50% dissolved)` in min, `Dissolution shape`, `Lag time` in min, harvested from
the OSP formulation catalog; see `cpf.formulations.WEIBULL_PARAMETERS`):

    fraction dissolved(t) = 1 - exp(-ln 2 · ((t - lag) / t50) ** shape)   for t > lag, else 0

so that half the dose is dissolved at t50 after the lag. The equation has not yet been confirmed against PK-Sim's
own release curve on the engine (plan harvest rule): `ENGINE_CONFIRMED` is False and every fit says so until that
run is recorded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import numpy as np
import yaml

ENGINE_CONFIRMED = False
EQUATION = "fraction dissolved(t) = 1 - exp(-ln2 * ((t - lag) / t50) ** shape)"
FUNCTION_VERSION = "weibull-pksim-1"
_MINUTES = {"min": 1.0, "h": 60.0, "day": 1440.0}


@lru_cache
def load_rules() -> dict[str, Any]:
    text = resources.files("pbpk_domain.rulesets").joinpath("dissolution_similarity.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


@dataclass(frozen=True)
class ProfileKey:
    product: str
    role: str
    strength_mg: float | None = None
    batch: str = ""
    apparatus: str = ""
    rpm: float | None = None
    medium: str = ""
    ph: float | None = None
    volume_ml: float | None = None

    def label(self) -> str:
        bits = [self.product, self.role, self.medium + (f" pH {self.ph:g}" if self.ph is not None else "")]
        bits += [b for b in (self.batch and f"batch {self.batch}", self.apparatus, self.rpm and f"{self.rpm:g} rpm") if b]
        return " · ".join(b for b in bits if b)

    def condition(self) -> tuple:
        """What two profiles must share to be compared: the test conditions, not the product."""
        return (self.apparatus, self.rpm, self.medium, self.ph, self.volume_ml)


@dataclass(frozen=True)
class Profile:
    key: ProfileKey
    times_min: tuple[float, ...]
    vessels: tuple[tuple[float | None, ...], ...]   # one tuple per vessel, aligned with times
    mean: tuple[float, ...]
    sd: tuple[float | None, ...]
    n: int
    cells: tuple[str, ...] = ()

    @property
    def cv(self) -> tuple[float | None, ...]:
        return tuple(None if s is None or m <= 0 else 100.0 * s / m for m, s in zip(self.mean, self.sd, strict=True))


class DissolutionError(ValueError):
    pass


def _key(values: dict[str, Any]) -> ProfileKey:
    return ProfileKey(product=str(values.get("product", "")), role=str(values.get("role", "")),
                      strength_mg=values.get("strength_mg"), batch=str(values.get("batch") or ""),
                      apparatus=str(values.get("apparatus") or ""), rpm=values.get("rpm"), medium=str(values.get("medium", "")),
                      ph=values.get("ph"), volume_ml=values.get("volume_ml"))


def profiles_from_rows(rows: list[dict[str, Any]]) -> tuple[list[Profile], list[str]]:
    """Canonical profiles from template rows (`values` with vessel_1 … vessel_12 and/or mean, sd, n; `cells`)."""
    groups: dict[ProfileKey, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_key(row["values"]), []).append(row)
    out, problems = [], []
    for key, group in groups.items():
        points = []
        for row in group:
            v = row["values"]
            unit = v.get("time_unit", "min")
            if unit not in _MINUTES or v.get("time") is None:
                problems.append(f"{key.label()}: time {v.get('time')!r} {unit!r} not usable")
                continue
            vessels = [v.get(f"vessel_{i}") for i in range(1, 13)]
            measured = [x for x in vessels if x is not None]
            if measured:
                mean = float(np.mean(measured))
                sd = float(np.std(measured, ddof=1)) if len(measured) > 1 else None
                n = len(measured)
            elif v.get("mean") is not None:
                mean, sd, n = float(v["mean"]), v.get("sd"), int(v["n"]) if v.get("n") is not None else 0
            else:
                problems.append(f"{key.label()} at {v.get('time')} {unit}: no vessel values and no mean")
                continue
            points.append((float(v["time"]) * _MINUTES[unit], vessels, mean, sd, n, tuple(row.get("cells", {}).values())))
        if not points:
            continue
        points.sort(key=lambda p: p[0])
        times = [p[0] for p in points]
        if len(set(times)) != len(times):
            problems.append(f"{key.label()}: a time appears twice")
            continue
        used = [i for i in range(12) if any(p[1][i] is not None for p in points)]
        out.append(Profile(key=key, times_min=tuple(times),
                           vessels=tuple(tuple(p[1][i] for p in points) for i in used),
                           mean=tuple(p[2] for p in points), sd=tuple(p[3] for p in points),
                           n=min(p[4] for p in points), cells=tuple(c for p in points for c in p[5])))
    return out, problems


def profiles_from_records(records: list[dict[str, Any]]) -> tuple[list[Profile], list[str]]:
    """Canonical profiles from mapping-recipe records (`DissolutionObservation`: one row per vessel and time)."""
    rows: dict[tuple, dict[str, Any]] = {}
    vessel_index: dict[tuple, dict[str, int]] = {}
    for r in records:
        # the recipe's constants name the product, its role and the test conditions (blank when the sheet does not)
        values = {"product": r.get("product") or "", "role": (r.get("role") or "").upper(), "strength_mg": r.get("strength_mg"),
                  "batch": r.get("batch", ""), "apparatus": r.get("apparatus") or "", "rpm": r.get("rpm"),
                  "medium": r.get("medium", ""), "ph": r.get("ph"), "volume_ml": r.get("volume_ml")}
        key = _key(values)
        index = vessel_index.setdefault(key.condition() + (key.batch,), {})
        slot = index.setdefault(str(r.get("vessel")), len(index) + 1)
        if slot > 12:
            continue
        row = rows.setdefault((key, r["time"], r.get("time_unit", "min")),
                              {"values": {**values, "time": r["time"], "time_unit": r.get("time_unit", "min")}, "cells": {}})
        row["values"][f"vessel_{slot}"] = r["percent_dissolved"]
        row["cells"][f"vessel_{slot}"] = (r.get("source") or {}).get("cells", {}).get("value", "")
    return profiles_from_rows(list(rows.values()))


def check_profile(profile: Profile) -> tuple[list[str], str]:
    """Flags for a person to look at, and the release model the data support: Weibull, Dissolved (rapid), or Table."""
    rules = load_rules()["profile"]
    flags = []
    for t, m in zip(profile.times_min, profile.mean, strict=True):
        if m > rules["max_percent"]:
            flags.append(f"{m:.1f} % at {t:g} min exceeds {rules['max_percent']} %")
        if t == 0 and m > rules["zero_time_max_percent"]:
            flags.append(f"{m:.1f} % dissolved at t = 0: check the time origin")
    for (t0, m0), (t1, m1) in zip(zip(profile.times_min, profile.mean, strict=True),
                                  zip(profile.times_min[1:], profile.mean[1:], strict=True), strict=False):
        if m1 < m0 - 5:
            flags.append(f"mean falls from {m0:.1f} % ({t0:g} min) to {m1:.1f} % ({t1:g} min)")
    rapid = rules["rapidly_dissolving"]
    if any(t <= rapid["within_min"] and m >= rapid["percent"] for t, m in zip(profile.times_min, profile.mean, strict=True)):
        return flags, "Dissolved"
    plateau = rules["plateau"]
    tail = profile.mean[-plateau["window_points"]:]
    if len(tail) == plateau["window_points"] and max(tail) - min(tail) <= plateau["max_change_percent"] and max(tail) < plateau["below_percent"]:
        flags.append(f"release plateaus at {max(tail):.0f} %: a Weibull curve to 100 % cannot represent it (table formulation)")
        return flags, "Table"
    return flags, "Weibull"


@dataclass(frozen=True)
class F2Result:
    value: float | None
    similar: bool | None
    applicable: bool
    reasons: tuple[str, ...] = ()
    times_used: tuple[float, ...] = ()
    ruleset: str = ""

    def to_content(self) -> dict[str, Any]:
        return {"f2": self.value, "similar": self.similar, "applicable": self.applicable, "reasons": list(self.reasons),
                "times_used": list(self.times_used), "ruleset": self.ruleset}


def f2(test: Profile, reference: Profile) -> F2Result:
    """f2 = 50·log10(100 / sqrt(1 + mean((R - T)²))) on the time points the conditions allow, or why it does not apply."""
    doc = load_rules()
    rules, ruleset = doc["f2"], f"{doc['id']}@{doc['version']} ({doc['status']})"
    if test.times_min != reference.times_min:
        return F2Result(None, None, False, ("the two profiles are not sampled at the same times",), ruleset=ruleset)
    rapid = rules["very_rapid"]
    early = [i for i, t in enumerate(test.times_min) if 0 < t <= rapid["within_min"]]
    if early and all(max(p.mean[i] for i in early) >= rapid["percent"] for p in (test, reference)):
        return F2Result(None, True, False, (f"both ≥ {rapid['percent']} % within {rapid['within_min']} min: similar without f2",),
                        ruleset=ruleset)
    reasons = []
    for name, p in (("test", test), ("reference", reference)):
        if p.n < rules["min_units"]:
            reasons.append(f"{name}: {p.n} units, at least {rules['min_units']} needed")
    used: list[int] = []
    after_85 = 0
    for i, t in enumerate(test.times_min):
        if t <= 0:
            continue
        if test.mean[i] > 85 or reference.mean[i] > 85:
            after_85 += 1
            if after_85 > rules["max_points_after_85"]:
                break
        used.append(i)
    if len(used) < rules["min_time_points"]:
        reasons.append(f"{len(used)} usable time points, at least {rules['min_time_points']} needed")
    for name, p in (("test", test), ("reference", reference)):
        for i in used:
            cv = p.cv[i]
            limit = rules["cv_early_max_percent"] if p.times_min[i] <= rules["early_until_min"] else rules["cv_later_max_percent"]
            if cv is None:
                reasons.append(f"{name}: no SD at {p.times_min[i]:g} min, the CV cannot be checked")
                break
            if cv > limit:
                reasons.append(f"{name}: CV {cv:.1f} % at {p.times_min[i]:g} min exceeds {limit} %")
    times = tuple(test.times_min[i] for i in used)
    if reasons:
        return F2Result(None, None, False, tuple(reasons), times, ruleset)
    diff = np.array([reference.mean[i] - test.mean[i] for i in used])
    value = 50.0 * math.log10(100.0 / math.sqrt(1.0 + float(np.mean(diff ** 2))))
    return F2Result(round(value, 2), value >= rules["similar_at_least"], True, (), times, ruleset)


def weibull_fraction(t: np.ndarray, t50: float, shape: float, lag: float = 0.0) -> np.ndarray:
    shifted = np.clip(np.asarray(t, dtype=float) - lag, 0.0, None)
    return 1.0 - np.exp(-math.log(2.0) * (shifted / t50) ** shape)


@dataclass(frozen=True)
class WeibullFit:
    t50_min: float | None
    shape: float | None
    lag_min: float
    se_t50: float | None = None
    se_shape: float | None = None
    rmse_percent: float | None = None
    n_points: int = 0
    converged: bool = False
    note: str = ""
    engine_confirmed: bool = ENGINE_CONFIRMED
    equation: str = EQUATION
    function_version: str = FUNCTION_VERSION

    def to_content(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("t50_min", "shape", "lag_min", "se_t50", "se_shape", "rmse_percent", "n_points",
                                              "converged", "note", "engine_confirmed", "equation", "function_version")}


def fit_weibull(profile: Profile, *, lag_min: float = 0.0) -> WeibullFit:
    """Least-squares fit of t50 and shape to the mean profile (percent dissolved), lag fixed (0 by default, as the OSP
    tablets have it). Standard errors from the Jacobian at the optimum."""
    from scipy.optimize import least_squares

    t = np.array(profile.times_min, dtype=float)
    y = np.array(profile.mean, dtype=float) / 100.0
    keep = t > 0
    t, y = t[keep], y[keep]
    if len(t) < 3:
        return WeibullFit(None, None, lag_min, n_points=len(t), note="fewer than 3 time points after t = 0: not fitted")
    # start: t50 where the profile crosses 50 % (interpolated), shape 1
    above = np.nonzero(y >= 0.5)[0]
    t50_0 = float(np.interp(0.5, y[: above[0] + 1], t[: above[0] + 1])) if len(above) and above[0] > 0 else float(np.median(t))

    def residuals(p: np.ndarray) -> np.ndarray:
        return weibull_fraction(t, p[0], p[1], lag_min) - y

    result = least_squares(residuals, x0=[max(t50_0, 1e-3), 1.0], bounds=([1e-3, 0.05], [1e5, 20.0]), method="trf")
    dof = max(len(t) - 2, 1)
    s2 = float(np.sum(result.fun ** 2)) / dof
    se_t50 = se_shape = None
    try:
        cov = np.linalg.inv(result.jac.T @ result.jac) * s2
        se_t50, se_shape = (float(math.sqrt(cov[0, 0])), float(math.sqrt(cov[1, 1])))
    except np.linalg.LinAlgError:
        pass
    rmse = float(math.sqrt(np.mean(result.fun ** 2))) * 100.0
    return WeibullFit(round(float(result.x[0]), 4), round(float(result.x[1]), 4), lag_min, se_t50, se_shape, round(rmse, 3),
                      len(t), bool(result.success), note=result.message if not result.success else "")
