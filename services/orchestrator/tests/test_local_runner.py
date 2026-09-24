"""The single-node LocalExecutor runs a whole campaign against a stub engine (no Temporal, no subprocess).

A complete renal CPF + its MAP + the golden Aciclovir profile bundle flow through S0 readiness and the S1
round loop; the stub engine writes the golden ``profiles.json`` for each simulate job, so the tier gate passes
and the campaign completes, writing the live monitor view (campaigns.json). A far-off observed dataset makes
the gate fail and the stage escalate, writing an escalation for the review inbox.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_contracts.runs import CampaignRequest, EngineJob, EngineManifest, OutputFile
from modeler_orchestrator.local_runner import CampaignArtifactWriter, LocalExecutor, run_campaign
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import (
    FoodState,
    FormulationKind,
    QuestionOfInterest,
    Route,
    StudyRecord,
    split_studies,
)
from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

GOLDEN = Path(__file__).parents[2] / "engine-worker" / "golden" / "results_sample" / "results.csv"
GOLDEN_AUC, GOLDEN_CMAX = 4064.1245, 50.25272


def _renal_cpf() -> CPF:
    """An S0-complete renal compound (mw, logp, pKa-neutral, fu, solubility, GFR elimination)."""
    prov = Provenance(source_type="measured", reference="OSP Aciclovir")
    return CPF(compound="Renaldrug", parameters=(
        ParameterRecord(id="phys.mw", value=225.2, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=-1.6, unit="Log Units", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.pka.neutral", value=1.0, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="bind.fu", value=0.85, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=1.3, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="elim.renal.gfr_fraction", value=1.0, status=ParameterStatus.FIXED, provenance=prov),
    ))


def _seed_campaign(tmp_path: Path, observed: dict) -> tuple[CampaignRequest, str]:
    """Write CPF + MAP + observed under a read-root; return the CampaignRequest and the root path."""
    root = tmp_path / "read-root"
    tenant_dir = root / "t1"
    (tenant_dir / "cpf").mkdir(parents=True)
    cpf = _renal_cpf()
    cpf_path = tenant_dir / "cpf" / "Renaldrug.json"
    cpf_path.write_text(cpf.model_dump_json(), encoding="utf-8")

    studies = [StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0, infusion_time_min=5.0,
                           formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15)]
    map_doc = generate_map(compound="Renaldrug", cpf=cpf, studies=studies,
                           split=split_studies(studies, QuestionOfInterest()), objective="renal FIH",
                           context_of_use="starting dose", food_effect_in_question=False, model_risk=Rating.MEDIUM,
                           engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"})
    map_path = tenant_dir / "map.json"
    map_path.write_text(map_doc.model_dump_json(), encoding="utf-8")
    obs_path = tenant_dir / "observed.json"
    obs_path.write_text(json.dumps(observed), encoding="utf-8")

    request = CampaignRequest(
        campaign_id="camp-loc", tenant_id="t1", compound="Renaldrug", map_id="map-1",
        cpf_uri=cpf_path.as_uri(), cpf_sha256=hashlib.sha256(cpf_path.read_bytes()).hexdigest(),
        map_uri=map_path.as_uri(), observed_uri=obs_path.as_uri(),
        stages=["S0", "S1"], stage_budgets_seconds={"S1": 600},
    )
    return request, str(root)


def _golden_profile() -> dict:
    rows = [r for r in csv.reader(GOLDEN.open(encoding="utf-8-sig")) if r]
    times = [float(r[1]) for r in rows[1:]]
    concs = [float(r[2]) for r in rows[1:]]
    return {"iv": {"times_min": times, "concentrations": concs, "unit": "µmol/l"}}


class StubEngine:
    """Writes the golden profile bundle for each simulate job (no PK-Sim); returns a SUCCEEDED manifest."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, job: EngineJob) -> EngineManifest:
        self.calls += 1
        out_dir = Path(unquote(urlparse(job.outputs_uri).path))
        out_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[OutputFile] = []
        if job.task == "simulate":
            p = out_dir / "profiles.json"
            p.write_text(json.dumps({"profiles": _golden_profile()}), encoding="utf-8")
            outputs.append(OutputFile(name="profiles.json", uri=p.as_uri(),
                                      sha256=hashlib.sha256(p.read_bytes()).hexdigest(), size_bytes=p.stat().st_size))
        return EngineManifest(job_id=job.job_id, status="SUCCEEDED", engine_id="stub", image_digest="stub",
                              started_at="t0", finished_at="t1", inputs={}, outputs=outputs, warnings=[],
                              engine_info={}, stderr_tail="")


