"""Planning and checking for parameter identification (PI).

Pure, deterministic logic used by the fitting workflow:
- start values for multi-start fitting (Latin hypercube, log space for log-scaled parameters)
- runtime estimates and a multi-start plan that fits a wall-clock budget
- agreement between starts, parameters at bounds, correlation and precision checks

Runtime model. Inside one local optimization, evaluations run one after another; only the
simulations of a single evaluation (one per study) run in parallel. More cores therefore give more
simultaneous starts, not a faster single start. Population algorithms (DEoptim) evaluate a whole
generation at once and do get faster with more cores.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FitParameter:
    name: str
    lower: float
    upper: float
    log_scale: bool = False

    def __post_init__(self) -> None:
        if not self.lower < self.upper:
            raise ValueError(f"{self.name}: lower bound must be below upper bound")
        if self.log_scale and self.lower <= 0:
            raise ValueError(f"{self.name}: log-scaled parameters need a positive lower bound")

    def to_unit(self, value: float) -> float:
        """Position of a value inside the bounds, 0 at the lower and 1 at the upper bound."""
        if self.log_scale:
            return (math.log(value) - math.log(self.lower)) / (math.log(self.upper) - math.log(self.lower))
        return (value - self.lower) / (self.upper - self.lower)

    def from_unit(self, u: float) -> float:
        if self.log_scale:
            return math.exp(math.log(self.lower) + u * (math.log(self.upper) - math.log(self.lower)))
        return self.lower + u * (self.upper - self.lower)


def sample_start_values(parameters: Sequence[FitParameter], n_starts: int, seed: int) -> list[dict[str, float]]:
    """Latin hypercube start values: each parameter's range is split into n_starts strata, one draw per stratum."""
    if n_starts < 1:
        raise ValueError("n_starts must be >= 1")
    rng = np.random.default_rng(seed)
    columns = {p.name: (rng.permutation(n_starts) + rng.random(n_starts)) / n_starts for p in parameters}
    return [{p.name: p.from_unit(float(columns[p.name][i])) for p in parameters} for i in range(n_starts)]


# --- runtime ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeEstimate:
    algorithm: str
    simulations: int
    wall_seconds: float
    parallel_starts: int = 1


