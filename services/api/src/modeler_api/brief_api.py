"""P0 initiate and P1 Project Brief (plan §5.2, review layer L1; task T-41).

P0: ``POST /projects:initiate`` takes the drug name, optional context and the technical proposal (any number of PDF,
Word, Markdown, text, CSV or Excel files), creates the project, stores every file as a DOCUMENT artifact with
quotable pages, writes the brief's first version (the drug name as entered, everything else missing) and starts
the extraction. Extraction resolves the drug's identity (PubChem, RDKit cross-check) and, when an LLM provider is
configured (D-16), runs agent A1, whose every value is checked by code before it enters the brief. Without a
provider the brief is filled by hand on the same page: every step has a manual path.

P1: the brief is edited field by field (each change says why), questions are answered or accepted as limitations,
and the brief is approved by a named reviewer (D-07: a simple approval, "Reviewed") once nothing blocks it.
"""

from __future__ import annotations

import re
import threading
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from modeler_api import agent_jobs
from modeler_api.auth import Principal, require_project
from modeler_api.config import SettingsDep
from modeler_api.deps import Reader, StoreDep, Writer, impact_view, version_view, workspace_for
from modeler_api.responses import answers, envelope
from modeler_api.views.brief import (
    AgentRunDetail,
    BriefImpact,
    BriefPage,
    DocumentPage,
    Documents,
    ExtractionStart,
    ProjectStarted,
)
from modeler_intake.documents import DocumentError
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import (
    BriefPathError,
    FieldStatus,
    ProjectBrief,
    catalog,
    empty_brief,
    remove_item,
    validate_brief,
)
from modeler_project.brief_ops import BRIEF_ID, EditError, edit_field, locked, resolve_identity, save_brief, summary
from modeler_project.documents import DocumentLibrary
from modeler_storage.filestore import FileReadStore, FileWriteStore

router = APIRouter(prefix="/api/v1", tags=["brief"])

_RUNNING: set[tuple[str, str]] = set()
_RUNNING_LOCK = threading.Lock()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or f"project-{uuid.uuid4().hex[:8]}"


def _file_stores(settings: SettingsDep) -> tuple[FileReadStore, FileWriteStore]:
    if not settings.read_root:
        raise HTTPException(status_code=503, detail="Storage is not configured. Set MODELER_READ_ROOT.")
    return FileReadStore(settings.read_root), FileWriteStore(settings.read_root)


ProjectsDep = Annotated[tuple[FileReadStore, FileWriteStore], Depends(_file_stores)]


def _brief(ws: Workspace) -> ProjectBrief | None:
    version = ws.latest(ArtifactKind.BRIEF, BRIEF_ID)
    return ProjectBrief.from_content(version.content) if version else None


def _document_refs(ws: Workspace):
    return [v.ref for v in ws.list(ArtifactKind.DOCUMENT)]


def _document_view(version) -> dict[str, Any]:
    c = version.content
    return {"id": version.id, "sha256": c["sha256"], "name": c["name"], "kind": c["kind"], "role": c["role"],
            "n_pages": c["n_pages"], "size_bytes": c["size_bytes"], "warnings": c.get("warnings", []),
            "uploaded_at": version.created_at.isoformat(), "uploaded_by": version.created_by}


# --- extraction (identity + agent A1), in the background ------------------------------------------------------


def _merge_agent_result(latest: ProjectBrief, produced: ProjectBrief, paths: list[str]) -> ProjectBrief:
    """Apply the agent's accepted fields onto the latest brief, skipping any a person locked meanwhile."""
    from modeler_project.brief import set_record

    merged = latest
    for path in dict.fromkeys(paths):
        if locked(merged, path):
            continue
        try:
            merged = set_record(merged, path, produced.get(path))
        except BriefPathError:
            continue
    known = {(q.field, q.question) for q in merged.questions}
    extra = tuple(q for q in produced.questions if (q.field, q.question) not in known)
    return merged.model_copy(update={"questions": (*merged.questions, *extra)})


