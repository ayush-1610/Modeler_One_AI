"""run_round finalizes a round from the engine manifest, and the run->evaluate chain (T-13 <-> T-09 wiring).

No engine needed: run_round reads the engine's profiles.json output from the manifest and points the round's
result at it; a synthesized manifest (carrying the golden profile bundle) flows through run_round into
evaluate_round and passes the tier gate, exercising the whole simulate->evaluate chain minus the subprocess.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from modeler_contracts.runs import (
    EngineManifest,
    FitRoundOutcome,
    FitStartOutcome,
    OutputFile,
    RoundBuild,
    RoundContext,
    RoundRun,
    RoundRunResult,
)
from modeler_orchestrator.campaign_activities import evaluate_round, prepare_round_job, run_round
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import (
    FoodState,
    FormulationKind,
    QuestionOfInterest,
    Route,
    StudyRecord,
    split_studies,
)
from pbpk_domain.cpf import CPF, FitPolicy, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

GOLDEN = Path(__file__).parents[2] / "engine-worker" / "golden" / "results_sample" / "results.csv"
GOLDEN_AUC, GOLDEN_CMAX = 4064.1245, 50.25272


def _ctx(**kw) -> RoundContext:
    base = dict(campaign_id="c1", tenant_id="t1", stage="S1", round_index=1,
                cpf_uri="file:///tmp/cpf.json", cpf_sha256="a" * 64, pending_action=None)
    base.update(kw)
    return RoundContext(**base)


def _manifest(outputs: list[OutputFile], status: str = "SUCCEEDED") -> EngineManifest:
    return EngineManifest(
        job_id="c1-S1-r1", status=status, engine_id="e", image_digest="sha256:x",
        started_at="t0", finished_at="t1", inputs={"snapshot.json": "b" * 64},
        outputs=outputs, warnings=[], engine_info={}, stderr_tail="",
    )


def _build() -> RoundBuild:
    return RoundBuild(snapshot_uri="file:///tmp/snap.json", snapshot_sha256="b" * 64)


# --- run_round finalization ----------------------------------------------------------------------


def test_points_result_at_engine_profiles(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps({"profiles": {"iv": {"times_min": [0, 1], "concentrations": [0, 1]}}}))
    manifest = _manifest([
        OutputFile(name="results/iv.csv", uri="file:///x/iv.csv", sha256="c" * 64, size_bytes=10),
        OutputFile(name="profiles.json", uri=profiles.as_uri(), sha256="d" * 64, size_bytes=20),
    ])
    result = run_round(RoundRun(context=_ctx(), build=_build(), manifest=manifest))
    assert result.results_uri == profiles.as_uri()
    assert result.cpf_uri == "file:///tmp/cpf.json"  # CPF carried forward (no fit applied yet)


def test_no_manifest_reports_no_results() -> None:
    result = run_round(RoundRun(context=_ctx(), build=_build(), manifest=None))
    assert result.results_uri.endswith("#no-results-r1")


def test_manifest_without_profiles_reports_no_results() -> None:
    manifest = _manifest([OutputFile(name="results/iv.csv", uri="file:///x/iv.csv", sha256="c" * 64, size_bytes=10)])
    result = run_round(RoundRun(context=_ctx(), build=_build(), manifest=manifest))
    assert result.results_uri.endswith("#no-results-r1")


def test_failed_engine_reports_no_results(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps({"profiles": {}}))
    manifest = _manifest([OutputFile(name="profiles.json", uri=profiles.as_uri(), sha256="d" * 64, size_bytes=20)], status="CANCELLED")
    result = run_round(RoundRun(context=_ctx(), build=_build(), manifest=manifest))
    assert result.results_uri.endswith("#no-results-r1")


# --- prepare_round_job ---------------------------------------------------------------------------


def test_prepare_round_job_builds_simulate_job(monkeypatch) -> None:
    monkeypatch.setenv("MODELER_OBJECT_STORE_URI", "file:///store")
    job = prepare_round_job(_ctx(deadline_seconds=120.0), _build())
    assert job.task == "simulate"
    assert job.job_id == "c1-S1-r1"
    assert [i.name for i in job.inputs] == ["snapshot.json"]
    assert job.inputs[0].uri == "file:///tmp/snap.json"
    assert job.outputs_uri == "file:///store/tenants/t1/campaigns/c1/S1/r1"
    assert job.timeout_s == 120


# --- run -> evaluate chain over the golden profile bundle ----------------------------------------


def _golden_profiles(tmp_path: Path) -> str:
    rows = [r for r in csv.reader(GOLDEN.open(encoding="utf-8-sig")) if r]
    times = [float(r[1]) for r in rows[1:]]
    concs = [float(r[2]) for r in rows[1:]]
    p = tmp_path / "profiles.json"
    p.write_text(json.dumps({"profiles": {"iv": {"times_min": times, "concentrations": concs}}}))
    return p.as_uri()


def _map_and_observed(tmp_path: Path) -> tuple[str, str]:
    prov = Provenance(source_type="measured", reference="x")
    cpf = CPF(compound="Example-A", parameters=(
        ParameterRecord(id="phys.mw", value=408.5, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.6, unit="Log Units", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="bind.fu", value=0.02, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=0.1, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
    ))
    studies = [StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0, infusion_time_min=5.0,
                           formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15)]
    m = generate_map(compound="Example-A", cpf=cpf, studies=studies, split=split_studies(studies, QuestionOfInterest()),
                     objective="o", context_of_use="c", food_effect_in_question=False, model_risk=Rating.HIGH,
                     engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"})
    map_p = tmp_path / "map.json"
    map_p.write_text(m.model_dump_json(), encoding="utf-8")
    obs_p = tmp_path / "observed.json"
    obs_p.write_text(json.dumps({"iv": {"auc": GOLDEN_AUC, "cmax": GOLDEN_CMAX}}))
    return map_p.as_uri(), obs_p.as_uri()


def _fit_outcome(estimates: dict, *, best: int | None = 0) -> FitRoundOutcome:
    return FitRoundOutcome(
        round_id="c1-S1-r1", planned_starts=1,
        starts=[FitStartOutcome(start_index=0, status="SUCCEEDED", estimates=estimates, objective=0.1, converged=True, evaluations=30)],
        acceptable=True, findings=[], best_start_index=best, deadline_reached=False,
    )


def test_run_round_applies_fit_estimates_to_a_new_cpf(tmp_path: Path) -> None:
    prov = Provenance(source_type="measured", reference="x")
    cpf = CPF(compound="Drug", parameters=(
        ParameterRecord(id="phys.mw", value=300.0, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.5, unit="Log Units", status=ParameterStatus.PREDICTED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=4.0)),
    ))
    cpf_path = tmp_path / "cpf.json"
    cpf_path.write_text(cpf.model_dump_json(), encoding="utf-8")
    ctx = _ctx(cpf_uri=cpf_path.as_uri(), cpf_sha256="a" * 64)
    manifest = _manifest([OutputFile(name="profiles.json", uri=_golden_profiles(tmp_path), sha256="d" * 64, size_bytes=20)])

    result = run_round(RoundRun(context=ctx, build=_build(), manifest=manifest, fit_outcome=_fit_outcome({"phys.logp": 3.3})))

    assert result.cpf_uri != ctx.cpf_uri  # a new CPF version was written
    from pbpk_domain.cpf import CPF as _CPF
    updated = _CPF.model_validate_json(Path(result.cpf_uri.removeprefix("file://")).read_text())
    assert updated.version == cpf.version + 1
    logp = updated.require("phys.logp")
    assert logp.numeric_value == 3.3 and logp.status.value == "FITTED"


def test_run_round_no_estimates_carries_cpf_forward(tmp_path: Path) -> None:
    ctx = _ctx()
    manifest = _manifest([OutputFile(name="profiles.json", uri=_golden_profiles(tmp_path), sha256="d" * 64, size_bytes=20)])
    result = run_round(RoundRun(context=ctx, build=_build(), manifest=manifest, fit_outcome=_fit_outcome({}, best=None)))
    assert result.cpf_uri == ctx.cpf_uri and result.cpf_sha256 == ctx.cpf_sha256


def test_manifest_flows_through_run_round_into_evaluate(tmp_path: Path) -> None:
    map_uri, observed_uri = _map_and_observed(tmp_path)
    manifest = _manifest([OutputFile(name="profiles.json", uri=_golden_profiles(tmp_path), sha256="d" * 64, size_bytes=20)])
    ctx = _ctx(map_uri=map_uri, observed_uri=observed_uri)

    run_result = run_round(RoundRun(context=ctx, build=_build(), manifest=manifest))
    assert isinstance(run_result, RoundRunResult)
    evaluation = evaluate_round(ctx, run_result)
    assert evaluation.gate_passed is True
    assert evaluation.metrics["AUC"]["n"] == 1


def test_collect_pkml_inputs_from_manifest() -> None:
    from modeler_contracts.runs import EngineInput
    from modeler_orchestrator.campaign_activities import collect_pkml_inputs
    manifest = _manifest([
        OutputFile(name="camp1-S1-r1-iv.pkml", uri="file:///o/camp1-S1-r1-iv.pkml", sha256="e" * 64, size_bytes=100),
        OutputFile(name="profiles.json", uri="file:///o/profiles.json", sha256="d" * 64, size_bytes=20),
        OutputFile(name="camp1-S1-r1-iv-Results.csv", uri="file:///o/x.csv", sha256="c" * 64, size_bytes=30),
    ])
    inputs = collect_pkml_inputs(manifest)
    assert inputs == [EngineInput(name="camp1-S1-r1-iv.pkml", uri="file:///o/camp1-S1-r1-iv.pkml", sha256="e" * 64)]
