"""Configuration is read in one place per process and reaches code by injection (docs/ARCHITECTURE_BOUNDARIES.md, B5).

Configuration read in ~20 modules with different defaults meant a router that started reading a setting in a new helper
broke other routers' tests, which patched `get_settings` module by module. This test keeps the reads where they are now:

- only the modules listed under [config] in boundaries.toml (locked) touch `os.environ` / `os.getenv` or define a
  pydantic `BaseSettings`;
- no test patches `get_settings`: API tests use the `api_settings` fixture (`modeler_api.config.use_settings`).
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
CONFIG = tomllib.loads(Path(__file__).with_name("boundaries.toml").read_text())
READERS = set(CONFIG["config"]["readers"])


def _members() -> list[Path]:
    members = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["workspace"]["members"]
    return [ROOT / m for m in members]


def _files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts) if directory.is_dir() else []


def _module(src: Path, path: Path) -> str:
    rel = path.relative_to(src).with_suffix("")
    return ".".join(rel.parts[:-1] if rel.name == "__init__" else rel.parts)


def _reads_environment(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv") and isinstance(node.value, ast.Name) \
                and node.value.id == "os" or isinstance(node, ast.ImportFrom) and node.module == "os" and any(a.name in ("environ", "getenv")
                                                                              for a in node.names) or isinstance(node, ast.ClassDef) and any(isinstance(b, ast.Name) and b.id == "BaseSettings" for b in node.bases):
            lines.append(node.lineno)
    return lines


def test_only_the_config_modules_read_the_environment():
    found = []
    for member in _members():
        src = member / "src"
        for path in _files(src):
            module = _module(src, path)
            lines = _reads_environment(ast.parse(path.read_text(), filename=str(path)))
            if lines and module not in READERS:
                found.append(f"- {module} (line {', '.join(map(str, lines))})")
    assert not found, (
        "these modules read the environment directly:\n" + "\n".join(found)
        + "\nRead it through modeler_api.config.Settings (API, injected as SettingsDep) or "
          "modeler_contracts.runtime.runtime_env() (orchestrator, engine). A new reader needs the owner's approval "
          "([config] in tests/architecture/boundaries.toml).")


def test_the_config_readers_exist():
    modules = {_module(m / "src", p) for m in _members() for p in _files(m / "src")}
    assert READERS <= modules, sorted(READERS - modules)


def _patches_settings(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setattr":
            texts = [a.value for a in node.args[:2] if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if any(t == "get_settings" or t.endswith(".get_settings") for t in texts):
                lines.append(node.lineno)
    return lines


def test_no_test_patches_get_settings():
    found = []
    for member in _members():
        for path in _files(member / "tests"):
            if lines := _patches_settings(ast.parse(path.read_text(), filename=str(path))):
                found.append(f"- {path.relative_to(ROOT)} (line {', '.join(map(str, lines))})")
    assert not found, ("these tests patch get_settings; use the api_settings fixture (services/api/tests/conftest.py):\n"
                       + "\n".join(found))
