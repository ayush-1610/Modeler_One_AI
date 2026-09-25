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
from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
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
        # bound to PK-Sim's GFR process, or the pathway could not be placed and S0 refuses the CPF
        ParameterRecord(id="elim.renal.gfr_fraction", value=1.0, status=ParameterStatus.FIXED, provenance=prov,
                        engine_binding=EngineBinding(building_block="Compound", process="GlomerularFiltration",
                                                     parameter="GFR fraction", data_source="Literature")),
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


def test_s0_refuses_a_process_whose_protein_has_no_expression_profile(tmp_path: Path) -> None:
    """MS-01 §S0: an enzyme with no expression profile would eliminate nothing on PK-Sim (proven 2026-09-24)."""
    from modeler_contracts.runs import CampaignRequest as _Req
    from modeler_orchestrator.campaign_activities import plan_campaign
    from pbpk_domain.cpf import EngineBinding

    prov = Provenance(source_type="measured", reference="x")
    base = list(_renal_cpf().parameters)
    unharvested = ParameterRecord(
        id="elim.hepatic.CYP2C99.clspec", value=0.5, unit="l/µmol/min", status=ParameterStatus.FIXED, provenance=prov,
        engine_binding=EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:CYP2C99",
                                     parameter="CLspec/[Enzyme]", data_source="Optimized"))
    path = tmp_path / "cpf.json"
    path.write_text(CPF(compound="Renaldrug", parameters=(*base, unharvested)).model_dump_json(), encoding="utf-8")
    readiness = plan_campaign(_Req(campaign_id="c", tenant_id="t1", compound="Renaldrug", map_id="m",
                                   cpf_uri=path.as_uri(), cpf_sha256="a" * 64))
    assert readiness.ready is False
    assert any("no expression profile for CYP2C99" in f for f in readiness.findings)


def test_fit_starts_run_in_parallel_as_planned(monkeypatch) -> None:
    """The multistart plan assumes parallel starts; running them one by one multiplied the fit time by up to 32."""
    import threading
    import time as _time

    from modeler_orchestrator import local_runner as lr

    class Req:
        simulations_per_evaluation, cores = 1, 8

    jobs = [object() for _ in range(6)]
    monkeypatch.setattr(lr, "plan_jobs", lambda request: jobs)
    monkeypatch.setattr(lr, "assess_fit_round", lambda request, j, manifests, deadline_reached: manifests)
    active, peak, lock = [0], [0], threading.Lock()

    def engine(job):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        _time.sleep(0.05)
        with lock:
            active[0] -= 1
        return job

    monkeypatch.delenv("MODELER_FIT_WORKERS", raising=False)
    monkeypatch.setattr(lr.os, "cpu_count", lambda: 4)
    assert lr.LocalExecutor(engine=engine)._run_fit(Req()) == jobs      # results in job order
    assert peak[0] == 4                                                  # min(plan 8, cpus 4, jobs 6)
    monkeypatch.setenv("MODELER_FIT_WORKERS", "1")
    peak[0] = 0
    lr.LocalExecutor(engine=engine)._run_fit(Req())
    assert peak[0] == 1                                                  # a host can force one at a time


class VpcStubEngine(StubEngine):
    """Also exports the per-study model and answers population jobs with a band `scale` × the golden profile."""

    def __init__(self, low: float, high: float) -> None:
        super().__init__()
        self.low, self.high, self.population_jobs = low, high, 0

    def __call__(self, job: EngineJob) -> EngineManifest:
        manifest = super().__call__(job)
        out_dir = Path(unquote(urlparse(job.outputs_uri).path))
        outputs = list(manifest.outputs)
        if job.task == "simulate" and job.options.get("export_pkml"):
            p = out_dir / "snapshot-iv.pkml"
            p.write_text("<pkml/>", encoding="utf-8")
            outputs.append(OutputFile(name=p.name, uri=p.as_uri(), sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                      size_bytes=p.stat().st_size))
        if job.task == "population":
            self.population_jobs += 1
            assert job.options["population"]["number_of_individuals"] == 100 and job.options["vpc"]["output_path"]
            g = _golden_profile()["iv"]
            band = {"individuals": 100, "times_min": g["times_min"], "percentiles": {
                "5": [c * self.low for c in g["concentrations"]], "50": g["concentrations"],
                "95": [c * self.high for c in g["concentrations"]]}}
            p = out_dir / "vpc.json"
            p.write_text(json.dumps(band), encoding="utf-8")
            outputs.append(OutputFile(name=p.name, uri=p.as_uri(), sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                      size_bytes=p.stat().st_size))
        return manifest.__class__(**{**manifest.__dict__, "outputs": outputs})


def _golden_observed() -> dict:
    """Observed data sampled from the golden curve; AUC and Cmax by NCA of those samples, as campaign:prepare does
    (the observed PK must be the PK of the observed profile, or the comparison is not like with like)."""
    from pbpk_domain.nca import nca

    g = _golden_profile()["iv"]
    idx = range(5, len(g["times_min"]), 20)
    times = [g["times_min"][i] for i in idx]
    values = [g["concentrations"][i] for i in idx]
    pk = nca(times, values)
    return {"iv": {"auc": pk.auc_last, "cmax": pk.c_max, "profile": {
        "times": times, "values": values, "time_unit": "min", "unit": "µmol/l"}}}


