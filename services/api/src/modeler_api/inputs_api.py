"""Step 2 · Inputs (redesign §3.2; T-49): CPF v1, the study catalog and their readiness, as PK-Sim's building blocks.

`inputs:assemble` regenerates CPF v1 from the evidence not excluded and the study catalog from the datasets not excluded,
and checks their readiness; every route that changes a source does the same (D-27). Structure choices the evidence does
not decide (which PK-Sim process carries a pathway, which formulation a solid study used, a study left out) are a
person's, with a reason. Nothing is accepted: Review & sign plans from the current, ready inputs, and the signed MAP
stages the campaign's CPF and studies.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modeler_api.deps import Reader, StoreDep, Writer, blinded_sources, redact, version_view, workspace_for
from modeler_api.reference_models import published_models
from modeler_api.responses import answers, envelope
from modeler_api.views.inputs import IdentityProposal, InputsPage
from modeler_intake.fields import FIELDS as INTAKE_FIELDS
from modeler_project import ArtifactKind, Workspace
from modeler_project.brief import PURPOSES, ProjectBrief
from modeler_project.datasets import HUMAN_POPULATIONS
from modeler_project.evidence import EvidenceState
from modeler_project.evidence_register import items
from modeler_project.inputs import (
    MAIN,
    assemble,
    choices,
    cpf_assembly,
    current_cpf,
    placement,
    propose_identity_mw,
    set_choice,
    tab_of,
    todo,
)
from modeler_project.inputs_view import compound_rows, study_rows
from modeler_project.release_choice import ReleaseChoiceError, release_states, set_release_model
from modeler_project.sources import rule
from pbpk_domain.campaign.split import FoodState, FormulationKind, Route, Sex
from pbpk_domain.cpf.process_bindings import binding_candidates, is_process_id

router = APIRouter(prefix="/api/v1", tags=["inputs"])

# What a person may give a study (the Studies and Individuals tabs): the study record's own enums and the harvested
# PK-Sim population databases, never free text the builder would not know. With them, for the client data's values:
# the intake vocabulary's matrix words (`modeler_intake.fields`, stated through Delivery's `:enter` with field "matrix")
# and the analytes the brief names (`_study_options`).
_STUDY_OPTIONS = {"route": [r.value for r in Route], "formulation": [f.value for f in FormulationKind],
                  "food_state": [f.value for f in FoodState], "purpose": list(PURPOSES), "sex": [s.value for s in Sex],
                  "population": list(HUMAN_POPULATIONS), "matrix": list(INTAKE_FIELDS["matrix"].choices)}

def _drug(ws: Workspace) -> str:
    brief = ws.latest(ArtifactKind.BRIEF, MAIN)
    return ProjectBrief.from_content(brief.content).drug_name if brief else ""


def _study_options(ws: Workspace) -> dict[str, list[str]]:
    """`_STUDY_OPTIONS` and `analyte`: the brief's parent drug, as the brief names it (a label: one the ledger has as an
    analyte already is posted by its id, the Delivery page's `analytes`; else as `new_analyte`). No field of the brief
    names a metabolite, so none is offered: a metabolite is named as a new analyte on Delivery (`values:assign`)."""
    drug = _drug(ws).strip()
    return {**_STUDY_OPTIONS, "analyte": [drug] if drug else []}


def _view(ws: Workspace) -> dict[str, Any]:
    cpf_version = ws.latest(ArtifactKind.CPF, MAIN)
    catalog = ws.latest(ArtifactKind.STUDY_CATALOG, MAIN)
    ready = ws.latest(ArtifactKind.READINESS, MAIN)
    cpf = current_cpf(ws)
    records = []
    for record in (cpf.parameters if cpf else ()):
        row = record.model_dump(mode="json")
        row["block"] = tab_of(record.id)
        row["placement"] = placement(record.id)
        if is_process_id(record.id) and record.engine_binding is None:
            row["candidates"] = [c.process for c in binding_candidates(record.id)]
        records.append(row)
    open_items = todo(ws)
    # a study's values are withheld by the rule every view of them follows (the project's list and the delivery's, by
    # name and by the sheet form's withheld groups; final review rounds 6 and 7): its catalog row's profile, and its row
    # on Studies says it is blinded, and why
    hidden = blinded_sources(ws)
    return {
        "cpf": version_view(ws, cpf_version, with_content=False) | {"assembly": cpf_assembly(ws)} if cpf_version else None,
        "records": records,
        "catalog": (version_view(ws, catalog) | {"content": redact(ws, ArtifactKind.STUDY_CATALOG, catalog.content, hidden)})
                   if catalog else None,
        "readiness": version_view(ws, ready) if ready else None,
        "choices": choices(ws).model_dump(),
        "todo": open_items,
        "compound": compound_rows(ws, open_items, empty=True),
        "studies": study_rows(ws, hidden.withholds, hidden.study_why),
        "study_options": _study_options(ws),
        "selection_rule": f"source selection {rule().version} ({rule().status})",
        "published_models": [{"id": tid, "name": spec["name"]} for tid, spec in published_models(_drug(ws))],
        "release_models": [{"formulation": name, **state} for name, state in sorted(release_states(ws).items())],
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
        # the process types that can carry the pathway's parameters: from the assembled CPF, or from the evidence not
        # excluded when nothing is assembled yet (the choice may come first)
        cpf = current_cpf(ws)
        targets = {r.id for r in (cpf.parameters if cpf else ())}
        targets |= {e.target for e in items(ws) if e.state is not EvidenceState.REJECTED}
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


class ReleaseModelAnswer(BaseModel):
    model: Literal["weibull", "particles"]
    reason: str = ""                       # required to hold a formulation for particle dissolution


@router.post("/projects/{project_id}/formulations/{name}:release-model", **answers(InputsPage))
def answer_release_model(project_id: str, name: str, body: ReleaseModelAnswer, principal: Writer,
                         store: StoreDep) -> dict[str, Any]:
    """A formulation's release model, chosen here (the owner's D1; plan 2026-11-26 §8): "weibull" confirms the Data
    room's proposal (or takes a held formulation's Weibull values again); "particles" holds the formulation for particle
    dissolution, with a reason (its Weibull values are set aside; Inputs cannot hold the particle inputs yet). The
    inputs are assembled again."""
    ws = workspace_for(project_id, principal, store)
    try:
        set_release_model(ws, name, model=body.model, reason=body.reason, by=principal.user_id)
    except ReleaseChoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        assemble(ws, by=principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return envelope(_view(ws))
