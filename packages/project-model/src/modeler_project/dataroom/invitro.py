"""In vitro data from the cells code read (plan 2026-11-21 v2 §8 "Dissolution", "Solubility"): dissolution profiles
per product, batch and medium (mean and spread from the units, checked against the client's own mean row), f2 where it
applies, a Weibull fit on every profile; composition side by side; solubility with the volume the dose needs.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from collections import defaultdict
from collections.abc import Sequence

from modeler_project.dataroom.extract import parse_number
from modeler_project.dataroom.model import (
    CheckedFact,
    Chip,
    CompositionRow,
    DissolutionView,
    F2View,
    Problem,
    ReadTable,
    SolubilityRow,
)
from modeler_project.dataroom.rules import Rules, load_rules
from pbpk_domain.dissolution import Profile, ProfileKey, WeibullFit, f2, fit_weibull, weibull_fraction

CURVE_POINTS = 61       # points of a fitted curve drawn beside the means (0 to the last time)

_PH = re.compile(r"\bpH\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_SOLUBILITY_UNITS = {"mg/ml": 1.0, "g/l": 1.0, "mg/l": 1e-3, "µg/ml": 1e-3, "ug/ml": 1e-3, "mcg/ml": 1e-3,
                     "μg/ml": 1e-3, "ng/ml": 1e-6, "mg/100ml": 1e-2, "g/100ml": 10.0, "% w/v": 10.0}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", text.lower()).strip()


def _ph_of(*texts: str) -> float | None:
    for text in texts:
        if text and (m := _PH.search(text)):
            return float(m.group(1))
    return None


def _decimals(text: str) -> int:
    return len(text.split(".")[1]) if "." in text else 0


def weibull_curve(fit: WeibullFit, last_min: float) -> tuple[tuple[float, float], ...]:
    """The fitted Weibull curve from 0 to the last time (min, % dissolved), for drawing it over the means; none when the
    fit did not converge. The fraction is `pbpk_domain.dissolution.weibull_fraction`, the release PK-Sim's tablet uses."""
    if not fit.converged or fit.t50_min is None or fit.shape is None or last_min <= 0:
        return ()
    import numpy as np

    times = np.linspace(0.0, last_min, CURVE_POINTS)
    percent = 100.0 * weibull_fraction(times, fit.t50_min, fit.shape, fit.lag_min)
    return tuple((round(float(t), 4), round(float(y), 3)) for t, y in zip(times, percent, strict=True))