def run_extraction(store: ProjectStore, tenant_id: str, project_id: str, *, by: str, context_note: str = "",
                   model=None, fetch_identity=None, max_turns: int = 80) -> dict[str, Any]:
    """Resolve identity and (with a model) run A1; commit the result as the brief's next version. Returns a summary."""
    from modeler_project.identity import fetch_pubchem

    ws = Workspace(store, tenant_id, project_id)
    library = DocumentLibrary(ws)
    start = _brief(ws)
    if start is None:
        raise RuntimeError("no brief to extract into")

    def store_record(record) -> str:
        return library.add_text(record.text, f"pubchem-{_slug(record.query)}.txt", role="retrieved_record",
                                by="system").content["sha256"]

    brief, notes = resolve_identity(start, store_record=store_record, by="system", fetch=fetch_identity or fetch_pubchem)
    accepted_paths = [p for p in ("drug.pubchem_cid", "drug.smiles", "drug.inchikey", "drug.mw_free_base")
                      if brief.get(p) != start.get(p)]
    result: dict[str, Any] = {"identity_notes": notes, "run_id": None, "status": "IDENTITY_ONLY"}
    actor = "system"
    if model is not None:
        run = agent_jobs.AgentRun(getattr(store, "root", None), tenant_id=tenant_id, project_id=project_id,
                                  agent="A1-proposal-intake", model=model, max_turns=max_turns)
        outcome = agent_jobs.proposal_intake(model, library=library, brief=brief, actor=run.actor,
                                             context_note=context_note, max_turns=max_turns, log_step=run.log_step)
        run.finish(outcome, {"accepted": len(outcome.accepted), "rejected": len(outcome.rejected),
                             "summary": outcome.summary[:4000], "error": outcome.error})
        brief = outcome.brief
        accepted_paths += [a["path"] for a in outcome.accepted]
        actor = run.actor
        result.update(run_id=run.run_id, status=outcome.status, accepted=len(outcome.accepted),
                      rejected=len(outcome.rejected))
    latest = _brief(ws) or start
    merged = _merge_agent_result(latest, brief, accepted_paths)
    reason = (f"extracted by A1 ({result.get('accepted', 0)} fields accepted, {result.get('rejected', 0)} rejected)"
              if model is not None else "drug identity resolved")
    version = save_brief(ws, merged, actor=actor, reason=reason, derived_from=_document_refs(ws))
    result["brief_version"] = version.version
    return result


def _start_extraction(store: ProjectStore, principal: Principal, project_id: str, context_note: str) -> dict[str, Any]:
    model, problem = agent_jobs.chat_model()
    if model is None and problem is None:
        problem = "agents are off: identity resolved; fill the rest of the brief by hand"
    key = (principal.tenant_id, project_id)
    with _RUNNING_LOCK:
        if key in _RUNNING:
            raise HTTPException(status_code=409, detail="an extraction is already running for this project")
        _RUNNING.add(key)

    def job() -> None:
        try:
            run_extraction(store, principal.tenant_id, project_id, by=principal.user_id, context_note=context_note,
                           model=model)
        finally:
            with _RUNNING_LOCK:
                _RUNNING.discard(key)

    threading.Thread(target=job, name=f"extract-{project_id}", daemon=True).start()
    return {"started": True, "agents": model is not None, "problem": problem}


# --- P0 ------------------------------------------------------------------------------------------------------


@router.post("/projects:initiate", status_code=201, **answers(ProjectStarted))
async def initiate_project(
    principal: Writer, store: StoreDep, projects: ProjectsDep,
    drug_name: Annotated[str, Form(min_length=1)],
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI's form-file default
    name: Annotated[str, Form()] = "",
    context: Annotated[str, Form()] = "",
    extract: Annotated[bool, Form()] = True,
) -> dict[str, Any]:
    """P0: create the project from the drug name and the technical proposal, then start the extraction."""
    read, write = projects
    title = name.strip() or f"{drug_name.strip()} PBPK"
    project_id = _slug(title)
    if read.get_project(principal.tenant_id, project_id) is not None:
        project_id = f"{project_id}-{uuid.uuid4().hex[:4]}"
    payloads = [(f.filename or "upload", await f.read()) for f in files]
    if not payloads and not context.strip():
        raise HTTPException(status_code=422, detail="upload the technical proposal (or at least describe the project)")
    ws = Workspace(store, principal.tenant_id, project_id)
    library = DocumentLibrary(ws)
    documents = []
    try:
        for filename, data in payloads:
            documents.append(library.add(data, filename, role="proposal", by=principal.user_id))
        if context.strip():
            documents.append(library.add_text(context.strip(), "project-context.md", role="context", by=principal.user_id,
                                              note="typed at project start"))
    except DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    write.put_project(principal.tenant_id, {"id": project_id, "name": title, "compounds": [drug_name.strip()],
                                            "openQuestions": 0, "risk": "medium", "questions": [], "pipeline": True})
    brief = empty_brief(drug_name, by=principal.user_id)
    version = save_brief(ws, brief, actor=principal.user_id, reason="project started",
                         derived_from=[d.ref for d in documents])
    extraction = _start_extraction(store, principal, project_id, context.strip()) if extract else None
    return envelope({"project_id": project_id, "name": title, "documents": [_document_view(d) for d in documents],
                     "brief_version": version.version, "extraction": extraction})


