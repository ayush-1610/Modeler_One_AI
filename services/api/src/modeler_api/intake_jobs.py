"""The client's files read in the background when they arrive (plan 2026-11-05 §3.1), by the reading agent (A4) when
agents are on, one file after the other in one `reading` job. A service, not a router: the client-data upload and the
project's start both start it. Code reads each data sheet at once, on arrival (`modeler_project.sheet_intake`); the
agent then does what code could not:
- each PDF or Word file, read for its data (I4, build C2);
- the sheets code could not sort, sorted with a header quote, then read by code like the others;
- each sheet whose code reading has a problem, read again by the agent: its reading replaces code's only when its check
  is clean, and is saved at once when nothing is left to ask (`sheet_intake.adopt_agent_reading`).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from modeler_api import agent_jobs, jobs
from modeler_intake.grid import read_workbook_bytes
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.client_data import READABLE_DOCUMENTS, ClientDataError, set_triage, submission
from modeler_project.documents import DocumentLibrary
from modeler_project.sheet_intake import (
    READ,
    adopt_agent_reading,
    agent_could_not,
    has_problem,
    products_of,
    read_on_arrival,
)


def run_document_job(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, model,
                     max_turns: int = 30) -> dict[str, Any]:
    """A4 reads one client PDF or Word file for project data (plan 2026-11-03 §3.4, I4): study facts, profiles, NCA
    tables, dissolution profiles and links between two names of a study, each quoted and checked by code. What code
    accepted is recorded on the file and waits on Inputs, in its study or product, until a person confirms it."""
    ws = Workspace(store, tenant_id, project_id)
    if submission(ws, sid) is None:
        raise ClientDataError(f"no client file {sid}")
    version = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(version.content) if version else None
    run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                              agent="A4-document-reading", model=model, max_turns=max_turns)
    ctx, outcome = agent_jobs.document_reading(model, ws=ws, library=DocumentLibrary(ws), sid=sid,
                                               drug=brief.drug_name if brief else "", actor=run.actor, run_id=run.run_id,
                                               max_turns=max_turns, log_step=run.log_step)
    summary = {"datasets": len(ctx.datasets), "facts": len(ctx.facts), "dissolution_rows": len(ctx.dissolution),
               "links": len(ctx.links), "refused": len(ctx.refused), "summary": outcome.final_text[:2000],
               "error": outcome.error}
    run.finish(outcome, summary)
    return {"run_id": run.run_id, "status": outcome.status, **summary}


def undecided_sheets(content: dict[str, Any]) -> list[str]:
    """The sheets code could not sort (left "other" by code), for the agent to sort."""
    return [t["sheet"] for t in content.get("triage", []) if t["category"] == "OTHER" and t.get("by") == "code"]


def problem_sheets(content: dict[str, Any]) -> list[str]:
    """The data sheets code read on arrival whose reading has a problem, not saved yet, the agent not tried yet."""
    read = {t.get("sheet") for m in content.get("mappings", []) if not m.get("replaced_by") for t in m["recipe"].get("tables", [])}
    return [sheet for sheet, d in (content.get("readings") or {}).items()
            if d.get("by") == "code" and sheet not in read and not d.get("agent_tried") and has_problem(d)]


def _needs_agent(content: dict[str, Any]) -> bool:
    if content.get("repeat"):
        return False
    if content.get("kind") in READABLE_DOCUMENTS:
        return not content.get("document_reads")
    return not content.get("template") and bool(undecided_sheets(content) or problem_sheets(content))


def run_arrival_job(store: ProjectStore, tenant_id: str, project_id: str, sid: str, *, model) -> dict[str, Any]:
    """What the agent does for one file that has arrived: a document read for its data; a workbook's sheets sorted where
    code could not, then each sheet whose code reading has a problem read again. Each run is logged like any agent run."""
    ws = Workspace(store, tenant_id, project_id)
    content = submission(ws, sid)
    if content is None:
        raise ClientDataError(f"no client file {sid}")
    if content.get("kind") in READABLE_DOCUMENTS:
        return run_document_job(store, tenant_id, project_id, sid, model=model)
    path = ws.store.blob_path(tenant_id, project_id, content["sha256"])
    if content.get("template") or path is None:
        return {"status": "COMPLETED", "sorted": 0, "read": []}
    workbook = read_workbook_bytes(path.read_bytes(), content["file"])
    version = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(version.content) if version else None
    drug, products, library = brief.drug_name if brief else "", products_of(brief), DocumentLibrary(ws)
    out: dict[str, Any] = {"status": "COMPLETED", "sorted": 0, "read": []}
    if undecided := undecided_sheets(content):
        run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                                  agent="A4-sheet-triage", model=model, max_turns=6)
        ctx, outcome = agent_jobs.sheet_triage(model, workbook=workbook, sheets=undecided, actor=run.actor, max_turns=6,
                                               log_step=run.log_step)
        for triaged in ctx.accepted:
            set_triage(ws, sid, triaged, by=ctx.actor, reason=triaged.note or "A4, header quoted")
        run.finish(outcome, {"classified": len(ctx.accepted), "rejected": len(ctx.rejected), "error": outcome.error})
        out["sorted"] = len(ctx.accepted)
        if data := [t.sheet for t in ctx.accepted if t.category.value in READ]:    # read by code, as on arrival
            read_on_arrival(ws, library, sid, workbook, by=run.actor, drug=drug, products=products, sheets=data)
    content = submission(ws, sid) or content
    categories = {t["sheet"]: t["category"] for t in content.get("triage", [])}
    for sheet in problem_sheets(content):
        run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                                  agent="A4-sheet-reading", model=model, max_turns=8)
        reading = agent_jobs.sheet_reading(model, workbook=workbook, sheet=sheet, drug=drug, actor=run.actor,
                                           category=categories.get(sheet, ""), products=products, max_turns=8,
                                           log_step=run.log_step)
        if reading.form is not None:
            result = adopt_agent_reading(ws, library, sid, workbook, sheet, reading.form, reading.notes, by=run.actor,
                                         run_id=run.run_id)
        else:                             # no reading code accepted: code's draft stays, marked as tried
            agent_could_not(ws, sid, sheet, content["readings"][sheet], by=run.actor, run_id=run.run_id,
                            why="it proposed no reading code accepts")
            result = {"adopted": False, "saved": []}
        run.finish(reading.outcome, {"sheet": sheet, **result, "refused": len(reading.rejected), "error": reading.outcome.error})
        out["read"].append({"sheet": sheet, "run_id": run.run_id, **result})
    return out


def read_later(store: ProjectStore, tenant_id: str, project_id: str, sids: list[str], *, by: str) -> bool:
    """The agent's part for the files that have just arrived (`run_arrival_job`), in the background, one file after the
    other, started by the person `by` who added them; False when agents are off, nothing needs the agent, or a reading is running already (then each file keeps its
    buttons: "Read the data in this file", "Sort the sheets", "Read this sheet")."""
    model, _problem = agent_jobs.chat_model("A4")
    if model is None or not sids:
        return False
    ws = Workspace(store, tenant_id, project_id)
    todo = [sid for sid in dict.fromkeys(sids) if (content := submission(ws, sid)) is not None and _needs_agent(content)]
    if not todo:
        return False

    def job() -> None:
        for sid in todo:
            run_arrival_job(store, tenant_id, project_id, sid, model=model)

    try:
        jobs.start(store, tenant_id, project_id, "reading", job, by=by, busy="a reading run is already in progress",
                   name=f"arrival-{project_id}")
    except HTTPException:
        return False
    return True
