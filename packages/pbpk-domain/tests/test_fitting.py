import math

import pytest

from pbpk_domain.fitting import (
    BudgetTooSmallError,
    FitParameter,
    StartResult,
    assess_fit,
    estimate_local_multistart,
    estimate_population_algorithm,
    plan_multistart,
    sample_start_values,
)

LIPO = FitParameter("Lipophilicity", -1.0, 5.0)
CL = FitParameter("CLspec", 0.001, 10.0, log_scale=True)


def test_latin_hypercube_covers_every_stratum_and_is_reproducible():
    starts = sample_start_values([LIPO, CL], n_starts=8, seed=42)
    assert starts == sample_start_values([LIPO, CL], n_starts=8, seed=42)
    for p in (LIPO, CL):
        strata = sorted(int(p.to_unit(s[p.name]) * 8) for s in starts)
        assert strata == list(range(8))


def test_runtime_model_matches_architecture_example():
    # 8 starts x 300 evaluations x 12 studies at 1 s on 96 cores -> 8 parallel starts, 300 s wall.
    local = estimate_local_multistart(8, 300, 12, 1.0, 96)
    assert (local.simulations, local.wall_seconds, local.parallel_starts) == (28_800, 300, 8)
    # One 48-thread server: 4 starts in parallel, two waves.
    assert estimate_local_multistart(8, 300, 12, 1.0, 48).wall_seconds == 600
    population = estimate_population_algorithm(50, 100, 12, 1.0, 96)
    assert population.simulations == 60_000
    assert population.wall_seconds == 100 * math.ceil(600 / 96)


def test_plan_fills_budget_after_reserving_validation_time():
    plan = plan_multistart(
        budget_seconds=3600, reserved_seconds=900, evaluations_per_start=300,
        simulations_per_evaluation=12, seconds_per_simulation=1.0, cores=48,
    )
    assert plan.estimate.wall_seconds <= 2700
    assert plan.n_starts == 32
    with pytest.raises(BudgetTooSmallError, match="reduce fitted parameters"):
        plan_multistart(
            budget_seconds=3600, reserved_seconds=900, evaluations_per_start=300,
            simulations_per_evaluation=12, seconds_per_simulation=10.0, cores=48,
        )


def result(i, lipo, cl, objective, converged=True):
    return StartResult(i, {"Lipophilicity": lipo, "CLspec": cl}, objective, converged, 300)


def test_agreeing_starts_pass():
    results = [result(0, 2.00, 0.50, 10.0), result(1, 2.01, 0.51, 10.01), result(2, 2.02, 0.49, 10.02), result(3, 4.0, 5.0, 30.0)]
    assessment = assess_fit(results, [LIPO, CL])
    assert assessment.acceptable
    assert assessment.agreement_fraction == pytest.approx(0.75)


def test_problems_are_reported():
    scattered = [result(0, 0.5, 0.01, 10.0), result(1, 3.0, 2.0, 10.5), result(2, 4.5, 0.2, 11.0), result(3, 1.5, 8.0, 12.0)]
    codes = {f.code for f in assess_fit(scattered, [LIPO, CL]).findings}
    assert "MULTIPLE_OPTIMA" in codes

    at_bound = assess_fit([result(0, 5.0, 0.5, 1.0), result(1, 4.999, 0.5, 1.0)], [LIPO, CL])
    assert [f.code for f in at_bound.findings] == ["AT_BOUND"]

    correlated = assess_fit(
        [result(0, 2.0, 0.5, 1.0)], [LIPO, CL],
        correlations={("Lipophilicity", "CLspec"): 0.98},
        confidence_intervals={"CLspec": (0.05, 2.0)},
    )
    assert {f.code for f in correlated.findings} == {"HIGHLY_CORRELATED", "POORLY_DETERMINED"}

    assert assess_fit([result(0, 2.0, 0.5, 1.0, converged=False)], [LIPO, CL]).findings[0].code == "NO_CONVERGENCE"