def test_campaign_completes_and_writes_live_monitor(tmp_path: Path) -> None:
    request, root = _seed_campaign(tmp_path, observed={"iv": {"auc": GOLDEN_AUC, "cmax": GOLDEN_CMAX}})
    engine = StubEngine()

    outcome = run_campaign(request, read_root=root, project="renal-demo", question="FIH starting dose",
                           model_risk="medium", engine=engine)

    assert outcome.status == "COMPLETED", outcome.reason
    assert engine.calls >= 1  # the engine actually ran the S1 simulation
    assert [s.stage for s in outcome.stages] == ["S0", "S1"]
    assert outcome.stages[1].status == "PASSED"

    # The monitor read model the web app serves is populated and shows S1 passed with a round + GOF.
    campaign = FileReadStore(root).get_campaign("t1", "camp-loc")
    assert campaign is not None
    assert campaign["status"] == "COMPLETED" and campaign["project"] == "renal-demo"
    s1 = next(s for s in campaign["stages"] if s["stage"] == "S1")
    assert s1["status"] == "PASSED" and s1["rounds"][0]["verdict"] == "passed"
    assert any(series["kind"] == "simulated" for series in campaign["gof"])


def test_far_off_observed_escalates_and_records_review_item(tmp_path: Path) -> None:
    # Observed AUC/Cmax ~10x the simulated golden profile: the tier gate cannot pass, the stage escalates.
    request, root = _seed_campaign(tmp_path, observed={"iv": {"auc": GOLDEN_AUC * 10, "cmax": GOLDEN_CMAX * 10}})
    outcome = run_campaign(request, read_root=root, project="renal-demo", engine=StubEngine())

    assert outcome.status == "ESCALATED"
    escalations = FileReadStore(root).list_escalations("t1")
    assert escalations and escalations[0]["campaignId"] == "camp-loc"
    assert escalations[0]["options"][0]["id"] == "retry"


def test_writer_projects_gmfe_per_round(tmp_path: Path) -> None:
    # The monitor round row carries AUC/Cmax GMFE the executor reads from evaluate's metrics.
    store = FileWriteStore(str(tmp_path))
    writer = CampaignArtifactWriter(store=store, tenant_id="t1", campaign_id="c", project="p", compound="Cmp",
                                    question="q", model_risk="high", budget_seconds=600, stages=["S0", "S1"])
    from modeler_contracts.runs import RoundEvaluation
    writer.add_round("S1", 1, "fit elim.renal.gfr_fraction",
                     RoundEvaluation(gate_passed=False, acceptable=False,
                                     metrics={"AUC": {"gmfe": 1.42}, "Cmax": {"gmfe": 1.31}}))
    writer.flush(current_stage="S1", status="RUNNING")
    row = FileReadStore(str(tmp_path)).get_campaign("t1", "c")["stages"][1]["rounds"][0]
    # a round that misses the gate is "no pass", whatever action it took — never labelled "improved" unmeasured
    assert row["aucGmfe"] == 1.42 and row["cmaxGmfe"] == 1.31 and row["verdict"] == "no pass"


def test_executor_stops_when_s0_not_ready(tmp_path: Path) -> None:
    # A CPF missing an elimination pathway fails S0; the campaign escalates before any engine run.
    request, _root = _seed_campaign(tmp_path, observed={})
    incomplete = CPF(compound="Renaldrug", parameters=(
        ParameterRecord(id="phys.mw", value=225.2, unit="g/mol", status=ParameterStatus.FIXED,
                        provenance=Provenance(source_type="measured", reference="x")),
    ))
    Path(unquote(urlparse(request.cpf_uri).path)).write_text(incomplete.model_dump_json(), encoding="utf-8")
    engine = StubEngine()
    outcome = LocalExecutor(engine=engine, writer=None).run(request)
    assert outcome.status == "ESCALATED" and "S0 readiness failed" in outcome.reason
    assert engine.calls == 0


