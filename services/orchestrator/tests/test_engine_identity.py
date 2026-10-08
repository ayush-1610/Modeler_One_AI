"""Every campaign records what produced its numbers, so a stub run can never be read as a PBPK result."""

from __future__ import annotations

import pytest

from modeler_orchestrator.local_runner import engine_identity

pytestmark = pytest.mark.req("T-28")


@pytest.mark.parametrize(("command", "kind"), [
    ("python3 /repo/deploy/dev/stub_engine.py", "software-fixture"),
    ("python3 deploy/dev/analytical_engine.py", "software-fixture"),
    ("Rscript /home/x/Modeler_One_AI/services/engine-worker/r/run_job.R", "pksim"),
    ("bash /repo/deploy/dev/docker_engine.sh", "pksim"),
    ("/usr/bin/something-else", "unknown"),
])
def test_engine_kind_follows_the_configured_command(monkeypatch, command, kind):
    monkeypatch.setenv("MODELER_ENGINE_COMMAND", command)
    assert engine_identity()["kind"] == kind


def test_an_injected_engine_is_never_claimed_as_pksim():
    def echo(job):
        return job

    assert engine_identity(echo) == {"kind": "injected", "command": "echo"}


def test_development_runs_the_stub_engine_when_no_command_is_set(monkeypatch):
    # one default per variable (2026-10-08): development falls back to the stub, labelled a software fixture
    monkeypatch.delenv("MODELER_ENGINE_COMMAND", raising=False)
    monkeypatch.delenv("MODELER_DEPLOYMENT", raising=False)
    assert engine_identity()["kind"] == "software-fixture"


def test_production_has_no_default_engine(monkeypatch):
    from modeler_contracts.runtime import ConfigurationError

    monkeypatch.delenv("MODELER_ENGINE_COMMAND", raising=False)
    monkeypatch.setenv("MODELER_DEPLOYMENT", "production")
    with pytest.raises(ConfigurationError, match="MODELER_ENGINE_COMMAND"):
        engine_identity()

