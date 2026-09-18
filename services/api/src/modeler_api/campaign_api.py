"""Campaign-facing endpoints: generate a MAP, start a campaign (task T-17 <-> T-16/T-13 API surface).

`map:generate` runs the MS-01 MAP generator (`pbpk_domain.campaign.map.generate_map`) for a question's CPF,
studies and context; the split is computed deterministically here. Both endpoints require an authenticated
project member (T-06). Starting a campaign submits the ModelingCampaignWorkflow to Temporal.
"""

from __future__ import annotations

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


@router.post("/projects/{project_id}/campaigns", status_code=202)
async def start_campaign(project_id: str, request: CampaignStartRequest, principal: Author) -> dict[str, Any]:
    """Submit a modeling campaign to the orchestrator (ModelingCampaignWorkflow)."""
    require_project(project_id, principal)
    settings = get_settings()
    if not settings.temporal_address:
        raise HTTPException(status_code=503, detail="Campaign orchestration is not configured. Set MODELER_TEMPORAL_ADDRESS.")

    from temporalio.client import Client

    from modeler_contracts.runs import CampaignRequest

    campaign_id = f"camp_{uuid.uuid4().hex}"
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    await client.start_workflow(
        "ModelingCampaignWorkflow",
        CampaignRequest(
            campaign_id=campaign_id, tenant_id=principal.tenant_id, compound=request.compound, map_id=request.map_id,
            cpf_uri=request.cpf_uri, cpf_sha256=request.cpf_sha256, map_uri=request.map_uri, observed_uri=request.observed_uri,
        ),
        id=campaign_id,
        task_queue="orchestrator",
    )
    return {"campaign_id": campaign_id, "status": "QUEUED", "status_url": f"/api/v1/campaigns/{campaign_id}"}
