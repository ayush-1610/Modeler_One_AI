"""Every JSON answer of the API has a response model (docs/ARCHITECTURE_BOUNDARIES.md, B2, phases 6 and 9).

A view was a `dict[str, Any]`: a renamed or dropped key passed every contract check and failed in the browser. Phase 6
gave each P0–P4 and escalation route a pydantic response model, which the OpenAPI snapshot then records; phase 9 does
the same for the rest of the API. Two lists in [response] of boundaries.toml (locked) record what is left, and only
shrink: a new entry fails, and so does an entry that has been typed or is gone.

- `untyped`: routes that answer with no pydantic model (a dict, or no annotation at all).
- `open`: routes typed only as `Envelope[dict[str, Any]]`, stored content without a model.

A route whose handler is annotated to return a `Response` (a file download) has no JSON body and is not counted.
"""

from __future__ import annotations

import importlib
import tomllib
import typing
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.responses import Response

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


def _is_file(route: APIRoute) -> bool:
    returns = typing.get_type_hints(route.endpoint).get("return")
    return isinstance(returns, type) and issubclass(returns, Response)


def _typed(route: APIRoute) -> bool:
    return isinstance(route.response_model, type) and issubclass(route.response_model, BaseModel)


def _is_open(route: APIRoute) -> bool:
    """`Envelope[dict[str, Any]]`: an envelope whose data is an open object."""
    data = route.response_model.model_fields.get("data") if _typed(route) else None
    return data is not None and typing.get_origin(data.annotation) is dict


def _untyped() -> set[str]:
    return {key for key, route in _routes().items() if not _is_file(route) and not _typed(route)}


def _open() -> set[str]:
    return {key for key, route in _routes().items() if _is_open(route)}


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


def test_no_new_open_answers():
    new = sorted(_open() - set(CONFIG["open"]))
    assert not new, (
        "these routes answer an open object (Envelope[dict[str, Any]]):\n" + "\n".join(f"- {k}" for k in new)
        + "\nAnswer with the owner module's content model. A new open answer needs the owner's approval "
          "([response] open in boundaries.toml).")


def test_no_stale_open_entries():
    stale = sorted(set(CONFIG["open"]) - _open())
    assert not stale, ("these routes in [response] open (boundaries.toml) have a model now or are gone; remove them so "
                       "the list only shrinks:\n" + "\n".join(f"- {k}" for k in stale))


def test_the_guarded_routers_are_routers():
    assert _routes(), "no routes found: check [response] routers in boundaries.toml"


def test_file_routes_are_the_downloads():
    # the exemption is for handlers that build their own Response; a JSON route cannot claim it by accident
    files = sorted(key for key, route in _routes().items() if _is_file(route))
    assert all(key.startswith("GET ") for key in files), files
