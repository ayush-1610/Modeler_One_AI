"""Campaign-facing endpoints: generate a MAP, start a campaign (task T-17 <-> T-16/T-13 API surface).

`map:generate` runs the MS-01 MAP generator (`pbpk_domain.campaign.map.generate_map`) for a question's CPF,
studies and context; the split is computed deterministically here. Both endpoints require an authenticated
project member (T-06). Starting a campaign runs it through the configured execution backend: the single-node
``local`` executor in-process (the no-Docker path — no Temporal needed) or the Temporal cluster (``temporal``).
"""

from __future__ import annotations

import threading
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modeler_api.auth import Principal, require_project, require_role
from modeler_api.config import get_settings
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import QuestionOfInterest, StudyRecord, split_studies
from pbpk_domain.cpf.models import CPF
from pbpk_domain.m15 import Rating

router = APIRouter(prefix="/api/v1", tags=["campaigns"])

Author = Annotated[Principal, Depends(require_role("modeler-curator", "modeler-reviewer"))]


def _launch_local_campaign(campaign_request: Any, *, read_root: str, project: str, question: str, model_risk: str) -> None:
    """Run the campaign single-node on a background thread (the local execution backend).

    Imported lazily because the orchestrator depends on this package (importing it at module load would be a
    cycle). The runner writes the live monitor view under ``read_root`` as it progresses.
    """
    from modeler_orchestrator.local_runner import run_campaign

    threading.Thread(
        target=run_campaign,
        kwargs={"request": campaign_request, "read_root": read_root, "project": project,
                "question": question, "model_risk": model_risk},
        daemon=True,
    ).start()


class MapGenerateRequest(BaseModel):
    compound: str = Field(min_length=1)
    cpf: CPF
    studies: list[StudyRecord] = Field(min_length=1)
    question: QuestionOfInterest = QuestionOfInterest()
    objective: str = Field(min_length=1)
    context_of_use: str = Field(min_length=1)
    food_effect_in_question: bool = False
    model_risk: Rating
    engine_image_digest: str = Field(min_length=1)
    software_versions: dict[str, str]


@router.post("/projects/{project_id}/questions/{question_id}/map:generate")
def generate_map_endpoint(project_id: str, question_id: str, request: MapGenerateRequest, principal: Author) -> dict[str, Any]:
    """Generate the MAP (version 1, DRAFT) for a question from its CPF, studies and context."""
    require_project(project_id, principal)
    split = split_studies(request.studies, request.question)
    document = generate_map(
        compound=request.compound, cpf=request.cpf, studies=request.studies, split=split,
        objective=request.objective, context_of_use=request.context_of_use,
        food_effect_in_question=request.food_effect_in_question, model_risk=request.model_risk,
        engine_image_digest=request.engine_image_digest, software_versions=request.software_versions,
    )
    return {"question_id": question_id, "map": document.model_dump(mode="json")}


class CampaignStartRequest(BaseModel):
    compound: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    cpf_uri: str = Field(min_length=1)
    cpf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    map_uri: str = ""
    observed_uri: str = ""
    system_uri: str = ""      # a model system staged by campaign:prepare ("" for a single compound)
    system_sha256: str = ""
    question: str = ""
    model_risk: str = "medium"
    stages: list[str] | None = None
    stage_budgets_seconds: dict[str, int] = Field(default_factory=dict)


@router.post("/projects/{project_id}/campaigns", status_code=202)
async def start_campaign(project_id: str, request: CampaignStartRequest, principal: Author) -> dict[str, Any]:
    """Start a modeling campaign through the configured execution backend (local single-node, or Temporal)."""
    require_project(project_id, principal)
    settings = get_settings()

    from modeler_contracts.runs import CAMPAIGN_STAGES, CampaignRequest

    campaign_id = f"camp_{uuid.uuid4().hex}"
    campaign_request = CampaignRequest(
        campaign_id=campaign_id, tenant_id=principal.tenant_id, compound=request.compound, map_id=request.map_id,
        cpf_uri=request.cpf_uri, cpf_sha256=request.cpf_sha256, map_uri=request.map_uri, observed_uri=request.observed_uri,
        system_uri=request.system_uri, system_sha256=request.system_sha256,
        stages=request.stages or list(CAMPAIGN_STAGES), stage_budgets_seconds=request.stage_budgets_seconds,
    )

    if settings.execution_backend == "temporal":
        if not settings.temporal_address:
            raise HTTPException(status_code=503, detail="Campaign orchestration is not configured. Set MODELER_TEMPORAL_ADDRESS.")
        from temporalio.client import Client

        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
        await client.start_workflow(
            "ModelingCampaignWorkflow", campaign_request, id=campaign_id, task_queue="orchestrator",
        )
        return {"campaign_id": campaign_id, "status": "QUEUED", "status_url": f"/api/v1/campaigns/{campaign_id}"}

    # local backend: run single-node in-process (no Temporal). Requires a read root for the monitor artifacts.
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Local execution needs a read root. Set MODELER_READ_ROOT.")
    _launch_local_campaign(campaign_request, read_root=settings.read_root, project=project_id,
                           question=request.question, model_risk=request.model_risk)
    return {"campaign_id": campaign_id, "status": "QUEUED", "status_url": f"/api/v1/campaigns/{campaign_id}"}
