"""Activities for fitting rounds: planning start values and assessing finished starts."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from temporalio import activity

from modeler_contracts.runs import (
    EngineInput,
    EngineJob,
    EngineManifest,
    FitRoundOutcome,
    FitRoundRequest,
    FitStartOutcome,
)
from pbpk_domain.fitting import FitParameter, StartResult, assess_fit, plan_multistart, sample_start_values


def _fit_parameters(request: FitRoundRequest) -> list[FitParameter]:
    return [FitParameter(p.name, p.lower, p.upper, p.log_scale) for p in request.parameters]


def plan_jobs(request: FitRoundRequest) -> list[EngineJob]:
    plan = plan_multistart(
        budget_seconds=request.budget_seconds,
        reserved_seconds=request.reserved_seconds,
        evaluations_per_start=request.evaluations_per_start,
        simulations_per_evaluation=request.simulations_per_evaluation,
        seconds_per_simulation=request.seconds_per_simulation,
        cores=request.cores,
    )
    starts = sample_start_values(_fit_parameters(request), plan.n_starts, request.seed)
    root = os.environ.get("MODELER_OBJECT_STORE_URI", "file:///tmp/modeler-object-store").rstrip("/")
    return [
        EngineJob(
            job_id=f"{request.round_id}-s{index:03d}",
            tenant_id=request.tenant_id,
            task="parameter_identification",
            inputs=[
                EngineInput(name="pi_spec_base.json", uri=request.base_spec_uri, sha256=request.base_spec_sha256),
                *request.model_inputs,
            ],
            outputs_uri=f"{root}/tenants/{request.tenant_id}/fits/{request.round_id}/start-{index:03d}",
            options={"start_index": index, "start_values": values, "seed": request.seed + index},
            timeout_s=request.budget_seconds - request.reserved_seconds,
        )
        for index, values in enumerate(starts)
    ]


def _read_result(manifest: EngineManifest) -> dict:
    result_file = next((o for o in manifest.outputs if o.name.endswith("pi_result.json")), None)
    if result_file is None:
        raise ValueError(f"{manifest.job_id}: engine produced no pi_result.json")
    parsed = urlparse(result_file.uri)
    if parsed.scheme != "file":
        raise NotImplementedError("reading results from object storage is provided by the storage adapter")
    with open(parsed.path, encoding="utf-8") as handle:
        return json.load(handle)


def assess_round(
    request: FitRoundRequest, jobs: list[EngineJob], manifests: list[EngineManifest | None], deadline_reached: bool
) -> FitRoundOutcome:
    starts: list[FitStartOutcome] = []
    results: list[StartResult] = []
    for job, manifest in zip(jobs, manifests, strict=True):
        index = job.options["start_index"]
        if manifest is None:
            starts.append(FitStartOutcome(index, "CANCELLED_AT_DEADLINE" if deadline_reached else "FAILED"))
            continue
        data = _read_result(manifest)
        estimates = {e["name"]: float(e["estimate"]) for e in data["estimates"]}
        converged = str(data.get("convergence", "")).lower() not in ("false", "0", "failed", "")
        outcome = FitStartOutcome(
            index, "SUCCEEDED", estimates, float(data["objective_value"]), converged, int(data["function_evaluations"]), manifest
        )
        starts.append(outcome)
        results.append(StartResult(index, estimates, outcome.objective, converged, outcome.evaluations))

    assessment = assess_fit(results, _fit_parameters(request))
    findings = [f"{f.code}: {f.message}" for f in assessment.findings]
    if deadline_reached:
        findings.append("DEADLINE_REACHED: some starts were cancelled at the time budget")
    return FitRoundOutcome(
        round_id=request.round_id,
        planned_starts=len(jobs),
        starts=starts,
        acceptable=assessment.acceptable and not deadline_reached,
        findings=findings,
        best_start_index=assessment.best.start_index if assessment.best else None,
        deadline_reached=deadline_reached,
    )


@activity.defn(name="plan_fit_round")
def plan_fit_round(request: FitRoundRequest) -> list[EngineJob]:
    return plan_jobs(request)


@activity.defn(name="assess_fit_round")
def assess_fit_round(
    request: FitRoundRequest, jobs: list[EngineJob], manifests: list[EngineManifest | None], deadline_reached: bool
) -> FitRoundOutcome:
    return assess_round(request, jobs, manifests, deadline_reached)
