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
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from modeler_api.auth import Principal, require_project, require_role
from modeler_api.config import SettingsDep
from modeler_api.cpf_view import project_cpf_view
from modeler_api.responses import answers, envelope
from modeler_api.studies import StudiesUpload, observed_from_studies
from modeler_api.views.read import CpfView
from modeler_api.views.write import CampaignInputs, StudiesStored, SystemView
from modeler_contracts.runs import CAMPAIGN_STAGES
from modeler_storage.filestore import FileReadStore, FileWriteStore
from modeler_storage.records import ProjectRecord, QuestionRecord
from pbpk_domain.cpf.models import CPF
from pbpk_domain.m15 import Rating

router = APIRouter(prefix="/api/v1", tags=["write"])

Author = Annotated[Principal, Depends(require_role("modeler-curator", "modeler-reviewer"))]

def _stores(settings: SettingsDep) -> tuple[FileReadStore, FileWriteStore]:
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
    # A project that may sign verdicts judged on synthetic or illustrative data (machinery tests, demos). Its verdicts
    # stay labelled TEST ONLY; any other project needs real observed data to sign S4/S5 (plan §9.4, D-19).
    exploratory: bool = False


@router.post("/projects", status_code=201, **answers(ProjectRecord))
def create_project(body: ProjectCreate, principal: Author, stores: StoresDep) -> dict[str, Any]:
    _read, write = stores
    project_id = _slug(body.name)
    questions = []
    if body.question:
        questions.append(QuestionRecord(id=f"qoi-{uuid.uuid4().hex[:6]}", question=body.question,
                                        application=body.application or "PBPK", modelRisk=body.model_risk,
                                        stage="planning", failingCriteria=0))
    project = ProjectRecord(id=project_id, name=body.name, compounds=[body.compound], openQuestions=len(questions),
                            risk=body.risk, questions=questions, exploratory=body.exploratory).stored()
    write.put_project(principal.tenant_id, project)
    return envelope(project)


# --- put the compound's CPF -----------------------------------------------------------------------


@router.put("/projects/{project_id}/compounds/{compound}/cpf", **answers(CpfView))
def put_cpf(project_id: str, compound: str, cpf: CPF, principal: Author, stores: StoresDep) -> dict[str, Any]:
    require_project(project_id, principal)
    if cpf.compound != compound:
        raise HTTPException(status_code=422, detail=f"CPF compound {cpf.compound!r} does not match {compound!r} in the path")
    _read, write = stores
    write.put_cpf(principal.tenant_id, project_id, compound, cpf)
    return envelope(project_cpf_view(cpf))


def _project_system(read, tenant_id: str, project_id: str, links_doc: dict[str, Any]):
    """The project's model system: its links with each compound's current CPF (ValueError names what is missing)."""
    from pbpk_domain.system import SystemLinks, assemble

    links = SystemLinks.model_validate(links_doc)
    cpfs = {c: cpf for c in links.compounds if (cpf := read.get_cpf(tenant_id, project_id, c)) is not None}
    return assemble(links, cpfs)


@router.put("/projects/{project_id}/system", **answers(SystemView))
def put_system(project_id: str, links: dict[str, Any], principal: Author, stores: StoresDep) -> dict[str, Any]:
    """Relate the project's compounds as one model system (parent, enantiomers, metabolites): roles, formation links,
    products with their dose fractions (required: never defaulted), published sum observers and analytes. Each
    compound's CPF is put first; the system is checked against them before it is stored."""
    require_project(project_id, principal)
    read, write = stores
    try:
        system = _project_system(read, principal.tenant_id, project_id, links)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"model system: {exc}") from exc
    from pbpk_domain.system import links_of

    write.put_system(principal.tenant_id, project_id, links_of(system).model_dump(mode="json"))
    project = read.get_project(principal.tenant_id, project_id)
    if project is not None:  # the project lists every compound of its system (the parent first)
        members = [c.compound for c in system.compounds]
        compounds = list(dict.fromkeys([*project.get("compounds", []), *members]))
        write.put_project(principal.tenant_id, ProjectRecord.model_validate({**project, "compounds": compounds}).stored())
    return envelope({"name": system.name, "compounds": [c.compound for c in system.compounds], "roles": system.roles,
                     "products": system.products, "analytes": sorted(system.analytes), "sha256": system.sha256})


# --- upload observed studies ----------------------------------------------------------------------


@router.post("/projects/{project_id}/studies", status_code=201, **answers(StudiesStored))
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


class ApplicationRequest(BaseModel):
    """An application the campaign runs at S6 (T-31): an analysis template and the person's inputs to it."""

    template: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)


class PrepareRequest(BaseModel):
    compound: str = Field(min_length=1)
    objective: str = "Predict exposure for the question of interest"
    context_of_use: str = "Model-informed decision"
    food_effect_in_question: bool = False
    model_risk: str = "medium"
    stages: list[str] | None = None
    applications: list[ApplicationRequest] = Field(default_factory=list)


