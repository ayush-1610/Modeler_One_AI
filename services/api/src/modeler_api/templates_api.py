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
from modeler_api.config import Settings, SettingsDep
from modeler_api.reference_models import TEMPLATES, reference_dir
from modeler_api.responses import answers, envelope
from modeler_api.views.templates import TemplateContent, Templates

router = APIRouter(prefix="/api/v1", tags=["templates"])

_READ_ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer")
PrincipalDep = Annotated[Principal, Depends(require_role(*_READ_ROLES))]

_HERE = Path(__file__).resolve().parent
_TEMPLATES = TEMPLATES   # the tests and the routes below read the registry by this name
_reference_dir = reference_dir


@lru_cache(maxsize=8)
def _published(snapshot_path: str) -> dict[str, Any]:
    from pbpk_domain.reference import import_osp_snapshot

    imported = import_osp_snapshot(json.loads(Path(snapshot_path).read_text(encoding="utf-8")))
    if imported.unplaced:
        raise ValueError("the model has parts the builder cannot place: " + "; ".join(imported.unplaced))
    return {
        "cpf": imported.cpf.model_dump(mode="json", exclude={"created_at"}),
        # the clinical data the published model was built and qualified with (plan §9.4)
        "studies": [{**study, "origin": "OSP_LIBRARY"} for study in imported.studies],
        "skipped": list(imported.skipped),
        "notes": list(imported.notes),
        "source": imported.source,
    }


# The S0 gate's parameters (pbpk_domain.cpf.completeness), empty: a user's own compound starts from these. The
# elimination pathway is PK-Sim's total hepatic clearance, bound as the OSP models bind it (harvested: OSP Digoxin
# "Total Hepatic Clearance", LiverClearance "Plasma clearance" in ml/min/kg); other processes are added as records.
_BLANK_PARAMETERS = (("phys.mw", "g/mol", None), ("phys.logp", "Log Units", None), ("phys.pka.neutral", None, None),
                     ("bind.fu", None, None), ("phys.solubility.ref", "mg/ml", None),
                     ("elim.hepatic.total.plasma_clearance", "ml/min/kg",
                      {"building_block": "Compound", "parameter": "Plasma clearance", "process": "LiverClearance",
                       "data_source": "Literature"}))


def _content(template_id: str, spec: dict[str, Any], settings: Settings) -> dict[str, Any]:
    if spec.get("blank"):
        cpf = {"compound": spec["compound"], "parameters": [
            {"id": pid, "value": None, "unit": unit, "status": "MISSING", **({"engine_binding": eb} if eb else {})}
            for pid, unit, eb in _BLANK_PARAMETERS]}
        return {"cpf": cpf, "studies": [], "skipped": [], "notes": [], "source": "your own data"}
    if "snapshot" in spec:
        path = _reference_dir(settings) / spec["snapshot"]
        if not path.is_file():
            raise HTTPException(status_code=503, detail=f"reference model {spec['snapshot']} is not installed at {path.parent}")
        try:
            return _published(str(path))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"template {template_id}: {exc}") from exc
    data = json.loads((_HERE / "templates" / spec["file"]).read_text(encoding="utf-8"))
    # hand-made example data: it runs the pipeline but is never evidence (plan §9.4 item 4)
    studies = [{**study, "origin": "ILLUSTRATIVE"} for study in data["studies"]]
    return {"cpf": data["cpf"], "studies": studies, "skipped": [], "notes": [], "source": "illustrative"}


def _summary(template_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {"id": template_id, "blank": bool(spec.get("blank")),
            **{k: spec[k] for k in ("name", "compound", "question", "model_risk", "real_data", "description")}}


@router.get("/templates", **answers(Templates))
def list_templates(principal: PrincipalDep):
    """The wizard's starting points, the published real-data model first."""
    return envelope({"templates": [_summary(tid, spec) for tid, spec in _TEMPLATES.items()]})


@router.get("/templates/{template_id}", **answers(TemplateContent))
def get_template(template_id: str, principal: PrincipalDep, settings: SettingsDep):
    """One starting point in full: the CPF, the studies in the upload shape, and what was left out and why."""
    spec = _TEMPLATES.get(template_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"template {template_id} not found")
    return envelope(_summary(template_id, spec) | _content(template_id, spec, settings))
