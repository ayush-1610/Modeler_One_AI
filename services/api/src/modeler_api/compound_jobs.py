"""The compound's values in the background (plan 2026-11-05 §3.3, build B): the free structured sources by code, then
the literature agent on what is still missing. Started at the project's start (`projects:initiate`) and by "Search the
sources and the literature" on Inputs; one `research` job per project at a time. A service, not a router: the brief's
and the evidence's routers both start it.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import HTTPException

from modeler_api import agent_jobs, jobs
from modeler_project import ArtifactKind, ProjectStore, Workspace
from modeler_project.brief import ProjectBrief
from modeler_project.brief_ops import BRIEF_ID, save_brief
from modeler_project.documents import DocumentLibrary
from modeler_project.inputs import refresh_inputs
from modeler_project.requirements import RequirementMatrix, literature_items
from modeler_project.start_drafts import read_disposition

_log = logging.getLogger(__name__)


def _follow_inputs(ws: Workspace, *, by: str) -> None:
    """Assemble the inputs again when they have begun. Before (the job started with the project, while Start waits on
    the person) the values are only stored: Inputs stays blocked until Start is done (decision 7 of 2026-10-29), and the
    Inputs page assembles them when the person opens it."""
    if ws.latest(ArtifactKind.READINESS, "main") is not None:
        refresh_inputs(ws, by=by)


def _disposition_on_start(ws: Workspace, *, by: str) -> list[str]:
    """The drug's disposition drafted on Start from the FDA label just stored, for the fields still empty (the
    proposal's reading may have finished before the label was stored; the owner, 2026-11-07). Drafts only: a person
    confirms each on Start."""
    with ws.editing(ArtifactKind.BRIEF, BRIEF_ID):
        version = ws.latest(ArtifactKind.BRIEF, BRIEF_ID)
        if version is None:
            return []
        brief, drafted = read_disposition(DocumentLibrary(ws, for_agents=True), ProjectBrief.from_content(version.content),
                                          by=by)
        if drafted:
            save_brief(ws, brief, actor=by, reason=f"the drug's disposition drafted by code ({', '.join(drafted)})")
    return drafted


def _matrix(ws: Workspace) -> tuple[Any, RequirementMatrix]:
    version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    if version is None:
        raise HTTPException(status_code=409, detail="this project has no data checklist yet: it is derived from the brief "
                                                    "at Start")
    return version, RequirementMatrix.from_content(version.content)


class CodeRunner:
    """What a run record names for the structured sources: code, not a model."""

    provider, model = "code", "structured sources (no AI)"


SOURCES_AGENT = "A2-sources"
AUTO_TURNS = 60      # the literature agent's budget when it starts on its own, at the project's start


def run_sources_job(store: ProjectStore, tenant_id: str, project_id: str) -> dict[str, Any]:
    """The compound's values from PubChem, the FDA label and ChEMBL, by code in seconds (plan 2026-11-05 §3.3),
    recorded as a run like the agents' so the Inputs page can show what each source gave."""
    ws = Workspace(store, tenant_id, project_id)
    _, matrix = _matrix(ws)
    brief_version = ws.latest(ArtifactKind.BRIEF, "main")
    drug = ProjectBrief.from_content(brief_version.content).drug_name if brief_version else project_id
    run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                              agent=SOURCES_AGENT, model=CodeRunner(), max_turns=0)
    outcome = agent_jobs.compound_sources(ws=ws, library=DocumentLibrary(ws), requirements=literature_items(matrix),
                                         drug=drug, actor=run.actor, log_step=run.log_step)
    run.finish(outcome, outcome.summary())
    _follow_inputs(ws, by=run.actor)   # the values flow into the inputs (D-27)
    drafted = _disposition_on_start(ws, by="code:start-reading")
    return {"run_id": run.run_id, "status": outcome.status, **outcome.summary(), "drafted_on_start": drafted}


def run_compound_job(store: ProjectStore, tenant_id: str, project_id: str, *, model, max_turns: int = 120) -> None:
    """The structured sources first (seconds), then, with a model, the literature agent on what is still missing. A
    fault in the sources' reading is logged and never keeps the literature agent from its search."""
    try:
        run_sources_job(store, tenant_id, project_id)
    except Exception:
        if model is None:
            raise
        _log.exception("the structured sources could not be read for %s; the literature agent searches all", project_id)
    if model is not None:
        run_research_job(store, tenant_id, project_id, model=model, max_turns=max_turns)


def start_compound_job(store: ProjectStore, tenant_id: str, project_id: str, *, by: str, max_turns: int = AUTO_TURNS) -> bool:
    """Start the compound's sources and literature in the background (at the project's start, by the person `by`); False
    when a literature run is already going. Without a model, the structured sources alone."""
    model, _problem = agent_jobs.chat_model()

    def job() -> None:
        run_compound_job(store, tenant_id, project_id, model=model, max_turns=max_turns)

    try:
        jobs.start(store, tenant_id, project_id, "research", job, by=by, busy="a literature run is already in progress",
                   name=f"compound-{project_id}")
    except HTTPException:
        return False
    return True


def run_research_job(store: ProjectStore, tenant_id: str, project_id: str, *, model, europe_pmc=None,
                     max_turns: int = 120, agent: Literal["A2", "A3"] = "A2") -> dict[str, Any]:
    """A2 (parameter values) or A3 (observed clinical data) over the data plan's literature items."""
    ws = Workspace(store, tenant_id, project_id)
    _, matrix = _matrix(ws)
    brief_version = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(brief_version.content) if brief_version else None
    drug = brief.drug_name if brief else project_id
    run = agent_jobs.AgentRun(store.root, tenant_id=tenant_id, project_id=project_id,  # type: ignore[attr-defined]
                              agent="A2-literature" if agent == "A2" else "A3-observed-data", model=model,
                              max_turns=max_turns)
    outcome = agent_jobs.literature_research(model, agent=agent, ws=ws, library=DocumentLibrary(ws, for_agents=True),
                                             requirements=literature_items(matrix), actor=run.actor, drug=drug,
                                             max_turns=max_turns, log_step=run.log_step, europe_pmc=europe_pmc,
                                             brief=brief)
    summary = {"proposed": len(outcome.proposed), "rejected": len(outcome.rejected), "not_found": outcome.not_found,
               "access_requests": len(outcome.access_requests), "summary": outcome.summary[:4000], "error": outcome.error}
    run.finish(outcome, summary)
    _follow_inputs(ws, by=run.actor)   # what the agent found flows into the inputs (D-27)
    return {"run_id": run.run_id, "status": outcome.status, **summary}