# --- review-inbox decisions on an escalated campaign (MS-01 §4) -----------------------------------


def _escalated(tmp_path: Path):
    """Run a campaign that cannot pass the gate, leaving an open escalation to decide on."""
    request, root = _seed_campaign(tmp_path, observed={"iv": {"auc": GOLDEN_AUC * 10, "cmax": GOLDEN_CMAX * 10}})
    outcome = run_campaign(request, read_root=root, project="renal-demo", engine=StubEngine())
    assert outcome.status == "ESCALATED"
    return root


def test_abort_decision_ends_the_campaign_and_clears_the_review_item(tmp_path: Path) -> None:
    from modeler_orchestrator.local_runner import resolve_escalation

    root = _escalated(tmp_path)
    assert FileReadStore(root).list_escalations("t1")  # awaiting a decision

    result = resolve_escalation(read_root=root, tenant_id="t1", campaign_id="camp-loc", stage="S1",
                                action="abort", engine=StubEngine(), background=False)

    assert result["status"] == "ABORTED"
    campaign = FileReadStore(root).get_campaign("t1", "camp-loc")
    assert campaign["status"] == "ABORTED"
    assert next(s for s in campaign["stages"] if s["stage"] == "S1")["status"] == "ABORTED"
    assert FileReadStore(root).list_escalations("t1") == []  # resolved, no longer in the inbox
    assert campaign["resume"] is None


def test_accept_best_closes_the_stage_and_finishes_the_campaign(tmp_path: Path) -> None:
    from modeler_orchestrator.local_runner import resolve_escalation

    root = _escalated(tmp_path)
    result = resolve_escalation(read_root=root, tenant_id="t1", campaign_id="camp-loc", stage="S1",
                                action="accept_best", engine=StubEngine(), background=False)

    # S1 was the last stage, so accepting it completes the campaign
    assert result["status"] == "COMPLETED"
    campaign = FileReadStore(root).get_campaign("t1", "camp-loc")
    assert next(s for s in campaign["stages"] if s["stage"] == "S1")["status"] == "ACCEPTED"
    assert campaign["status"] == "COMPLETED"
    assert FileReadStore(root).list_escalations("t1") == []


def test_retry_reruns_the_stage_and_keeps_earlier_history(tmp_path: Path) -> None:
    from modeler_orchestrator.local_runner import resolve_escalation

    root = _escalated(tmp_path)
    before = FileReadStore(root).get_campaign("t1", "camp-loc")
    assert next(s for s in before["stages"] if s["stage"] == "S0")["status"] == "PASSED"

    engine = StubEngine()
    resolve_escalation(read_root=root, tenant_id="t1", campaign_id="camp-loc", stage="S1",
                       action="retry", engine=engine, background=False)

    after = FileReadStore(root).get_campaign("t1", "camp-loc")
    assert engine.calls >= 1  # the stage actually ran again on the engine
    assert next(s for s in after["stages"] if s["stage"] == "S0")["status"] == "PASSED"  # earlier stage kept
    # the observed data is still far off, so it escalates again and is back in the inbox for another decision
    assert FileReadStore(root).list_escalations("t1")


def test_decision_on_a_campaign_with_no_open_escalation_is_rejected(tmp_path: Path) -> None:
    from modeler_orchestrator.local_runner import resolve_escalation

    request, root = _seed_campaign(tmp_path, observed={"iv": {"auc": GOLDEN_AUC, "cmax": GOLDEN_CMAX}})
    run_campaign(request, read_root=root, project="renal-demo", engine=StubEngine())  # completes, no escalation
    import pytest
    with pytest.raises(ValueError, match="no open escalation"):
        resolve_escalation(read_root=root, tenant_id="t1", campaign_id="camp-loc", stage="S1",
                           action="retry", engine=StubEngine(), background=False)


