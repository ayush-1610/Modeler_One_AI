import json

import pytest

from modeler_contracts.runs import EngineInput, EngineManifest, FitParameterBounds, FitRoundRequest, OutputFile, fit_signals
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
                "estimates": [{"name": "Lipophilicity", "estimate": lipo, "scale": "linear"},
                              {"name": "CLspec", "estimate": cl, "scale": "log"}],
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


def _identifiability_manifest(tmp_path, index, objective, *, correlations=None, ci_error=None):
    path = tmp_path / f"start-{index}" / "pi_result.json"
    path.parent.mkdir()
    result = {
        "convergence": True, "objective_value": objective, "function_evaluations": 120,
        "estimates": [{"name": "Lipophilicity", "estimate": 2.0, "sd": 0.1, "cv": 0.05, "lowerCI": 1.8, "upperCI": 2.2,
                       "scale": "linear"},
                      {"name": "CLspec", "estimate": 0.5, "sd": 0.6, "cv": 1.2, "lowerCI": 0.05, "upperCI": 4.8, "scale": "log"}],
        "correlations": correlations or [],
    }
    if ci_error:
        result["ci_error"] = ci_error
    path.write_text(json.dumps(result))
    return EngineManifest(
        job_id=f"round-1-s{index:03d}", status="SUCCEEDED", engine_id="ospsuite-12.4.4", image_digest="sha256:x",
        started_at="", finished_at="", inputs={}, outputs=[OutputFile("pi_result.json", path.as_uri(), "c" * 64, 10)],
        warnings=[], engine_info={}, stderr_tail="",
    )


def test_the_best_starts_correlations_and_intervals_are_flagged_and_its_strong_pairs_reach_the_diagnosis(tmp_path):
    """PI-2 (2026-10-24): run_pi.R exports the Hessian CI's correlations. A pair beyond 0.95 and a CI wider than its
    estimate are flagged. PI-2b (2026-10-25): the best start's pairs beyond 0.95 are handed to the diagnosis, which
    carries out MS-01's fix_and_refit."""
    jobs = plan_jobs(REQUEST)[:2]
    manifests = [_identifiability_manifest(tmp_path, 0, 10.0, correlations=[{"a": "Lipophilicity", "b": "CLspec", "r": -0.97}]),
                 _identifiability_manifest(tmp_path, 1, 10.01, correlations=[{"a": "Lipophilicity", "b": "CLspec", "r": 0.1}])]
    outcome = assess_round(REQUEST, jobs, manifests, deadline_reached=False)
    assert outcome.best_start_index == 0 and outcome.correlations == [{"a": "Lipophilicity", "b": "CLspec", "r": -0.97}]
    assert any(f.startswith("HIGHLY_CORRELATED: Lipophilicity and CLspec") for f in outcome.findings)
    assert any(f.startswith("POORLY_DETERMINED: CLspec") for f in outcome.findings)
    assert not any("Lipophilicity: 95%" in f for f in outcome.findings)  # a narrow CI is not flagged
    assert outcome.correlated_pairs == [["Lipophilicity", "CLspec"]] and not outcome.acceptable
    assert fit_signals(outcome)["correlated_pairs"] == [["Lipophilicity", "CLspec"]]
    assert outcome.starts[0].uncertainty["CLspec"] == {"sd": 0.6, "cv": 1.2, "ci_lower": 0.05, "ci_upper": 4.8}


@pytest.mark.req("T-14")
def test_a_pair_below_the_limit_is_recorded_but_not_handed_on_and_the_strongest_pair_comes_first(tmp_path):
    jobs = plan_jobs(REQUEST)[:1]
    weak = assess_round(REQUEST, jobs, [_identifiability_manifest(
        tmp_path, 0, 10.0, correlations=[{"a": "Lipophilicity", "b": "CLspec", "r": 0.95}])], deadline_reached=False)
    assert weak.correlated_pairs == [] and weak.correlations == [{"a": "Lipophilicity", "b": "CLspec", "r": 0.95}]

    from pbpk_domain.fitting import FitParameter, StartResult, assess_fit

    params = [FitParameter(n, 0.0, 10.0) for n in ("a", "b", "c")]
    result = assess_fit([StartResult(0, {"a": 5.0, "b": 5.0, "c": 5.0}, 1.0, True, 10)], params,
                        correlations={("a", "b"): 0.96, ("a", "c"): -0.99, ("b", "c"): 0.2})
    assert result.correlated_pairs == (("a", "c"), ("a", "b"))


def test_a_fit_without_a_ci_says_why(tmp_path):
    jobs = plan_jobs(REQUEST)[:1]
    outcome = assess_round(REQUEST, jobs, [_identifiability_manifest(
        tmp_path, 0, 10.0, ci_error="Covariance matrix validity check: Covariance matrix is not positive definite.")],
        deadline_reached=False)
    assert outcome.ci_error.endswith("not positive definite.") and outcome.correlations == []
    assert any(f.startswith("NO_CI: Covariance matrix validity check") for f in outcome.findings)


