"""API test fixtures. Settings are replaced through `modeler_api.config.use_settings`, never by patching a router module
(docs/ARCHITECTURE_BOUNDARIES.md, rule B5; `tests/architecture/test_config_reads.py` checks it)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack

import pytest

from modeler_api.config import Settings, reload_settings, use_settings


@pytest.fixture(autouse=True)
def _settings_from_this_tests_environment():
    """Each test reads MODELER_* afresh, so a `monkeypatch.setenv` in one test never leaks into the next."""
    reload_settings()
    yield
    reload_settings()


@pytest.fixture
def api_settings() -> Iterator[Callable[..., Settings]]:
    """`api_settings(read_root=..., execution_backend="local")`: the API runs with these settings for this test."""
    with ExitStack() as stack:
        yield lambda **fields: stack.enter_context(use_settings(Settings(**fields)))


@pytest.fixture(autouse=True)
def _typed_answers_are_the_handlers_answers(monkeypatch):
    """Phase 6 types the answers as they are (docs/plans/2026-10-08-phase-6-contracts.md): a response model may not drop,
    add or coerce anything the handler returned. Every JSON answer in these tests is compared with the handler's own
    return value, serialized without a model; any difference fails the test that made the request."""
    import json

    from fastapi import routing
    from fastapi.encoders import jsonable_encoder

    original = routing.serialize_response
    differences: list[str] = []

    def canonical(value) -> str:
        if isinstance(value, bytes | bytearray):
            value = json.loads(value)
        return json.dumps(value, sort_keys=True, ensure_ascii=False)

    async def checked(**kwargs):
        served = await original(**kwargs)
        if kwargs.get("field") is not None:
            returned = canonical(jsonable_encoder(kwargs["response_content"]))
            if canonical(served) != returned:
                differences.append(f"served {canonical(served)[:400]}\nreturned {returned[:400]}")
        return served

    monkeypatch.setattr(routing, "serialize_response", checked)
    yield
    assert not differences, "a response model changed the handler's answer:\n" + "\n\n".join(differences)