def test_vpc_gates_s1_and_is_recorded_per_study(tmp_path: Path) -> None:
    """MS-01 S1: ≥ 80 % of observed points inside the 5–95 % band of a 100-individual population."""
    request, root = _seed_campaign(tmp_path, observed=_golden_observed())
    engine = VpcStubEngine(low=0.5, high=2.0)
    outcome = run_campaign(request, read_root=root, project="p", engine=engine)
    assert outcome.status == "COMPLETED", outcome.reason
    assert engine.population_jobs == 1
    rnd = next(s for s in FileReadStore(root).get_campaign("t1", "camp-loc")["stages"] if s["stage"] == "S1")["rounds"][0]
    assert rnd["verdict"] == "passed"


def test_vpc_that_misses_the_data_escalates_with_its_own_reason(tmp_path: Path) -> None:
    request, root = _seed_campaign(tmp_path, observed=_golden_observed())
    engine = VpcStubEngine(low=1.5, high=2.0)  # band sits above every observed point
    outcome = run_campaign(request, read_root=root, project="p", engine=engine)
    assert outcome.status == "ESCALATED" and "vpc_coverage_below_80" in outcome.reason
    assert "VPC: 0/" in outcome.reason  # the finding says how many points were covered


def test_s4_reports_a_low_vpc_but_does_not_gate_on_it(tmp_path: Path) -> None:
    """MS-01 §4: the VPC gates S1/S2; at S4 it is a report item ("VPC per study"), the gate is PK acceptance."""
    request, root = _seed_campaign(tmp_path, observed=_golden_observed())
    from dataclasses import replace

    request = replace(request, stages=["S0", "S4"])
    outcome = run_campaign(request, read_root=root, project="p", engine=VpcStubEngine(low=1.5, high=2.0))
    assert outcome.status == "COMPLETED", outcome.reason
    s4 = next(s for s in outcome.stages if s.stage == "S4")
    assert s4.status == "PASSED" and any("reported, not gated at S4" in f for f in s4.findings)


class FullStubEngine(VpcStubEngine):
    """Everything S0–S7 asks of the engine: simulations with result tables, VPC bands, sensitivity, batches."""

    def __call__(self, job: EngineJob) -> EngineManifest:
        manifest = super().__call__(job)
        out_dir = Path(unquote(urlparse(job.outputs_uri).path))
        outputs = list(manifest.outputs)

        def emit(name: str, data: bytes) -> None:
            p = out_dir / name
            p.write_bytes(data)
            outputs.append(OutputFile(name=name, uri=p.as_uri(), sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data)))

        golden = GOLDEN.read_bytes()
        if job.task == "simulate":
            emit("snapshot-iv-Results.csv", golden)
        if job.task == "convert_to_project":  # PK-Sim saves the project the snapshot loads into (run_job.R)
            emit("snapshot.pksim5", b"PK-Sim project")
        if job.task == "sensitivity":
            path = job.options["parameter_paths"][0]
            emit("sensitivity.csv", ("QuantityPath,Parameter,PKParameter,Value\n"
                                     f"Organism|PeripheralVenousBlood|Renaldrug|Plasma (Peripheral Venous Blood),{path},C_max,-0.42\n"
                                     ).encode())
        if job.task == "batch":
            runs = job.options["runs"]
            index = {"parameter_paths": job.options["parameter_paths"], "runs": []}
            for i, _run in enumerate(runs, start=1):
                emit(f"batch-{i:03d}-results.csv", golden)
                index["runs"].append({"run": i, "results": f"batch-{i:03d}-results.csv"})
            emit("batch_index.json", json.dumps(index).encode())
        return manifest.__class__(**{**manifest.__dict__, "outputs": outputs})


