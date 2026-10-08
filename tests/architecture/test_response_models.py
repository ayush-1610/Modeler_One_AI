"""Every P0–P4 answer, and the escalation answers, has a response model (docs/ARCHITECTURE_BOUNDARIES.md, B2, phase 6).

A view was a `dict[str, Any]`: a renamed or dropped key passed every contract check and failed in the browser. Phase 6
gives each route a pydantic response model, which the OpenAPI snapshot then records. The routes still answering with
an untyped dict are listed under [response] in boundaries.toml (locked); a new untyped route fails, and so does a listed
route that has been typed, so the list only shrinks. Routes that answer with a file (no JSON body) are not counted.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel

pytestmark = pytest.mark.req("T-25")

CONFIG = tomllib.loads(Path(__file__).with_name("boundaries.toml").read_text())["response"]


def _routes() -> dict[str, APIRoute]:
    """'METHOD path' → route, for every route of the guarded routers."""
    out = {}
    for name in CONFIG["routers"]:
        for route in importlib.import_module(name).router.routes:
            if isinstance(route, APIRoute):
                out.update({f"{method} {route.path}": route for method in sorted(route.methods)})
    return out


def _typed(route: APIRoute) -> bool:
    return isinstance(route.response_model, type) and issubclass(route.response_model, BaseModel)


def _untyped() -> set[str]:
    # response_model None: the route answers with a file (a Response it builds itself), not a JSON body
    return {key for key, route in _routes().items() if route.response_model is not None and not _typed(route)}


def test_no_new_untyped_routes():
    new = sorted(_untyped() - set(CONFIG["untyped"]))
    assert not new, (
        "these routes answer with an untyped dict:\n" + "\n".join(f"- {k}" for k in new)
        + "\nDeclare response_model=Envelope[...] (modeler_api.responses, the models in modeler_api.views) and update "
          "the OpenAPI snapshot. A new untyped route needs the owner's approval ([response] in boundaries.toml).")


def test_no_stale_untyped_entries():
    stale = sorted(set(CONFIG["untyped"]) - _untyped())
    assert not stale, ("these routes in [response] untyped (boundaries.toml) are typed or gone; remove them so the list "
                       "only shrinks:\n" + "\n".join(f"- {k}" for k in stale))


def test_the_guarded_routers_are_routers():
    assert _routes(), "no routes found: check [response] routers in boundaries.toml"
