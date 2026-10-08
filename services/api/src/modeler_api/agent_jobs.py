"""The API's one seam to the agents package (docs/ARCHITECTURE_BOUNDARIES.md, rule B4; `[seams]` in boundaries.toml).

Routers reach the LLM edge only through this module and never import `modeler_agents` themselves (bar two deterministic
helpers, the quote check and the recipe review, which leave the agents package in phase 5c), so replacing an agent or
the agents package touches this file, not the HTTP layer. What is here:
- the configured model (`chat_model`, `require_chat_model`, `agents_status`);
- an agent run's record (`AgentRun`: started, each step logged, finished once) and the records a page lists;
- one entry point per agent: A1 proposal intake, A2/A3 literature research, A4 sheet triage, A5 planning.

Each imports `modeler_agents` when called: the package brings the provider SDKs, which an API that runs with agents off
never needs to load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException

# --- the configured model ------------------------------------------------------------------------------------------


def chat_model() -> tuple[Any | None, str | None]:
    """The configured chat model, or None with the configuration error (None too when agents are simply off)."""
    from modeler_agents.llm import LLMConfigError, chat_model_from_env

    try:
        return chat_model_from_env(), None
    except LLMConfigError as exc:
        return None, str(exc)


def require_chat_model(off: str) -> Any:
    """The model an agent endpoint needs: 409 with the configuration error, or with `off` when agents are off."""
    model, problem = chat_model()
    if problem:
        raise HTTPException(status_code=409, detail=problem)
    if model is None:
        raise HTTPException(status_code=409, detail=off)
    return model


def agents_status() -> dict[str, Any]:
    """Whether an LLM provider is configured, without exposing any key."""
    model, problem = chat_model()
    if problem:
        return {"enabled": False, "problem": problem}
    if model is None:
        return {"enabled": False, "problem": "agents are off (MODELER_LLM_PROVIDER not set): fill the brief by hand"}
    return {"enabled": True, "provider": model.provider, "model": model.model}


# --- run records ---------------------------------------------------------------------------------------------------


class AgentRun:
    """One agent run's record (modeler_agents.run_store): started on creation, each step logged, finished once."""

    def __init__(self, root: str | Path, *, tenant_id: str, project_id: str, agent: str, model, max_turns: int):
        from modeler_agents.run_store import FileRunStore

        self._runs = FileRunStore(root, project_id=project_id)
        self.run_id = self._runs.start_run(tenant_id=tenant_id, agent=agent, provider=model.provider, model=model.model,
                                           campaign_id=None, budget={"max_turns": max_turns})
        self.actor = f"agent:{self.run_id}"
        self._seq = 0

    def log_step(self, step: dict[str, Any]) -> None:
        self._seq += 1
        self._runs.record_step(run_id=self.run_id, seq=self._seq, kind=step.get("type", "step"), content=step,
                               usage=step.get("usage", {}))

    def finish(self, outcome, summary: dict[str, Any]) -> None:
        self._runs.finish_run(run_id=self.run_id, status=outcome.status, input_tokens=outcome.usage["input_tokens"],
                              output_tokens=outcome.usage["output_tokens"], cost_usd=0.0, summary=summary)


def project_runs(root: str | Path | None, tenant_id: str, project_id: str) -> list[dict[str, Any]]:
    """A project's agent runs, newest first (none when the store has no file root)."""
    from modeler_agents.run_store import FileRunStore

    return FileRunStore(root).runs(tenant_id, project_id=project_id) if root else []


def run_record(root: str | Path, run_id: str) -> dict[str, Any]:
    """One run's record (KeyError when there is no such run)."""
    from modeler_agents.run_store import FileRunStore

    return FileRunStore(root).get(run_id)


def run_steps(root: str | Path, run_id: str) -> list[dict[str, Any]]:
    """One run's steps; read only after the caller has checked the run is the viewer's."""
    from modeler_agents.run_store import FileRunStore

    return FileRunStore(root).steps(run_id)


# --- the agents ----------------------------------------------------------------------------------------------------


def proposal_intake(model, *, library, brief, actor: str, context_note: str, max_turns: int, log_step):
    """A1: read the proposal documents into the brief (the outcome carries the brief it produced)."""
    from modeler_agents.proposal_intake import IntakeContext, run_proposal_intake

    ctx = IntakeContext(library=library, brief=brief, actor=actor)
    return run_proposal_intake(model, ctx, context_note=context_note, max_turns=max_turns, log_step=log_step)


def literature_research(model, *, agent: Literal["A2", "A3"], ws, library, requirements, actor: str, drug: str,
                        max_turns: int, log_step, europe_pmc=None):
    """A2 (parameter values) or A3 (observed clinical data) over the data plan's literature items."""
    from modeler_agents.evidence_agent import ResearchContext, run_research
    from modeler_agents.observed_data_agent import run_observed_data
    from modeler_agents.sources import EuropePMC

    ctx = ResearchContext(ws=ws, library=library, requirements=requirements, actor=actor,
                          europe_pmc=europe_pmc or EuropePMC())
    runner = run_research if agent == "A2" else run_observed_data
    return runner(model, ctx, drug=drug, max_turns=max_turns, log_step=log_step)


def sheet_triage(model, *, workbook, sheets, actor: str, max_turns: int, log_step):
    """A4 on the sheets code left undecided: (context with the accepted and rejected classifications, outcome)."""
    from modeler_agents.sheet_triage import TriageContext, run_triage

    ctx = TriageContext(workbook=workbook, sheets=sheets, actor=actor)
    return ctx, run_triage(model, ctx, max_turns=max_turns, log_step=log_step)


def planning(model, *, plan, cpf, rows, actor: str, exploratory: bool, drug: str, max_turns: int, log_step):
    """A5 on the model plan: (context with the plan it drafted and its counts, outcome)."""
    from modeler_agents.planning_agent import PlanningContext, run_planning

    ctx = PlanningContext(plan=plan, cpf=cpf, rows=rows, actor=actor, exploratory=exploratory)
    return ctx, run_planning(model, ctx, drug=drug, max_turns=max_turns, log_step=log_step)