def _quantity(text: str, units: dict[str, float], *, bare: bool = False) -> float | None:
    """The first number written with one of the units ("900 mL at 37 ± 0.5 °C" -> 900), or, `bare`, a text that is one
    number alone ("75")."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(units, key=len, reverse=True)) + r")\b", text, re.IGNORECASE)
    if m:
        return float(m.group(1)) * units[m.group(2).lower()]
    if bare and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", text or ""):
        return float(text)
    return None


def batch_products(facts: Sequence[CheckedFact]) -> dict[str, str]:
    """Each batch as written (normalised) -> the product the client says it is a batch of."""
    out: dict[str, str] = {}
    for f in facts:
        if f.ok and f.fact.field == "product.batch" and f.fact.product:
            out[_norm(f.fact.value)] = f.fact.product
    return out


def _view_id(table_id: str, group: str) -> str:
    return "ds-" + hashlib.sha256(f"{table_id}|{group}".encode()).hexdigest()[:10]


def dissolution_views(table: ReadTable, *, products: dict[str, str] | None = None,
                      rules: Rules | None = None) -> tuple[list[DissolutionView], list[Problem]]:
    """One profile per group of a dissolution table (a batch, a product, a medium), in any of the three layouts a lab
    writes (a new delivery, 2026-11-24: the second and third read nothing and said nothing):
    - units down and times across (each time a column with its time in the header);
    - times down and units across (a "time" column; each unit a value column);
    - one line per unit and time (a "unit", a "time" and a "value" column; a "batch" or "medium" column groups them).
    A line whose "statistic" cell says mean, SD or RSD is the client's own summary, as a summary line is."""
    rules = rules or load_rules()
    desc = table.description
    products = products or {}
    factor = 60.0 if desc.time_unit.strip().lower() in ("h", "hr", "hour", "hours") else 1.0
    const = {k.lower(): v for k, v in desc.constants.items()}
    medium = const.get("medium", "")
    problems: list[Problem] = []
    # group -> unit -> time (min) -> (number, chip); the units keep the order they are met in
    data: dict[str, dict[tuple, dict[float, tuple[float | None, Chip]]]] = defaultdict(lambda: defaultdict(dict))
    summaries: dict[str, dict[str, dict[float, tuple[str, Chip]]]] = defaultdict(lambda: defaultdict(dict))
    group_medium: dict[str, str] = {}
    untimed = 0
    for row in table.rows:
        one = {c.role: c for c in row.cells if c.role in ("unit", "time", "batch", "medium", "statistic")}
        row_time = parse_number(one["time"].text, decimal_comma=table.decimal_comma) if "time" in one else None
        row_group = " · ".join(one[r].text.strip() for r in ("batch", "medium") if r in one and one[r].text.strip())
        statistic = one["statistic"].text.strip().lower().rstrip(":") if "statistic" in one else ""
        summary = (row.summary or ("mean" if statistic in ("mean", "avg", "average") else
                                   statistic if statistic in ("sd", "rsd", "%rsd", "rsd%", "cv", "cv%") else "")).lower()
        for c in (c for c in row.cells if c.role == "value"):
            t = c.time if c.time is not None else row_time
            group = c.group or row_group
            if "medium" in one and one["medium"].text.strip():
                group_medium[group] = one["medium"].text.strip()
            if t is None:
                untimed += 1
                continue
            if summary:
                summaries[group][summary][t * factor] = (c.text, c.chip)
                continue
            number = parse_number(c.text, decimal_comma=table.decimal_comma)
            if number is None and c.text.strip():
                problems.append(Problem(code="UNREADABLE_VALUE", where=c.chip,
                                        message=f"line {row.line}: {c.text!r} is not a percentage dissolved"))
            # the unit a value belongs to: its line (times across), its own unit cell (one line per unit and time), or
            # its column (times down, units across)
            unit = (("line", row.line) if c.time is not None else ("unit", one["unit"].text.strip()) if "unit" in one
                    else ("column", c.chip.cell))
            data[group][unit][t * factor] = (number, c.chip)
    if untimed and not data:
        problems.append(Problem(code="NO_TIME_FOR_VALUES", severity="error", message=(
            f"the dissolution table on {desc.part} of {desc.file}: {untimed} values have no time (none in their column's "
            "header and no time column on their line); no profile is read from it")))
    views: list[DissolutionView] = []
    tol_digit, rsd_tol = rules.dissolution.client_mean_tolerance_last_digit, rules.dissolution.rsd_tolerance_points
    for group, units in data.items():
        unit_keys = list(units)
        by_time: dict[float, list[tuple[float | None, Chip]]] = {
            t: [units[u][t] for u in unit_keys if t in units[u]] for t in sorted({t for u in unit_keys for t in units[u]})}
        empty = [t for t, got in by_time.items() if not any(x is not None for x, _ in got)]
        if empty:
            problems.append(Problem(code="TIME_WITHOUT_VALUES", message=(
                f"{group or 'the profile'}: no unit has a value at {', '.join(f'{t:g}' for t in sorted(empty))} min; left out")))
        times = sorted(t for t in by_time if t not in empty)
        if not times:
            continue
        n_units = len(unit_keys)
        vessels = [tuple(units[u][t][0] if t in units[u] else None for t in times) for u in unit_keys]
        means, sds, chips = [], [], []
        own: list[Problem] = []
        for t in times:
            xs = [x for x, _ in by_time[t] if x is not None]
            means.append(round(statistics.fmean(xs), 4) if xs else float("nan"))
            sds.append(round(statistics.stdev(xs), 4) if len(xs) > 1 else None)
            chips += [chip for _, chip in by_time[t]]
        client_mean: list[float | None] = []
        summary = summaries.get(group, {})
        mean_row = next((summary[k] for k in ("mean", "avg", "average") if k in summary), {})
        rsd_row = next((summary[k] for k in ("rsd", "cv", "%rsd", "rsd%") if k in summary), {})
        for i, t in enumerate(times):
            text, chip = mean_row.get(t, ("", None))
            theirs = parse_number(text, decimal_comma=table.decimal_comma) if text else None
            client_mean.append(theirs)
            if theirs is not None and abs(theirs - means[i]) > tol_digit * 10 ** -_decimals(text) + 1e-9:
                own.append(Problem(code="MEAN_ROW_DIFFERS", where=chip, message=(
                    f"{t:g} min: the client's mean {text} %, the units' mean {means[i]:.2f} %")))
            rtext, rchip = rsd_row.get(t, ("", None))
            rsd = parse_number(rtext, decimal_comma=table.decimal_comma) if rtext else None
            if rsd is not None and sds[i] is not None and means[i] > 0:
                ours = 100 * sds[i] / means[i]
                if abs(ours - rsd) > rsd_tol + 10 ** -_decimals(rtext):
                    own.append(Problem(code="RSD_ROW_DIFFERS", where=rchip, message=(
                        f"{t:g} min: the client's RSD {rtext} %, the units' {ours:.2f} %")))
        medium = group_medium.get(group) or const.get("medium", "")
        batch = const.get("batch", "") or group.split(" · ")[0]
        product = products.get(_norm(batch), const.get("product", "")) or products.get(_norm(group), "")
        ph = _ph_of(const.get("ph", ""), medium) if not parse_number(const.get("ph", "")) else parse_number(const["ph"])
        volume = _quantity(const.get("volume", "") or medium, {"ml": 1.0, "l": 1000.0}, bare=True)
        rpm = _quantity(const.get("rpm", const.get("speed", "")) or medium, {"rpm": 1.0}, bare=True)
        key = ProfileKey(product=product or batch, role="", batch=batch, apparatus=const.get("apparatus", ""), rpm=rpm,
                         medium=medium, ph=ph, volume_ml=volume)
        profile = Profile(key=key, times_min=tuple(times), vessels=tuple(vessels), mean=tuple(means), sd=tuple(sds), n=n_units)
        fit = fit_weibull(profile)
        early = [m for t, m in zip(times, means, strict=True) if t <= rules.dissolution.very_rapid_within_min]
        very_rapid = bool(early) and max(early) >= rules.dissolution.very_rapid_percent
        plateau = bool(means) and max(means) < rules.dissolution.plateau_below_percent
        if plateau:
            own.append(Problem(code="PLATEAU", severity="info", message=(
                f"the profile levels off at {max(means):.0f} %: a Weibull curve rises to 100 %; a table of the profile "
                "may describe it better (a decision)")))
        views.append(DissolutionView(
            id=_view_id(table.id, group), product=product, batch=batch, medium=medium, ph=ph,
            apparatus=const.get("apparatus", ""), rpm=rpm, volume_ml=volume, n_units=n_units, times_min=tuple(times),
            mean=tuple(means), sd=tuple(sds), client_mean=tuple(client_mean), weibull=fit.to_content(),
            weibull_curve=weibull_curve(fit, times[-1] if times else 0.0),
            very_rapid=very_rapid, plateau=plateau, sources=tuple(chips[:1] + [c for c in (mean_row.get(times[0], ("", None))[1],) if c]),
            problems=tuple(own)))
    return views, problems


