"""In vitro data from the cells code read (plan 2026-11-21 v2 §8 "Dissolution", "Solubility"): dissolution profiles
per product, batch and medium (mean and spread from the units, checked against the client's own mean row), f2 where it
applies, a Weibull fit on every profile; composition side by side; solubility with the volume the dose needs.

The science checks of plan 2026-11-24 §8 (thresholds in `dataroom_rules.yaml`, UNVERIFIED; f2's unit count read from
the locked dissolution ruleset, never copied):
- dissolution (feature 7): fewer units than f2 needs, a bell shape, a likely disintegration lag, the batches of one
  product tested by different methods;
- which step limits absorption (feature 8): the dose number per medium (Amidon 1995: Do = dose / (250 mL × Cs)) and
  the sink index of each dissolution medium (Cs × V / dose);
- excipients by function (feature 9): each component's functional class, its mg per unit, and a test-versus-reference
  difference within a class, for the SME to judge.
"""

from __future__ import annotations

import hashlib
import math
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence

from modeler_project.dataroom.extract import is_bound, parse_number, unreadable
from modeler_project.dataroom.model import (
    CheckedFact,
    Chip,
    CompositionRow,
    DissolutionView,
    DoseNumber,
    F2View,
    LimitingStep,
    Problem,
    ReadTable,
    SolubilityRow,
)
from modeler_project.dataroom.rules import Rules, load_rules
from pbpk_domain.dissolution import Profile, ProfileKey, WeibullFit, f2, fit_weibull, weibull_fraction
from pbpk_domain.dissolution import load_rules as dissolution_ruleset

CURVE_POINTS = 61       # points of a fitted curve drawn beside the means (0 to the last time)

_PH = re.compile(r"\bpH\s*[=:]?\s*([0-9]+(?:[.,][0-9]+)?)", re.IGNORECASE)    # "pH 6.8", "pH 4,5", "pH = 1.2"
# a solubility medium as files name it (the fact's subject may be the substance instead: a new delivery, 2026-11-24)
_MEDIUM = re.compile(r"(?i)\bpH\s*[=:]?\s*\d|buffer|\bhcl\b|water|fassif|fessif|fassgf|\bsgf\b|\bsif\b|acetate|"
                     r"phosphate|citrate|simulated|media\b|medium\b")
_SOLUBILITY_UNITS = {"mg/ml": 1.0, "g/l": 1.0, "mg/l": 1e-3, "µg/ml": 1e-3, "ug/ml": 1e-3, "mcg/ml": 1e-3,
                     "μg/ml": 1e-3, "ng/ml": 1e-6, "mg/100ml": 1e-2, "g/100ml": 10.0, "% w/v": 10.0}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", text.lower()).strip()


def _ph_of(*texts: str) -> float | None:
    for text in texts:
        if text and (m := _PH.search(text)):
            return float(m.group(1).replace(",", "."))
    return None


def _medium_of(subject: str, quote: str) -> str:
    """A solubility fact's medium: its subject when that names a medium, else the part of the quote that does ("in 0.1 N
    HCl"), else the subject as written; never the substance's name taken for a medium."""
    subject = subject.strip()
    if _MEDIUM.search(subject):
        return subject
    for piece in re.split(r"[,;:()]", quote):
        if _MEDIUM.search(piece):
            return piece.strip()
    return subject or "as stated"


def _unit_in(text: str) -> str:
    """A solubility unit written in a column's header ("Solubility (mg/mL)"): the table was described without it."""
    low = text.lower().replace(" ", "")
    return next((u for u in sorted(_SOLUBILITY_UNITS, key=len, reverse=True) if u.replace(" ", "") in low), "")


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


