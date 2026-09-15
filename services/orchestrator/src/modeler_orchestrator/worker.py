from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from modeler_orchestrator.activities import ingest_results, notify_reviewers, prepare_engine_job
from modeler_orchestrator.workflows import PopulationRunWorkflow, ReviewGateWorkflow, SimulationRunWorkflow


async def main() -> None:
    client = await Client.connect(
        os.environ["MODELER_TEMPORAL_ADDRESS"], namespace=os.environ.get("MODELER_TEMPORAL_NAMESPACE", "default")
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        worker = Worker(
            client,
            task_queue="orchestrator",
            workflows=[SimulationRunWorkflow, PopulationRunWorkflow, ReviewGateWorkflow],
            activities=[prepare_engine_job, ingest_results, notify_reviewers],
            activity_executor=executor,
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