def _profile(view: DissolutionView) -> Profile:
    return Profile(key=ProfileKey(product=view.product, role="", batch=view.batch, medium=view.medium, ph=view.ph),
                   times_min=view.times_min, vessels=(), mean=view.mean, sd=view.sd, n=view.n_units)


def _condition(view: DissolutionView) -> tuple:
    return (_norm(view.medium), view.ph, _norm(view.apparatus), view.rpm, view.volume_ml)


def f2_pairs(views: Sequence[DissolutionView], roles: dict[str, str]) -> list[F2View]:
    """f2 for each test product against the reference, and each reformulated product against the original and the
    reference, only between profiles run under the same conditions (medium, pH, apparatus, speed, volume)."""
    against = {"test": ("reference",), "reformulated": ("original", "reference"), "original": ("reference",)}
    out: list[F2View] = []
    for test in views:
        for ref_role in against.get(roles.get(test.product, ""), ()):
            for ref in views:
                if roles.get(ref.product) != ref_role or ref.id == test.id or _condition(ref) != _condition(test):
                    continue
                result = f2(_profile(test), _profile(ref))
                out.append(F2View(test=test.id, reference=ref.id, value=result.value, similar=result.similar,
                                  applicable=result.applicable, reasons=result.reasons))
    return out


def composition_rows(tables: Sequence[ReadTable]) -> list[CompositionRow]:
    """Each component once, its amount per product side by side; a row whose amounts differ is marked changed."""
    rows: dict[str, dict] = {}
    for table in tables:
        about = table.description.about
        for row in table.rows:
            one = {c.role: c for c in row.cells if c.role in ("component", "function")}
            if "component" not in one or not one["component"].text.strip():
                continue
            name = one["component"].text.strip()
            entry = rows.setdefault(_norm(name), {"component": name, "function": "", "amounts": {}, "sources": []})
            if "function" in one and one["function"].text.strip():
                entry["function"] = entry["function"] or one["function"].text.strip()
            for c in row.cells:
                if c.role in ("amount", "percent") and c.text.strip():
                    product = c.group or about or "product"
                    entry["amounts"][product + (" (%)" if c.role == "percent" else "")] = c.text.strip()
                    entry["sources"].append(c.chip)
    out = []
    for entry in rows.values():
        mg = {k: v for k, v in entry["amounts"].items() if not k.endswith("(%)")}
        values = {parse_number(v) for v in mg.values()}
        changed = len(mg) > 1 and len(values) > 1
        out.append(CompositionRow(component=entry["component"], function=entry["function"], amounts=entry["amounts"],
                                  changed=changed, sources=tuple(entry["sources"][:4])))
    return out