def named_in(label: str, names: Iterable[str]) -> str | None:
    """The one of `names` a label means, however the files write them: the same words ("NP-R-2201" and "np r 2201"), or a
    name written whole inside the label ("Tablet, Lot NP-R-2201"; "Zelitrex 10 mg tablet, batch ZT-R-118" for
    "Zelitrex 10 mg tablet"); the longest such name; None when none or two equally long ones (a new delivery,
    2026-11-24: exact strings left 5 f2 values uncomputed and said nothing)."""
    want = f" {_norm(label)} "
    by_norm = {_norm(n): n for n in names if _norm(n)}
    if want.strip() in by_norm:
        return by_norm[want.strip()]
    inside = sorted((k for k in by_norm if f" {k} " in want or f" {want.strip()} " in f" {k} "), key=len, reverse=True)
    if not inside or (len(inside) > 1 and len(inside[0]) == len(inside[1])):
        return None
    return by_norm[inside[0]]


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
                code, message = unreadable(row.line, c.text, "percentage dissolved")
                problems.append(Problem(code=code, where=c.chip, message=message))
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
        product = (products.get(_norm(batch), const.get("product", "")) or products.get(_norm(group), "")
                   or products.get(_norm(named_in(group, products) or ""), ""))
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
        own += profile_checks(times, means, n_units, rules)
        views.append(DissolutionView(
            id=_view_id(table.id, group), product=product, batch=batch, medium=medium, ph=ph,
            ph_convention=rules.convention_ph(medium) if ph is None else None,
            apparatus=const.get("apparatus", ""), rpm=rpm, volume_ml=volume, n_units=n_units, times_min=tuple(times),
            mean=tuple(means), sd=tuple(sds), client_mean=tuple(client_mean), weibull=fit.to_content(),
            weibull_curve=weibull_curve(fit, times[-1] if times else 0.0),
            very_rapid=very_rapid, plateau=plateau, sources=tuple(chips[:1] + [c for c in (mean_row.get(times[0], ("", None))[1],) if c]),
            problems=tuple(own)))
    return views, problems


def profile_checks(times: Sequence[float], means: Sequence[float], n_units: int, rules: Rules) -> list[Problem]:
    """A profile's own checks (plan 2026-11-24 §8 feature 7; the PBBM review's pitfalls, docs/research/2026-11-24-pbbm-
    absorption-inputs.md §3): fewer units than f2 needs (the locked dissolution ruleset's `f2.min_units`, read here),
    a mean falling below an earlier one (a bell shape), and near-zero dissolution at the first time point(s) (a likely
    disintegration lag). Thresholds: `dataroom_rules.yaml` dissolution, UNVERIFIED."""
    out: list[Problem] = []
    ruleset = dissolution_ruleset()
    need = ruleset["f2"]["min_units"]
    if n_units < need:
        out.append(Problem(code="FEWER_UNITS", message=(
            f"{n_units} units; f2 needs at least {need} per profile ({ruleset['id']} {ruleset['version']}, "
            f"{ruleset['status']}): no f2 with this profile until {need} units are tested")))
    cfg = rules.dissolution
    best_t, best = None, float("-inf")
    for t, m in zip(times, means, strict=True):
        if math.isnan(m):               # a time with no value
            continue
        if best_t is not None and m < best - cfg.bell_drop_points:
            out.append(Problem(code="BELL_SHAPE", message=(
                f"the mean falls from {best:.1f} % at {best_t:g} min to {m:.1f} % at {t:g} min, more than "
                f"{cfg.bell_drop_points:g} points: a bell shape, possibly degradation or a form change in the vessel; "
                "a stability check in the medium would tell")))
            break
        if m > best:
            best_t, best = t, m
    early = [(t, m) for t, m in zip(times, means, strict=True) if t > 0 and not math.isnan(m)]
    low = []
    for t, m in early:
        if m >= cfg.lag_below_percent:
            break
        low.append((t, m))
    if low and len(low) < len(early):
        said = ", ".join(f"{m:.1f} % at {t:g} min" for t, m in low)
        out.append(Problem(code="DISINTEGRATION_LAG", severity="info", message=(
            f"{said}, below {cfg.lag_below_percent:g} %: a likely disintegration lag; remove it before fitting a "
            "particle model (the Weibull fit's lag time may hold it)")))
    return out


def _method(view: DissolutionView) -> str:
    parts = [view.medium or "medium not stated", f"pH {view.ph:g}" if view.ph is not None and str(view.ph) not in view.medium
             else "", view.apparatus, f"{view.rpm:g} rpm" if view.rpm is not None else "",
             f"{view.volume_ml:g} mL" if view.volume_ml is not None else ""]
    return ", ".join(x for x in parts if x)


def method_checks(views: Sequence[DissolutionView]) -> list[Problem]:
    """The batches of one product tested by different methods (apparatus, speed, volume or medium differ): said once
    per product (plan 2026-11-24 §8 feature 7; the PBBM review: a fluconazole case judged of limited value for it)."""
    out: list[Problem] = []
    by_product: dict[str, dict[str, set[tuple]]] = defaultdict(lambda: defaultdict(set))
    words: dict[tuple, str] = {}
    for v in views:
        if not v.batch:
            continue
        key = _condition(v)
        by_product[v.product or v.batch][v.batch].add(key)
        words.setdefault(key, _method(v))
    for product, batches in by_product.items():
        if len(batches) < 2 or len({frozenset(x) for x in batches.values()}) == 1:
            continue
        said = "; ".join(f"batch {b}: " + " / ".join(sorted(words[k] for k in keys)) for b, keys in sorted(batches.items()))
        out.append(Problem(code="DISSOLUTION_METHODS_DIFFER", message=(
            f"the batches of {product} were not tested by the same methods ({said}): a profile compares with another "
            "only under the same apparatus, speed, volume and medium; ask for the missing runs")))
    return out


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


