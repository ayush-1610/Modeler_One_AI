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
                                verdicts={("S2", "A"): "B", ("S1", "B"): False, ("SJ", "B"): ("C", False)},
                                base={("SJ", "B"): False})
    outcome = executor.run(request(stages))
    assert outcome.status == "ESCALATED" and "regression" in outcome.reason     # the joint refit did not save it
    assert [s.stage for s in outcome.stages] == ["S0", "S1", "S2"]               # S4 never ran
    assert ("S1", "B", "after-S2", None) in executor.calls                       # S1 judged again on B, separately
    campaign = FileReadStore(str(tmp_path)).get_campaign("t1", "camp-s")
    s1 = next(s for s in campaign["stages"] if s["stage"] == "S1")
    check = next(r for r in s1["rounds"] if r["action"] == "no-regression check with S2's CPF")
    assert check["verdict"] == "no pass"
    assert campaign["resume"]["escalated_stage"] == "S2"


@pytest.mark.req("T-52")
def test_a_fit_that_keeps_earlier_stages_passing_goes_on(tmp_path, monkeypatch):
    patch_planning(monkeypatch)
    stages = ["S0", "S1", "S2", "S4"]
    executor = ScriptedExecutor(engine=None, writer=_writer(tmp_path, stages), verdicts={("S2", "A"): "B"})  # type: ignore[arg-type]
    outcome = executor.run(request(stages))
    assert outcome.status == "COMPLETED" and outcome.final_cpf_sha256 == "sha-B"
    assert ("S1", "B", "after-S2", None) in executor.calls and ("S4", "B", "", None) in executor.calls
    # a stage that did not change the parameter set triggers no re-check
    plain = ScriptedExecutor(engine=None, writer=_writer(tmp_path / "plain", stages))  # type: ignore[arg-type]
    plain.run(request(stages))
    assert not any(phase.startswith("after-") for _s, _c, phase, _a in plain.calls)


@pytest.mark.req("T-53")
def test_sj_keeps_the_joint_estimate_only_when_every_study_passes_and_agreement_is_no_worse(tmp_path, monkeypatch):
    patch_planning(monkeypatch)
    stages = ["S0", "S1", "S2", "SJ", "S4"]
    kept = ScriptedExecutor(engine=None, writer=_writer(tmp_path / "kept", stages),  # type: ignore[arg-type]
                            verdicts={("S2", "A"): "B", ("SJ", "B"): "C"}, gmfe={("SJ", "B"): 1.4, ("SJ", "C"): 1.2})
    outcome = kept.run(request(stages))
    assert outcome.status == "COMPLETED" and outcome.final_cpf_sha256 == "sha-C"
    assert ("SJ", "B", "", "fit phys.logp+perm.intestinal") in kept.calls and ("S4", "C", "", None) in kept.calls
    sj = next(s for s in outcome.stages if s.stage == "SJ")
    assert sj.status == "PASSED" and any("joint estimate kept" in f for f in sj.findings)

    worse = ScriptedExecutor(engine=None, writer=_writer(tmp_path / "worse", stages),  # type: ignore[arg-type]
                             verdicts={("S2", "A"): "B", ("SJ", "B"): "C"}, gmfe={("SJ", "B"): 1.2, ("SJ", "C"): 1.5})
    outcome = worse.run(request(stages))
    assert outcome.status == "COMPLETED" and outcome.final_cpf_sha256 == "sha-B"          # sequential estimates stay
    assert any("not kept: the agreement got worse" in f for f in next(s for s in outcome.stages if s.stage == "SJ").findings)

    nothing = ScriptedExecutor(engine=None, writer=_writer(tmp_path / "nothing", stages), joint_ids=())  # type: ignore[arg-type]
    outcome = nothing.run(request(stages))
    assert next(s for s in outcome.stages if s.stage == "SJ").status == "SKIPPED" and outcome.status == "COMPLETED"


@pytest.mark.req("T-53")
def test_a_regression_is_first_remedied_by_a_joint_refit_of_the_stages_up_to_it(tmp_path, monkeypatch):
    patch_planning(monkeypatch)
    stages = ["S0", "S1", "S2", "S4"]
    executor = ScriptedExecutor(engine=None, writer=_writer(tmp_path, stages),  # type: ignore[arg-type]
                                verdicts={("S2", "A"): "B", ("S1", "B"): False, ("SJ", "B"): "D"},
                                base={("SJ", "B"): False}, gmfe={("SJ", "B"): 1.6, ("SJ", "D"): 1.25})
    outcome = executor.run(request(stages))
    assert outcome.status == "COMPLETED" and outcome.final_cpf_sha256 == "sha-D"
    assert ("SJ", "B", "after-regression", "fit phys.logp+perm.intestinal") in executor.calls
    s2 = next(s for s in outcome.stages if s.stage == "S2")
    assert s2.status == "PASSED" and any("no longer passes" in f for f in s2.findings)
    campaign = FileReadStore(str(tmp_path)).get_campaign("t1", "camp-s")
    actions = [r["action"] for s in campaign["stages"] if s["stage"] == "S2" for r in s["rounds"]]
    assert "joint refit after the regression" in actions


