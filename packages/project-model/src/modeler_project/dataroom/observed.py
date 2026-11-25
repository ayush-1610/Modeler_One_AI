"""Observed data that know their statistic (plan 2026-11-24 §8 feature 5).

A client's mean concentrations are an arithmetic mean, a geometric mean or a median, with an SD, a CV, an SEM or a
geometric SD beside them, and an n. Comparing an arithmetic mean with a simulated geometric mean is a silent error
(docs/research/2026-11-24-clinical-pk-data-curation.md §5), so code records what the table itself states, from its own
words: the label of a summary line ("Mean", "Geo. mean", "SD", "SEM", "N"), the header of a column ("Mean (SD)"), or a
cell written "12.3 (4.5)" / "12.3 ± 4.5" under such a header. An SEM becomes an SD (SEM × √n) only where the table
states n. "Mean" alone is the arithmetic mean, and the profile says so; a mean whose statistic the table does not state
is said, never assumed.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Sequence

from modeler_project.dataroom.extract import parse_number
from modeler_project.dataroom.model import Chip, ClientMean, ClientMeanPoint, Problem, ReadRow, ReadTable

# the words a table writes for each statistic, the more specific first
_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("geometric_sd", re.compile(r"(?i)geo\w*\.?\s*(?:sd|s\.d\.|std|standard\s+deviation)|\bgsd\b")),
    ("geometric_cv_percent", re.compile(r"(?i)geo\w*\.?\s*(?:%\s*)?cv|\bgcv\b|geo\w*\.?\s*coefficient")),
    ("geometric_mean", re.compile(r"(?i)geo\w*\.?\s*mean|\bgmean\b|\bg\.?\s*mean\b|\bgm\b")),
    ("median", re.compile(r"(?i)\bmedian\b")),
    ("sem", re.compile(r"(?i)\bsem\b|\bs\.e\.m\.?|\bse\b|standard\s+error")),
    ("cv_percent", re.compile(r"(?i)\bcv\b|%\s*cv|cv\s*%|coefficient\s+of\s+variation|\brsd\b")),
    ("sd", re.compile(r"(?i)\bsd\b|\bs\.d\.|std\.?\s*dev|standard\s+deviation")),
    ("range", re.compile(r"(?i)\brange\b|\bmin(?:imum)?\b|\bmax(?:imum)?\b")),
    ("n", re.compile(r"(?i)^\s*n\s*$|^\s*n\s*[=:(]|\bnumber\s+of\s+(?:subjects|values|observations)\b|^\s*count\s*$")),
    ("arithmetic_mean", re.compile(r"(?i)arith\w*\.?\s*mean|\bmean\b|\baverage\b|\bavg\b")),
)
# a column that holds a statistic: "value", or a role named for the statistic (its header still decides)
_VALUE_ROLES = ("value", "mean", "sd", "sem", "cv", "n", "median", "geometric_mean", "geometric_sd")
CENTRAL = ("arithmetic_mean", "geometric_mean", "median")
SPREAD = ("sd", "cv_percent", "sem", "geometric_sd", "geometric_cv_percent", "range")
WORDS = {"arithmetic_mean": "arithmetic mean", "geometric_mean": "geometric mean", "median": "median", "sd": "SD",
         "cv_percent": "CV %", "sem": "SEM", "geometric_sd": "geometric SD", "geometric_cv_percent": "geometric CV %",
         "range": "range", "": "statistic not stated"}
# which spread goes with which central value when a table gives several
_PAIRS = {"arithmetic_mean": ("sd", "sem", "cv_percent", "range"), "geometric_mean": ("geometric_sd", "geometric_cv_percent",
          "cv_percent"), "median": ("range",)}
_N_IN = re.compile(r"(?i)\bn\s*=\s*(\d+)")
_PAIR_CELL = re.compile(r"^\s*([-+]?\d[\d.,]*(?:[eE][-+]?\d+)?)\s*(?:\(\s*([-+]?\d[\d.,]*(?:[eE][-+]?\d+)?)\s*%?\s*\)|"
                        r"±\s*([-+]?\d[\d.,]*(?:[eE][-+]?\d+)?))\s*$")


def is_statistic(text: str) -> bool:
    """A cell that names a statistic ("Mean", "SD", "N", "Geo. mean (CV%)"), not a subject."""
    return kinds_in(text) != (None, None, None)


def kinds_in(label: str) -> tuple[str | None, str | None, int | None]:
    """The central statistic, the spread and an n a label names ("Mean (SD)" → arithmetic mean, SD; "Geo. mean (CV%),
    n = 12"; "SEM"; "N"): its parts before and inside brackets or after "±", each matched alone."""
    central = spread = None
    n_hit = _N_IN.search(label)
    n = int(n_hit.group(1)) if n_hit else None
    for part in re.split(r"[()±/,;]|\bplus\s*/?\s*minus\b", label):
        part = _N_IN.sub("", part).strip()
        if not part:
            continue
        kind = next((k for k, rx in _KINDS if rx.search(part)), None)
        if kind in CENTRAL and central is None:
            central = kind
        elif kind in SPREAD and spread is None:
            spread = kind
        elif kind == "n" and central is None and spread is None and n is None:
            return None, None, -1                              # an n line: its values are the n per time
    return central, spread, n


def _hours(unit: str) -> float:
    from modeler_project.dataroom.clinical import _time_factor

    return _time_factor(unit) or 1.0


def _written(row: ReadRow) -> str:
    """What a summary line's own cells say it is (its label cell: the subject, statistic or treatment column)."""
    for role in ("statistic", "subject", "sequence", "group"):
        text = next((c.text.strip() for c in row.cells if c.role == role and c.text.strip()), "")
        if text and parse_number(text) is None:
            return text
    return ""


def _group(row: ReadRow) -> str:
    return " · ".join(dict.fromkeys(c.text.strip() for c in row.cells if c.role in ("treatment", "period") and c.text.strip()))


class _Lines:
    """One group's statistic lines: kind -> time -> (value, spread from a "12.3 (4.5)" cell, chip)."""

    def __init__(self) -> None:
        self.central: dict[str, dict[float, tuple[float, float | None, Chip]]] = defaultdict(dict)
        self.spread: dict[str, dict[float, tuple[float, Chip]]] = defaultdict(dict)
        self.n: dict[float, int] = {}
        self.written: dict[str, str] = {}
        self.label_n: int | None = None
        self.paired: dict[str, str] = {}                    # central -> the spread its own cells carry


def client_means(table: ReadTable) -> tuple[list[ClientMean], list[Problem]]:
    """The client's mean profiles in a concentrations table: its summary lines (times across), or its lines per time
    whose columns are statistics (times down). Each says the statistic and spread its own words state."""
    desc = table.description
    factor = _hours(desc.time_unit) if desc.time_unit else 1.0
    groups: dict[str, _Lines] = defaultdict(_Lines)

    def take(group: str, label: str, t: float, text: str, chip: Chip, fallback: str = "") -> None:
        central, spread, n = kinds_in(label)
        if central is None and spread is None and n is None and fallback:
            central, spread, n = kinds_in(fallback)
            label = f"{label} (described as {fallback})" if label else fallback
        lines = groups[group]
        if n == -1:
            if (x := parse_number(text, decimal_comma=table.decimal_comma)) is not None:
                lines.n[t] = int(x)
            return
        if n is not None:
            lines.label_n = n
        pair = _PAIR_CELL.match(text)
        value = parse_number(pair.group(1) if pair else text, decimal_comma=table.decimal_comma)
        if value is None:
            return
        second = parse_number(pair.group(2) or pair.group(3), decimal_comma=table.decimal_comma) if pair else None
        if central is not None:
            lines.central[central][t] = (value, second if spread else None, chip)
            lines.written.setdefault(central, label)
            if spread and second is not None:
                lines.paired[central] = spread
                lines.written.setdefault(spread, label)
        elif spread is not None:
            lines.spread[spread][t] = (value, chip)
            lines.written.setdefault(spread, label)
        elif label:
            lines.central[""][t] = (value, None, chip)
            lines.written.setdefault("", label)

    for row in table.rows:
        cells = [c for c in row.cells if c.role in _VALUE_ROLES]
        statistic_cell = any(c.role == "statistic" and c.text.strip() for c in row.cells)
        subject_cell = next((c for c in row.cells if c.role == "subject" and c.text.strip()), None)
        if row.summary or statistic_cell or (subject_cell is not None and is_statistic(subject_cell.text)):
            # a summary line, times across: its own label says the statistic (the description's name as a fallback)
            for c in cells:
                if c.time is not None:
                    take(_group(row) or c.group, _written(row), c.time * factor, c.text, c.chip, fallback=row.summary)
            continue
        time_cell = next((c for c in row.cells if c.role == "time" and c.text.strip()), None)
        if subject_cell is None and time_cell is not None:
            # a line per time, times down: each value column's header says its statistic
            t = parse_number(time_cell.text, decimal_comma=table.decimal_comma)
            if t is None:
                continue
            # columns that name no statistic are one profile's values only when there is one such column (several
            # are subjects or groups side by side, which are not a mean)
            nameless = [c for c in cells if c.role == "value" and not is_statistic(c.label)]
            for c in cells:
                if c in nameless and len(nameless) > 1:
                    continue
                if c.label.strip() or c.role != "value":
                    take(c.group or _group(row), c.label, t * factor, c.text, c.chip,
                         fallback="" if c.role == "value" else c.role.replace("_", " "))
    out: list[ClientMean] = []
    for group, lines in groups.items():
        spreads = dict(lines.spread)
        for central, points in lines.central.items():
            spread = lines.paired.get(central) or next((s for s in _PAIRS.get(central, ()) if s in spreads), None)
            if spread is None and central == "" and spreads:
                spread = next(iter(spreads))
            from_line = spreads.pop(spread, {}) if spread and spread != lines.paired.get(central) else {}
            n_all = lines.label_n
            notes: list[str] = []
            pts = []
            for t in sorted(points):
                value, own, _chip = points[t]
                s = own if own is not None else (from_line[t][0] if t in from_line else None)
                n = lines.n.get(t, n_all)
                sd = s if spread == "sd" else (round(s * math.sqrt(n), 6) if spread == "sem" and s is not None and n else None)
                pts.append(ClientMeanPoint(time_h=round(t, 6), value=value, spread=s, n=n, sd=sd))
            if spread == "sem":
                notes.append("SD = SEM × √n, with the n the table states" if any(p.n for p in pts) else
                             "SEM with no n stated: not turned into an SD")
            if central == "arithmetic_mean" and re.fullmatch(r"(?i)\s*(?:mean|average|avg)\s*(?:\(.*\)|±.*)?\s*",
                                                             lines.written.get(central, "")):
                notes.append("\"Mean\" read as the arithmetic mean (the table does not say geometric)")
            ns = {p.n for p in pts}
            chips = tuple(dict.fromkeys(c for _v, _s, c in points.values()))[:2]
            out.append(ClientMean(group=group, statistic=central, statistic_as_written=lines.written.get(central, ""),
                                  spread=spread or "", spread_as_written=lines.written.get(spread, "") if spread else "",
                                  n=next(iter(ns)) if len(ns) == 1 else None, points=tuple(pts), unit=desc.value_unit,
                                  note="; ".join(notes), sources=chips))
    problems = [Problem(code="STATISTIC_NOT_STATED", where=m.sources[0] if m.sources else None, message=(
        f"the client's mean profile{f' of {m.group}' if m.group else ''} on {desc.part} of {desc.file} "
        f"({m.statistic_as_written!r}) does not say which statistic it is (arithmetic or geometric mean, or median): "
        "ask, before it is compared with a simulation")) for m in out if not m.statistic]
    return out, problems


def statistic_words(mean: ClientMean) -> str:
    """The client's profile in words, exactly as its table states it: "geometric mean ± geometric SD, N = 12"."""
    text = WORDS[mean.statistic]
    if mean.spread:
        text += f" ± {WORDS[mean.spread]}" + (" (SD = SEM × √n)" if mean.spread == "sem" and any(p.sd for p in mean.points)
                                              else "")
    ns = sorted({p.n for p in mean.points if p.n})
    if ns:
        text += f", N = {ns[0]}" if len(ns) == 1 else f", N = {ns[0]}–{ns[-1]}"
    else:
        text += ", N not stated"
    said = " · ".join(x for x in dict.fromkeys((mean.statistic_as_written, mean.spread_as_written)) if x)
    return text + (f" (as the table writes it: {said})" if said else "")


def means_of(tables: Sequence[ReadTable]) -> tuple[list[ClientMean], list[Problem]]:
    out: list[ClientMean] = []
    problems: list[Problem] = []
    for t in tables:
        got, found = client_means(t)
        out += got
        problems += found
    return out, problems