_MASS_UNIT = re.compile(r"(?i)(?<![a-zµμ])(mg|g|µg|μg|ug|mcg)(?![a-z])(?!\s*/\s*(?:ml|l)\b)")
_MG = {"mg": 1.0, "g": 1000.0, "µg": 1e-3, "μg": 1e-3, "ug": 1e-3, "mcg": 1e-3}
_ACTIVE = re.compile(r"(?i)\bactive\b|\bapi\b|drug\s+substance|active\s+ingredient")


def mg_of(text: str, *units: str) -> float | None:
    """An amount in mg when the files state a mass unit: in the cell ("12.5 mg"), the column's unit or its header
    ("mg/tablet"); a percentage or an amount with no unit stays as written (None)."""
    if "%" in text:
        return None
    number = parse_number(re.sub(r"(?i)\s*(mg|g|µg|μg|ug|mcg)\b.*$", "", text.strip()))
    if number is None:
        return None
    for where in (text, *units):
        if where and "%" not in where and (m := _MASS_UNIT.search(where)):
            return round(number * _MG[m.group(1).lower()], 6)
    return None


def composition_rows(tables: Sequence[ReadTable], rules: Rules | None = None) -> list[CompositionRow]:
    """Each component once, its amount per product side by side; a row whose amounts differ is marked changed. Each
    component has its functional class (`dataroom_rules.yaml` excipient_classes, by its name, else by the function
    written beside it; "active" for the drug substance) and its mg per unit where the files state mg."""
    rules = rules or load_rules()
    rows: dict[str, dict] = {}
    for table in tables:
        about = table.description.about
        for row in table.rows:
            one = {c.role: c for c in row.cells if c.role in ("component", "function")}
            if "component" not in one or not one["component"].text.strip():
                continue
            name = one["component"].text.strip()
            entry = rows.setdefault(_norm(name), {"component": name, "function": "", "amounts": {}, "mg": {}, "sources": []})
            if "function" in one and one["function"].text.strip():
                entry["function"] = entry["function"] or one["function"].text.strip()
            for c in row.cells:
                if c.role in ("amount", "percent") and c.text.strip():
                    product = c.group or about or "product"
                    entry["amounts"][product + (" (%)" if c.role == "percent" else "")] = c.text.strip()
                    entry["sources"].append(c.chip)
                    if c.role == "amount" and (mg := mg_of(c.text, c.unit, c.label, table.description.value_unit)) is not None:
                        entry["mg"][product] = mg
    out = []
    for entry in rows.values():
        mg = {k: v for k, v in entry["amounts"].items() if not k.endswith("(%)")}
        values = {parse_number(v) for v in mg.values()}
        changed = len(mg) > 1 and len(values) > 1
        found = rules.excipient_class(entry["component"], entry["function"])
        if found is not None:
            cls, by, label = found[0].id, found[1], found[0].label
        elif _ACTIVE.search(entry["function"]):
            cls, by, label = "active", "function", "active substance"
        else:
            cls, by, label = "other", "", "other"
        out.append(CompositionRow(component=entry["component"], function=entry["function"], amounts=entry["amounts"],
                                  changed=changed, excipient_class=cls, class_label=label, class_by=by, mg=entry["mg"],
                                  sources=tuple(entry["sources"][:4])))
    return out


_ROLE_WORDS = (("reference", "reference"), ("rld", "reference"), ("innovator", "reference"), ("test", "test"),
               ("reformulat", "reformulated"), ("original", "original"))


def _role_of(product: str, roles: dict[str, str]) -> str:
    card = named_in(product, roles)
    if card:
        return roles[card]
    low = product.lower()
    return next((role for word, role in _ROLE_WORDS if word in low), "")


