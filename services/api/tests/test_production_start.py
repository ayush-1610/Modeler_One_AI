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
