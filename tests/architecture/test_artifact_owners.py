"""Each artifact kind has one owner module (docs/ARCHITECTURE_BOUNDARIES.md, B3, phase 6).

An artifact's stored content had no owner: a router wrote the MAP and blinding read its signature from the raw JSON, so
a change to one key broke a page nobody had touched. [owners] in boundaries.toml (locked) names the one module that
writes each kind (`ws.commit(ArtifactKind.X, …)`); only the owner modules read stored content raw
(`version.content[…]`, `.content.get(…)`, `**version.content`), everyone else asks the owner. Today's exceptions are
listed under [owner_exceptions]: a new one fails, and so does an exception that no longer occurs, so the lists only
shrink. The read counts are exact, so a module's count is lowered in the change that removes reads.
"""

from __future__ import annotations

import ast
import tomllib
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = tomllib.loads(Path(__file__).with_name("boundaries.toml").read_text())
OWNERS: dict[str, str] = CONFIG["owners"]
EXCEPTIONS = CONFIG["owner_exceptions"]


def _sources() -> list[tuple[str, ast.AST]]:
    members = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["workspace"]["members"]
    out = []
    for member in members:
        src = ROOT / member / "src"
        for path in sorted(p for p in src.rglob("*.py") if "__pycache__" not in p.parts):
            rel = path.relative_to(src).with_suffix("")
            module = ".".join(rel.parts[:-1] if rel.name == "__init__" else rel.parts)
            out.append((module, ast.parse(path.read_text(), filename=str(path))))
    return out


def _writes(tree: ast.AST) -> set[str]:
    """Kinds committed in this module: `<anything>.commit(ArtifactKind.X, ...)`."""
    kinds = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "commit" and node.args:
            kind = node.args[0]
            if isinstance(kind, ast.Attribute) and isinstance(kind.value, ast.Name) and kind.value.id == "ArtifactKind":
                kinds.add(kind.attr.lower())
    return kinds


def _raw_reads(tree: ast.AST) -> int:
    """`x.content[...]`, `x.content.get(...)` and `**x.content`: stored content read without its owner."""
    def is_content(expr: ast.expr) -> bool:
        return isinstance(expr, ast.Attribute) and expr.attr == "content"

    count = 0
    for node in ast.walk(tree):
        subscript = isinstance(node, ast.Subscript) and is_content(node.value)
        get = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" \
            and is_content(node.func.value)
        if subscript or get:
            count += 1
        elif isinstance(node, ast.Dict):
            count += sum(1 for k, v in zip(node.keys, node.values, strict=True)
                         if k is None and is_content(v))
    return count


def _found() -> tuple[set[tuple[str, str]], Counter[str]]:
    owner_modules = {m for m in OWNERS.values() if m}
    writers: set[tuple[str, str]] = set()
    reads: Counter[str] = Counter()
    for module, tree in _sources():
        writers |= {(module, kind) for kind in _writes(tree) if OWNERS.get(kind) != module}
        if module not in owner_modules and (n := _raw_reads(tree)):
            reads[module] = n
    return writers, reads


def test_every_artifact_kind_has_an_owner():
    from modeler_project.artifacts import ArtifactKind

    assert set(OWNERS) == {k.value for k in ArtifactKind}, "name an owner for every ArtifactKind in [owners]"


def test_each_kind_is_written_by_its_owner_only():
    writers, _ = _found()
    allowed = {(w["module"], w["kind"]) for w in EXCEPTIONS.get("writer", [])}
    new = sorted(writers - allowed)
    stale = sorted(allowed - writers)
    assert not new, ("these modules write an artifact kind they do not own:\n"
                     + "\n".join(f"- {m} writes {k} (owner: {OWNERS.get(k) or 'nobody'})" for m, k in new)
                     + "\nCall the owner's function instead. An exception needs the owner's approval.")
    assert not stale, ("these writer exceptions in [owner_exceptions] no longer occur; remove them:\n"
                       + "\n".join(f"- {m} → {k}" for m, k in stale))


def test_only_owners_read_stored_content_raw():
    _, reads = _found()
    recorded = {m: int(n) for m, n in EXCEPTIONS.get("reads", {}).items()}
    changed = sorted(m for m in reads.keys() | recorded.keys() if reads.get(m, 0) != recorded.get(m, 0))
    assert not changed, (
        "raw content reads outside the owner modules differ from [owner_exceptions.reads] in boundaries.toml:\n"
        + "\n".join(f"- {m}: recorded {recorded.get(m, 0)}, found {reads.get(m, 0)}" for m in changed)
        + "\nMore reads: ask the owner module instead (a new read needs the owner's approval). "
          "Fewer reads: lower the recorded count (remove the entry at zero) so the list only shrinks.")
