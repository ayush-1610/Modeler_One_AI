"""Two analysts' keys of one delivery, compared (plan 2026-11-12 G1, decision 8; contracts §8.1).

Decision 8: a trained analyst fills the key, a second analyst verifies it independently, and their disagreements go to
the scientist, who adjudicates. `compare` lists the disagreements; `render_comparison` writes them for the scientist.
It reads two loaded keys and nothing else.

The rows of the two keys join as the scorer joins a key and a delivery (`value_score`), never on where they say a
value stands: on (study, arm, analyte, matrix, subject, product, batch, vessel, period, conditions, field, time in
minutes), a study under the other names either key's Studies sheet gives it. Inside one join group the rows pair as
multisets: the same value in the same unit first, then the same value in another unit (`unit_differs`), then the rest
in row order (`value_differs`); what is left is `only_a` or `only_b`. A pair that agrees on value and unit but names
another file, sheet or page (a page by its number: "p. 2" is "2"), or table is `where_differs`. A Not data table of
one key that the other does not list is `not_data_differs`. A row whose value or time neither scorer could read is
compared by its text, so every row is compared and none is dropped. Beyond §8.1's six classes: a pair that agrees on
value, unit and place but not on an attribute either key states (statistic, spread, spread_kind, n, occasion,
sequence) is `attributes_differ`, and a study whose Studies rows differ (its other names, a routing tag, or listed by
one key only) is `studies_differs`, since the tags drive the totals by tag and the names the study joins.

The comparison holds the keys' values and labels: it is read on the server, like the keys, and never sent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from modeler_intake.document_reading import name_key
from modeler_project.value_key import (
    ATTRIBUTE_COLUMNS,
    LABEL_COLUMNS,
    KeyRow,
    Mark,
    Reading,
    ValueKey,
    clean,
    conditions_key,
    file_key,
    key_marks,
    label_key,
    norm_text,
    parse_conditions,
    read_value,
    readings_equal,
    spread_kind_key,
    statistic_key,
    study_groups,
    text_key,
    time_minutes,
    to_decimal,
    unit_key,
    where_key,
)

DIFFERENCES = ("only_a", "only_b", "value_differs", "unit_differs", "where_differs", "not_data_differs")
MORE_DIFFERENCES = ("attributes_differ", "studies_differs")     # beyond §8.1's list (see the module docstring)


def _reading(row: KeyRow, mark: Mark | None) -> Reading:
    reading = read_value(row.field, row.value, mark)
    if reading.kind in ("empty", "unreadable", "ambiguous"):
        return Reading("text", text=norm_text(row.value))
    return reading


def _time(row: KeyRow, mark: Mark | None) -> Any:
    try:
        return time_minutes(row.time, row.time_unit, mark)
    except ValueError:
        return ("as written", norm_text(row.time), norm_text(row.time_unit))


def _where(row: KeyRow | dict[str, str]) -> tuple[str, tuple[str, Any], str]:
    """Where a row or a Not data entry says it stands: its file, its sheet or pages (`where_key`), its table."""
    if isinstance(row, KeyRow):
        return file_key(row.file), where_key(row.where), norm_text(row.table)
    return file_key(row.get("file", "")), where_key(row.get("where", "")), norm_text(row.get("table", ""))


def _attribute(name: str, text: str, mark: Mark | None) -> Any:
    """An attribute as two keys compare it ("" when not stated)."""
    if not clean(text):
        return ""
    if name == "statistic":
        return statistic_key(text)
    if name == "spread_kind":
        return spread_kind_key(text)
    if name in ("spread", "n"):
        number = to_decimal(text, mark)
        return number if number is not None else norm_text(text)
    return label_key(name, text)


def _attributes_differ(x: KeyRow, y: KeyRow, marks_a: dict[int, Mark | None], marks_b: dict[int, Mark | None]
                       ) -> list[str]:
    return [name for name in ATTRIBUTE_COLUMNS
            if _attribute(name, getattr(x, name), marks_a.get(x.row)) != _attribute(name, getattr(y, name), marks_b.get(y.row))]


def _row(row: KeyRow) -> dict[str, Any]:
    return {"row": row.row, "field": row.field, "value": row.value, "unit": row.unit, "time": row.time,
            "time_unit": row.time_unit, "file": row.file, "where": row.where, "table": row.table,
            "labels": {c: getattr(row, c) for c in (*LABEL_COLUMNS, "conditions") if getattr(row, c)},
            "attributes": {c: getattr(row, c) for c in ATTRIBUTE_COLUMNS if getattr(row, c)}}


def _pair(open_a: list[KeyRow], open_b: list[KeyRow], test: Callable[[KeyRow, KeyRow], bool]) -> list[tuple[KeyRow, KeyRow]]:
    """Pair each row of A, in row order, with the first open row of B that passes `test`; both leave the open lists."""
    pairs = []
    for x in list(open_a):
        y = next((y for y in open_b if test(x, y)), None)
        if y is not None:
            open_a.remove(x)
            open_b.remove(y)
            pairs.append((x, y))
    return pairs


def compare(a: ValueKey, b: ValueKey) -> dict[str, Any]:
    """The disagreements of two keys (see the module docstring): each list holds rows as the keys write them, a pair
    with both rows (`a`, `b`); `agree` counts the rows that pair with no difference. Identical keys give empty lists."""
    groups_of = study_groups(a, b)
    marks_a, marks_b = key_marks(a.rows), key_marks(b.rows)

    def join(row: KeyRow, marks: dict[int, Mark | None]) -> tuple[Any, ...]:
        labels = tuple(groups_of.get(name_key(row.study), name_key(row.study)) if c == "study"
                       else label_key(c, getattr(row, c)) for c in LABEL_COLUMNS)
        return (*labels, conditions_key(parse_conditions(row.conditions) if row.conditions else {}), row.field,
                _time(row, marks.get(row.row)))

    groups: dict[tuple[Any, ...], tuple[list[KeyRow], list[KeyRow]]] = {}
    for side, key, marks in ((0, a, marks_a), (1, b, marks_b)):
        for row in key.rows:
            groups.setdefault(join(row, marks), ([], []))[side].append(row)

    out: dict[str, Any] = {name: [] for name in (*DIFFERENCES, *MORE_DIFFERENCES)}
    agree = 0
    for rows_a, rows_b in groups.values():
        open_a, open_b = list(rows_a), list(rows_b)

        def same_value(x: KeyRow, y: KeyRow) -> bool:
            return readings_equal(_reading(x, marks_a.get(x.row)), _reading(y, marks_b.get(y.row)))

        def same_unit(x: KeyRow, y: KeyRow) -> bool:
            return unit_key(x.field, x.unit) == unit_key(y.field, y.unit)

        def same_place(x: KeyRow, y: KeyRow) -> bool:
            return same_value(x, y) and same_unit(x, y) and _where(x) == _where(y)

        for x, y in _pair(open_a, open_b, lambda x, y: same_place(x, y) and not _attributes_differ(x, y, marks_a, marks_b)):
            agree += 1
        for x, y in _pair(open_a, open_b, same_place):
            out["attributes_differ"].append({"a": _row(x), "b": _row(y),
                                             "attributes": _attributes_differ(x, y, marks_a, marks_b)})
        for x, y in _pair(open_a, open_b, lambda x, y: same_value(x, y) and same_unit(x, y)):
            out["where_differs"].append({"a": _row(x), "b": _row(y)})
        for x, y in _pair(open_a, open_b, same_value):
            out["unit_differs"].append({"a": _row(x), "b": _row(y)})
        for x, y in _pair(open_a, open_b, lambda x, y: True):
            out["value_differs"].append({"a": _row(x), "b": _row(y)})
        out["only_a"] += [_row(x) for x in open_a]
        out["only_b"] += [_row(y) for y in open_b]

    def tables(key: ValueKey) -> dict[tuple[Any, ...], dict[str, str]]:
        return {_where(n): n for n in key.not_data}

    nd_a, nd_b = tables(a), tables(b)
    out["not_data_differs"] = ([{"side": "a", **n} for w, n in nd_a.items() if w not in nd_b]
                               + [{"side": "b", **n} for w, n in nd_b.items() if w not in nd_a])
    out["studies_differs"] = _studies_differ(a, b, groups_of)
    for name in ("only_a", "only_b"):
        out[name].sort(key=lambda r: r["row"])
    for name in ("value_differs", "unit_differs", "where_differs", "attributes_differ"):
        out[name].sort(key=lambda p: p["a"]["row"])
    return {"a": {"analyst": a.analyst, "status": a.status, "date": a.date, "rows": len(a.rows)},
            "b": {"analyst": b.analyst, "status": b.status, "date": b.date, "rows": len(b.rows)},
            "agree": agree, **out}


def _studies_differ(a: ValueKey, b: ValueKey, groups_of: dict[str, str]) -> list[dict[str, Any]]:
    """The studies whose Studies rows differ between two keys: listed by one key only, other names (by name_key) or a
    routing tag (a choice by the one it states, other text case and spacing aside) that differ."""
    def rows(key: ValueKey) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for study in key.studies:
            canonical = groups_of.get(name_key(study["study"]), name_key(study["study"]))
            out.setdefault(canonical, study)
        return out

    def names(study: dict[str, str]) -> set[str]:
        return ({name_key(study.get("study", ""))} | {name_key(n) for n in study.get("names", "").split(";")}) - {""}

    rows_a, rows_b = rows(a), rows(b)
    out = []
    for canonical in sorted(set(rows_a) | set(rows_b)):
        x, y = rows_a.get(canonical), rows_b.get(canonical)
        item: dict[str, Any] = {"study": (x or y or {}).get("study", ""), "row_a": (x or {}).get("row"),
                                "row_b": (y or {}).get("row")}
        if x is None or y is None:
            out.append({**item, "only": "a" if y is None else "b"})
            continue
        tags = [t for t in dict.fromkeys([*x, *y]) if t not in ("study", "names", "row")]
        differ = {t: [x.get(t, ""), y.get(t, "")] for t in tags
                  if text_key(t, x.get(t, "")) != text_key(t, y.get(t, ""))}
        if names(x) != names(y):
            item["names"] = [x.get("names", ""), y.get("names", "")]
        if differ:
            item["tags"] = differ
        if "names" in item or differ:
            out.append(item)
    return out


def _cell(text: Any) -> str:
    return str("" if text is None else text).replace("|", "\\|").replace("\n", " ")


def _what(r: dict[str, Any]) -> str:
    labels = ", ".join(f"{k} {v}" for k, v in r["labels"].items())
    time = f" at {r['time']} {r['time_unit']}".rstrip() if r["time"] else ""
    return f"{r['field']}{time}" + (f" ({labels})" if labels else "")


def _value(r: dict[str, Any]) -> str:
    return f"{r['value']} {r['unit']}".strip()


def _attributes(r: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in r.get("attributes", {}).items())


def _study_difference(s: dict[str, Any]) -> str:
    if "only" in s:
        return f"listed by key {s['only'].upper()} only"
    parts = [f"names: {s['names'][0] or '(none)'} / {s['names'][1] or '(none)'}"] if "names" in s else []
    parts += [f"{tag}: {a or '(none)'} / {b or '(none)'}" for tag, (a, b) in s.get("tags", {}).items()]
    return "; ".join(parts)


def _place(r: dict[str, Any]) -> str:
    return " / ".join(x for x in (r["file"], r["where"], r["table"]) if x)


def render_comparison(result: dict[str, Any]) -> str:
    """The disagreements as Markdown for the scientist: each with both analysts' rows (row numbers, values, units,
    places), so a decision can be written into the adjudicated key. It holds values: read it on the server only."""
    a, b = result["a"], result["b"]
    counts = {name: len(result.get(name, [])) for name in (*DIFFERENCES, *MORE_DIFFERENCES)}
    lines = ["# Two keys compared", "",
             "**Holds the keys' values: read on the server only; never send it.**", "",
             (f"A: {a['analyst'] or 'analyst not named'}, {a['status']}, {a['date']}, {a['rows']} rows. "
              f"B: {b['analyst'] or 'analyst not named'}, {b['status']}, {b['date']}, {b['rows']} rows."), "",
             f"{result['agree']} rows agree; " + ", ".join(f"{n} {name.replace('_', ' ')}" for name, n in counts.items())
             + ".", ""]
    if not any(counts.values()):
        lines.append("The two keys agree on every row.")
        return "\n".join(lines) + "\n"

    def table(title: str, head: list[str], rows: list[list[Any]]) -> None:
        if not rows:
            return
        lines.extend([f"## {title}", "", "| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"])
        lines.extend("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)
        lines.append("")

    table("Values differ", ["row A", "row B", "what", "A", "B"],
          [[p["a"]["row"], p["b"]["row"], _what(p["a"]), _value(p["a"]), _value(p["b"])] for p in result["value_differs"]])
    table("Units differ", ["row A", "row B", "what", "A", "B"],
          [[p["a"]["row"], p["b"]["row"], _what(p["a"]), _value(p["a"]), _value(p["b"])] for p in result["unit_differs"]])
    table("Same value, another place", ["row A", "row B", "what", "A's place", "B's place"],
          [[p["a"]["row"], p["b"]["row"], _what(p["a"]), _place(p["a"]), _place(p["b"])] for p in result["where_differs"]])
    table("Only in A", ["row", "what", "value", "place"],
          [[r["row"], _what(r), _value(r), _place(r)] for r in result["only_a"]])
    table("Only in B", ["row", "what", "value", "place"],
          [[r["row"], _what(r), _value(r), _place(r)] for r in result["only_b"]])
    table("Attributes differ", ["row A", "row B", "what", "attributes", "A", "B"],
          [[p["a"]["row"], p["b"]["row"], _what(p["a"]), ", ".join(p["attributes"]), _attributes(p["a"]),
            _attributes(p["b"])] for p in result.get("attributes_differ", [])])
    table("Studies differ", ["study", "Studies row A", "Studies row B", "what differs"],
          [[s["study"], s["row_a"] or "", s["row_b"] or "", _study_difference(s)] for s in result.get("studies_differs", [])])
    table("Not data, listed by one key only", ["key", "row", "file", "where", "table", "reason"],
          [[n["side"].upper(), n.get("row", ""), n.get("file", ""), n.get("where", ""), n.get("table", ""),
            n.get("reason", "")] for n in result["not_data_differs"]])
    return "\n".join(lines) + "\n"
