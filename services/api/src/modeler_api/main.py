"""Modeler One API (v1).

Scaffold scope: snapshot preview (F-101), M15 table validation (F-401), run submission to Temporal
(F-102). Authentication is not wired yet; ``X-Tenant-Id`` stands in for the OIDC tenant claim and
must be replaced before any non-local deployment.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from modeler_api.auth import Principal, require_role
from modeler_api.campaign_api import router as campaign_router
from modeler_api.config import get_settings
from modeler_api.escalations import router as escalations_router
from modeler_api.read_api import router as read_router
from modeler_api.responses import envelope
from modeler_api.results_api import router as results_router
from modeler_api.signatures_api import router as signatures_router
from modeler_contracts.runs import RUN_TASKS, RunRequest
from pbpk_domain.m15 import AssessmentTable, Stage, allowed_model_risk, validate_table
from pbpk_domain.snapshot.builder import (
    CompoundSpec,
    FormulationSpec,
    ProtocolSpec,
    SimulationSpec,
    SnapshotBuilder,
    SnapshotBuildError,
    SubjectSpec,
)

app = FastAPI(title="Modeler One API", version="0.1.0")
app.include_router(escalations_router)
app.include_router(signatures_router)
app.include_router(campaign_router)
app.include_router(results_router)
app.include_router(read_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class ModelBuildRequest(BaseModel):
    snapshot_version: int = 80
    compounds: list[CompoundSpec] = Field(min_length=1)
    subjects: list[SubjectSpec] = Field(default_factory=list)
    protocols: list[ProtocolSpec] = Field(default_factory=list)
    formulations: list[FormulationSpec] = Field(default_factory=list)
    simulations: list[SimulationSpec] = Field(default_factory=list)


@app.post("/api/v1/model-versions/preview")
def preview_model_version(request: ModelBuildRequest):
    """Build and validate a snapshot without persisting it."""
    builder = SnapshotBuilder(snapshot_version=request.snapshot_version)
    try:
        for compound in request.compounds:
            builder.add_compound(compound)
        for subject in request.subjects:
            builder.add_subject(subject)
        for protocol in request.protocols:
            builder.add_protocol(protocol)
        for formulation in request.formulations:
            builder.add_formulation(formulation)
        for simulation in request.simulations:
            builder.add_simulation(simulation)
        snapshot = builder.build()
    except SnapshotBuildError as exc:
        return JSONResponse(
            status_code=422,
            content=envelope(errors=[{"code": i.code, "location": i.location, "message": i.message} for i in exc.issues]),
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content=envelope(errors=[{"code": "INVALID_MODEL", "message": str(exc)}]))
    return envelope(
        {
            "snapshot_sha256": snapshot.sha256(),
            "snapshot_version": snapshot.version,
            "snapshot": snapshot.to_json_dict(),
        }
    )


class M15ValidationRequest(BaseModel):
    stage: Stage
    table: AssessmentTable


@app.post("/api/v1/m15/validate")
def validate_m15_table(request: M15ValidationRequest):
    issues = validate_table(request.table, request.stage)
    influence = request.table.model_influence.rating
    consequence = request.table.consequence_of_wrong_decision.rating
    allowed = list(allowed_model_risk(influence, consequence)) if influence and consequence else None
    return envelope(
        {
            "complete": not issues,
            "allowed_model_risk": allowed,
            "issues": [{"code": i.code, "location": i.location, "message": i.message} for i in issues],
        }
    )


class RunSubmission(BaseModel):
    snapshot_uri: str
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task: str = "simulate"
    options: dict[str, Any] = Field(default_factory=dict)
    resource_class: str = Field(default="s", pattern=r"^(s|m|l)$")


@app.post("/api/v1/runs", status_code=202)
async def submit_run(
    submission: RunSubmission,
    principal: Annotated[Principal, Depends(require_role("modeler-curator", "modeler-reviewer"))],
):
    if submission.task not in RUN_TASKS:
        raise HTTPException(status_code=422, detail=f"task must be one of {', '.join(RUN_TASKS)}")
    settings = get_settings()
    if not settings.temporal_address:
        raise HTTPException(status_code=503, detail="Run orchestration is not configured. Set MODELER_TEMPORAL_ADDRESS.")

    from temporalio.client import Client

    run_id = f"run_{uuid.uuid4().hex}"
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    await client.start_workflow(
        "SimulationRunWorkflow",
        RunRequest(
            run_id=run_id,
            tenant_id=principal.tenant_id,
            snapshot_uri=submission.snapshot_uri,
            snapshot_sha256=submission.snapshot_sha256,
            task=submission.task,
            options=submission.options,
            resource_class=submission.resource_class,
        ),
        id=run_id,
        task_queue="orchestrator",
    )
    return envelope({"run_id": run_id, "status": "QUEUED", "status_url": f"/api/v1/runs/{run_id}"})
