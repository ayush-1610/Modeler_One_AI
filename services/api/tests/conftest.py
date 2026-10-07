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
