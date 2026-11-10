"""The delivery map in words (plan 2026-11-10, R4): what the reading agent is told about a file before it reads it, and
the one line the reading tray shows for each file.

The map itself is kept by `client_data` (`delivery_map`, `record_delivery_map`): per file, and per sheet of a workbook,
what the file is (study, product, role, strength, batch, fed or fasted, medium, pH), each value quoted from the file
(a page, a cell, or the file's name) and checked by code; and the links between two names of one study, product or
batch across files. The map is context, never a value: every value a reading proposes is still quoted from its own file.
"""

from __future__ import annotations

from typing import Any

# what the delivery pass says about a file, in the order a person reads it
FIELDS = ("study", "product", "role", "strength_mg", "batch", "food_state", "medium", "ph")
_LABEL = {"study": "study", "product": "product", "role": "role", "strength_mg": "strength", "batch": "batch",
          "food_state": "food", "medium": "medium", "ph": "pH"}
MAX_OTHER_FILES = 40


def _value(field: str, fact: dict[str, Any]) -> str:
    value = fact.get("value")
    if field == "strength_mg":
        return f"{value:g} mg" if isinstance(value, (int, float)) else str(value)
    if field == "ph":
        return f"pH {value:g}" if isinstance(value, (int, float)) else str(value)
    return str(value)


def facts_line(facts: dict[str, dict[str, Any]]) -> str:
    """"study 093-26 · TEST · 50 mg · fasted" (the fields in order; empty when none)."""
    return " · ".join(f"{_LABEL[f]} {_value(f, facts[f])}" if f in ("study", "batch", "product") else _value(f, facts[f])
                      for f in FIELDS if f in facts)


def file_line(entry: dict[str, Any]) -> str:
    """One line for a file: its own facts, then each sheet's ("Sheet pH 1.2: medium 0.1 N HCl · pH 1.2")."""
    parts = [facts_line(entry.get("facts", {}))]
    parts += [f"sheet {sheet}: {facts_line(part.get('facts', {}))}" for sheet, part in entry.get("sheets", {}).items()
              if part.get("facts")]
    return "; ".join(p for p in parts if p)


def _quoted(facts: dict[str, dict[str, Any]]) -> list[str]:
    return [f"- {_LABEL[f]}: {_value(f, facts[f])} (“{facts[f].get('quote', '')}”, {facts[f].get('where', '')})"
            for f in FIELDS if f in facts]


def note_for(mapped: dict[str, Any], sid: str, *, sheet: str | None = None) -> str:
    """What the reading agent is told before it reads the file `sid` (or one of its sheets): what the delivery pass
    found in this file, quoted; one line for each other file of the delivery; the names known to be one study, product
    or batch. Empty when the map has nothing."""
    files = mapped.get("files", {})
    lines: list[str] = []
    own = files.get(sid)
    if own:
        facts = dict(own.get("facts", {}))
        if sheet is not None:
            facts.update(own.get("sheets", {}).get(sheet, {}).get("facts", {}))
        if facts:
            lines.append("What this file is, by the delivery pass (each quoted from this file and checked by code):")
            lines += _quoted(facts)
        if sheet is None and own.get("sheets"):
            lines += [f"- sheet {name}: {facts_line(part.get('facts', {}))}" for name, part in own["sheets"].items()
                      if part.get("facts")]
    others = [(entry.get("file", other), file_line(entry)) for other, entry in files.items() if other != sid]
    others = [(name, line) for name, line in others if line]
    if others:
        lines.append("The other files of this delivery:")
        lines += [f"- {name}: {line}" for name, line in others[:MAX_OTHER_FILES]]
        if len(others) > MAX_OTHER_FILES:
            lines.append(f"- and {len(others) - MAX_OTHER_FILES} more")
    links = mapped.get("links", [])
    if links:
        lines.append("Names the files give one study, product or batch: "
                     + "; ".join(f"{' = '.join(link['names'])} ({link['kind']})" for link in links[:30]))
    if not lines:
        return ""
    head = ("The delivery map (context to know which study, product and condition a table belongs to; every value you "
            "propose must still be quoted from this file):")
    return "\n".join([head, *lines])
