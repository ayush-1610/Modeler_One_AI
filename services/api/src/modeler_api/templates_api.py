"""Project starting points for the create-project wizard: a compound's CPF plus its observed studies.

The published template is an OSP library model imported on request (`pbpk_domain.reference`): its CPF and its real
clinical studies, straight from the peer-reviewed snapshot. The illustrative one is a small hand-made set kept for a
fast software check of the pipeline; it says so in its label and in every study's reference, so its numbers are
never mistaken for evidence.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from modeler_api.auth import Principal, require_role
from modeler_api.config import SettingsDep
from modeler_api.reference_models import starting_point, starting_points
from modeler_api.responses import answers, envelope
from modeler_api.views.templates import TemplateContent, Templates

router = APIRouter(prefix="/api/v1", tags=["templates"])

_READ_ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer", "modeler-qa")
PrincipalDep = Annotated[Principal, Depends(require_role(*_READ_ROLES))]

@router.get("/templates", **answers(Templates))
def list_templates(principal: PrincipalDep):
    """The wizard's starting points, the published real-data model first."""
    return envelope({"templates": starting_points()})


@router.get("/templates/{template_id}", **answers(TemplateContent))
def get_template(template_id: str, principal: PrincipalDep, settings: SettingsDep):
    """One starting point in full: the CPF, the studies in the upload shape, and what was left out and why."""
    try:
        return envelope(starting_point(template_id, settings))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"template {template_id} not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
