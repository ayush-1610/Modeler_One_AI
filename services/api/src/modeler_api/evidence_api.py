"""P2 literature evidence (plan §5.2, review layer L2a; T-44).

`POST /evidence:research` runs agent A2 in the background on the data plan's literature items (and the client items
flagged for a cross-check). A person can also propose a value by hand (the manual path, same checks and grade). Each
proposal is accepted or rejected with a reason; the phase closes when every required literature item has accepted
evidence or is recorded as not available, and the register snapshot is approved (named approval, D-07).
"""

from __future__ import annotations

import threading
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from modeler_api.brief_api import agents_status
from modeler_api.project_api import Reader, StoreDep, Writer, version_view, workspace_for
from modeler_api.responses import envelope
from modeler_intake.documents import DocumentError
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceItem, EvidenceState, Extraction, SourceRef, SourceType, new_id
from modeler_project.evidence_register import (
    REGISTER_LITERATURE,
    EvidenceError,
    blocking,
    close_register,
    coverage,
    decide,
    fulfil_access,
    items,
    propose,
)
from modeler_project.requirements import RequirementMatrix, literature_items

router = APIRouter(prefix="/api/v1", tags=["evidence"])
_RUNNING: set[tuple[str, str]] = set()
_LOCK = threading.Lock()


def _matrix(ws: Workspace) -> tuple[Any, RequirementMatrix]:
    version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    if version is None:
        raise HTTPException(status_code=409, detail="derive and approve the data plan first (P1)")
    return version, RequirementMatrix.from_content(version.content)


def _evidence_view(item: EvidenceItem) -> dict[str, Any]:
    return item.model_dump(mode="json")


def _view(ws: Workspace) -> dict[str, Any]:
    matrix_version, matrix = _matrix(ws)
    evidence = items(ws)
    rows = coverage(matrix, evidence)
    register = ws.latest(ArtifactKind.EVIDENCE, REGISTER_LITERATURE)
    from modeler_agents.run_store import FileRunStore

    root = getattr(ws.store, "root", None)
    runs = [r for r in (FileRunStore(root).runs(ws.tenant_id, project_id=ws.project_id) if root else [])
            if r["agent"].startswith("A2")]
    return {
        "data_plan": {"version": matrix_version.version, "status": ws.status(matrix_version).value},
        "evidence": [_evidence_view(e) for e in evidence],
        "coverage": [r.__dict__ | {"accepted": list(r.accepted), "proposed": list(r.proposed)} for r in rows],
        "blocking": [r.req_id for r in blocking(rows)],
        "access_requests": [{"id": v.id, **v.content} for v in ws.list(ArtifactKind.ACCESS_REQUEST)],
        "register": version_view(ws, register, with_content=False) if register else None,
        "agents": agents_status(), "running": (ws.tenant_id, ws.project_id) in _RUNNING,
        "runs": [{k: r.get(k) for k in ("run_id", "status", "model", "started_at", "finished_at", "summary")} for r in runs[:5]],
    }


