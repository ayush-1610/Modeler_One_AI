"""P4 model inputs (plan §5.2 P4; T-49): CPF v1, the study catalog, readiness, and hand-over to the campaign path.

`inputs:assemble` regenerates CPF v1 from the accepted evidence and the study catalog from the accepted datasets and
checks their readiness; the page shows them as PK-Sim's building blocks. Structure choices the evidence does not decide
(which PK-Sim process carries a pathway, which formulation a solid study used, a study left out) are a person's, with a
reason. `inputs:accept` closes P4 when ready; `inputs:publish` hands the accepted CPF and catalog to the campaign path
(the project's CPF and studies), from which P5 plans and P6 runs.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modeler_api.config import SettingsDep
from modeler_api.deps import Reader, StoreDep, Writer, redact, version_view, workspace_for
from modeler_api.responses import answers, envelope
from modeler_api.views.inputs import IdentityProposal, InputsPage
from modeler_project import ArtifactKind, Workspace
from modeler_project.evidence import EvidenceState
from modeler_project.evidence_register import items
from modeler_project.inputs import (
    MAIN,
    accept_inputs,
    assemble,
    choices,
    current_cpf,
    placement,
    propose_identity_mw,
    set_choice,
    todo,
)
from pbpk_domain.cpf.process_bindings import binding_candidates, is_process_id

router = APIRouter(prefix="/api/v1", tags=["inputs"])

# The PK-Sim building block a CPF id belongs to (the page's tabs mirror PK-Sim's).
_BLOCKS = (("form.", "Formulations"), ("indiv.", "Individuals"), ("expr.", "Individuals"), ("sim", "Simulation settings"),
           ("alt.", "Compound"), ("molecule.", "Individuals"))


def _block(cpf_id: str) -> str:
    return next((block for prefix, block in _BLOCKS if cpf_id.startswith(prefix)), "Compound")


def _view(ws: Workspace) -> dict[str, Any]:
    cpf_version = ws.latest(ArtifactKind.CPF, MAIN)
    catalog = ws.latest(ArtifactKind.STUDY_CATALOG, MAIN)
    ready = ws.latest(ArtifactKind.READINESS, MAIN)
    cpf = current_cpf(ws)
    records = []
    for record in (cpf.parameters if cpf else ()):
        row = record.model_dump(mode="json")
        row["block"] = _block(record.id)
        row["placement"] = placement(record.id)
        if is_process_id(record.id) and record.engine_binding is None:
            row["candidates"] = [c.process for c in binding_candidates(record.id)]
        records.append(row)
    return {
        "cpf": version_view(ws, cpf_version, with_content=False) | {"assembly": cpf_version.content["assembly"]} if cpf_version else None,
        "records": records,
        "catalog": (version_view(ws, catalog) | {"content": redact(ws, ArtifactKind.STUDY_CATALOG, catalog.content)})
                   if catalog else None,
        "readiness": version_view(ws, ready) if ready else None,
        "choices": choices(ws).model_dump(),
        "published": published.content if (published := ws.latest(ArtifactKind.CPF, "published")) else None,
        "todo": todo(ws),
    }


@router.get("/projects/{project_id}/inputs", **answers(InputsPage))
def get_inputs(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope(_view(workspace_for(project_id, principal, store)))


@router.post("/projects/{project_id}/inputs:assemble", **answers(InputsPage))
def assemble_inputs(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    try:
        assemble(ws, by=principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return envelope(_view(ws))


@router.post("/projects/{project_id}/inputs:propose-identity", status_code=201, **answers(IdentityProposal))
def propose_identity(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """Propose the molecular weight from the brief's PubChem record (accepted like any other evidence)."""
    ws = workspace_for(project_id, principal, store)
    try:
        item = propose_identity_mw(ws, by=principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return envelope({"evidence": item.id, **_view(ws)})


class ChoiceRequest(BaseModel):
    kind: Literal["process", "formulation", "excluded_studies"]
    key: str = Field(min_length=1)
    value: str | None = None
    reason: str = Field(min_length=1)


@router.put("/projects/{project_id}/inputs/choices", **answers(InputsPage))
def put_choice(project_id: str, body: ChoiceRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """A structure choice with its reason; the inputs are re-assembled with it."""
    ws = workspace_for(project_id, principal, store)
    if body.kind == "process" and body.value is not None:
        # the process types that can carry the pathway's parameters: from the assembled CPF, or from the accepted
        # evidence when nothing is assembled yet (the choice may come first)
        cpf = current_cpf(ws)
        targets = {r.id for r in (cpf.parameters if cpf else ())}
        targets |= {e.target for e in items(ws) if e.state is EvidenceState.ACCEPTED}
        offered = {c.process for t in targets if t.startswith(body.key + ".") for c in binding_candidates(t)}
        if body.value not in offered:
            raise HTTPException(status_code=422, detail=f"{body.value} is not a harvested process for {body.key} "
                                                        f"({', '.join(sorted(offered))})")
    set_choice(ws, kind=body.kind, key=body.key, value=body.value, reason=body.reason, by=principal.user_id)
    try:
        assemble(ws, by=principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return envelope(_view(ws))


class AcceptRequest(BaseModel):
    note: str = ""


@router.post("/projects/{project_id}/inputs:accept", **answers(InputsPage))
def accept(project_id: str, body: AcceptRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    try:
        accept_inputs(ws, by=principal.user_id, printed_name=principal.printed_name, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return envelope(_view(ws))


_UPLOAD_FIELDS = ("study_id", "reference", "n", "design", "dosing_interval_h", "n_doses", "route", "dose_mg", "dose_per_kg",
                  "infusion_time_min", "formulation", "formulation_name", "food_state", "population_type",
                  "special_population", "co_medication", "n_timepoints", "lloq", "profile", "origin")


@router.post("/projects/{project_id}/inputs:publish", **answers(InputsPage))
def publish(project_id: str, principal: Writer, store: StoreDep, settings: SettingsDep) -> dict[str, Any]:
    """Hand the accepted CPF v1 and the judged studies to the campaign path (the project's CPF and studies)."""
    from modeler_api.studies import StudyUpload
    from modeler_storage.filestore import FileWriteStore

    ws = workspace_for(project_id, principal, store)
    ready = ws.latest(ArtifactKind.READINESS, MAIN)
    if ready is None or ws.status(ready).value != "APPROVED":
        raise HTTPException(status_code=409, detail="accept the inputs (P4) before handing them to the plan")
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Write models are not configured. Set MODELER_READ_ROOT.")
    cpf = current_cpf(ws)
    rows = ws.latest(ArtifactKind.STUDY_CATALOG, MAIN).content["studies"]
    studies = [StudyUpload.model_validate({k: r[k] for k in _UPLOAD_FIELDS if k in r and r[k] is not None}).model_dump()
               for r in rows if r.get("evaluable")]
    write = FileWriteStore(settings.read_root)
    write.put_cpf(principal.tenant_id, project_id, cpf.compound, cpf)
    write.put_studies(principal.tenant_id, project_id, studies)
    cpf_ref = ws.latest(ArtifactKind.CPF, MAIN).ref
    record = {"compound": cpf.compound, "studies": [s["study_id"] for s in studies], "cpf": cpf_ref.model_dump(mode="json"),
              "readiness": ready.ref.model_dump(mode="json")}
    ws.commit(ArtifactKind.CPF, "published", record, derived_from=[cpf_ref, ready.ref], actor=principal.user_id,
              reason=f"handed to the campaign path: {len(studies)} studies")
    return envelope(_view(ws))
