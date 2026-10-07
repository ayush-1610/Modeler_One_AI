"""Import boundaries between the workspace packages (docs/ARCHITECTURE_BOUNDARIES.md, phase 1).

A change rippled into unrelated features because nothing stopped a package from importing upward or sideways. This
test reads every package's source and tests with `ast` (lazy, function-level imports count the same) and checks:

- layer:    a package imports only itself or a lower layer; two packages on one layer do not import each other;
- declared: every workspace package a module imports is a direct dependency in its own pyproject.toml;
- seam:     modeler_api reaches modeler_orchestrator / modeler_agents only through one seam module each;
- router:   a module that defines an APIRouter does not import another router module;
- tests:    a package's tests obey the layer rule too.

Today's exceptions are listed, with reasons, in boundaries.toml (a locked file). A new violation fails; an exception
that no longer occurs fails too, so the list only shrinks.
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = tomllib.loads((Path(__file__).with_name("boundaries.toml")).read_text())
LAYERS: dict[str, int] = CONFIG["layers"]
SEAMS: dict[str, str] = CONFIG["seams"]
DOC = "docs/ARCHITECTURE_BOUNDARIES.md"


@dataclass(frozen=True)
class Package:
    name: str           # import name, e.g. modeler_api
    dist: str           # distribution name, e.g. modeler-api
    root: Path          # workspace member directory
    depends: frozenset[str]


@dataclass(frozen=True)
class Violation:
    rule: str
    importer: str
    imported: str
    detail: str

    @property
    def key(self) -> tuple[str, str, str]:
        return self.rule, self.importer, self.imported


def _dist_name(requirement: str) -> str:
    return re.split(r"[\s<>=!~\[;(]", requirement, maxsplit=1)[0].strip().lower().replace("_", "-")


@cache
def packages() -> dict[str, Package]:
    members = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["workspace"]["members"]
    by_dist: dict[str, tuple[str, Path, list[str]]] = {}
    for member in members:
        root = ROOT / member
        project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
        names = [p.name for p in (root / "src").iterdir() if (p / "__init__.py").is_file()]
        assert len(names) == 1, f"{member}: expected one import package under src/, found {names}"
        by_dist[project["name"].lower()] = (names[0], root, project.get("dependencies", []))
    out = {}
    for dist, (name, root, deps) in by_dist.items():
        firstparty = frozenset(by_dist[d][0] for d in map(_dist_name, deps) if d in by_dist)
        out[name] = Package(name=name, dist=dist, root=root, depends=firstparty)
    return out


def _module_name(pkg: Package, path: Path) -> str:
    rel = path.relative_to(pkg.root / "src").with_suffix("")
    parts = list(rel.parts[:-1]) if rel.name == "__init__" else list(rel.parts)
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    """Absolute module names imported anywhere in the file (relative imports stay inside the package)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def _defines_router(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "APIRouter") or (
                    isinstance(func, ast.Attribute) and func.attr == "APIRouter"):
                return True
    return False


def _py_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


@cache
def violations() -> tuple[Violation, ...]:
    pkgs = packages()
    found: dict[tuple[str, str, str], Violation] = {}

    def add(v: Violation) -> None:
        found.setdefault(v.key, v)

    api = pkgs.get("modeler_api")
    routers = {_module_name(api, p) for p in _py_files(api.root / "src") if _defines_router(p)} if api else set()

    for pkg in pkgs.values():
        for path in _py_files(pkg.root / "src"):
            module = _module_name(pkg, path)
            for imported in _imports(path):
                top = imported.split(".")[0]
                if top not in pkgs or top == pkg.name:
                    if pkg.name == "modeler_api" and module in routers and top == "modeler_api":
                        target = next((r for r in routers if imported == r or imported.startswith(r + ".")), None)
                        if target and target != module:
                            add(Violation("router", module, target, "a router imports another router's module"))
                    continue
                if LAYERS[top] >= LAYERS[pkg.name]:
                    direction = "upward" if LAYERS[top] > LAYERS[pkg.name] else "sideways (same layer)"
                    add(Violation("layer", module, imported,
                                  f"L{LAYERS[pkg.name]} → L{LAYERS[top]}: {direction}"))
                if top not in pkg.depends:
                    add(Violation("declared", pkg.name, top, f"{pkg.dist} does not declare {pkgs[top].dist}"))
                if pkg.name == "modeler_api" and top in SEAMS and module != SEAMS[top]:
                    add(Violation("seam", module, imported, f"only {SEAMS[top]} may import {top}"))

        tests = pkg.root / "tests"
        if tests.is_dir():
            for path in _py_files(tests):
                rel = path.relative_to(ROOT).as_posix()
                for imported in _imports(path):
                    top = imported.split(".")[0]
                    if top in pkgs and top != pkg.name and LAYERS[top] >= LAYERS[pkg.name]:
                        add(Violation("tests", rel, top, f"tests of L{LAYERS[pkg.name]} import L{LAYERS[top]}"))
    return tuple(sorted(found.values(), key=lambda v: v.key))


def _allowed() -> dict[tuple[str, str, str], str]:
    return {(a["rule"], a["importer"], a["imported"]): a["reason"] for a in CONFIG.get("allow", [])}


_HINT = {
    "layer": "move the shared code down a layer, or pass it in through a port in modeler_contracts",
    "declared": "add the dependency to the package's pyproject.toml (if the layer rule allows the import at all)",
    "seam": "route the call through the seam module named above",
    "router": "move the shared code into a service or modeler_api.deps; routers only handle HTTP",
    "tests": "test through the package's own public surface, or move the test to the higher package",
}


def test_every_workspace_package_has_a_layer():
    missing = sorted(set(packages()) - set(LAYERS))
    extra = sorted(set(LAYERS) - set(packages()))
    assert not missing, f"place these packages on a layer in tests/architecture/boundaries.toml: {missing}"
    assert not extra, f"boundaries.toml names packages that are not workspace members: {extra}"


def test_seam_modules_belong_to_the_api():
    assert all(seam.startswith("modeler_api.") for seam in SEAMS.values())


def test_scan_sees_the_whole_workspace():
    # guards the scanner itself: every package has source, and known downward imports are seen
    pkgs = packages()
    assert all(_py_files(p.root / "src") for p in pkgs.values())
    seen = {(name, imported.split(".")[0]) for name, pkg in pkgs.items() for path in _py_files(pkg.root / "src")
            for imported in _imports(path)}
    assert {("modeler_project", "pbpk_domain"), ("modeler_api", "modeler_project")} <= seen


def test_no_new_boundary_violations():
    allowed = _allowed()
    new = [v for v in violations() if v.key not in allowed]
    lines = [f"- [{v.rule}] {v.importer} imports {v.imported}: {v.detail}. Fix: {_HINT[v.rule]}." for v in new]
    assert not new, (
        f"{len(new)} new import-boundary violation(s) (see {DOC}):\n" + "\n".join(lines)
        + "\nAn exception needs the owner's approval and an entry in tests/architecture/boundaries.toml (locked).")


def test_no_stale_exceptions():
    current = {v.key for v in violations()}
    stale = sorted(k for k in _allowed() if k not in current)
    assert not stale, (
        "these exceptions in tests/architecture/boundaries.toml no longer occur; remove them so the list "
        "only shrinks:\n" + "\n".join(f"- [{r}] {a} → {b}" for r, a, b in stale))
