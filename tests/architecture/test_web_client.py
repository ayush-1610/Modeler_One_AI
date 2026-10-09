"""The web app calls the API through its one client, typed by route (docs/ARCHITECTURE_BOUNDARIES.md, B6, phase 7c).

`apps/web/lib/api.ts` is the only module that fetches. Every JSON route has a response model since phase 9
(test_response_models.py), so every call names its route with `get` / `send` / `upload` / `serverGet` / `post`, and its
path parameters, body and answer type follow from the contract. The untyped helpers that called a bare URL (`apiGet`,
`apiSend`, `apiUpload`, `serverRead`, `rawPost`) were removed in phase 9e, and none may come back under another name: the
only exported function of the client that takes a URL is `apiFile`, the download of a file route. A raw `fetch`
anywhere else in the app fails here too.

A client page reads a typed route with `useResource` and changes state with `useMutation` (`lib/hooks.ts`, phase 7d),
so a change refreshes the page's resources and the phase rail. Only the hooks import the typed browser read `get`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
CLIENT = WEB / "lib" / "api.ts"
HOOKS = WEB / "lib" / "hooks.ts"
GENERATED = WEB / "lib" / "api-types.ts"
REMOVED = ("apiGet", "apiSend", "apiUpload", "serverRead", "rawPost")
# an exported function of the client and its parameter list
EXPORTED = re.compile(r"export\s+(?:async\s+)?function\s+(\w+)\s*(?:<(?:[^<>]|<[^<>]*>)*>)?\s*\(([^)]*)\)", re.DOTALL)


def _sources() -> list[Path]:
    return sorted(p for d in ("app", "components", "lib") for p in (WEB / d).rglob("*.ts*")
                  if p.suffix in {".ts", ".tsx"} and p not in {CLIENT, GENERATED})


def test_only_the_client_fetches() -> None:
    offenders = [f"{p.relative_to(ROOT)}:{n}" for p in _sources()
                 for n, line in enumerate(p.read_text().splitlines(), 1) if re.search(r"(?<![\w.])fetch\(", line)]
    assert not offenders, (
        "Only apps/web/lib/api.ts fetches (rule B6): call the API with get/send/upload/serverGet, or apiFile for a "
        "download:\n  " + "\n  ".join(offenders))


def test_no_untyped_helper_remains() -> None:
    found = [f"{p.relative_to(ROOT)}: {name}" for p in [*_sources(), CLIENT]
             for name in REMOVED if re.search(rf"\b{name}\b", p.read_text())]
    assert not found, ("The untyped helpers were removed in phase 9e: call the route by name with get/send/upload/"
                       "serverGet/post (lib/api.ts):\n  " + "\n  ".join(found))


def test_the_client_calls_routes_by_name() -> None:
    # a new helper that takes a bare URL would be an untyped call under another name; only the file download takes one
    exported = {name: params for name, params in EXPORTED.findall(CLIENT.read_text())}
    assert {"get", "send", "upload", "serverGet", "post", "apiFile"} <= exported.keys(), sorted(exported)
    by_url = sorted(name for name, params in exported.items() if re.search(r"\burl\s*:\s*string", params))
    assert by_url == ["apiFile"], (
        "Only apiFile (a file download) takes a bare URL; a JSON call names its route (`route: R`) so its parameters, "
        f"body and answer follow from the contract: {by_url}")


def test_pages_read_through_the_hooks() -> None:
    imports = re.compile(r"import\s*\{([^}]*)\}\s*from\s*\"@/lib/api\"")
    offenders = [str(p.relative_to(ROOT)) for p in _sources() if p != HOOKS
                 for m in imports.finditer(p.read_text()) if re.search(r"(?<![\w.])get\b(?!\s+as)", m.group(1))]
    assert not offenders, (
        "A page reads a typed route with useResource (lib/hooks.ts), so a change made with useMutation refreshes it and "
        "the phase rail; only the hooks import `get`:\n  " + "\n  ".join(offenders))
