"""The client's files read in the background when they arrive (plan 2026-11-05 §3.1, build C2): each PDF or Word file
by the reading agent (A4), when agents are on, one after the other in one `reading` job. A service, not a router: the
client-data upload and the project's start both start it. Its sheets are read by code at once, on arrival
(`modeler_project.sheet_intake`); a document needs the agent.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from modeler_api import agent_jobs, jobs
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.client_data import READABLE_DOCUMENTS, ClientDataError, submission
from modeler_project.documents import DocumentLibrary


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


def unread_documents(read: list[dict[str, Any]]) -> list[str]:
    """The newly stored PDF and Word files no reading has read yet."""
    return [r["id"] for r in read if r.get("id") and r.get("kind") in READABLE_DOCUMENTS and not r.get("document_reads")
            and not r.get("repeat")]


def read_documents_later(store: ProjectStore, tenant_id: str, project_id: str, sids: list[str]) -> bool:
    """Read the files by A4 in the background, one after the other; False when agents are off, there is nothing to
    read, or a reading is running already (then each file keeps its "Read the data in this file" button)."""
    model, _problem = agent_jobs.chat_model()
    if model is None or not sids:
        return False

    def job() -> None:
        for sid in sids:
            run_document_job(store, tenant_id, project_id, sid, model=model)

    try:
        jobs.start(store, tenant_id, project_id, "reading", job, busy="a reading run is already in progress",
                   name=f"documents-{project_id}")
    except HTTPException:
        return False
    return True
