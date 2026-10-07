"""The HTTP contract the web app and the T-56 kit rely on (docs/ARCHITECTURE_BOUNDARIES.md, phase 1).

The API's OpenAPI document is compared with the committed snapshot docs/api/openapi.json, so a renamed field, a
removed route or a changed request model shows up in review instead of as a runtime failure in the browser. When the
change is intended, rewrite the snapshot and record the change in CHANGELOG.md:

    UPDATE_SNAPSHOTS=1 uv run pytest tests/architecture/test_openapi_contract.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "docs" / "api" / "openapi.json"
_METHODS = {"get", "put", "post", "delete", "patch", "head", "options"}


def _render(spec: dict) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _operations(spec: dict) -> dict[str, dict]:
    return {f"{m.upper()} {path}": op for path, item in spec.get("paths", {}).items()
            for m, op in item.items() if m in _METHODS}


def _differences(old: dict, new: dict) -> list[str]:
    lines = []
    for label, a, b in (("operation", _operations(old), _operations(new)),
                        ("schema", old.get("components", {}).get("schemas", {}),
                         new.get("components", {}).get("schemas", {}))):
        lines += [f"+ {label} {k}" for k in sorted(b.keys() - a.keys())]
        lines += [f"- {label} {k}" for k in sorted(a.keys() - b.keys())]
        lines += [f"~ {label} {k}" for k in sorted(a.keys() & b.keys()) if a[k] != b[k]]
    rest = {k for k in old.keys() | new.keys() if k not in ("paths", "components") and old.get(k) != new.get(k)}
    lines += [f"~ {k}" for k in sorted(rest)]
    return lines


def test_openapi_matches_the_committed_contract():
    from modeler_api.main import app

    current = json.loads(_render(app.openapi()))   # normalised exactly as the snapshot is written
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(_render(current), encoding="utf-8")
    assert SNAPSHOT.is_file(), f"no snapshot yet: run UPDATE_SNAPSHOTS=1 uv run pytest {Path(__file__).name}"
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    diff = _differences(committed, current)
    assert not diff and committed == current, (
        "the API contract changed (+ added, - removed, ~ changed):\n" + "\n".join(diff[:60])
        + ("\n…" if len(diff) > 60 else "")
        + "\nIf intended: UPDATE_SNAPSHOTS=1 uv run pytest tests/architecture/test_openapi_contract.py, "
          "and say what changed for clients in CHANGELOG.md.")
