"""Locked files change only deliberately (CLAUDE.md "Locked files"; docs/ARCHITECTURE_BOUNDARIES.md).

docs/architecture/locked-files.json lists the locked patterns (owner, layer, reason) and the SHA-256 of every file
they cover. This test fails when a locked file's bytes change, when a new file appears under a locked pattern, or when
a locked file disappears. A locked file changes only in its own PR with the owner's approval and a CHANGELOG entry;
SME-governed content also stays marked UNVERIFIED and bumps its version. After an approved change:

    UPDATE_LOCKED=1 uv run pytest tests/architecture/test_locked_files.py

rewrites the hashes (the patterns are edited by hand, and only with the owner's approval).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "architecture" / "locked-files.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _covered(patterns: list[dict]) -> dict[str, dict]:
    """Every file a pattern covers -> the first pattern that covers it."""
    out: dict[str, dict] = {}
    for entry in patterns:
        matches = sorted(p for p in ROOT.glob(entry["pattern"])
                         if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
        assert matches, f"locked pattern {entry['pattern']!r} matches no file"
        for path in matches:
            out.setdefault(path.relative_to(ROOT).as_posix(), entry)
    return out


def _sha256(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def test_every_pattern_names_an_owner_a_layer_and_a_reason():
    for entry in _manifest()["patterns"]:
        assert entry["owner"] in ("SME", "core"), entry
        assert entry["layer"] in ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "repo"), entry
        assert entry["reason"].strip(), entry


def test_locked_files_are_unchanged():
    manifest = _manifest()
    covered = _covered(manifest["patterns"])
    if os.environ.get("UPDATE_LOCKED") == "1":
        # one object per file, path and hash on separate lines (a hash beside "auth.py" reads as a key to gitleaks)
        manifest["files"] = [{"path": rel, "sha256": _sha256(rel)} for rel in sorted(covered)]
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    recorded: dict[str, str] = {f["path"]: f["sha256"] for f in manifest["files"]}

    changed = sorted(rel for rel in covered.keys() & recorded.keys() if _sha256(rel) != recorded[rel])
    added = sorted(covered.keys() - recorded.keys())
    removed = sorted(recorded.keys() - covered.keys())

    def owner(rel: str) -> str:
        entry = covered.get(rel)
        return f"{entry['owner']}, {entry['layer']}" if entry else "no longer covered"

    lines = ([f"~ {rel} ({owner(rel)})" for rel in changed] + [f"+ {rel} ({owner(rel)})" for rel in added]
             + [f"- {rel} (missing or no longer covered)" for rel in removed])
    assert not lines, (
        "locked files changed (~ edited, + new under a locked pattern, - gone):\n" + "\n".join(lines)
        + "\nLocked files change only in their own PR with the owner's approval and a CHANGELOG entry (SME-governed "
          "content also stays UNVERIFIED and bumps its version). After approval: "
          "UPDATE_LOCKED=1 uv run pytest tests/architecture/test_locked_files.py")
