"""Temporal worker for one engine resource class (task queue ``engine-<class>``)."""

from __future__ import annotations

import asyncio
import os
import shlex
from concurrent.futures import ThreadPoolExecutor

from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from modeler_contracts.runs import EngineJob, EngineManifest
from modeler_engine.runner import (
    EngineFailedError,
    EngineRunner,
    EngineTimeoutError,
    InputIntegrityError,
    LocalObjectStore,
)


def _runner() -> EngineRunner:
    return EngineRunner(
        command=shlex.split(os.environ.get("MODELER_ENGINE_COMMAND", "Rscript /engine/run_job.R")),
        store=LocalObjectStore(),  # replace with the S3 store in deployed profiles
        engine_id=os.environ.get("MODELER_ENGINE_ID", "unknown"),
        image_digest=os.environ.get("MODELER_IMAGE_DIGEST", "unknown"),
        on_heartbeat=lambda fraction: activity.heartbeat(fraction),
    )


@activity.defn(name="run_engine_job")
def run_engine_job(job: EngineJob) -> EngineManifest:
    try:
        return _runner().run(job)
    except InputIntegrityError as exc:
        raise ApplicationError(str(exc), type="InputIntegrityError", non_retryable=True) from exc
    except EngineTimeoutError as exc:
        raise ApplicationError(str(exc), type="EngineTimeout", non_retryable=True) from exc
    except EngineFailedError as exc:
        raise ApplicationError(str(exc), type="EngineError", non_retryable=True) from exc


async def main() -> None:
    client = await Client.connect(
        os.environ["MODELER_TEMPORAL_ADDRESS"], namespace=os.environ.get("MODELER_TEMPORAL_NAMESPACE", "default")
    )
    concurrency = int(os.environ.get("MODELER_ENGINE_CONCURRENCY", "1"))
    task_queue = f"engine-{os.environ.get('MODELER_RESOURCE_CLASS', 's')}"
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