def test_unknown_action_is_rejected(tmp_path: Path) -> None:
    import pytest

    from modeler_orchestrator.local_runner import resolve_escalation
    with pytest.raises(ValueError, match="unknown escalation action"):
        resolve_escalation(read_root=str(tmp_path), tenant_id="t1", campaign_id="c", stage="S1", action="nope")


def test_an_engine_failure_is_recorded_rather_than_hanging(tmp_path: Path) -> None:
    """A crashing engine used to kill the background thread silently, leaving the campaign stuck at RUNNING."""
    request, root = _seed_campaign(tmp_path, observed={"iv": {"auc": GOLDEN_AUC, "cmax": GOLDEN_CMAX}})

    def exploding_engine(job):
        raise RuntimeError("engine exited with status 1")

    outcome = run_campaign(request, read_root=root, project="renal-demo", engine=exploding_engine)

    assert outcome.status == "ESCALATED"
    assert "engine exited with status 1" in outcome.reason
    campaign = FileReadStore(root).get_campaign("t1", "camp-loc")
    assert campaign["status"] == "ESCALATED"          # not left RUNNING
    assert next(s for s in campaign["stages"] if s["stage"] == "S1")["status"] == "FAILED"


def test_iv_only_campaign_runs_every_stage_skipping_those_without_data(tmp_path: Path) -> None:
    """R0/R1: asked for S0–S5, an IV-only compound fits S1, skips S2/S3 with their documented reasons (MS-01
    §6.2), re-simulates the fitted study in S4, and records S5 as not achievable — it no longer stops at S1."""
    request, root = _seed_campaign(tmp_path, observed={"iv": {"auc": GOLDEN_AUC, "cmax": GOLDEN_CMAX}})
    from dataclasses import replace

    request = replace(request, stages=["S0", "S1", "S2", "S3", "S4", "S5"])
    outcome = run_campaign(request, read_root=root, project="renal-demo", engine=StubEngine())

    assert outcome.status == "COMPLETED", outcome.reason
    status = {s.stage: s.status for s in outcome.stages}
    assert status == {"S0": "PASSED", "S1": "PASSED", "S2": "SKIPPED", "S3": "SKIPPED", "S4": "PASSED", "S5": "SKIPPED"}
    assert "§6.2" in next(s for s in outcome.stages if s.stage == "S2").findings[0]
    assert "not achievable" in next(s for s in outcome.stages if s.stage == "S5").findings[0]

    campaign = FileReadStore(root).get_campaign("t1", "camp-loc")
    stages = {s["stage"]: s for s in campaign["stages"]}
    assert stages["S4"]["rounds"][0]["action"] == "validate" and stages["S4"]["rounds"][0]["verdict"] == "passed"
    assert stages["S4"]["rounds"][0]["studies"][0]["study_id"] == "iv"      # per-study evidence for the monitor
    assert any("§6.2" in n for n in stages["S2"]["notes"])                  # the reason is shown, not just logged
    assert set(campaign["gofByStage"]) == {"S1", "S4"}                      # each stage keeps its own plot


def test_failed_internal_validation_escalates_without_refitting(tmp_path: Path) -> None:
    # S1 is not run here, so S4 judges the unfitted model against far-off data: it must escalate, never fit.
    request, root = _seed_campaign(tmp_path, observed={"iv": {"auc": GOLDEN_AUC * 10, "cmax": GOLDEN_CMAX * 10}})
    from dataclasses import replace

    request = replace(request, stages=["S0", "S4"])
    engine = StubEngine()
    outcome = run_campaign(request, read_root=root, project="renal-demo", engine=engine)
    assert outcome.status == "ESCALATED" and "S4" in outcome.reason
    assert engine.calls == 1  # one simulation; a validation stage never starts a fit
    escalation = FileReadStore(root).list_escalations("t1")[0]
    assert escalation["reasonCode"] == "INTERNAL_VALIDATION_FAILED"
    assert [o["id"] for o in escalation["options"]] == ["accept_best", "abort"]  # §6.6: no blind retry
