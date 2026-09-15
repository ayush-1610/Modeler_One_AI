from __future__ import annotations

import asyncio
import math
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from modeler_contracts.runs import (
        EngineJob,
        EngineManifest,
        PopulationRunRequest,
        ReviewDecision,
        ReviewRequest,
        RunOutcome,
        RunRequest,
        derive_chunk_seed,
    )

# Engine errors are deterministic for a given input; only infrastructure failures are retried.
ENGINE_RETRY = RetryPolicy(
    maximum_attempts=2,
    non_retryable_error_types=["InputIntegrityError", "EngineError", "EngineTimeout"],
)


@workflow.defn
class SimulationRunWorkflow:
    @workflow.run
    async def run(self, request: RunRequest) -> RunOutcome:
        job = await workflow.execute_activity(
            "prepare_engine_job",
            request,
            start_to_close_timeout=timedelta(seconds=30),
            result_type=EngineJob,
        )
        manifest = await workflow.execute_activity(
            "run_engine_job",
            job,
            task_queue=f"engine-{request.resource_class}",
            start_to_close_timeout=timedelta(seconds=request.timeout_s + 300),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=ENGINE_RETRY,
            result_type=EngineManifest,
        )
        await workflow.execute_activity(
            "ingest_results",
            manifest,
            start_to_close_timeout=timedelta(minutes=10),
        )
        return RunOutcome(run_id=request.run_id, status=manifest.status, manifest=manifest)


@workflow.defn
class PopulationRunWorkflow:
    """Split a population run into independent, deterministically seeded chunks."""

    @workflow.run
    async def run(self, request: PopulationRunRequest) -> list[RunOutcome]:
        chunk_count = math.ceil(request.population_size / request.chunk_size)
        children = []
        for index in range(chunk_count):
            size = min(request.chunk_size, request.population_size - index * request.chunk_size)
            chunk = RunRequest(
                run_id=f"{request.run_id}-c{index:04d}",
                tenant_id=request.tenant_id,
                snapshot_uri=request.snapshot_uri,
                snapshot_sha256=request.snapshot_sha256,
                task="population",
                options={**request.options, "population_size": size, "seed": derive_chunk_seed(request.seed, index)},
                resource_class="m",
                timeout_s=request.chunk_timeout_s,
            )
            children.append(workflow.execute_child_workflow(SimulationRunWorkflow.run, chunk, id=chunk.run_id))
        return list(await asyncio.gather(*children))


@workflow.defn
class ReviewGateWorkflow:
    """Waits for a signed human decision on a record (e.g. evaluation review, MAP approval)."""

    def __init__(self) -> None:
        self._decision: ReviewDecision | None = None

    @workflow.signal
    def record_decision(self, decision: ReviewDecision) -> None:
        self._decision = decision

    @workflow.run
    async def run(self, request: ReviewRequest) -> ReviewDecision:
        await workflow.execute_activity(
            "notify_reviewers",
            request,
            start_to_close_timeout=timedelta(minutes=1),
        )
        await workflow.wait_condition(lambda: self._decision is not None, timeout=timedelta(days=request.timeout_days))
        assert self._decision is not None
        return self._decision