def estimate_local_multistart(
    n_starts: int,
    evaluations_per_start: int,
    simulations_per_evaluation: int,
    seconds_per_simulation: float,
    cores: int,
) -> RuntimeEstimate:
    cores_per_start = min(simulations_per_evaluation, cores)
    parallel_starts = max(1, cores // cores_per_start)
    seconds_per_evaluation = seconds_per_simulation * math.ceil(simulations_per_evaluation / cores_per_start)
    waves = math.ceil(n_starts / parallel_starts)
    return RuntimeEstimate(
        algorithm="local multi-start",
        simulations=n_starts * evaluations_per_start * simulations_per_evaluation,
        wall_seconds=waves * evaluations_per_start * seconds_per_evaluation,
        parallel_starts=min(parallel_starts, n_starts),
    )


def estimate_population_algorithm(
    population_size: int,
    generations: int,
    simulations_per_evaluation: int,
    seconds_per_simulation: float,
    cores: int,
) -> RuntimeEstimate:
    simulations_per_generation = population_size * simulations_per_evaluation
    return RuntimeEstimate(
        algorithm="population (DEoptim)",
        simulations=generations * simulations_per_generation,
        wall_seconds=generations * math.ceil(simulations_per_generation / cores) * seconds_per_simulation,
    )


class BudgetTooSmallError(ValueError):
    pass


@dataclass(frozen=True)
class MultiStartPlan:
    n_starts: int
    evaluations_per_start: int
    parallel_starts: int
    estimate: RuntimeEstimate
    budget_seconds: float
    reserved_seconds: float


def plan_multistart(
    *,
    budget_seconds: float,
    reserved_seconds: float,
    evaluations_per_start: int,
    simulations_per_evaluation: int,
    seconds_per_simulation: float,
    cores: int,
    min_starts: int = 4,
    max_starts: int = 32,
) -> MultiStartPlan:
    """Largest number of starts that finishes inside the budget, keeping time reserved for validation and reporting."""
    available = budget_seconds - reserved_seconds
    probe = estimate_local_multistart(1, evaluations_per_start, simulations_per_evaluation, seconds_per_simulation, cores)
    cores_per_start = min(simulations_per_evaluation, cores)
    parallel_starts = max(1, cores // cores_per_start)
    waves = math.floor(available / probe.wall_seconds) if probe.wall_seconds > 0 else 0
    n_starts = min(max_starts, waves * parallel_starts)
    if n_starts < min_starts:
        raise BudgetTooSmallError(
            f"{min_starts} starts need {min_starts / parallel_starts * probe.wall_seconds / 60:.1f} min but only "
            f"{available / 60:.1f} min are available; reduce fitted parameters or evaluations, shorten simulations, or add cores"
        )
    estimate = estimate_local_multistart(n_starts, evaluations_per_start, simulations_per_evaluation, seconds_per_simulation, cores)
    return MultiStartPlan(n_starts, evaluations_per_start, estimate.parallel_starts, estimate, budget_seconds, reserved_seconds)


# --- result checks ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class StartResult:
    start_index: int
    estimates: dict[str, float]
    objective: float
    converged: bool
    evaluations: int


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    parameter: str | None = None


@dataclass(frozen=True)
class FitAssessment:
    best: StartResult | None
    agreement_fraction: float
    clusters: list[list[StartResult]]
    findings: list[Finding]

    @property
    def acceptable(self) -> bool:
        return self.best is not None and not self.findings


def cluster_solutions(
    results: Sequence[StartResult], parameters: Sequence[FitParameter], tolerance: float = 0.05
) -> list[list[StartResult]]:
    """Group converged starts whose estimates lie within ``tolerance`` of the group's best start (bound-normalized)."""
    clusters: list[list[StartResult]] = []
    for result in sorted((r for r in results if r.converged), key=lambda r: r.objective):
        for cluster in clusters:
            leader = cluster[0]
            if all(
                abs(p.to_unit(result.estimates[p.name]) - p.to_unit(leader.estimates[p.name])) <= tolerance for p in parameters
            ):
                cluster.append(result)
                break
        else:
            clusters.append([result])
    return clusters


def assess_fit(
    results: Sequence[StartResult],
    parameters: Sequence[FitParameter],
    *,
    correlations: Mapping[tuple[str, str], float] | None = None,
    confidence_intervals: Mapping[str, tuple[float, float]] | None = None,
    min_agreement: float = 0.5,
    bound_tolerance: float = 0.01,
    correlation_limit: float = 0.95,
    max_relative_ci_width: float = 1.0,
) -> FitAssessment:
    findings: list[Finding] = []
    clusters = cluster_solutions(results, parameters)
    converged = sum(len(c) for c in clusters)
    if not clusters:
        return FitAssessment(None, 0.0, [], [Finding("NO_CONVERGENCE", "no start converged")])

    best = clusters[0][0]
    agreement = len(clusters[0]) / converged
    if agreement < min_agreement:
        findings.append(
            Finding(
                "MULTIPLE_OPTIMA",
                f"only {len(clusters[0])} of {converged} converged starts reached the best solution; "
                "parameters may not be identifiable from these data",
            )
        )

    for p in parameters:
        u = p.to_unit(best.estimates[p.name])
        if u <= bound_tolerance or u >= 1 - bound_tolerance:
            findings.append(Finding("AT_BOUND", f"{p.name} = {best.estimates[p.name]:.4g} is at its bound", p.name))

    for (a, b), r in (correlations or {}).items():
        if a != b and abs(r) > correlation_limit:
            findings.append(
                Finding("HIGHLY_CORRELATED", f"{a} and {b} are correlated (r = {r:.2f}); fix one of them or add data", a)
            )

    for name, (lower, upper) in (confidence_intervals or {}).items():
        estimate = best.estimates[name]
        if estimate != 0 and (upper - lower) / abs(estimate) > max_relative_ci_width:
            findings.append(
                Finding("POORLY_DETERMINED", f"{name}: 95% CI [{lower:.3g}, {upper:.3g}] is wide relative to the estimate", name)
            )

    return FitAssessment(best, agreement, clusters, findings)