def _mg_per_ml(value: float, unit: str) -> float | None:
    u = unit.strip().lower().replace(" ", "").replace("μ", "µ")
    for k, f in _SOLUBILITY_UNITS.items():
        if u == k.replace(" ", ""):
            return value * f
    return None


def solubility_rows(tables: Sequence[ReadTable], *, dose_mg: float | None, medium_volume_ml: float | None = None,
                    rules: Rules | None = None) -> tuple[list[SolubilityRow], list[Problem]]:
    """Solubility per medium or pH, with the volume the dose needs and the share of the dose that dissolves in a glass
    of water and in the dissolution medium."""
    rules = rules or load_rules()
    out, problems = [], []
    glass = rules.solubility.glass_volume_ml
    for table in tables:
        unit = table.description.value_unit
        for row in table.rows:
            one = {c.role: c for c in row.cells}
            if "solubility" not in one or not one["solubility"].text.strip():
                continue
            text = one["solubility"].text.strip()
            number = parse_number(text, decimal_comma=table.decimal_comma)
            col_unit = one["solubility"].unit or unit
            mg_ml = _mg_per_ml(number, col_unit) if number is not None else None
            if number is not None and mg_ml is None:
                problems.append(Problem(code="UNIT_UNKNOWN", where=one["solubility"].chip,
                                        message=f"line {row.line}: solubility unit {col_unit!r} is not one code converts"))
            medium = one["medium"].text.strip() if "medium" in one else ""
            ph = parse_number(one["ph"].text, decimal_comma=table.decimal_comma) if "ph" in one else _ph_of(medium)
            need = round(dose_mg / mg_ml, 2) if dose_mg and mg_ml else None
            out.append(SolubilityRow(
                medium=medium, ph=ph, solubility_mg_ml=mg_ml, as_written=f"{text} {col_unit}".strip(),
                volume_for_dose_ml=need, fraction_in_glass=round(min(1.0, mg_ml * glass / dose_mg), 4) if need else None,
                fraction_in_medium=(round(min(1.0, mg_ml * medium_volume_ml / dose_mg), 4)
                                    if need and medium_volume_ml else None),
                sources=(one["solubility"].chip,)))
    return out, problems


def solubility_from_facts(facts: Sequence[CheckedFact], *, dose_mg: float | None, medium_volume_ml: float | None = None,
                          rules: Rules | None = None) -> list[SolubilityRow]:
    """Solubility values stated as facts ("0.20 mg/mL in water at 37 °C"), as rows beside the tables' rows, so the
    reference solubility is chosen among all of them."""
    rules = rules or load_rules()
    glass = rules.solubility.glass_volume_ml
    out = []
    for f in facts:
        if f.number is None:
            continue
        mg_ml = _mg_per_ml(f.number, f.fact.unit) if f.fact.unit else None
        text = f"{f.fact.subject} {f.fact.value} {f.fact.quote}"      # the medium's pH: not from the agent's note
        need = round(dose_mg / mg_ml, 2) if dose_mg and mg_ml else None
        out.append(SolubilityRow(
            medium=(f.fact.subject or "as stated").strip(), ph=_ph_of(text), solubility_mg_ml=mg_ml,
            as_written=f"{f.fact.value} {f.fact.unit}".strip(), volume_for_dose_ml=need,
            fraction_in_glass=round(min(1.0, mg_ml * glass / dose_mg), 4) if need else None,
            fraction_in_medium=round(min(1.0, mg_ml * medium_volume_ml / dose_mg), 4) if need and medium_volume_ml else None,
            sources=(f.chip,) if f.chip else ()))
    return out