@router.get("/projects/{project_id}/evidence")
def get_evidence(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    return envelope(_view(workspace_for(project_id, principal, store)))


def run_research_job(store: ProjectStore, tenant_id: str, project_id: str, *, model, europe_pmc=None,
                     max_turns: int = 120) -> dict[str, Any]:
    from modeler_agents.evidence_agent import ResearchContext, run_research
    from modeler_agents.run_store import FileRunStore
    from modeler_agents.sources import EuropePMC

    ws = Workspace(store, tenant_id, project_id)
    _, matrix = _matrix(ws)
    brief_version = ws.latest(ArtifactKind.BRIEF, "main")
    drug = ProjectBrief.from_content(brief_version.content).drug_name if brief_version else project_id
    runs = FileRunStore(store.root, project_id=project_id)  # type: ignore[attr-defined]
    run_id = runs.start_run(tenant_id=tenant_id, agent="A2-literature", provider=model.provider, model=model.model,
                            campaign_id=None, budget={"max_turns": max_turns})
    seq = [0]

    def log_step(step: dict[str, Any]) -> None:
        seq[0] += 1
        runs.record_step(run_id=run_id, seq=seq[0], kind=step.get("type", "step"), content=step, usage=step.get("usage", {}))

    ctx = ResearchContext(ws=ws, library=DocumentLibrary(ws), requirements=literature_items(matrix), actor=f"agent:{run_id}",
                          europe_pmc=europe_pmc or EuropePMC())
    outcome = run_research(model, ctx, drug=drug, max_turns=max_turns, log_step=log_step)
    summary = {"proposed": len(outcome.proposed), "rejected": len(outcome.rejected), "not_found": outcome.not_found,
               "access_requests": len(outcome.access_requests), "summary": outcome.summary[:4000], "error": outcome.error}
    runs.finish_run(run_id=run_id, status=outcome.status, input_tokens=outcome.usage["input_tokens"],
                    output_tokens=outcome.usage["output_tokens"], cost_usd=0.0, summary=summary)
    return {"run_id": run_id, "status": outcome.status, **summary}


@router.post("/projects/{project_id}/evidence:research", status_code=202)
def start_research(project_id: str, principal: Writer, store: StoreDep) -> dict[str, Any]:
    from modeler_agents.llm import LLMConfigError, chat_model_from_env

    ws = workspace_for(project_id, principal, store)
    _matrix(ws)
    try:
        model = chat_model_from_env()
    except LLMConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if model is None:
        raise HTTPException(status_code=409, detail="agents are off: enter the evidence by hand (Add a value)")
    key = (principal.tenant_id, project_id)
    with _LOCK:
        if key in _RUNNING:
            raise HTTPException(status_code=409, detail="a literature run is already in progress")
        _RUNNING.add(key)

    def job() -> None:
        try:
            run_research_job(store, principal.tenant_id, project_id, model=model)
        finally:
            with _LOCK:
                _RUNNING.discard(key)

    threading.Thread(target=job, name=f"research-{project_id}", daemon=True).start()
    return envelope({"started": True, "provider": model.provider, "model": model.model})


class ManualEvidence(BaseModel):
    req_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    value: float | str
    unit: str | None = None
    source_type: SourceType
    quote: str = ""
    doc_sha256: str | None = None
    page: int | None = None
    locator: str = ""
    title: str = ""
    authors: str = ""
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None
    conditions: dict[str, str] = Field(default_factory=dict)
    note: str = ""


@router.post("/projects/{project_id}/evidence", status_code=201)
def add_evidence(project_id: str, body: ManualEvidence, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """The manual path: a person enters a value with its source. A quote from a stored document is checked verbatim."""
    from modeler_agents.citations import quote_appears_in, value_stated_in_quote

    ws = workspace_for(project_id, principal, store)
    _, matrix = _matrix(ws)
    requirement = matrix.get(body.req_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail=f"no requirement {body.req_id}")
    stated = None
    if body.doc_sha256:
        page = DocumentLibrary(ws).page_text(body.doc_sha256, body.page or 1)
        if page is None:
            raise HTTPException(status_code=422, detail="no such document page")
        if not quote_appears_in(page, body.quote):
            raise HTTPException(status_code=422, detail="the quote is not on that page (copy it exactly, ≥ 12 characters)")
        stated = value_stated_in_quote(float(body.value), body.quote) if isinstance(body.value, float) else None
    elif body.source_type not in (SourceType.ASSUMPTION, SourceType.PREDICTED) and not (body.doi or body.pmid or body.url):
        raise HTTPException(status_code=422, detail="cite the source: a stored document page, a DOI, a PMID or a URL")
    item = EvidenceItem(
        id=new_id(), req_id=body.req_id, target=body.target, value=body.value, unit=body.unit, source_type=body.source_type,
        source=SourceRef(doc_sha256=body.doc_sha256, page=body.page, locator=body.locator, title=body.title,
                         authors=body.authors, year=body.year, doi=body.doi, pmid=body.pmid, url=body.url),
        quote=body.quote, extraction=Extraction.MANUAL, conditions=body.conditions,
        purpose=requirement.purpose or "model_building", provider="CLIENT" if requirement.provider == "CLIENT" else "LITERATURE",
        note=body.note)
    stored = propose(ws, item, actor=principal.user_id, requirement=requirement, value_in_quote=stated)
    return envelope(_evidence_view(stored))


class Decision(BaseModel):
    state: Literal["ACCEPTED", "REJECTED", "PROPOSED"]
    reason: str = Field(min_length=1)
    value_pksim: float | None = None
    unit_pksim: str | None = None


@router.post("/projects/{project_id}/evidence/{evidence_id}:decide")
def decide_evidence(project_id: str, evidence_id: str, body: Decision, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    try:
        decide(ws, evidence_id, state=EvidenceState(body.state), reason=body.reason, by=principal.user_id,
               value_pksim=body.value_pksim, unit_pksim=body.unit_pksim)
    except EvidenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return envelope(_view(ws))


class CloseRequest(BaseModel):
    note: str = ""


@router.post("/projects/{project_id}/evidence:approve")
def approve_evidence(project_id: str, body: CloseRequest, principal: Writer, store: StoreDep) -> dict[str, Any]:
    ws = workspace_for(project_id, principal, store)
    matrix_version, matrix = _matrix(ws)
    try:
        close_register(ws, matrix_version.ref, matrix, by=principal.user_id, note=body.note,
                       printed_name=principal.printed_name)
    except (EvidenceError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return envelope(_view(ws))


@router.post("/projects/{project_id}/access-requests/{request_id}:fulfil")
async def fulfil_request(project_id: str, request_id: str, principal: Writer, store: StoreDep,
                         file: Annotated[UploadFile, File()], note: Annotated[str, Form()] = "") -> dict[str, Any]:
    """A person supplies the paper the agent asked for; it is stored as a citable document."""
    ws = workspace_for(project_id, principal, store)
    try:
        doc = DocumentLibrary(ws).add(await file.read(), file.filename or "paper.pdf", role="paper", by=principal.user_id,
                                      note=note or f"supplied for {request_id}")
        fulfil_access(ws, request_id, doc_sha256=doc.content["sha256"], by=principal.user_id)
    except (DocumentError, EvidenceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return envelope(_view(ws))
