"""Platform-side activities. ``run_engine_job`` lives in the engine worker, not here."""

from __future__ import annotations

import os

from temporalio import activity

from modeler_contracts.runs import EngineInput, EngineJob, EngineManifest, ReviewRequest, RunRequest


@activity.defn(name="prepare_engine_job")
def prepare_engine_job(request: RunRequest) -> EngineJob:
    root = os.environ.get("MODELER_OBJECT_STORE_URI", "file:///tmp/modeler-object-store").rstrip("/")
    return EngineJob(
        job_id=request.run_id,
        tenant_id=request.tenant_id,
        task=request.task,
        inputs=[EngineInput(name="snapshot.json", uri=request.snapshot_uri, sha256=request.snapshot_sha256)],
        outputs_uri=f"{root}/tenants/{request.tenant_id}/runs/{request.run_id}",
        options=request.options,
        timeout_s=request.timeout_s,
    )


@activity.defn(name="ingest_results")
def ingest_results(manifest: EngineManifest) -> dict[str, int]:
    # Phase 0 target: convert result CSVs to Parquet, load PK parameters into Postgres, and write the
    # run record + audit event in one transaction. Until then only the manifest is acknowledged.
    activity.logger.info("run %s produced %d output files", manifest.job_id, len(manifest.outputs))
    return {"outputs": len(manifest.outputs), "warnings": len(manifest.warnings)}


@activity.defn(name="notify_reviewers")
def notify_reviewers(request: ReviewRequest) -> None:
    activity.logger.info("review requested for %s %s (%s)", request.record_type, request.record_id, request.required_meaning)
