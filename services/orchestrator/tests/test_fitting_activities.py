import json

from modeler_contracts.runs import EngineInput, EngineManifest, FitParameterBounds, FitRoundRequest, OutputFile
from modeler_orchestrator.fitting_activities import assess_round, plan_jobs

REQUEST = FitRoundRequest(
    round_id="round-1",
    tenant_id="t1",
    base_spec_uri="file:///tmp/base.json",
    base_spec_sha256="a" * 64,
    parameters=[FitParameterBounds("Lipophilicity", -1.0, 5.0), FitParameterBounds("CLspec", 0.001, 10.0, log_scale=True)],
    simulations_per_evaluation=12,
    evaluations_per_start=300,
    seconds_per_simulation=0.2,
    cores=48,
    model_inputs=[EngineInput(name="IV.pkml", uri="file:///tmp/IV.pkml", sha256="b" * 64)],
)


def test_plan_creates_budgeted_starts_with_all_inputs():
    jobs = plan_jobs(REQUEST)
    assert len(jobs) == 32
    assert {i.name for i in jobs[0].inputs} == {"pi_spec_base.json", "IV.pkml"}
    for job in jobs:
        values = job.options["start_values"]
        assert -1.0 <= values["Lipophilicity"] <= 5.0 and 0.001 <= values["CLspec"] <= 10.0
        assert job.timeout_s == 2700
    assert len({j.job_id for j in jobs}) == 32


def manifest_with_result(tmp_path, index, lipo, cl, objective):
    path = tmp_path / f"start-{index}" / "pi_result.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "convergence": True,
                "objective_value": objective,
                "function_evaluations": 250,
                "estimates": [{"name": "Lipophilicity", "estimate": lipo}, {"name": "CLspec", "estimate": cl}],
            }
        )
    )
    return EngineManifest(
        job_id=f"round-1-s{index:03d}", status="SUCCEEDED", engine_id="ospsuite-12.4.4", image_digest="sha256:x",
        started_at="", finished_at="", inputs={}, outputs=[OutputFile("pi_result.json", path.as_uri(), "c" * 64, 10)],
        warnings=[], engine_info={}, stderr_tail="",
    )


def test_assessment_uses_finished_starts_and_reports_the_deadline(tmp_path):
    jobs = plan_jobs(REQUEST)[:4]
    manifests = [
        manifest_with_result(tmp_path, 0, 2.00, 0.50, 10.0),
        manifest_with_result(tmp_path, 1, 2.01, 0.51, 10.02),
        manifest_with_result(tmp_path, 2, 4.00, 5.00, 40.0),
        None,
    ]
    outcome = assess_round(REQUEST, jobs, manifests, deadline_reached=False)
    assert outcome.acceptable and outcome.best_start_index == 0
    assert [s.status for s in outcome.starts] == ["SUCCEEDED", "SUCCEEDED", "SUCCEEDED", "FAILED"]

    at_deadline = assess_round(REQUEST, jobs, manifests, deadline_reached=True)
    assert not at_deadline.acceptable
    assert at_deadline.starts[3].status == "CANCELLED_AT_DEADLINE"
    assert any(f.startswith("DEADLINE_REACHED") for f in at_deadline.findings)
