"""The web app calls the API through its one client, typed by route (docs/ARCHITECTURE_BOUNDARIES.md, B6, phase 7c).

`apps/web/lib/api.ts` is the only module that fetches. A route the contract types (its answer is a response model in
docs/api/openapi.json, in the envelope or without it) is called by name with `get` / `send` / `upload` / `serverGet` /
`post`, so its path parameters, body and answer type follow from the contract. The untyped helpers (`apiGet`, `apiSend`, `apiUpload`,
`serverRead`) remain only for routes the contract does not type yet; a call of one on a typed route fails here, and
so does a raw `fetch` anywhere else in the app.

A client page reads a typed route with `useResource` and changes state with `useMutation` (`lib/hooks.ts`, phase 7d),
so a change refreshes the page's resources and the phase rail. Only the hooks import the typed browser read `get`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
CLIENT = WEB / "lib" / "api.ts"
HOOKS = WEB / "lib" / "hooks.ts"
GENERATED = WEB / "lib" / "api-types.ts"
UNTYPED = {"apiGet": "get", "apiSend": None, "apiUpload": "post", "serverRead": "get"}
# a call of an untyped helper: its name, an optional type argument, then the URL as a string or template literal
CALL = re.compile(r"\b(apiGet|apiSend|apiUpload|serverRead)\s*(?:<[^()]*?>)?\s*\(\s*([`\"])(.*?)\2", re.DOTALL)
WRITE_METHOD = re.compile(r"\s*,\s*\"(POST|PUT)\"")


def _sources() -> list[Path]:
    return sorted(p for d in ("app", "components", "lib") for p in (WEB / d).rglob("*.ts*")
                  if p.suffix in {".ts", ".tsx"} and p not in {CLIENT, GENERATED})


def _typed_routes() -> list[tuple[str, str]]:
    """(method, example path) of every route whose answer has a model (in the envelope or, since phase 9d, without it);
    a parameter reads as "x"."""
    spec = json.loads((ROOT / "docs" / "api" / "openapi.json").read_text())
    out = []
    for route, operations in spec["paths"].items():
        for method, op in operations.items():
            answers = [r.get("content", {}).get("application/json", {}).get("schema", {})
                       for code, r in op["responses"].items() if code.startswith("2")]
            if any(a.get("$ref") for a in answers):
                out.append((method, re.sub(r"\{[^}]+\}", "x", route)))
    return out


def _url_pattern(url: str) -> re.Pattern[str]:
    """A called URL as a pattern over example paths. A `${…}` is one path segment (or part of one), except a leading
    one, which is a prefix the caller builds (`${base(projectId)}/layout`). The query string is left out."""
    parts = re.split(r"\$\{[^}]*\}", url)
    pattern = ""
    for i, part in enumerate(parts):
        if i:
            pattern += ".*" if i == 1 and not parts[0] else "[^/]*"
        pattern += re.escape(part.split("?")[0])
        if "?" in part:
            break
    return re.compile(f"^{pattern}$")


def test_only_the_client_fetches() -> None:
    offenders = [f"{p.relative_to(ROOT)}:{n}" for p in _sources()
                 for n, line in enumerate(p.read_text().splitlines(), 1) if re.search(r"(?<![\w.])fetch\(", line)]
    assert not offenders, (
        "Only apps/web/lib/api.ts fetches (rule B6): call the API with get/send/upload/serverGet, or apiFile for a "
        "download:\n  " + "\n  ".join(offenders))


def test_untyped_helpers_are_not_renamed() -> None:
    renamed = [f"{p.relative_to(ROOT)}: {m.group(0)}" for p in _sources()
               for m in re.finditer(r"\b(?:apiGet|apiSend|apiUpload|serverRead)\s+as\s+\w+", p.read_text())]
    assert not renamed, "Import the untyped helpers under their own names, so this guard sees their calls:\n  " + "\n  ".join(renamed)


def test_typed_routes_are_called_by_name() -> None:
    typed = _typed_routes()
    offenders = []
    for source in _sources():
        text = source.read_text()
        for call in CALL.finditer(text):
            helper, url = call.group(1), call.group(3)
            method = UNTYPED[helper]
            if method is None:
                found = WRITE_METHOD.match(text, call.end())
                method = found.group(1).lower() if found else "post"
            pattern = _url_pattern(url)
            if any(m == method and pattern.match(example) for m, example in typed):
                line = text.count("\n", 0, call.start()) + 1
                offenders.append(f"{source.relative_to(ROOT)}:{line} {helper}({url})")
    assert not offenders, (
        "A route the contract types is called with its name, through get/send/upload/serverGet in lib/api.ts, so its "
        "parameters, body and answer follow from the contract:\n  " + "\n  ".join(offenders))



def test_pages_read_through_the_hooks() -> None:
    imports = re.compile(r"import\s*\{([^}]*)\}\s*from\s*\"@/lib/api\"")
    offenders = [str(p.relative_to(ROOT)) for p in _sources() if p != HOOKS
                 for m in imports.finditer(p.read_text()) if re.search(r"(?<![\w.])get\b(?!\s+as)", m.group(1))]
    assert not offenders, (
        "A page reads a typed route with useResource (lib/hooks.ts), so a change made with useMutation refreshes it and "
        "the phase rail; only the hooks import `get`:\n  " + "\n  ".join(offenders))
