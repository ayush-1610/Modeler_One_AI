"""The Data room's calibration tool (deploy/dev/calibrate_dataroom.py; plan 2026-11-24 §2.3, decision D2) end to end with
a scripted model that answers nothing: the key comes from the platform's key store, every paid call is priced and kept
on the platform's paid ledger, the run's cap pauses it (never fails it), and the report scores the room against the
hand-written answers. No model is called and no network is used."""

from __future__ import annotations

import base64
import json
import runpy
import sys
from pathlib import Path

import pytest

from modeler_agents import llm
from modeler_agents.llm import ChatResult
from modeler_api import platform_settings

pytestmark = pytest.mark.req("T-47")
TOOL = Path(__file__).resolve().parents[3] / "deploy" / "dev" / "calibrate_dataroom.py"


class Scripted:
    provider = "anthropic"

    def __init__(self, model: str):
        self.model = model

    def complete(self, messages, tools):
        return ChatResult(content="nothing to add", tool_calls=(), finish_reason="end_turn",
                          usage={"input_tokens": 1000, "output_tokens": 100}, model=self.model)


@pytest.fixture
def server(tmp_path, monkeypatch):
    master = base64.b64encode(b"k" * 32).decode()
    monkeypatch.setenv("MODELER_READ_ROOT", str(tmp_path))
    monkeypatch.setenv("MODELER_MASTER_KEY", master)
    keys = platform_settings.KeyStore(str(tmp_path), master)
    keys.activate(keys.add("anthropic", "test", {"api_key": "sk-not-a-key"}, by="test")["id"])
    monkeypatch.setattr(llm, "chat_model_from_env", lambda env=None: Scripted(env["MODELER_LLM_MODEL"]))
    return tmp_path


def _run(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["calibrate_dataroom.py", *args])
    runpy.run_path(str(TOOL), run_name="__main__")


def test_a_dry_run_names_the_models_and_the_estimate_and_calls_nothing(server, monkeypatch, capsys):
    _run(monkeypatch, "--dry")
    out = capsys.readouterr().out
    assert "A8 anthropic/claude-opus-5-5" in out and "estimate $3.90" in out and "of $90" in out
    assert not (server / "_platform" / "calibration").exists()
    assert platform_settings.PaidSpend(str(server)).month_usd() == 0


def test_the_run_is_capped_priced_on_the_ledger_and_scored(server, monkeypatch, capsys):
    _run(monkeypatch, "--cap", "0.05", "--out", str(server / "out"))
    out = capsys.readouterr().out
    assert "PAUSED" in out and "COST $0.05" in out and "ACCURACY 0 of 60 right" in out
    report = json.loads((server / "out" / "report.json").read_text())
    assert report["score"]["of"] == 60 and report["usd"] == pytest.approx(0.05, abs=0.02)
    ledger = platform_settings.PaidSpend(str(server))
    assert ledger.month_usd() == pytest.approx(report["usd"]) and all(
        r["project_id"] == "calibration" for r in ledger.rows())


def test_a_preset_whose_provider_has_no_active_key_stops_before_any_call(server, monkeypatch):
    with pytest.raises(SystemExit, match="no active nvidia key"):
        _run(monkeypatch, "--preset", "free", "--dry")


def test_a_model_that_cannot_answer_is_waited_for_as_the_app_does_and_the_same_run_goes_on(server, monkeypatch, capsys):
    import time

    from modeler_agents.run import LLMUnavailableError

    class OnceUnavailable(Scripted):
        failed = False

        def complete(self, messages, tools):
            if not OnceUnavailable.failed:
                OnceUnavailable.failed = True
                raise LLMUnavailableError("HTTP 429: Too Many Requests")
            return super().complete(messages, tools)

    waited: list[float] = []
    monkeypatch.setattr(llm, "chat_model_from_env", lambda env=None: OnceUnavailable(env["MODELER_LLM_MODEL"]))
    monkeypatch.setattr(time, "sleep", waited.append)
    _run(monkeypatch, "--cap", "0.05", "--out", str(server / "out"))
    out = capsys.readouterr().out
    assert "waiting 10 min" in out and len(waited) == 1 and 0 < waited[0] <= 600
    assert out.index("waiting 10 min") < out.index("  question  done")   # the same run went on after the wait