def test_a_start_whose_engine_ignored_the_signed_log_scale_is_not_used(tmp_path):
    """PI-4 B1b (2026-11-02): the spec passes the signed log scale and the engine says what it applied. An engine image
    older than B1 ignores the scale and fits the linear value, which would contradict the signed MAP."""
    jobs = plan_jobs(REQUEST)[:2]
    honoured = manifest_with_result(tmp_path, 0, 2.00, 0.50, 10.0)
    old = manifest_with_result(tmp_path, 1, 2.00, 0.50, 9.0)
    path = tmp_path / "start-1" / "pi_result.json"
    data = json.loads(path.read_text())
    for e in data["estimates"]:
        e.pop("scale")
    path.write_text(json.dumps(data))
    outcome = assess_round(REQUEST, jobs, [honoured, old], deadline_reached=False)
    assert [s.status for s in outcome.starts] == ["SUCCEEDED", "FAILED"] and outcome.best_start_index == 0
    assert any(f.startswith("ENGINE_SCALE_IGNORED: the engine did not fit CLspec on the signed log scale")
               for f in outcome.findings)
    only_old = assess_round(REQUEST, jobs[1:], [old], deadline_reached=False)
    assert not only_old.acceptable and only_old.best_start_index is None


def test_a_grouped_fit_is_assessed_on_its_factor_and_its_members_estimates_are_applied(tmp_path):
    """PI-4 B2: the engine optimises a group's factor in place of its members (run_pi.R). The starts are compared on
    the factor, its CI and correlations name the group, and the members' estimates (factor x start) are what the CPF
    receives."""
    request = FitRoundRequest(
        round_id="round-g", tenant_id="t1", base_spec_uri="file:///tmp/base.json", base_spec_sha256="a" * 64,
        parameters=[FitParameterBounds("Lipophilicity", -1.0, 5.0), FitParameterBounds("hepatic", 0.1, 10.0, log_scale=True)],
        simulations_per_evaluation=12, evaluations_per_start=300, seconds_per_simulation=0.2, cores=48,
        model_inputs=[EngineInput(name="IV.pkml", uri="file:///tmp/IV.pkml", sha256="b" * 64)],
    )
    jobs = plan_jobs(request)[:2]
    manifests = []
    for index, (factor, objective, group_scale) in enumerate([(0.5, 10.0, "log"), (0.52, 10.01, "log")]):
        path = tmp_path / f"start-{index}" / "pi_result.json"
        path.parent.mkdir()
        path.write_text(json.dumps({
            "convergence": True, "objective_value": objective, "function_evaluations": 90,
            "estimates": [{"name": "Lipophilicity", "estimate": 2.0, "scale": "linear"},
                          {"name": "cyp", "estimate": 0.4 * factor, "scale": group_scale, "group": "hepatic"},
                          {"name": "ugt", "estimate": 0.2 * factor, "scale": group_scale, "group": "hepatic"}],
            "groups": [{"name": "hepatic", "scale": group_scale, "factor": factor, "sd": 0.01, "cv": 0.02,
                        "lowerCI": factor * 0.96, "upperCI": factor * 1.04, "members": ["cyp", "ugt"]}],
            "correlations": [{"a": "Lipophilicity", "b": "hepatic", "r": 0.2}],
        }))
        manifests.append(EngineManifest(
            job_id=f"round-g-s{index:03d}", status="SUCCEEDED", engine_id="ospsuite-12.4.4", image_digest="sha256:x",
            started_at="", finished_at="", inputs={}, outputs=[OutputFile("pi_result.json", path.as_uri(), "c" * 64, 10)],
            warnings=[], engine_info={}, stderr_tail=""))
    assert all("hepatic" in j.options["start_values"] and "cyp" not in j.options["start_values"] for j in jobs)
    outcome = assess_round(request, jobs, manifests, deadline_reached=False)
    assert outcome.acceptable and outcome.best_start_index == 0 and outcome.starts_agreement == 1.0
    best = outcome.starts[0]
    assert best.estimates == {"Lipophilicity": 2.0, "cyp": 0.2, "ugt": 0.1}            # what the CPF receives
    assert best.groups["hepatic"] == {"factor": 0.5, "sd": 0.01, "cv": 0.02, "ci_lower": 0.48, "ci_upper": 0.52}
    assert outcome.correlations == [{"a": "Lipophilicity", "b": "hepatic", "r": 0.2}]
    assert not any(f.startswith("ENGINE_SCALE_IGNORED") for f in outcome.findings)