def excipient_checks(rows: Sequence[CompositionRow], roles: dict[str, str]) -> list[Problem]:
    """A test-versus-reference (and reformulated-versus-original) difference within a functional class (plan 2026-11-24
    §8 feature 9): any difference is said, with the mg per unit; no threshold is set (the rules give none), so each is
    for the SME to judge."""
    products = list(dict.fromkeys(k for r in rows for k in r.amounts if not k.endswith("(%)")))
    of_role: dict[str, str] = {}
    for p in products:
        of_role.setdefault(_role_of(p, roles), p)
    out: list[Problem] = []
    for test_role, ref_role in (("test", "reference"), ("reformulated", "original"), ("reformulated", "reference")):
        test, ref = of_role.get(test_role), of_role.get(ref_role)
        if not test or not ref or test == ref:
            continue
        classes = dict.fromkeys(r.excipient_class for r in rows if r.excipient_class not in ("other", "active", ""))
        for cls in classes:
            members = [r for r in rows if r.excipient_class == cls]

            def said(product: str, members: list[CompositionRow] = members) -> str:
                got = [f"{r.component} {r.amounts[product]}" for r in members if r.amounts.get(product, "").strip()]
                return ", ".join(got) or "none"

            def amount(r: CompositionRow, product: str) -> tuple:
                return (r.mg.get(product), parse_number(r.amounts.get(product, "")), bool(r.amounts.get(product, "").strip()))

            if all(amount(r, test) == amount(r, ref) for r in members):
                continue
            totals = ""
            if all((not r.amounts.get(x, "").strip()) or x in r.mg for r in members for x in (test, ref)):
                t_mg, r_mg = (sum(r.mg.get(x, 0.0) for r in members) for x in (test, ref))
                totals = f" (in all {t_mg:g} mg against {r_mg:g} mg per unit)"
            out.append(Problem(code="EXCIPIENT_CLASS_DIFFERS", message=(
                f"{members[0].class_label}: {test} has {said(test)}; {ref} has {said(ref)}{totals}. A functional "
                "excipient differs between the products; no threshold is set, so it is for the SME to judge")))
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
            col_unit = one["solubility"].unit or unit or _unit_in(one["solubility"].label)
            mg_ml = _mg_per_ml(number, col_unit) if number is not None else None
            if number is not None and mg_ml is None:
                problems.append(Problem(code="UNIT_UNKNOWN", where=one["solubility"].chip,
                                        message=f"line {row.line}: solubility unit {col_unit!r} is not one code converts"))
            medium = one["medium"].text.strip() if "medium" in one else ""
            ph = parse_number(one["ph"].text, decimal_comma=table.decimal_comma) if "ph" in one else _ph_of(medium)
            need = round(dose_mg / mg_ml, 2) if dose_mg and mg_ml else None
            out.append(SolubilityRow(
                medium=medium, ph=ph, ph_convention=rules.convention_ph(medium) if ph is None else None,
                solubility_mg_ml=mg_ml, as_written=f"{text} {col_unit}".strip(),
                volume_for_dose_ml=need, fraction_in_glass=round(min(1.0, mg_ml * glass / dose_mg), 4) if need else None,
                fraction_in_medium=(round(min(1.0, mg_ml * medium_volume_ml / dose_mg), 4)
                                    if need and medium_volume_ml else None),
                dose_number=dose_number(dose_mg, mg_ml, glass), sources=(one["solubility"].chip,)))
    return out, problems


def solubility_from_facts(facts: Sequence[CheckedFact], *, dose_mg: float | None, medium_volume_ml: float | None = None,
                          rules: Rules | None = None) -> list[SolubilityRow]:
    """Solubility values stated as facts ("0.20 mg/mL in water at 37 °C"), as rows beside the tables' rows, so the
    reference solubility is chosen among all of them."""
    rules = rules or load_rules()
    glass = rules.solubility.glass_volume_ml
    out = []
    for f in facts:
        bound = is_bound(f.fact.value)
        if f.number is None and not bound:
            continue
        # a bound ("> 20 mg/mL") is kept as written, with no number: a limit is not the solubility
        mg_ml = _mg_per_ml(f.number, f.fact.unit) if f.fact.unit and f.number is not None else None
        text = f"{f.fact.subject} {f.fact.value} {f.fact.quote}"      # the medium's pH: not from the agent's note
        need = round(dose_mg / mg_ml, 2) if dose_mg and mg_ml else None
        medium = _medium_of(f.fact.subject, f.fact.quote)
        ph = _ph_of(text)
        out.append(SolubilityRow(
            medium=medium.strip(), ph=ph, ph_convention=rules.convention_ph(medium) if ph is None else None,
            solubility_mg_ml=mg_ml,
            as_written=f"{f.fact.value} {f.fact.unit}".strip(), volume_for_dose_ml=need,
            fraction_in_glass=round(min(1.0, mg_ml * glass / dose_mg), 4) if need else None,
            fraction_in_medium=round(min(1.0, mg_ml * medium_volume_ml / dose_mg), 4) if need and medium_volume_ml else None,
            dose_number=dose_number(dose_mg, mg_ml, glass), sources=(f.chip,) if f.chip else ()))
    return out