_STUDIES = {"S1": ["iv-1"], "S2": ["po-1"], "SJ": ["iv-1", "po-1"], "S4": ["iv-1", "po-1"]}


@pytest.mark.req("T-54")
def test_the_ledger_explains_every_verdict_change(tmp_path, monkeypatch):
    """Plan §12.3 N6 (T-54 acceptance, in software): S2's fit (A → B) makes po-1 pass and breaks iv-1; the joint
    refit (B → D) mends iv-1. Every verdict change is listed under the parameter change that caused it."""
    patch_planning(monkeypatch)
    stages = ["S0", "S1", "S2", "S4"]
    executor = ScriptedExecutor(engine=None, writer=_writer(tmp_path, stages), studies=_STUDIES,  # type: ignore[arg-type]
                                verdicts={("S2", "A"): "B", ("S1", "B"): False, ("SJ", "B"): "D"},
                                base={("SJ", "B"): False}, study_ok={("po-1", "B"): True})
    assert executor.run(request(stages)).status == "COMPLETED"
    ledger = FileReadStore(str(tmp_path)).get_campaign("t1", "camp-s")["ledger"]
    fit, joint = ledger["entries"]
    assert (fit["stage"], fit["kind"], fit["cpf_before"], fit["cpf_after"]) == ("S2", "fit", "sha-A", "sha-B")
    assert [(v["study_id"], v["before"], v["after"]) for v in fit["verdicts"]] == [("po-1", "fail", "pass"),
                                                                                  ("iv-1", "pass", "fail")]
    assert (joint["kind"], joint["cpf_before"], joint["cpf_after"]) == ("joint refit", "sha-B", "sha-D")
    assert [(v["study_id"], v["before"], v["after"]) for v in joint["verdicts"]] == [("iv-1", "fail", "pass")]
    assert ledger["current"] == "sha-D" and {s: v["verdict"] for s, v in ledger["verdicts"].items()} == {"iv-1": "pass",
                                                                                                         "po-1": "pass"}
    assert "not readable" in fit["note"]   # the scripted CPFs are not files: the parameter diff says so


@pytest.mark.req("T-54")
def test_a_trial_estimate_that_was_not_kept_moves_nothing(tmp_path, monkeypatch):
    patch_planning(monkeypatch)
    stages = ["S0", "S1", "S2", "SJ", "S4"]
    executor = ScriptedExecutor(engine=None, writer=_writer(tmp_path, stages), studies=_STUDIES,  # type: ignore[arg-type]
                                verdicts={("S2", "A"): "B", ("SJ", "B"): ("C", False)})
    assert executor.run(request(stages)).final_cpf_sha256 == "sha-B"
    ledger = FileReadStore(str(tmp_path)).get_campaign("t1", "camp-s")["ledger"]
    assert [e["kind"] for e in ledger["entries"]] == ["fit"] and ledger["current"] == "sha-B"
    assert all(v["cpf"] == "sha-B" or v["cpf"] == "sha-A" for v in ledger["verdicts"].values())
    assert {v["verdict"] for v in ledger["verdicts"].values()} == {"pass"}      # C's failures are not on the record


@pytest.mark.req("T-54")
def test_the_ledger_continues_on_a_resumed_campaign(tmp_path, monkeypatch):
    patch_planning(monkeypatch)
    stages = ["S0", "S1", "S2", "S4"]
    executor = ScriptedExecutor(engine=None, writer=_writer(tmp_path, stages), studies=_STUDIES,  # type: ignore[arg-type]
                                verdicts={("S2", "A"): "B"})
    executor.run(request(stages))
    campaign = FileReadStore(str(tmp_path)).get_campaign("t1", "camp-s")
    resumed = CampaignArtifactWriter.from_campaign(FileWriteStore(str(tmp_path)), "t1", campaign)
    assert resumed.ledger.to_content() == campaign["ledger"] and resumed.ledger.current == "sha-B"
