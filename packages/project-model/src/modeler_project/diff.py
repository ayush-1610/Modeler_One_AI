"""Field-level differences between two JSON documents, for edit previews and version history (plan §13.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_MISSING = object()


@dataclass(frozen=True)
class Change:
    path: str          # dotted path; list items as [i]
    before: Any        # None when added
    after: Any         # None when removed
    kind: str          # "added" | "removed" | "changed"


def _walk(path: str, a: Any, b: Any, out: list[Change]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            sub = f"{path}.{key}" if path else str(key)
            _walk(sub, a.get(key, _MISSING), b.get(key, _MISSING), out)
        return
    if isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            _walk(f"{path}[{i}]", a[i] if i < len(a) else _MISSING, b[i] if i < len(b) else _MISSING, out)
        return
    if a is _MISSING and b is _MISSING:
        return
    if a is _MISSING:
        out.append(Change(path, None, b, "added"))
    elif b is _MISSING:
        out.append(Change(path, a, None, "removed"))
    elif a != b:
        out.append(Change(path, a, b, "changed"))


def diff(before: Any, after: Any) -> list[Change]:
    """Every leaf that differs between `before` and `after`, in a stable order."""
    out: list[Change] = []
    _walk("", before, after, out)
    return out
