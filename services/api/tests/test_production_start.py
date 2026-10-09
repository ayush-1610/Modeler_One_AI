"""A production deployment refuses to start without its engine settings (the owner's decision, 2026-10-08)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from modeler_api.main import app
from modeler_contracts.runtime import ConfigurationError

pytestmark = pytest.mark.req("T-25")


def test_production_without_its_settings_does_not_start(monkeypatch):
    monkeypatch.setenv("MODELER_DEPLOYMENT", "production")
    for name in ("MODELER_OBJECT_STORE_URI", "MODELER_ENGINE_COMMAND", "MODELER_IMAGE_DIGEST"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="MODELER_ENGINE_COMMAND"), TestClient(app):
        pass


def test_production_with_its_settings_starts(monkeypatch):
    monkeypatch.setenv("MODELER_DEPLOYMENT", "production")
    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", "file:///tmp/objstore")
    monkeypatch.setenv("MODELER_ENGINE_COMMAND", "Rscript run_job.R")
    monkeypatch.setenv("MODELER_IMAGE_DIGEST", "catalog:sha256:" + "a" * 64)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def _engine_settings(monkeypatch, deployment: str) -> None:
    monkeypatch.setenv("MODELER_DEPLOYMENT", deployment)
    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", "file:///tmp/objstore")
    monkeypatch.setenv("MODELER_ENGINE_COMMAND", "Rscript run_job.R")
    monkeypatch.setenv("MODELER_IMAGE_DIGEST", "catalog:sha256:" + "a" * 64)


@pytest.fixture
def fresh_settings():
    from modeler_api.config import reload_settings

    reload_settings()
    yield
    reload_settings()


def test_production_refuses_the_dev_verifier(monkeypatch, fresh_settings):
    # the owner's decision, 2026-10-09: DEV signatures stand in for Part 11 step-up and are never a production record
    _engine_settings(monkeypatch, "production")
    monkeypatch.setenv("MODELER_DEV_AUTH", "1")
    with pytest.raises(ConfigurationError, match="MODELER_DEV_AUTH"), TestClient(app):
        pass


def test_a_pilot_runs_the_dev_verifier_and_says_so(monkeypatch, fresh_settings):
    _engine_settings(monkeypatch, "pilot")
    monkeypatch.setenv("MODELER_DEV_AUTH", "1")
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "deployment": "pilot", "verifier": "dev"}


def test_a_pilot_is_held_to_the_engine_settings(monkeypatch, fresh_settings):
    monkeypatch.setenv("MODELER_DEPLOYMENT", "pilot")
    monkeypatch.setenv("MODELER_DEV_AUTH", "1")
    for name in ("MODELER_OBJECT_STORE_URI", "MODELER_ENGINE_COMMAND", "MODELER_IMAGE_DIGEST"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="pilot deployment refused"), TestClient(app):
        pass