def _study_record(row: dict[str, Any]):
    from pbpk_domain.campaign.split import StudyRecord

    fields = {k: v for k, v in row.items() if k in StudyRecord.model_fields}
    return StudyRecord.model_validate(fields)


@router.post("/projects/{project_id}/questions/{question_id}/campaign:prepare", **answers(CampaignInputs))
def prepare_campaign(project_id: str, question_id: str, body: PrepareRequest, principal: Author,
                     stores: StoresDep, settings: SettingsDep) -> dict[str, Any]:
    """Stage the CPF, generate + persist the MAP, and derive observed PK, returning the runner's inputs."""
    read, write = stores
    require_project(project_id, principal)

    cpf = read.get_cpf(principal.tenant_id, project_id, body.compound)
    if cpf is None:
        raise HTTPException(status_code=404, detail=f"no CPF for {body.compound}; put it before preparing a campaign")
    rows = read.list_studies(principal.tenant_id, project_id)
    if not rows:
        raise HTTPException(status_code=422, detail="no observed studies uploaded for this project")

    from pbpk_domain.campaign.map import MapApplication, generate_map
    from pbpk_domain.campaign.split import QuestionOfInterest, split_studies
    from pbpk_domain.units import UnitError

    system = None
    links_doc = read.get_system(principal.tenant_id, project_id) if hasattr(read, "get_system") else None
    not_evaluated: list[str] = []
    if links_doc:
        try:
            system = _project_system(read, principal.tenant_id, project_id, links_doc)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=f"model system: {exc}") from exc
        if system.roles.get(body.compound) != "parent":
            raise HTTPException(status_code=422, detail=f"{body.compound} is not a parent of the {system.name} system; "
                                                        f"the campaign fits a parent ({', '.join(system.parents)})")
    mw = cpf.get("phys.mw")
    try:
        if system is None:
            observed = observed_from_studies(rows, mw.numeric_value if mw is not None else None)
        else:
            # each study's concentrations converted with its analyte's molecular weight; an analyte with no single
            # one (a mass-concentration sum) is not evaluated in phase 1 and is named
            from pbpk_domain.system import analyte_molecular_weight

            observed = {}
            kept = []
            for row in rows:
                analyte = row.get("analyte") or body.compound
                weight, reason = analyte_molecular_weight(system, analyte)
                if reason is not None:
                    not_evaluated.append(f"{row['study_id']}: {reason}")
                    continue
                observed.update(observed_from_studies([row], weight))
                kept.append(row)
            rows = kept
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
    try:  # each pinned at the registry's current version of its template
        applications = tuple(MapApplication.pinned(a.template, a.inputs) for a in body.applications)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"applications: no analysis template {exc}") from exc
    map_doc = generate_map(
        compound=body.compound, cpf=cpf, studies=studies, split=split_studies(studies, question),
        objective=body.objective, context_of_use=body.context_of_use,
        food_effect_in_question=body.food_effect_in_question, model_risk=risk,
        engine_image_digest=settings.image_digest, software_versions={"ospsuite": "12.4.4"},
        sampling_end_h=sampling_end_h, system=system, applications=applications,
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
    system_fields: dict[str, Any] = {}
    if system is not None:
        system_bytes = system.model_dump_json().encode("utf-8")
        system_path = write.materialize(principal.tenant_id, f"{prep}/system.json", system_bytes)
        system_fields = {"system_uri": system_path.as_uri(), "system_sha256": hashlib.sha256(system_bytes).hexdigest(),
                         "model_system_sha256": system.sha256, "not_evaluated": not_evaluated}

    map_id = f"map_{uuid.uuid4().hex[:8]}"
    return envelope({
        "map_id": map_id,
        "compound": body.compound,
        "cpf_uri": cpf_path.as_uri(), "cpf_sha256": hashlib.sha256(cpf_bytes).hexdigest(),
        "map_uri": map_path.as_uri(), "map_sha256": hashlib.sha256(map_bytes).hexdigest(),
        "observed_uri": observed_path.as_uri(),
        # Every stage by default: a stage with nothing to simulate is skipped with its documented reason, so
        # asking for fewer stages only hides the rest of the pipeline. SM only when the MAP plans it (MS-01 v1.3).
        "stages": [s for s in (body.stages or CAMPAIGN_STAGES)
                   if s != "SM" or any(p.stage == "SM" for p in map_doc.stage_plan)],
        "tier": map_doc.acceptance.tier,
        "studies": [{"study_id": s.study_id, "assignment": s.assignment} for s in map_doc.studies],
        # what each study's observed data is (plan §9.4); a study with no profile is not evaluable
        "origins": {sid: o.get("origin") for sid, o in observed.items()},
        "not_evaluable": sorted(r["study_id"] for r in rows if r["study_id"] not in observed),
        # what the MAP's applications still need before it can be signed (a never-defaulted input is named, not filled)
        **({"application_problems": map_doc.application_problems(cpf)} if applications else {}),
        **system_fields,
    })
