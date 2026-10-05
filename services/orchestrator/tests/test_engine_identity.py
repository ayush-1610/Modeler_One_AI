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