def dose_number(dose_mg: float | None, solubility_mg_ml: float | None, volume_ml: float) -> float | None:
    """Amidon's dose number, Do = M0 / (V0 · Cs), with V0 the 250 mL glass of water of the BCS (Amidon et al., Pharm Res
    1995;12:413-420): above 1 the dose does not dissolve in it, so solubility may limit absorption."""
    if not dose_mg or not solubility_mg_ml or solubility_mg_ml <= 0:
        return None
    return round(dose_mg / (volume_ml * solubility_mg_ml), 4)


def _limits(x: DoseNumber) -> str:
    where = f"at pH {x.ph:g}" + (f" ({x.medium})" if x.medium else "") if x.ph is not None else f"in {x.medium}"
    return f"solubility may limit absorption {where} (dose number {x.dose_number:.3g})"


def limiting_steps(solubility: Sequence[SolubilityRow], doses: Sequence[tuple[str, float, str, tuple[Chip, ...]]],
                   rules: Rules | None = None) -> list[LimitingStep]:
    """Which step may limit absorption, per product (plan 2026-11-24 §8 feature 8): its dose against each measured
    solubility, as the dose number (`dose_number`), and a plain statement for each medium where it is above 1. `doses`:
    (product, mg, as written, sources); product "" for the drug's one dose. No threshold but the definition's 1."""
    rules = rules or load_rules()
    volume = rules.solubility.glass_volume_ml
    out: list[LimitingStep] = []
    measured = [r for r in solubility if r.solubility_mg_ml]
    if not measured:
        return out
    for product, mg, written, chips in doses:
        numbers = [DoseNumber(medium=r.medium, ph=r.ph, solubility_mg_ml=r.solubility_mg_ml,  # type: ignore[arg-type]
                              dose_number=dose_number(mg, r.solubility_mg_ml, volume))  # type: ignore[arg-type]
                   for r in measured]
        above = [x for x in numbers if x.dose_number > 1]
        statements = [_limits(x) for x in sorted(above, key=lambda x: (x.ph or 0))]
        if not above:
            highest = max(x.dose_number for x in numbers)
            statements = [(f"the dose dissolves in {volume:g} mL in every medium measured (dose numbers up to "
                           f"{highest:.3g}): solubility is unlikely to limit absorption")]
        out.append(LimitingStep(product=product, dose_mg=mg, dose_as_written=written, volume_ml=volume,
                                dose_numbers=tuple(numbers), statements=tuple(statements), sources=chips))
    return out


def sink_index(view: DissolutionView, solubility: Sequence[SolubilityRow], dose_mg: float | None,
               rules: Rules | None = None) -> tuple[float | None, str, Problem | None]:
    """The sink index of a dissolution medium, Cs × V / dose (plan 2026-11-24 §8 feature 8): the solubility measured in
    the same medium (its pH within `solubility.ph_match`, else its name), the vessel's volume and the dose. Below the
    rules' minimum (`dissolution.sink_index_min`, USP <1092>, UNVERIFIED) the profile may show the solubility limit
    rather than the product's release."""
    rules = rules or load_rules()
    if not dose_mg or not view.volume_ml:
        return None, "", None
    by_ph = [r for r in solubility if r.solubility_mg_ml and r.ph is not None and view.ph is not None
             and abs(r.ph - view.ph) <= rules.solubility.ph_match + 1e-9]
    by_name = [r for r in solubility if r.solubility_mg_ml and _norm(r.medium) and view.medium
               and (_norm(r.medium) in _norm(view.medium) or _norm(view.medium) in _norm(r.medium))]
    row = (by_ph or by_name or [None])[0]
    if row is None:
        return None, "", None
    value = round(row.solubility_mg_ml * view.volume_ml / dose_mg, 3)  # type: ignore[operator]
    basis = (f"Cs {row.solubility_mg_ml:g} mg/mL ({row.medium}" + (f", pH {row.ph:g}" if row.ph is not None else "")
             + f") × {view.volume_ml:g} mL / {dose_mg:g} mg")
    problem = None
    if value < rules.dissolution.sink_index_min:
        problem = Problem(code="NOT_SINK", severity="info", message=(
            f"sink index {value:.3g} ({basis}), below {rules.dissolution.sink_index_min:g}: not sink conditions; the "
            "profile may show the solubility limit in the vessel rather than the product's release"))
    return value, basis, problem
