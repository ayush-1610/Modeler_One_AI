"""Records stored by an earlier build, read by this one (the server, 2026-11-24: "The campaigns could not be read (The API
answered HTTP 500); 'Running now' is not shown").

A stored record that carries a key this build no longer declares failed the whole list it was in: the typed answer
refuses an unknown key, so one campaign written in an earlier shape took every campaign off the dashboard. A list now
leaves out only the keys it does not know, and a record it still cannot read (a key it needs is missing, a value of the
wrong kind) is named in the answer with why, not answered, so the rest of the list stands. Nothing is written back: the
stored record stays as it was written, and the keys left out are logged with the record's id.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


def _where(loc: tuple[Any, ...]) -> str:
    return ".".join(str(part) for part in loc)


def _drop(record: dict[str, Any], loc: tuple[Any, ...]) -> bool:
    """Remove the key at `loc`. A part of the path that names no key (pydantic adds a union member's name to it) is
    passed over; False when the key is not found."""
    node: Any = record
    for part in loc[:-1]:
        if (isinstance(node, dict) and part in node) or (
                isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node)):
            node = node[part]
    if isinstance(node, dict) and loc and loc[-1] in node:
        del node[loc[-1]]
        return True
    return False


def readable(model: type[BaseModel], data: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """`data` as this build reads it as `model`: (the record without the keys it does not declare, those keys' paths),
    or (None, what still does not read)."""
    if not isinstance(data, dict):
        return None, ["the stored entry is not a record"]
    record = copy.deepcopy(data)
    dropped: list[str] = []
    for _ in range(3):     # one pass removes every unknown key pydantic reports; the rest are safety
        try:
            model.model_validate(record)
            return record, dropped
        except ValidationError as e:
            errors = e.errors()
            others = [f"{_where(err['loc'])}: {err['msg'].lower()}" for err in errors if err["type"] != "extra_forbidden"]
            if others:
                return None, others
            for err in errors:
                if not _drop(record, err["loc"]):
                    return None, [f"{_where(err['loc'])}: a key this version does not know, which could not be left out"]
                dropped.append(_where(err["loc"]))
    return None, ["keys this version does not know, which could not be left out"]


def read_list(model: type[BaseModel], entries: list[Any], kind: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the entries this build reads, each without the keys it does not know; those it cannot read as
    {id, problems}). Both are logged once per read, with the entry's id and never its content."""
    shown: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    for entry in entries:
        record, notes = readable(model, entry)
        ident = str(entry.get("id", "?")) if isinstance(entry, dict) else "?"
        if record is None:
            unreadable.append({"id": ident, "problems": notes})
            log.warning("a stored %s is left out of its list: %s (%s)", kind, ident, "; ".join(notes))
            continue
        if notes:
            log.info("a stored %s is read without keys this version does not know: %s (%s)", kind, ident, ", ".join(notes))
        shown.append(record)
    return shown, unreadable