def test_campaign_runs_s0_to_s7_with_the_signature_gate_and_releases_a_reproducible_package(tmp_path: Path, monkeypatch) -> None:
    """The whole pipeline: S6 waits for the signed S4/S5 evaluation (MS-01 §4 S6), then S6 predicts and S7
    re-runs every bundled simulation, writes the MAR and releases the package only because reproduction passed."""
    from dataclasses import replace

    from modeler_orchestrator.local_runner import resolve_escalation
    from pbpk_domain.cpf import FitPolicy, Uncertainty

    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", (tmp_path / "objstore").as_uri())
    request, root = _seed_campaign(tmp_path, observed=_golden_observed())
    cpf_path = Path(unquote(urlparse(request.cpf_uri).path))
    cpf = CPF.model_validate_json(cpf_path.read_text())
    prov = Provenance(source_type="ParameterIdentification", run="camp-loc-S1-r2")
    fitted = cpf.get("phys.logp").model_copy(update={
        "status": ParameterStatus.FITTED, "provenance": prov, "fit_policy": FitPolicy(stage=("S1",), lower=-3.0, upper=0.0),
        "uncertainty": Uncertainty(sd=0.1, cv_percent=6.0, ci95_lower=-1.8, ci95_upper=-1.4)})
    cpf_path.write_text(cpf.replace(fitted).model_dump_json())
    request = replace(request, stages=["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"],
                      cpf_sha256=hashlib.sha256(cpf_path.read_bytes()).hexdigest())
    engine = FullStubEngine(low=0.5, high=2.0)

    first = run_campaign(request, read_root=root, project="p", engine=engine)
    assert first.status == "AWAITING_SIGNATURE"
    inbox = FileReadStore(root).list_escalations("t1")
    assert inbox[0]["reasonCode"] == "SIGNATURE_REQUIRED" and inbox[0]["options"][0]["id"] == "approve"

    resolve_escalation(read_root=root, tenant_id="t1", campaign_id="camp-loc", stage="S6", action="approve",
                       engine=engine, background=False)
    campaign = FileReadStore(root).get_campaign("t1", "camp-loc")
    assert campaign["status"] == "COMPLETED", [s["notes"] for s in campaign["stages"]]
    status = {s["stage"]: s["status"] for s in campaign["stages"]}
    assert status["S6"] == "PASSED" and status["S7"] == "PASSED"
    # S6: a sensitivity ranking and prediction intervals from 200 uncertainty draws
    assert campaign["prediction"]["sensitivity"]["iv"][0]["parameter"] == "phys.logp"
    assert campaign["prediction"]["intervals"]["iv"]["AUC"]["n"] == 200
    # S7: reproduction passed on the bundled result table, the MAR rendered, the package released
    package = campaign["package"]
    assert package["reproduction"]["passes"] and package["reproduction"]["compared"] >= 1
    assert package["exportable"] and Path(package["package"]).exists()
    mar = Path(package["report"]["md"]).read_text()
    assert "Internal validation" in mar and "Prediction intervals" in mar and "phys.logp" in mar
    import zipfile

    names = zipfile.ZipFile(package["package"]).namelist()
    assert {"manifest.json", "rerun_all.R", "cpf/final.json", "map/map.json"} <= set(names)
    assert any(n.startswith("results/S4-camp-loc/") for n in names)  # the numeric tables the re-run is judged on
    # the PK-Sim project of every bundled simulation, the file a reviewer opens in PK-Sim
    assert {"pksim/S4-camp-loc.pksim5", "pksim/S5-camp-loc.pksim5"} & set(names)
    assert package["pksim_projects"] and not package.get("project_notes")


def test_package_is_withheld_when_reproduction_fails(tmp_path: Path, monkeypatch) -> None:
    """Decision D13: no export unless the re-run reproduces the bundled results."""
    from dataclasses import replace

    from modeler_orchestrator.local_runner import resolve_escalation

    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", (tmp_path / "objstore").as_uri())
    request, root = _seed_campaign(tmp_path, observed=_golden_observed())
    request = replace(request, stages=["S0", "S1", "S4", "S6", "S7"])

    class Drifting(FullStubEngine):
        def __call__(self, job: EngineJob) -> EngineManifest:
            manifest = super().__call__(job)
            if job.job_id.startswith("camp-loc-S7-rerun"):
                for o in manifest.outputs:
                    if o.name.endswith("-Results.csv"):
                        p = Path(unquote(urlparse(o.uri).path))
                        p.write_text(p.read_text().replace("50.25272", "51.0"))  # the re-run disagrees
            return manifest

    engine = Drifting(low=0.5, high=2.0)
    run_campaign(request, read_root=root, project="p", engine=engine)
    resolve_escalation(read_root=root, tenant_id="t1", campaign_id="camp-loc", stage="S6", action="approve",
                       engine=engine, background=False)
    campaign = FileReadStore(root).get_campaign("t1", "camp-loc")
    assert campaign["status"] == "ESCALATED"
    assert campaign["package"]["exportable"] is False and "package" not in campaign["package"]
    assert campaign["package"]["reproduction"]["failures"]


def test_s0_refuses_an_elimination_pathway_the_builder_cannot_place(tmp_path: Path) -> None:
    """A CPF clearance with no engine binding would be silently absent from every simulation (found 2026-09-24
    when a finished report listed 'NOT PLACED IN THE MODEL' yet concluded the model met its tier)."""
    from modeler_contracts.runs import CampaignRequest as _Req
    from modeler_orchestrator.campaign_activities import plan_campaign

    prov = Provenance(source_type="measured", reference="x")
    params = [p if p.id != "elim.renal.gfr_fraction" else
              ParameterRecord(id=p.id, value=1.0, status=ParameterStatus.FIXED, provenance=prov)  # unbound
              for p in _renal_cpf().parameters]
    path = tmp_path / "cpf.json"
    path.write_text(CPF(compound="Renaldrug", parameters=tuple(params)).model_dump_json(), encoding="utf-8")
    readiness = plan_campaign(_Req(campaign_id="c", tenant_id="t1", compound="Renaldrug", map_id="m",
                                   cpf_uri=path.as_uri(), cpf_sha256="a" * 64))
    assert readiness.ready is False
    assert any("elim.renal.gfr_fraction cannot be placed in the model" in f for f in readiness.findings)
