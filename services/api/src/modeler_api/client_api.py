"""P3 client data (plan §10, review layer L2b; T-47).

The client-data template is downloaded, filled and uploaded; it is read with no AI into CLIENT datasets and evidence.
Any other workbook is triaged sheet by sheet (by code, then agent A4 for the sheets code cannot decide) and read once a
person confirms a mapping recipe for a sheet. PDF, Word, CSV and Markdown files are stored as citable documents. The
view reconciles what arrived with what the data plan says the client provides; the phase closes when every required
client item is delivered, skipped as not available, or covered by an accepted literature cross-check (owner, R-07).
"""

from __future__ import annotations

import threading
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from modeler_api.brief_api import agents_status
from modeler_api.project_api import Reader, StoreDep, Writer, version_view, workspace_for
from modeler_api.responses import envelope
from modeler_intake.client_template import TEMPLATE_ID, build_template
from modeler_intake.documents import DocumentError
from modeler_intake.grid import WorkbookGrid, read_workbook_bytes
from modeler_intake.sheet_form import SheetForm, preview_rows, suggest, to_proposal
from modeler_intake.triage import SheetCategory, SheetTriage
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.client_data import (
    REGISTER,
    ClientDataError,
    close_register,
    datasets_from_observations,
    ingest,
    reconcile,
    record_mapping,
    set_triage,
    submissions,
)
from modeler_project.dataset_register import decide_dataset, propose_dataset
from modeler_project.datasets import DatasetError
from modeler_project.dissolution_register import DissolutionRegisterError, comparisons, profiles, propose_release_model
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.requirements import RequirementMatrix

router = APIRouter(prefix="/api/v1", tags=["client-data"])
_RUNNING: set[tuple[str, str]] = set()
_LOCK = threading.Lock()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _matrix(ws: Workspace) -> tuple[Any, RequirementMatrix]:
    version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    if version is None:
        raise HTTPException(status_code=409, detail="derive and approve the data plan first (P1)")
    return version, RequirementMatrix.from_content(version.content)


def _brief(ws: Workspace) -> ProjectBrief | None:
    version = ws.latest(ArtifactKind.BRIEF, "main")
    return ProjectBrief.from_content(version.content) if version else None


def _view(ws: Workspace) -> dict[str, Any]:
    matrix_version, matrix = _matrix(ws)
    recon = reconcile(ws, matrix)
    register = ws.latest(ArtifactKind.CLIENT_SUBMISSION, REGISTER)
    return {
        "template": TEMPLATE_ID,
        "data_plan": {"version": matrix_version.version, "status": ws.status(matrix_version).value},
        "files": submissions(ws),
        "reconciliation": recon.to_content(),
        "dissolution": {"profiles": profiles(ws), **comparisons(ws)},
        "register": version_view(ws, register, with_content=False) if register else None,
        "agents": agents_status(), "running": (ws.tenant_id, ws.project_id) in _RUNNING,
    }


@router.get("/client-data/template.xlsx")
def download_template(principal: Reader) -> Response:
    """The client-data workbook (D-11): README plus one sheet per kind of data, read with no AI."""
    return Response(build_template(), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_ID}.xlsx"'})


