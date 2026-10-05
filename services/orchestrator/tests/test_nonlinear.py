"""T-52 →: the non-linear backend's control flow, on a scripted executor (software only; PK-Sim checks on the server)."""

from __future__ import annotations

import pytest

from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_orchestrator.local_runner import CampaignArtifactWriter

from .scripted import ScriptedExecutor, patch_planning, request


def _writer(root, stages):
    return CampaignArtifactWriter(store=FileWriteStore(str(root)), tenant_id="t1", campaign_id="camp-s", project="p",
                                  compound="X", question="q", model_risk="medium", budget_seconds=3600, stages=stages)


@pytest.mark.req("T-52")
def test_a_fit_that_breaks_an_earlier_stage_is_caught_before_s4(tmp_path, monkeypatch):
    """Plan §12.3 N2 (T-52 acceptance, here in software): S2's fit gives parameter set B, which S1's studies no
    longer accept; the regression is caught at S2 and the campaign escalates before S4 with the regression named."""
    patch_planning(monkeypatch)
    stages = ["S0", "S1", "S2", "S4"]
    executor = ScriptedExecutor(engine=None, writer=_writer(tmp_path, stages),  # type: ignore[arg-type]
                                verdicts={("S2", "A"): "B", ("S1", "B"): False})
    outcome = executor.run(request(stages))
    assert outcome.status == "ESCALATED" and "regression" in outcome.reason
    assert [s.stage for s in outcome.stages] == ["S0", "S1", "S2"]               # S4 never ran
    assert ("S1", "B", "after-S2") in executor.calls                             # S1 judged again on B, separately
    campaign = FileReadStore(str(tmp_path)).get_campaign("t1", "camp-s")
    s1 = next(s for s in campaign["stages"] if s["stage"] == "S1")
    assert s1["rounds"][-1]["action"] == "no-regression check with S2's CPF" and s1["rounds"][-1]["verdict"] == "no pass"
    assert campaign["resume"]["escalated_stage"] == "S2"


@pytest.mark.req("T-52")
def test_a_fit_that_keeps_earlier_stages_passing_goes_on(tmp_path, monkeypatch):
    patch_planning(monkeypatch)
    stages = ["S0", "S1", "S2", "S4"]
    executor = ScriptedExecutor(engine=None, writer=_writer(tmp_path, stages), verdicts={("S2", "A"): "B"})  # type: ignore[arg-type]
    outcome = executor.run(request(stages))
    assert outcome.status == "COMPLETED" and outcome.final_cpf_sha256 == "sha-B"
    assert ("S1", "B", "after-S2") in executor.calls and ("S4", "B", "") in executor.calls
    # a stage that did not change the parameter set triggers no re-check
    plain = ScriptedExecutor(engine=None, writer=_writer(tmp_path / "plain", stages))  # type: ignore[arg-type]
    plain.run(request(stages))
    assert not any(phase.startswith("after-") for _s, _c, phase in plain.calls)
