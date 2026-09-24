"""Write APIs for the guided create-project flow (backs the "New project" wizard).

A project is created, its compound's CPF is put, observed studies are uploaded, and ``campaign:prepare``
turns the stored CPF + studies into the self-contained inputs the single-node runner reads (a staged CPF,
the generated MAP, and observed PK from deterministic NCA). The MAP is then signed (Part 11) and the campaign
started. Every write is role-gated (curator/reviewer) and scoped to a project the caller is a member of, and
persisted through ``FileWriteStore`` — the seam the Postgres §5 tables replace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modeler_api.auth import Principal, require_project, require_role
from modeler_api.config import get_settings
from modeler_api.filestore import FileReadStore, FileWriteStore
from modeler_api.read_api import project_cpf_view
from modeler_api.responses import envelope
from modeler_contracts.runs import CAMPAIGN_STAGES
from pbpk_domain.cpf.models import CPF
from pbpk_domain.m15 import Rating

router = APIRouter(prefix="/api/v1", tags=["write"])

Author = Annotated[Principal, Depends(require_role("modeler-curator", "modeler-reviewer"))]

_ENGINE_DIGEST = os.environ.get("MODELER_IMAGE_DIGEST", "sha256:" + "0" * 64)


def _stores() -> tuple[FileReadStore, FileWriteStore]:
    settings = get_settings()
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Write models are not configured. Set MODELER_READ_ROOT.")
    return FileReadStore(settings.read_root), FileWriteStore(settings.read_root)


StoresDep = Annotated[tuple[FileReadStore, FileWriteStore], Depends(_stores)]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"project-{uuid.uuid4().hex[:8]}"


# --- create project -------------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    compound: str = Field(min_length=1)
    risk: str = "medium"
    question: str = ""
    application: str = ""
    model_risk: str = "medium"


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, principal: Author, stores: StoresDep) -> dict[str, Any]:
    _read, write = stores
    project_id = _slug(body.name)
    questions = []
    if body.question:
        questions.append({"id": f"qoi-{uuid.uuid4().hex[:6]}", "question": body.question,
                          "application": body.application or "PBPK", "modelRisk": body.model_risk,
                          "stage": "planning", "failingCriteria": 0})
    project = {"id": project_id, "name": body.name, "compounds": [body.compound],
               "openQuestions": len(questions), "risk": body.risk, "questions": questions}
    write.put_project(principal.tenant_id, project)
    return envelope(project)


# --- put the compound's CPF -----------------------------------------------------------------------


@router.put("/projects/{project_id}/compounds/{compound}/cpf")
def put_cpf(project_id: str, compound: str, cpf: CPF, principal: Author, stores: StoresDep) -> dict[str, Any]:
    require_project(project_id, principal)
    if cpf.compound != compound:
        raise HTTPException(status_code=422, detail=f"CPF compound {cpf.compound!r} does not match {compound!r} in the path")
    _read, write = stores
    write.put_cpf(principal.tenant_id, compound, cpf)
    return envelope(project_cpf_view(cpf))


# --- upload observed studies ----------------------------------------------------------------------


class ObservedProfile(BaseModel):
    times: list[float] = Field(min_length=1)
    values: list[float] = Field(min_length=1)
    time_unit: str = "min"
    unit: str = "µmol/l"
    sd: list[float] | None = None
    lloq: float | None = None


class StudyUpload(BaseModel):
    study_id: str = Field(min_length=1)
    reference: str = ""
    n: int = Field(default=12, gt=0)
    design: str = "SD"
    dosing_interval_h: float | None = Field(default=None, gt=0)  # multiple dose: one dose every N hours…
    n_doses: int | None = Field(default=None, gt=0)              # …this many times
    route: str = "oral"
    dose_mg: float = Field(gt=0)
    dose_per_kg: bool = False  # dose_mg is per kg body weight
    infusion_time_min: float | None = None
    formulation: str = "solution"
    formulation_name: str | None = None  # a tablet/capsule study: the CPF formulation it used (form.{name}.*)
    food_state: str = "fasted"
    # Who was studied: a patient or special population (e.g. renal impairment) is classified SPECIAL by the split
    # (MS-01 §3.2) and never fits the healthy-volunteer model; without these it would be taken as healthy.
    population_type: str = "healthy"
    special_population: str | None = None
    co_medication: str | None = None  # a co-medicated arm is a DDI study (MS-01 §3.2), never the drug alone
    # The studied individual (population, sex, age, age range): the round build simulates the study in it.
    demographics: dict[str, Any] | None = None
    # A reference model's own individual for this study (reference import only): physiology overrides and expression
    # values, paths and units copied from the published snapshot (StudyRecord.published_individual).
    published_individual: dict[str, Any] | None = None
    analyte: str | None = None  # a model system's analyte (compound or sum) the study measures
    product: str | None = None  # the system's product the study administers
    n_timepoints: int = Field(default=10, gt=0)
    lloq: float | None = None
    profile: ObservedProfile


class StudiesUpload(BaseModel):
    studies: list[StudyUpload] = Field(min_length=1)


@router.post("/projects/{project_id}/studies", status_code=201)
def upload_studies(project_id: str, body: StudiesUpload, principal: Author, stores: StoresDep) -> dict[str, Any]:
    """Add observed studies to the project, replacing any with the same ``study_id`` and keeping the rest."""
    require_project(project_id, principal)
    read, write = stores
    rows = [s.model_dump() for s in body.studies]
    incoming = {r["study_id"] for r in rows}
    kept = [s for s in read.list_studies(principal.tenant_id, project_id) if s.get("study_id") not in incoming]
    write.put_studies(principal.tenant_id, project_id, kept + rows)
    return envelope({"stored": len(rows), "total": len(kept) + len(rows)})


# --- prepare the campaign inputs (CPF + MAP + observed) -------------------------------------------


class PrepareRequest(BaseModel):
    compound: str = Field(min_length=1)
    objective: str = "Predict exposure for the question of interest"
    context_of_use: str = "Model-informed decision"
    food_effect_in_question: bool = False
    model_risk: str = "medium"
    stages: list[str] | None = None


def _study_record(row: dict[str, Any]):
    from pbpk_domain.campaign.split import StudyRecord

    fields = {k: v for k, v in row.items() if k in StudyRecord.model_fields}
    return StudyRecord.model_validate(fields)


def _observed_from_studies(rows: list[dict[str, Any]], mol_weight: float | None) -> dict[str, Any]:
    """Deterministic NCA per uploaded profile → the observed PK the gate (auc/cmax) and the fit (profile) read.

    Each profile is first converted to the engine's units (minutes, µmol/l — `pbpk_domain.units`), so predicted
    and observed AUC/Cmax are compared in the same units whatever the study reported. Raises UnitError."""
    from pbpk_domain.nca import nca
    from pbpk_domain.units import normalize_profile

    observed: dict[str, Any] = {}
    for row in rows:
        profile = row.get("profile")
        if not profile:
            continue
        canonical = normalize_profile(profile, mol_weight)
        result = nca(list(canonical["times"]), list(canonical["values"]))
        observed[row["study_id"]] = {
            "auc": result.auc_last, "cmax": result.c_max, "tmax": result.t_max, "thalf": result.t_half,
            "profile": canonical,
        }
    return observed


@router.post("/projects/{project_id}/questions/{question_id}/campaign:prepare")
def prepare_campaign(project_id: str, question_id: str, body: PrepareRequest, principal: Author,
                     stores: StoresDep) -> dict[str, Any]:
    """Stage the CPF, generate + persist the MAP, and derive observed PK, returning the runner's inputs."""
    read, write = stores
    require_project(project_id, principal)

    cpf = read.get_cpf(principal.tenant_id, project_id, body.compound)
    if cpf is None:
        raise HTTPException(status_code=404, detail=f"no CPF for {body.compound}; put it before preparing a campaign")
    rows = read.list_studies(principal.tenant_id, project_id)
    if not rows:
        raise HTTPException(status_code=422, detail="no observed studies uploaded for this project")

    from pbpk_domain.campaign.map import generate_map
    from pbpk_domain.campaign.split import QuestionOfInterest, split_studies
    from pbpk_domain.units import UnitError

    mw = cpf.get("phys.mw")
    try:
        observed = _observed_from_studies(rows, mw.numeric_value if mw is not None else None)
    except UnitError as exc:
        raise HTTPException(status_code=422, detail=f"observed data: {exc}") from exc
    # Each study's last sampled time, so its simulation covers the whole observed window.
    sampling_end_h = {sid: max(o["profile"]["times"]) / 60.0 for sid, o in observed.items() if o["profile"]["times"]}

    studies = [_study_record(r) for r in rows]
    try:
        risk = Rating(body.model_risk)
    except ValueError:
        risk = Rating.MEDIUM
    question = QuestionOfInterest(food_effect=body.food_effect_in_question)
    map_doc = generate_map(
        compound=body.compound, cpf=cpf, studies=studies, split=split_studies(studies, question),
        objective=body.objective, context_of_use=body.context_of_use,
        food_effect_in_question=body.food_effect_in_question, model_risk=risk,
        engine_image_digest=_ENGINE_DIGEST, software_versions={"ospsuite": "12.4.4"},
        sampling_end_h=sampling_end_h,
    )

    # Stage a self-contained input set the single-node runner reads (build_round_snapshot writes its
    # snapshots and fitted-CPF versions next to the CPF, so keep them in the prep dir, not the canonical cpf/).
    prep = f"prep/{question_id}"
    cpf_bytes = cpf.model_dump_json().encode("utf-8")
    map_bytes = map_doc.model_dump_json().encode("utf-8")
    observed_bytes = json.dumps(observed, ensure_ascii=False).encode("utf-8")
    cpf_path = write.materialize(principal.tenant_id, f"{prep}/cpf.json", cpf_bytes)
    map_path = write.materialize(principal.tenant_id, f"{prep}/map.json", map_bytes)
    observed_path = write.materialize(principal.tenant_id, f"{prep}/observed.json", observed_bytes)

    map_id = f"map_{uuid.uuid4().hex[:8]}"
    return envelope({
        "map_id": map_id,
        "compound": body.compound,
        "cpf_uri": cpf_path.as_uri(), "cpf_sha256": hashlib.sha256(cpf_bytes).hexdigest(),
        "map_uri": map_path.as_uri(), "map_sha256": hashlib.sha256(map_bytes).hexdigest(),
        "observed_uri": observed_path.as_uri(),
        # Every stage by default: a stage with nothing to simulate is skipped with its documented reason, so
        # asking for fewer stages only hides the rest of the pipeline.
        "stages": body.stages or list(CAMPAIGN_STAGES),
        "tier": map_doc.acceptance.tier,
        "studies": [{"study_id": s.study_id, "assignment": s.assignment} for s in map_doc.studies],
    })
