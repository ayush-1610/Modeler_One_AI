"""Temporal worker for one engine resource class (task queue ``engine-<class>``)."""

from __future__ import annotations

import asyncio
import shlex
from concurrent.futures import ThreadPoolExecutor

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from modeler_contracts.runs import EngineJob, EngineManifest
from modeler_contracts.runtime import runtime_env
from modeler_engine.runner import (
    EngineFailedError,
    EngineRunner,
    EngineTimeoutError,
    InputIntegrityError,
    LocalObjectStore,
)


def _runner() -> EngineRunner:
    env = runtime_env()
    return EngineRunner(
        command=shlex.split(env.get("engine_command", "Rscript /engine/run_job.R")),
        store=LocalObjectStore(),  # replace with the S3 store in deployed profiles
        engine_id=env.get("engine_id", "unknown"),
        image_digest=env.get("image_digest", "unknown"),
        on_heartbeat=lambda fraction: activity.heartbeat(fraction),
    )


@activity.defn(name="run_engine_job")
def run_engine_job(job: EngineJob) -> EngineManifest:
    runner = _runner()
    runner.is_cancelled = activity.is_cancelled  # honour Temporal cancellation (heartbeat-delivered)
    try:
        return runner.run(job)
    except InputIntegrityError as exc:
        raise ApplicationError(str(exc), type="InputIntegrityError", non_retryable=True) from exc
    except EngineTimeoutError as exc:
        raise ApplicationError(str(exc), type="EngineTimeout", non_retryable=True) from exc
    except EngineFailedError as exc:
        raise ApplicationError(str(exc), type="EngineError", non_retryable=True) from exc


async def main() -> None:
    env = runtime_env()
    client = await Client.connect(env.require("temporal_address"), namespace=env.get("temporal_namespace", "default"))
    concurrency = int(env.get("engine_concurrency", "1"))
    task_queue = f"engine-{env.get('resource_class', 's')}"
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        worker = Worker(
            client,
            task_queue=task_queue,
            activities=[run_engine_job],
            activity_executor=executor,
            max_concurrent_activities=concurrency,
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