# --- documents -----------------------------------------------------------------------------------------------


@router.post("/projects/{project_id}/documents", status_code=201, **answers(Documents))
async def upload_documents(project_id: str, principal: Writer, store: StoreDep,
                           files: Annotated[list[UploadFile], File()],
                           role: Annotated[str, Form()] = "proposal") -> dict[str, Any]:
    if role not in ("proposal", "annex", "context", "client_file", "paper", "other"):
        raise HTTPException(status_code=422, detail=f"unknown document role {role!r}")
    ws = workspace_for(project_id, principal, store)
    library = DocumentLibrary(ws)
    added = []
    try:
        for f in files:
            added.append(library.add(await f.read(), f.filename or "upload", role=role, by=principal.user_id))  # type: ignore[arg-type]
    except DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return envelope({"documents": [_document_view(d) for d in added]})


@router.get("/projects/{project_id}/documents", **answers(Documents))
def list_documents(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    return envelope({"documents": [_document_view(d) for d in DocumentLibrary(ws).documents()]})


@router.get("/projects/{project_id}/documents/{sha256}/pages/{page}", **answers(DocumentPage))
def document_page(project_id: str, sha256: str, page: int, principal: Reader, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    library = DocumentLibrary(ws)
    version = library.by_sha(sha256)
    text = library.page_text(sha256, page)
    if version is None or text is None:
        raise HTTPException(status_code=404, detail="no such document page")
    return envelope({"sha256": sha256, "name": version.content["name"], "page": page, "n_pages": version.content["n_pages"],
                     "text": text})


@router.get("/projects/{project_id}/documents/{sha256}/raw")
def document_raw(project_id: str, sha256: str, principal: Reader, store: StoreDep):
    ws = workspace_for(project_id, principal, store)
    version = DocumentLibrary(ws).by_sha(sha256)
    path = store.blob_path(principal.tenant_id, project_id, sha256) if version else None
    if path is None:
        raise HTTPException(status_code=404, detail="no such document")
    return FileResponse(path, media_type=version.content["media_type"], filename=version.content["name"])


# --- the brief -----------------------------------------------------------------------------------------------


def _brief_view(ws: Workspace) -> dict[str, Any]:
    version = ws.latest(ArtifactKind.BRIEF, BRIEF_ID)
    if version is None:
        raise HTTPException(status_code=404, detail="this project has no brief yet (start it from a technical proposal)")
    brief = ProjectBrief.from_content(version.content)
    issues = validate_brief(brief)
    runs = agent_jobs.project_runs(getattr(ws.store, "root", None), ws.tenant_id, ws.project_id)
    return {
        "artifact": version_view(ws, version, with_content=False), "brief": brief.to_content(),
        "issues": [{"code": i.code, "path": i.path, "message": i.message} for i in issues],
        "blocking": len(issues), "summary": summary(brief), "catalog": catalog(),
        "agents": agent_jobs.agents_status(), "extraction_running": (ws.tenant_id, ws.project_id) in _RUNNING,
        "runs": [{k: r.get(k) for k in ("run_id", "agent", "status", "provider", "model", "started_at", "finished_at",
                                         "summary")} for r in runs[:5]],
    }


@router.get("/projects/{project_id}/brief", **answers(BriefPage))
def get_brief(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope(_brief_view(workspace_for(project_id, principal, store)))


class ExtractRequest(BaseModel):
    context_note: str = ""


@router.post("/projects/{project_id}/brief:extract", status_code=202, **answers(ExtractionStart))
def extract_brief(project_id: str, body: ExtractRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    if ws.latest(ArtifactKind.BRIEF, BRIEF_ID) is None:
        raise HTTPException(status_code=404, detail="no brief to extract into")
    return envelope(_start_extraction(store, principal, project_id, body.context_note))


class FieldChange(BaseModel):
    path: str = Field(min_length=1)
    status: Literal["EDITED", "CONFIRMED", "NOT_APPLICABLE", "MISSING"]
    value: Any = None
    unit: str | None = None
    note: str = ""


class BriefEdit(BaseModel):
    changes: list[FieldChange] = Field(min_length=1)
    reason: str = Field(min_length=1)
    preview: bool = False


def _apply_changes(brief: ProjectBrief, changes: list[FieldChange], by: str) -> ProjectBrief:
    for change in changes:
        try:
            brief = edit_field(brief, change.path, value=change.value, unit=change.unit, status=FieldStatus(change.status),
                               note=change.note or "", by=by)
        except (EditError, BriefPathError) as exc:
            raise HTTPException(status_code=422, detail=f"{change.path}: {exc}") from exc
    return brief


@router.put("/projects/{project_id}/brief", **answers(BriefPage | BriefImpact))
def edit_brief(project_id: str, body: BriefEdit, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """Change fields (each change says why). With ``preview`` the impact is returned and nothing is saved."""
    ws = workspace_for(project_id, principal, store)
    current = _brief(ws)
    if current is None:
        raise HTTPException(status_code=404, detail="no brief")
    updated = _apply_changes(current, body.changes, principal.user_id)
    if body.preview:
        return envelope({"impact": impact_view(ws.impact(ArtifactKind.BRIEF, BRIEF_ID, updated.to_content()))})
    save_brief(ws, updated, actor=principal.user_id, reason=body.reason)
    return envelope(_brief_view(ws))


class ItemRemoval(BaseModel):
    group: str
    index: int = Field(ge=0)
    reason: str = Field(min_length=1)


@router.post("/projects/{project_id}/brief/items:remove", **answers(BriefPage))
def remove_brief_item(project_id: str, body: ItemRemoval, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    current = _brief(ws)
    try:
        updated = remove_item(current, body.group, body.index)
    except BriefPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    save_brief(ws, updated, actor=principal.user_id, reason=body.reason)
    return envelope(_brief_view(ws))


class QuestionAnswer(BaseModel):
    answer: str = ""
    status: Literal["answered", "accepted_as_limitation", "open"] = "answered"


@router.post("/projects/{project_id}/brief/questions/{question_id}", **answers(BriefPage))
def answer_question(project_id: str, question_id: str, body: QuestionAnswer, principal: Writer,
                    store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    current = _brief(ws)
    if current is None or not any(q.id == question_id for q in current.questions):
        raise HTTPException(status_code=404, detail="no such question")
    if body.status != "open" and not body.answer.strip():
        raise HTTPException(status_code=422, detail="give the answer, or the reason it is accepted as a limitation")
    questions = tuple(q.model_copy(update={"answer": body.answer.strip(), "status": body.status})
                      if q.id == question_id else q for q in current.questions)
    updated = current.model_copy(update={"questions": questions})
    save_brief(ws, updated, actor=principal.user_id, reason=f"question {question_id} {body.status.replace('_', ' ')}")
    return envelope(_brief_view(ws))


class Approval(BaseModel):
    note: str = ""


@router.post("/projects/{project_id}/brief:approve", **answers(BriefPage))
def approve_brief(project_id: str, body: Approval, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """L1 gate (D-07: a named approval, meaning "Reviewed"): refused while anything blocks the brief."""
    ws = workspace_for(project_id, principal, store)
    version = ws.latest(ArtifactKind.BRIEF, BRIEF_ID)
    if version is None:
        raise HTTPException(status_code=404, detail="no brief")
    issues = validate_brief(ProjectBrief.from_content(version.content))
    if issues:
        raise HTTPException(status_code=409, detail={"code": "BRIEF_NOT_READY", "issues": [
            {"code": i.code, "path": i.path, "message": i.message} for i in issues]})
    try:
        ws.approve(version.ref, by=principal.user_id, printed_name=principal.printed_name, meaning="Reviewed",
                   note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # The data plan follows from the approved brief (plan §5.2 P1): derived at once, reviewed on the next tab.
    from modeler_project.data_plan import derive_data_plan

    derive_data_plan(ws, actor="system", reason="derived from the approved brief")
    return envelope(_brief_view(ws))


# --- agent runs ----------------------------------------------------------------------------------------------


@router.get("/projects/{project_id}/agent-runs/{run_id}", **answers(AgentRunDetail))
def get_agent_run(project_id: str, run_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    require_project(project_id, principal)
    root = getattr(store, "root", "")
    try:
        record = agent_jobs.run_record(root, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such agent run") from exc
    if record.get("project_id") != project_id or record.get("tenant_id") != principal.tenant_id:
        raise HTTPException(status_code=404, detail="no such agent run")
    return envelope({"run": record, "steps": agent_jobs.run_steps(root, run_id)})

