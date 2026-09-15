"""Fitting round: plan starts against the time budget, run them in parallel, stop at the deadline, assess.

The deadline is guaranteed; reaching the acceptance criteria inside it is not. Starts still running at the
deadline are cancelled, and the round is assessed on the starts that finished.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from modeler_contracts.runs import (
        EngineJob,
        EngineManifest,
        FitRoundOutcome,
        FitRoundRequest,
        FitStartOutcome,
    )

PI_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class FitRoundWorkflow:
    @workflow.run
    async def run(self, request: FitRoundRequest) -> FitRoundOutcome:
        started = workflow.now()
        jobs: list[EngineJob] = await workflow.execute_activity(
            "plan_fit_round",
            request,
            start_to_close_timeout=timedelta(minutes=2),
            result_type=list[EngineJob],
        )
        deadline_seconds = request.budget_seconds - request.reserved_seconds

        async def run_start(job: EngineJob) -> EngineManifest:
            return await workflow.execute_activity(
                "run_engine_job",
                job,
                task_queue="engine-l",
                start_to_close_timeout=timedelta(seconds=deadline_seconds),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=PI_RETRY,
                result_type=EngineManifest,
            )

        tasks = [asyncio.ensure_future(run_start(job)) for job in jobs]
        elapsed = (workflow.now() - started).total_seconds()
        done, pending = await asyncio.wait(tasks, timeout=max(1.0, deadline_seconds - elapsed))
        for task in pending:
            task.cancel()

        manifests: list[EngineManifest | None] = []
        for task in tasks:
            if task in done and task.exception() is None:
                manifests.append(task.result())
            else:
                manifests.append(None)

        return await workflow.execute_activity(
            "assess_fit_round",
            args=[request, jobs, manifests, bool(pending)],
            start_to_close_timeout=timedelta(minutes=5),
            result_type=FitRoundOutcome,
        )


__all__ = ["FitRoundWorkflow", "FitStartOutcome"]
