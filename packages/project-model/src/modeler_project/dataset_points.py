"""A dataset's points as a study's card shows them, with code's statistics of each profile (plan 2026-11-05 §3.2, build
C; the owner, 2026-11-05: "no data points, no graph, no metadata, no statistics").

Statistics are computed by code from the points, with the platform's own non-compartmental analysis (`pbpk_domain.nca`,
T-18: Cmax, tmax, AUC to the last time by linear-up / log-down trapezoids, the terminal half-life from a log-linear tail,
AUC to infinity), the same method the acceptance gate uses. They describe what the client sent, to check it; they
decide nothing. Points below the LLOQ (no value) are left out of them and counted. A blinded dataset (D-15) comes
here without its values, and gets no statistics.
"""

from __future__ import annotations

from typing import Any

from pbpk_domain.nca import nca


def _stats(times: list[float], values: list[float | None]) -> dict[str, Any] | None:
    pairs = [(float(t), float(v)) for t, v in zip(times, values, strict=False) if v is not None]
    blq = sum(1 for v in values if v is None)
    if len(pairs) < 2 or not any(v > 0 for _t, v in pairs):
        return None
    try:
        result = nca([t for t, _v in pairs], [v for _t, v in pairs])
    except ValueError:
        return None
    return {"c_max": result.c_max, "t_max": result.t_max, "auc_last": result.auc_last, "t_last": result.t_last,
            "t_half": result.t_half, "auc_inf": result.auc_inf, "points": len(pairs), "blq": blq}


def card_points(content: dict[str, Any]) -> dict[str, Any]:
    """The points of one dataset's content (already redacted for the viewer, D-15), each profile series with its
    statistics; the PK parameters the client reported, as reported."""
    blinded = bool(content.get("blinded"))
    profile = content.get("kind") == "profile"
    study = content.get("study") or {}
    series = []
    for s in content.get("series") or []:
        times, values = list(s.get("times") or []), list(s.get("values") or [])
        series.append({"name": str(s.get("name", "")), "statistic": str(s.get("statistic", "")), "times": times,
                       "values": values, "error": list(s["error"]) if s.get("error") else None,
                       "error_kind": str(s.get("error_kind") or "none"), "n": s.get("n"),
                       "stats": None if blinded or not profile else _stats(times, values)})
    reported = [{"parameter": r.get("parameter"), "value": r.get("value"), "unit": r.get("unit"),
                 "statistic": r.get("statistic", "")} for r in content.get("reported") or []]
    return {"kind": str(content.get("kind", "")), "time_unit": str(content.get("time_unit", "")),
            "unit": str(content.get("unit", "")), "lloq": study.get("lloq"), "blinded": blinded, "series": series,
            "reported": reported}
