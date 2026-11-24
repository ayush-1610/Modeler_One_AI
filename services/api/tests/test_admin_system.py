"""R-N08 (design-review/BACKEND_CHANGE_REQUIREMENTS.md): System status asks whether the engine answers. The configured
engine command is started without a job (its lightest call: each engine stops on its usage line before simulating
anything), with a short timeout, and the answer is kept a minute. A software fixture is named as one."""

from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from modeler_api import engine_check
from modeler_api.auth import get_verifier
from modeler_api.main import app

pytestmark = pytest.mark.req("T-05")

PEOPLE = {"owner": ("platform", ["modeler-admin"]), "ana": ("acme", ["modeler-viewer", "modeler-curator"])}


class _Verifier:
    def verify(self, token: str) -> dict:
        tenant, roles = PEOPLE[token]
        return {"sub": token, "name": token.title(), "tenant_id": tenant, "realm_access": {"roles": roles},
                "projects": [], "acr": "loa1"}


@pytest.fixture
def client(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _engine(client: TestClient) -> dict:
    answer = client.get("/api/v1/admin/system", headers=_as("owner"))
    assert answer.status_code == 200, answer.text
    return answer.json()["data"]


def test_the_development_stub_answers_and_is_named_a_software_fixture(client, monkeypatch):
    monkeypatch.delenv("MODELER_ENGINE_COMMAND", raising=False)
    data = _engine(client)
    engine = data["engine"]
    assert (engine["kind"], engine["reachable"], engine["image_digest"]) == ("software-fixture", True, None)
    assert "stub_engine.py" in engine["command"] and engine["checked_at"]
    assert "not PK-Sim" in engine["detail"] and "nothing is simulated" in engine["detail"]
    assert data["execution_backend"] == "local" and data["deployment"]
    assert client.get("/api/v1/admin/system", headers=_as("ana")).status_code == 403          # the platform owner's


def test_a_pksim_engine_that_answers_its_usage_is_reachable_and_one_that_cannot_start_is_not(client, monkeypatch, tmp_path):
    script = tmp_path / "run_job.R"
    script.write_text("# the engine's runner, as far as the check is concerned\n")
    calls: list[list[str]] = []

    def answers(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Error: usage: run_job.R <job.json>\nExecution halted\n")

    monkeypatch.setenv("MODELER_ENGINE_COMMAND", f"Rscript {script}")
    monkeypatch.setattr(engine_check.shutil, "which", lambda program: f"/usr/bin/{program}")
    monkeypatch.setattr(engine_check.subprocess, "run", answers)
    engine = _engine(client)["engine"]
    assert (engine["kind"], engine["reachable"]) == ("pksim", True)
    assert "usage: run_job.R <job.json>" in engine["detail"]
    assert calls == [["Rscript", str(script)]]                       # started without a job: nothing to simulate
    _engine(client)
    assert len(calls) == 1                                           # kept a minute

    # R starts but its packages do not load: the engine is not there
    engine_check.forget(tmp_path)
    monkeypatch.setattr(engine_check.subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(
        argv, 1, stdout="", stderr="Error in library(ospsuite) : there is no package called 'ospsuite'\n"))
    engine = _engine(client)["engine"]
    assert engine["reachable"] is False and "there is no package called 'ospsuite'" in engine["detail"]

    # it does not answer in time
    engine_check.forget(tmp_path)

    def hangs(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))

    monkeypatch.setattr(engine_check.subprocess, "run", hangs)
    engine = _engine(client)["engine"]
    assert engine["reachable"] is False and "did not answer within" in engine["detail"]

    # its program is not on this server
    engine_check.forget(tmp_path)
    monkeypatch.setattr(engine_check.shutil, "which", lambda program: None)
    engine = _engine(client)["engine"]
    assert engine["reachable"] is False and "Rscript is not found on this server" in engine["detail"]

    # a script it names is missing
    engine_check.forget(tmp_path)
    monkeypatch.setattr(engine_check.shutil, "which", lambda program: f"/usr/bin/{program}")
    monkeypatch.setenv("MODELER_ENGINE_COMMAND", f"Rscript {tmp_path / 'gone' / 'run_job.R'}")
    engine = _engine(client)["engine"]
    assert engine["reachable"] is False and "run_job.R is not found" in engine["detail"]
