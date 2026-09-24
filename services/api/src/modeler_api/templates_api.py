"""Project starting points for the create-project wizard: a compound's CPF plus its observed studies.

The published template is an OSP library model imported on request (`pbpk_domain.reference`): its CPF and its real
clinical studies, straight from the peer-reviewed snapshot. The illustrative one is a small hand-made set kept for a
fast software check of the pipeline; it says so in its label and in every study's reference, so its numbers are
never mistaken for evidence.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from modeler_api.auth import Principal, require_role
from modeler_api.config import get_settings
from modeler_api.responses import envelope

router = APIRouter(prefix="/api/v1", tags=["templates"])

_READ_ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer")
PrincipalDep = Annotated[Principal, Depends(require_role(*_READ_ROLES))]

_HERE = Path(__file__).resolve().parent
# The OSP reference snapshots harvested for the engine catalog (T-02); the repo layout is the same on the server.
_DEFAULT_REFERENCE_DIR = _HERE.parents[2] / "engine-worker" / "golden" / "fixtures"

_TEMPLATES: dict[str, dict[str, Any]] = {
    "dapagliflozin-osp": {
        "name": "Dapagliflozin — published OSP model, real clinical data",
        "compound": "Dapagliflozin",
        "question": "Predict dapagliflozin plasma exposure (AUC, Cmax) after 10 mg once daily in healthy adults",
        "model_risk": "medium",
        "real_data": True,
        "snapshot": "Dapagliflozin-Model.json",
        "description": "The peer-reviewed OSP Dapagliflozin PBPK model and the clinical studies it was built and "
                       "qualified on (13 publications: IV microdose, solution, capsules, tablet, fed, multiple dose, "
                       "renal impairment). Runs the whole MS-01 pipeline on real data.",
    },
    "aciclovir-illustrative": {
        "name": "Aciclovir — illustrative quick check (not clinical data)",
        "compound": "Aciclovir",
        "question": "First-in-human renal starting dose from IV disposition",
        "model_risk": "medium",
        "real_data": False,
        "file": "aciclovir_illustrative.json",
        "description": "One hand-made IV profile for a fast software check of the pipeline. Not evidence of "
                       "anything: use the published template to test the modelling.",
    },
}


def _reference_dir() -> Path:
    configured = get_settings().reference_models_dir
    return Path(configured) if configured else _DEFAULT_REFERENCE_DIR


@lru_cache(maxsize=8)
def _published(snapshot_path: str) -> dict[str, Any]:
    from pbpk_domain.reference import import_osp_snapshot

    imported = import_osp_snapshot(json.loads(Path(snapshot_path).read_text(encoding="utf-8")))
    if imported.unplaced:
        raise ValueError("the model has parts the builder cannot place: " + "; ".join(imported.unplaced))
    return {
        "cpf": imported.cpf.model_dump(mode="json", exclude={"created_at"}),
        "studies": list(imported.studies),
        "skipped": list(imported.skipped),
        "notes": list(imported.notes),
        "source": imported.source,
    }


def _content(template_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    if "snapshot" in spec:
        path = _reference_dir() / spec["snapshot"]
        if not path.is_file():
            raise HTTPException(status_code=503, detail=f"reference model {spec['snapshot']} is not installed at {path.parent}")
        try:
            return _published(str(path))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"template {template_id}: {exc}") from exc
    data = json.loads((_HERE / "templates" / spec["file"]).read_text(encoding="utf-8"))
    return {"cpf": data["cpf"], "studies": data["studies"], "skipped": [], "notes": [], "source": "illustrative"}


def _summary(template_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {"id": template_id, **{k: spec[k] for k in ("name", "compound", "question", "model_risk", "real_data",
                                                        "description")}}


@router.get("/templates")
def list_templates(principal: PrincipalDep):
    """The wizard's starting points, the published real-data model first."""
    return envelope({"templates": [_summary(tid, spec) for tid, spec in _TEMPLATES.items()]})


@router.get("/templates/{template_id}")
def get_template(template_id: str, principal: PrincipalDep):
    """One starting point in full: the CPF, the studies in the upload shape, and what was left out and why."""
    spec = _TEMPLATES.get(template_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"template {template_id} not found")
    return envelope(_summary(template_id, spec) | _content(template_id, spec))
