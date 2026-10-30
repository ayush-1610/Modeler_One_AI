"""P3 client data (plan §10, review layer L2b; T-47).

The client-data template is downloaded, filled and uploaded; it is read with no AI into CLIENT datasets and evidence.
Any other workbook is triaged sheet by sheet (by code, then agent A4 for the sheets code cannot decide); A4 then proposes
how to read each data sheet (checked by code), and a sheet is read once a person checks and confirms its reading. PDF, Word, CSV and Markdown files are stored as citable documents. The
view reconciles what arrived with what the data checklist says the client provides; Start's checklist ticks it off. It is
read on the Inputs step's Studies tab, and nothing is approved (D-27): the one review is at the MAP signature.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError

from modeler_api import agent_jobs, jobs
from modeler_api.deps import Reader, StoreDep, Writer, relates_to_form, version_view, workspace_for
from modeler_api.responses import answers, envelope
from modeler_api.views.client_data import (
    ClientDataPage,
    ClientUpload,
    MapPreview,
    MapReading,
    ReleaseProposal,
    SheetView,
    TriageStart,
)
from modeler_intake.client_template import TEMPLATE_ID, RequestRow, build_template
from modeler_intake.documents import DocumentError
from modeler_intake.grid import WorkbookGrid, read_workbook_bytes
from modeler_intake.sheet_form import SheetForm, preview_rows, suggest, to_proposal
from modeler_intake.triage import SheetCategory, SheetTriage
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.client_data import (
    REGISTER,
    ClientDataError,
    datasets_from_observations,
    ingest,
    reconcile,
    record_mapping,
    record_reading,
    set_triage,
    submission,
    submissions,
)
from modeler_project.dataset_register import dataset, decide_dataset, propose_dataset
from modeler_project.datasets import DatasetError
from modeler_project.dissolution_register import DissolutionRegisterError, comparisons, profiles, propose_release_model
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.inputs import refresh_inputs
from modeler_project.requirements import RequirementMatrix, client_request

router = APIRouter(prefix="/api/v1", tags=["client-data"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _matrix(ws: Workspace) -> tuple[Any, RequirementMatrix]:
    version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    if version is None:
        raise HTTPException(status_code=409, detail="this project has no data checklist yet: it is derived from the brief "
                                                    "at Start")
    return version, RequirementMatrix.from_content(version.content)


def _brief(ws: Workspace) -> ProjectBrief | None:
    version = ws.latest(ArtifactKind.BRIEF, "main")
    return ProjectBrief.from_content(version.content) if version else None


def _view(ws: Workspace) -> dict[str, Any]:
    matrix_version, matrix = _matrix(ws)
    recon = reconcile(ws, matrix)
    register = ws.latest(ArtifactKind.CLIENT_SUBMISSION, REGISTER)
    reading = jobs.running(ws.store, ws.tenant_id, ws.project_id, "reading")
    return {
        "template": TEMPLATE_ID,
        "data_plan": {"version": matrix_version.version, "status": ws.status(matrix_version).value},
        "files": submissions(ws),
        "reconciliation": recon.to_content(),
        "dissolution": {"profiles": profiles(ws), **comparisons(ws)},
        "register": version_view(ws, register, with_content=False) if register else None,
        "agents": agent_jobs.agents_status(), "running": jobs.running(ws.store, ws.tenant_id, ws.project_id, "triage") or reading,
        "reading": reading,
    }


@router.get("/client-data/template.xlsx")
def download_template(principal: Reader) -> Response:
    """The client-data workbook (D-11): README plus one sheet per kind of data, read with no AI."""
    return Response(build_template(), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_ID}.xlsx"'})


@router.get("/projects/{project_id}/client-data/request.xlsx")
def download_request(project_id: str, principal: Reader, store: StoreDep) -> Response:
    """The project's data request (page review 1, decision 2b): the client-data workbook with a first sheet listing what
    only the client can send, from the data plan, and where each goes. The client fills it and sends it back."""
    ws = workspace_for(project_id, principal, store)
    _version, matrix = _matrix(ws)
    brief = _brief(ws)
    drug = (brief.drug_name if brief else "") or project_id
    rows = [RequestRow(what=line.what, why=line.why, required=line.required, product=line.product, sheet=line.sheet)
            for line in client_request(matrix)]
    if not rows:
        raise HTTPException(status_code=409, detail="the data plan asks the client for nothing yet")
    heading = f"Data request: {drug} ({project_id}), {datetime.now(UTC).date().isoformat()}"
    return Response(build_template(rows, heading=heading), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{project_id}-data-request.xlsx"'})


@router.get("/projects/{project_id}/client-data", **answers(ClientDataPage))
def get_client_data(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope(_view(workspace_for(project_id, principal, store)))


@router.post("/projects/{project_id}/client-data", status_code=201, **answers(ClientUpload))
async def upload_client_files(project_id: str, principal: Writer, store: StoreDep,
                              files: Annotated[list[UploadFile], File()],
                              step: Annotated[str, Form()] = "", task: Annotated[str, Form()] = "") -> dict[str, Any]:
    """Store each file; read a filled template at once; triage any other workbook. `step` and `task`: what the files
    relate to (the document library's "Add data" card)."""
    relates_to = relates_to_form(step, task)
    ws = workspace_for(project_id, principal, store)
    _, matrix = _matrix(ws)
    library, brief = DocumentLibrary(ws), _brief(ws)
    read = []
    for upload in files:
        try:
            read.append(ingest(ws, library, await upload.read(), upload.filename or "client-file", by=principal.user_id,
                               matrix=matrix, brief=brief, relates_to=relates_to))
        except (DocumentError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"{upload.filename}: {exc}") from exc
    refresh_inputs(ws, by=principal.user_id)   # the inputs follow every change (redesign §3.2)
    return envelope({"read": [{k: r[k] for k in ("id", "file", "template")} for r in read], **_view(ws)})


def _workbook(ws: Workspace, sid: str, *, use: bool = False) -> tuple[dict[str, Any], WorkbookGrid]:
    """The file's record and its sheets. `use`: the file is to be read into the project (classified, triaged, read or
    mapped), which a withdrawn file is not until a person restores it (the document library, PR 2)."""
    content = submission(ws, sid)
    if content is None:
        raise HTTPException(status_code=404, detail=f"no client file {sid}")
    if use and (withdrawn := DocumentLibrary(ws).entry(content["sha256"]).withdrawn) is not None:
        raise HTTPException(status_code=409, detail=f"{content['file']} was withdrawn ({withdrawn.reason}); "
                                                    "restore it in the Project Document Library to read it")
    path = ws.store.blob_path(ws.tenant_id, ws.project_id, content["sha256"])
    if path is None:
        raise HTTPException(status_code=404, detail="the file's bytes are not in the store")
    try:
        return content, read_workbook_bytes(path.read_bytes(), content["file"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{content['file']} is not a workbook: {exc}") from exc


class Classification(BaseModel):
    category: SheetCategory
    reason: str = Field(min_length=1)


@router.post("/projects/{project_id}/client-data/{sid}/sheets/{sheet}:classify", **answers(ClientDataPage))
def classify(project_id: str, sid: str, sheet: str, body: Classification, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """A person says what a sheet holds (overrides code and A4)."""
    ws = workspace_for(project_id, principal, store)
    _, workbook = _workbook(ws, sid, use=True)
    if sheet not in workbook.sheets:
        raise HTTPException(status_code=404, detail=f"no sheet {sheet!r} in this file")
    set_triage(ws, sid, SheetTriage(sheet, body.category, by=principal.user_id, note=body.reason), by=principal.user_id,
               reason=body.reason)
    return envelope(_view(ws))


def run_triage_job(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, model, max_turns: int = 6) -> dict[str, Any]:
    """A4 on the sheets code left OTHER; each accepted classification carries a header quote checked by code."""
    ws = Workspace(store, tenant_id, project_id)
    content, workbook = _workbook(ws, sid, use=True)
    undecided = [t["sheet"] for t in content["triage"] if t["category"] == SheetCategory.OTHER.value and t["by"] == "code"]
    if not undecided:
        return {"status": "COMPLETED", "classified": 0, "rejected": 0}
    run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                              agent="A4-sheet-triage", model=model, max_turns=max_turns)
    ctx, outcome = agent_jobs.sheet_triage(model, workbook=workbook, sheets=undecided, actor=run.actor, max_turns=max_turns,
                                           log_step=run.log_step)
    for triaged in ctx.accepted:
        set_triage(ws, sid, triaged, by=ctx.actor, reason=triaged.note or "A4, header quoted")
    summary = {"classified": len(ctx.accepted), "rejected": len(ctx.rejected), "summary": outcome.final_text[:2000],
               "error": outcome.error}
    run.finish(outcome, summary)
    return {"run_id": run.run_id, "status": outcome.status, **summary}


@router.post("/projects/{project_id}/client-data/{sid}:triage", status_code=202, **answers(TriageStart))
def start_triage(project_id: str, sid: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    _workbook(ws, sid, use=True)
    model = agent_jobs.require_chat_model("agents are off: say what each sheet holds by hand")

    def job() -> None:
        run_triage_job(store, principal.tenant_id, project_id, sid, model=model)

    jobs.start(store, principal.tenant_id, project_id, "triage", job, busy="a triage run is already in progress",
               name=f"triage-{project_id}")
    return envelope({"status": "RUNNING"})


READABLE = (SheetCategory.PK_INDIVIDUAL.value, SheetCategory.PK_SUMMARY.value, SheetCategory.DISSOLUTION.value)


def _unread_sheets(content: dict[str, Any]) -> list[str]:
    """The file's data sheets that no confirmed reading has read yet."""
    read = {t.get("sheet") for m in content.get("mappings", []) if not m.get("replaced_by") for t in m["recipe"].get("tables", [])}
    return [t["sheet"] for t in content.get("triage", []) if t["category"] in READABLE and t["sheet"] not in read]


def run_reading_job(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, model, sheets: list[str] | None = None,
                    max_turns: int = 8) -> dict[str, Any]:
    """A4 proposes how to read each data sheet not read yet (or the sheets named), one agent run per sheet. A reading
    code accepted is kept on the file for the person to check, correct and save; nothing is read into the project here."""
    ws = Workspace(store, tenant_id, project_id)
    content, workbook = _workbook(ws, sid, use=True)
    brief = _brief(ws)
    products = [{"name": str(p.get("name") or ""), "role": str(p.get("role") or "")} for p in _brief_products(brief)]
    categories = {t["sheet"]: t["category"] for t in content.get("triage", [])}
    results = []
    for sheet in [s for s in (sheets or _unread_sheets(content)) if s in workbook.sheets]:
        run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                                  agent="A4-sheet-reading", model=model, max_turns=max_turns)
        reading = agent_jobs.sheet_reading(model, workbook=workbook, sheet=sheet, drug=brief.drug_name if brief else "",
                                           actor=run.actor, category=categories.get(sheet, ""), products=products,
                                           max_turns=max_turns, log_step=run.log_step)
        if reading.form is not None:
            record_reading(ws, sid, sheet=sheet, form=reading.form.model_dump(mode="json"), notes=reading.notes, by=run.actor,
                           run_id=run.run_id)
        summary = {"sheet": sheet, "proposed": reading.form is not None, "refused": len(reading.rejected),
                   "summary": reading.outcome.final_text[:2000], "error": reading.outcome.error}
        run.finish(reading.outcome, summary)
        results.append({"run_id": run.run_id, "status": reading.outcome.status, **summary})
    return {"status": "COMPLETED", "sheets": results}


class ReadingRequest(BaseModel):
    sheets: list[str] = Field(default_factory=list)       # none named: every data sheet not read yet


@router.post("/projects/{project_id}/client-data/{sid}:read", status_code=202, **answers(TriageStart))
def start_reading(project_id: str, sid: str, principal: Writer, store: StoreDep, body: ReadingRequest | None = None) -> dict[str, Any]:
    """A4 proposes how to read the file's data sheets, in the background; each proposal is checked by code and waits on
    its sheet for the person to check and save (nothing is read into the project until then)."""
    ws = workspace_for(project_id, principal, store)
    content, workbook = _workbook(ws, sid, use=True)
    sheets = body.sheets if body else []
    if content.get("template"):
        raise HTTPException(status_code=409, detail="the client-data template is read cell by cell, with no agent")
    unknown = [s for s in sheets if s not in workbook.sheets]
    if unknown:
        raise HTTPException(status_code=404, detail=f"no sheet {', '.join(map(repr, unknown))} in this file")
    if not (sheets or _unread_sheets(content)):
        raise HTTPException(status_code=409, detail="no data sheet is left to read in this file; open a sheet to read it again")
    model = agent_jobs.require_chat_model("agents are off: read each sheet with the form")

    def job() -> None:
        run_reading_job(store, principal.tenant_id, project_id, sid, model=model, sheets=sheets or None)

    jobs.start(store, principal.tenant_id, project_id, "reading", job, busy="a reading run is already in progress",
               name=f"reading-{project_id}")
    return envelope({"status": "RUNNING"})


@router.get("/projects/{project_id}/client-data/{sid}/sheets/{sheet}", **answers(SheetView))
def read_sheet(project_id: str, sid: str, sheet: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """One sheet as text, with the reading form to check: the reading agent's checked proposal when there is one, else
    code's first filling (units, dose and LLOQ quoted from their cells; what the sheet does not say left for the
    person), and the notes that say what was found and what was not."""
    ws = workspace_for(project_id, principal, store)
    content, workbook = _workbook(ws, sid)
    if sheet not in workbook.sheets:
        raise HTTPException(status_code=404, detail=f"no sheet {sheet!r} in this file")
    grid = workbook.sheets[sheet]
    brief = _brief(ws)
    products = [{"name": str(p.get("name") or ""), "role": str(p.get("role") or "")} for p in _brief_products(brief)]
    category = next((t["category"] for t in content.get("triage", []) if t["sheet"] == sheet), "")
    proposed = _proposed_reading(content, sheet)
    if proposed is not None:
        form, notes, by, run_id = proposed
    else:
        form, notes = suggest(grid, category=category, filename=content["file"], drug=brief.drug_name if brief else "",
                              products=products)
        by, run_id = "code", None
    read = [m for m in content.get("mappings", []) if not m.get("replaced_by")
            and any(t.get("sheet") == sheet for t in m["recipe"].get("tables", []))]
    return envelope({"sheet": sheet, "rows": preview_rows(grid), "max_row": grid.max_row, "max_column": grid.max_column,
                     "category": category, "form": form.model_dump(mode="json"), "notes": notes, "products": products,
                     "read_before": [{"recipe_id": m["recipe"].get("recipe_id"), "datasets": m.get("datasets", [])}
                                     for m in read], "proposed_by": by, "run_id": run_id})


def _proposed_reading(content: dict[str, Any], sheet: str) -> tuple[SheetForm, list[str], str, str | None] | None:
    """The reading agent's checked reading of the sheet, when there is one (else code fills the form first)."""
    proposed = (content.get("readings") or {}).get(sheet)
    if not proposed:
        return None
    try:
        return SheetForm.model_validate(proposed["form"]), list(proposed.get("notes", [])), proposed["by"], proposed.get("run_id")
    except (ValidationError, KeyError):
        return None


def _brief_products(brief: ProjectBrief | None) -> list[dict[str, Any]]:
    if brief is None:
        return []
    return [{k: brief.value(f"products[{i}].{k}") for k in item} for i, item in enumerate(brief.groups.get("products", ()))]


class MappingBody(BaseModel):
    """How to read a sheet: the page's form (`form`) or a mapping recipe (`proposal`, the data-mapping agent's shape or
    written by a person); the study facts the sheet does not state; and whether to keep the result (False: preview)."""

    proposal: dict[str, Any] | None = None
    form: SheetForm | None = None
    study: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False
    replace: bool = False      # this reading replaces the earlier readings of the same sheet (their datasets rejected)


def _sample(review, *, hide_values: bool) -> dict[str, Any]:
    """What the recipe read, in a person's terms: the series, the times, the first values with their cells."""
    if review.dissolution:
        records = review.dissolution
        rows = [{"series": r.vessel, "time": r.time, "value": None if hide_values else r.percent_dissolved,
                 "cell": r.source.cells.get("value", "")} for r in records[:12]]
        return {"series": sorted({r.vessel for r in records}), "times": sorted({r.time for r in records}),
                "time_unit": records[0].time_unit, "unit": "%", "rows": rows, "below_lloq": 0}
    records = review.concentrations
    if not records:
        return {"series": [], "times": [], "rows": [], "below_lloq": 0}
    rows = [{"series": r.series, "time": r.time, "value": None if hide_values else r.value, "blq": r.below_lloq,
             "cell": r.source.cells.get("value", "")} for r in records[:12]]
    return {"series": sorted({r.series for r in records}), "times": sorted({r.time for r in records}),
            "time_unit": records[0].time_unit, "unit": records[0].unit, "rows": rows,
            "below_lloq": sum(r.below_lloq for r in records)}


@router.post("/projects/{project_id}/client-data/{sid}:map", **answers(MapReading | MapPreview))
def map_sheets(project_id: str, sid: str, body: MappingBody, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """Apply a mapping recipe deterministically. Preview shows the records, problems and open questions; confirming a
    recipe with none of them creates the datasets (origin CLIENT) and keeps the recipe on the file's record."""
    from modeler_api.deps import blinding_view
    from modeler_intake.recipe_review import RecipeProposal, review_proposal
    from modeler_project.blinding import EXTERNAL_PURPOSES

    ws = workspace_for(project_id, principal, store)
    content, workbook = _workbook(ws, sid, use=body.confirm)   # a preview reads nothing into the project
    if (body.form is None) == (body.proposal is None):
        raise HTTPException(status_code=422, detail="send the reading form or a recipe (one of them)")
    raw = body.proposal
    if body.form is not None:
        if body.form.sheet not in workbook.sheets:
            raise HTTPException(status_code=404, detail=f"no sheet {body.form.sheet!r} in this file")
        raw = to_proposal(body.form, workbook.sheets[body.form.sheet])
    try:
        proposal = RecipeProposal.model_validate(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"recipe: {exc}") from exc
    review = review_proposal(workbook, proposal, recipe_id=f"{sid}-r{len(content.get('mappings', [])) + 1}")
    preview = {
        "ready": review.ready_for_confirmation,
        "issues": [{"code": i.code, "location": i.location, "message": i.message} for i in review.issues],
        "questions": review.questions, "concentrations": len(review.concentrations), "dissolution": len(review.dissolution),
        "studies": sorted({o.study_id for o in review.concentrations}), "recipe": raw,
    }
    blinding = blinding_view(ws)
    hidden = bool(blinding["on"] and not blinding["map_signed"] and body.study.get("purpose") in EXTERNAL_PURPOSES)
    preview["sample"] = {**_sample(review, hide_values=hidden), "values_hidden": hidden}
    if not body.confirm:
        return envelope(preview)
    if not review.ready_for_confirmation or review.recipe is None:
        raise HTTPException(status_code=409, detail="the recipe has problems or open questions; resolve them first")
    library = DocumentLibrary(ws)
    try:
        built = datasets_from_observations(review.concentrations, study=body.study, sha=content["sha256"],
                                           filename=content["file"], library=library)
        ids = [propose_dataset(ws, d, actor=principal.user_id).id for d in built]
    except (ClientDataError, DatasetError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    sheets = {t.sheet for t in review.recipe.tables}
    earlier = [m for m in content.get("mappings", []) if body.replace and not m.get("replaced_by")
               and any(t.get("sheet") in sheets for t in m["recipe"].get("tables", []))]
    record_mapping(ws, sid, recipe=review.recipe.model_dump(mode="json"), dataset_ids=ids,
                   dissolution=[o.model_dump(mode="json") for o in review.dissolution], by=principal.user_id,
                   replaces=tuple(m["recipe"]["recipe_id"] for m in earlier))
    for old_id in (d for m in earlier for d in m.get("datasets", [])):
        old = dataset(ws, old_id)
        if old is not None and old.state is not EvidenceState.REJECTED:
            decide_dataset(ws, old_id, state=EvidenceState.REJECTED, by=principal.user_id,
                           reason=f"replaced: {', '.join(sorted(sheets))} read again (recipe {review.recipe.recipe_id})")
    refresh_inputs(ws, by=principal.user_id)   # the inputs follow every change (redesign §3.2)
    return envelope({**preview, "datasets": ids, **_view(ws)})


class ReleaseModelRequest(BaseModel):
    formulation: str = Field(min_length=1)


@router.post("/projects/{project_id}/dissolution/{profile_id}:propose", status_code=201, **answers(ReleaseProposal))
def propose_release(project_id: str, profile_id: str, body: ReleaseModelRequest, principal: Writer,
                    store: StoreDep) -> dict[str, Any]:
    """Propose a profile's fit as a formulation's release model: evidence to accept or reject on the Parameters tab
    (which profile represents in vivo release is a planning decision, D-12)."""
    ws = workspace_for(project_id, principal, store)
    try:
        proposed = propose_release_model(ws, profile_id, formulation=body.formulation, by=principal.user_id)
    except DissolutionRegisterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    refresh_inputs(ws, by=principal.user_id)   # the inputs follow every change (redesign §3.2)
    return envelope({"evidence": [e.id for e in proposed], **_view(ws)})