@router.get("/projects/{project_id}/client-data")
def get_client_data(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope(_view(workspace_for(project_id, principal, store)))


@router.post("/projects/{project_id}/client-data", status_code=201)
async def upload_client_files(project_id: str, principal: Writer, store: StoreDep,
                              files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
    """Store each file; read a filled template at once; triage any other workbook."""
    ws = workspace_for(project_id, principal, store)
    _, matrix = _matrix(ws)
    library, brief = DocumentLibrary(ws), _brief(ws)
    read = []
    for upload in files:
        try:
            read.append(ingest(ws, library, await upload.read(), upload.filename or "client-file", by=principal.user_id,
                               matrix=matrix, brief=brief))
        except (DocumentError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"{upload.filename}: {exc}") from exc
    return envelope({"read": [{k: r[k] for k in ("id", "file", "template")} for r in read], **_view(ws)})


def _workbook(ws: Workspace, sid: str) -> tuple[dict[str, Any], WorkbookGrid]:
    version = ws.latest(ArtifactKind.CLIENT_SUBMISSION, sid)
    if version is None:
        raise HTTPException(status_code=404, detail=f"no client file {sid}")
    path = ws.store.blob_path(ws.tenant_id, ws.project_id, version.content["sha256"])
    if path is None:
        raise HTTPException(status_code=404, detail="the file's bytes are not in the store")
    try:
        return version.content, read_workbook_bytes(path.read_bytes(), version.content["file"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{version.content['file']} is not a workbook: {exc}") from exc


class Classification(BaseModel):
    category: SheetCategory
    reason: str = Field(min_length=1)


@router.post("/projects/{project_id}/client-data/{sid}/sheets/{sheet}:classify")
def classify(project_id: str, sid: str, sheet: str, body: Classification, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """A person says what a sheet holds (overrides code and A4)."""
    ws = workspace_for(project_id, principal, store)
    _, workbook = _workbook(ws, sid)
    if sheet not in workbook.sheets:
        raise HTTPException(status_code=404, detail=f"no sheet {sheet!r} in this file")
    set_triage(ws, sid, SheetTriage(sheet, body.category, by=principal.user_id, note=body.reason), by=principal.user_id,
               reason=body.reason)
    return envelope(_view(ws))


def run_triage_job(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, model, max_turns: int = 6) -> dict[str, Any]:
    """A4 on the sheets code left OTHER; each accepted classification carries a header quote checked by code."""
    from modeler_agents.run_store import FileRunStore
    from modeler_agents.sheet_triage import TriageContext, run_triage

    ws = Workspace(store, tenant_id, project_id)
    content, workbook = _workbook(ws, sid)
    undecided = [t["sheet"] for t in content["triage"] if t["category"] == SheetCategory.OTHER.value and t["by"] == "code"]
    if not undecided:
        return {"status": "COMPLETED", "classified": 0, "rejected": 0}
    runs = FileRunStore(store.root, project_id=project_id)  # type: ignore[attr-defined]
    run_id = runs.start_run(tenant_id=tenant_id, agent="A4-sheet-triage", provider=model.provider, model=model.model,
                            campaign_id=None, budget={"max_turns": max_turns})
    seq = [0]

    def log_step(step: dict[str, Any]) -> None:
        seq[0] += 1
        runs.record_step(run_id=run_id, seq=seq[0], kind=step.get("type", "step"), content=step, usage=step.get("usage", {}))

    ctx = TriageContext(workbook=workbook, sheets=undecided, actor=f"agent:{run_id}")
    outcome = run_triage(model, ctx, max_turns=max_turns, log_step=log_step)
    for triaged in ctx.accepted:
        set_triage(ws, sid, triaged, by=ctx.actor, reason=triaged.note or "A4, header quoted")
    summary = {"classified": len(ctx.accepted), "rejected": len(ctx.rejected), "summary": outcome.final_text[:2000],
               "error": outcome.error}
    runs.finish_run(run_id=run_id, status=outcome.status, input_tokens=outcome.usage["input_tokens"],
                    output_tokens=outcome.usage["output_tokens"], cost_usd=0.0, summary=summary)
    return {"run_id": run_id, "status": outcome.status, **summary}


@router.post("/projects/{project_id}/client-data/{sid}:triage", status_code=202)
def start_triage(project_id: str, sid: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    from modeler_agents.llm import LLMConfigError, chat_model_from_env

    ws = workspace_for(project_id, principal, store)
    _workbook(ws, sid)
    try:
        model = chat_model_from_env()
    except LLMConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if model is None:
        raise HTTPException(status_code=409, detail="agents are off: say what each sheet holds by hand")
    key = (principal.tenant_id, project_id)
    with _LOCK:
        if key in _RUNNING:
            raise HTTPException(status_code=409, detail="a triage run is already in progress")
        _RUNNING.add(key)

    def job() -> None:
        try:
            run_triage_job(store, principal.tenant_id, project_id, sid, model=model)
        finally:
            with _LOCK:
                _RUNNING.discard(key)

    threading.Thread(target=job, daemon=True).start()
    return envelope({"status": "RUNNING"})


@router.get("/projects/{project_id}/client-data/{sid}/sheets/{sheet}")
def read_sheet(project_id: str, sid: str, sheet: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """One sheet as text, with a first filling of the reading form found in it (units, dose and LLOQ quoted from their
    cells; what the sheet does not say left for the person) and the notes that say what was found and what was not."""
    ws = workspace_for(project_id, principal, store)
    content, workbook = _workbook(ws, sid)
    if sheet not in workbook.sheets:
        raise HTTPException(status_code=404, detail=f"no sheet {sheet!r} in this file")
    grid = workbook.sheets[sheet]
    brief = _brief(ws)
    products = [{"name": str(p.get("name") or ""), "role": str(p.get("role") or "")} for p in _brief_products(brief)]
    category = next((t["category"] for t in content.get("triage", []) if t["sheet"] == sheet), "")
    form, notes = suggest(grid, category=category, filename=content["file"], drug=brief.drug_name if brief else "",
                          products=products)
    read = [m for m in content.get("mappings", []) if not m.get("replaced_by")
            and any(t.get("sheet") == sheet for t in m["recipe"].get("tables", []))]
    return envelope({"sheet": sheet, "rows": preview_rows(grid), "max_row": grid.max_row, "max_column": grid.max_column,
                     "category": category, "form": form.model_dump(mode="json"), "notes": notes, "products": products,
                     "read_before": [{"recipe_id": m["recipe"].get("recipe_id"), "datasets": m.get("datasets", [])}
                                     for m in read]})


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


@router.post("/projects/{project_id}/client-data/{sid}:map")
def map_sheets(project_id: str, sid: str, body: MappingBody, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """Apply a mapping recipe deterministically. Preview shows the records, problems and open questions; confirming a
    recipe with none of them creates the datasets (origin CLIENT) and keeps the recipe on the file's record."""
    from modeler_agents.data_mapping import RecipeProposal, review_proposal
    from modeler_api.project_api import blinding_view
    from modeler_project.blinding import EXTERNAL_PURPOSES

    ws = workspace_for(project_id, principal, store)
    content, workbook = _workbook(ws, sid)
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
        version = ws.latest(ArtifactKind.DATASET, old_id)
        if version is not None and version.content.get("state") != "REJECTED":
            decide_dataset(ws, old_id, state=EvidenceState.REJECTED, by=principal.user_id,
                           reason=f"replaced: {', '.join(sorted(sheets))} read again (recipe {review.recipe.recipe_id})")
    return envelope({**preview, "datasets": ids, **_view(ws)})


class ReleaseModelRequest(BaseModel):
    formulation: str = Field(min_length=1)


@router.post("/projects/{project_id}/dissolution/{profile_id}:propose", status_code=201)
def propose_release(project_id: str, profile_id: str, body: ReleaseModelRequest, principal: Writer,
                    store: StoreDep) -> dict[str, Any]:
    """Propose a profile's fit as a formulation's release model: evidence to accept or reject on the Parameters tab
    (which profile represents in vivo release is a planning decision, D-12)."""
    ws = workspace_for(project_id, principal, store)
    try:
        proposed = propose_release_model(ws, profile_id, formulation=body.formulation, by=principal.user_id)
    except DissolutionRegisterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return envelope({"evidence": [e.id for e in proposed], **_view(ws)})


class CloseRequest(BaseModel):
    note: str = ""


@router.post("/projects/{project_id}/client-data:approve")
def approve_client_data(project_id: str, body: CloseRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """Close P3: snapshot the files and the reconciliation, with a named approval."""
    ws = workspace_for(project_id, principal, store)
    matrix_version, matrix = _matrix(ws)
    try:
        close_register(ws, matrix_version.ref, matrix, by=principal.user_id, note=body.note, printed_name=principal.printed_name)
    except (ClientDataError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return envelope(_view(ws))
