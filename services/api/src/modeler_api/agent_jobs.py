"""The API's one seam to the agents package (docs/ARCHITECTURE_BOUNDARIES.md, rule B4; `[seams]` in boundaries.toml).

Routers reach the LLM edge only through this module and never import `modeler_agents` themselves (bar two deterministic
helpers, the quote check and the recipe review, which leave the agents package in phase 5c), so replacing an agent or
the agents package touches this file, not the HTTP layer. What is here:
- the configured model (`chat_model`, `require_chat_model`, `agents_status`);
- an agent run's record (`AgentRun`: started, each step logged, finished once) and the records a page lists;
- one entry point per agent: A1 proposal intake, A2/A3 literature research, A4 sheet triage, sheet reading and
  client documents, A5 planning.

Each imports `modeler_agents` when called: the package brings the provider SDKs, which an API that runs with agents off
never needs to load.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException

from modeler_api import jobs, platform_settings
from modeler_api.config import get_settings

# --- the configured model ------------------------------------------------------------------------------------------


def chat_model(agent: str | None = None) -> tuple[Any | None, str | None]:
    """The chat model `agent` (A1 … A5) runs on, or None with the configuration error (None too when agents are off):
    the admin console's setting for it with its provider's active key (`platform_settings`), else the server's
    environment. Read at each start, so a change in the console needs no restart."""
    from modeler_agents.llm import LLMConfigError, chat_model_from_env

    try:
        settings = get_settings()
        env = platform_settings.model_env(settings.read_root, settings.master_key, agent) if agent else None
        return chat_model_from_env(env), None
    except (LLMConfigError, platform_settings.SettingsError) as exc:
        return None, str(exc)


def require_chat_model(off: str, agent: str | None = None) -> Any:
    """The model an agent endpoint needs: 409 with the configuration error, or with `off` when agents are off."""
    model, problem = chat_model(agent)
    if problem:
        raise HTTPException(status_code=409, detail=problem)
    if model is None:
        raise HTTPException(status_code=409, detail=off)
    return model


def agents_status(agent: str | None = None) -> dict[str, Any]:
    """Whether `agent` (or, without one, the server's environment) has a model, without exposing any key."""
    model, problem = chat_model(agent)
    if problem:
        return {"enabled": False, "problem": problem}
    if model is None:
        settings = get_settings()
        setting = platform_settings.AgentSettings(settings.read_root).current(agent) if agent and settings.read_root else None
        if setting and setting["provider"] == "off":
            return {"enabled": False, "problem": f"off in the admin console ({setting['reason']})"}
        return {"enabled": False, "problem": "agents are off (MODELER_LLM_PROVIDER not set)"}
    return {"enabled": True, "provider": model.provider, "model": model.model}


def test_key(provider: str, fields: dict[str, str]) -> tuple[bool, str]:
    """Whether a stored key answers: the in-house proxy lists the models it serves with it."""
    from modeler_agents.llm import OpenAICompatChat

    if provider == "litellm":
        served = OpenAICompatChat(provider="litellm", base_url=fields["base_url"], api_key=fields["key"], model="",
                                  timeout_s=30, max_retries=0).list_models()
        return (True, f"answers; serves {', '.join(served)}") if served else (
            False, f"no list of models from {fields['base_url']}: check the address and the key")
    return False, f"{provider} keys cannot be tested yet"


# --- run records ---------------------------------------------------------------------------------------------------


class AgentRun:
    """One agent run's record (modeler_agents.run_store): started on creation, each step logged, finished once."""

    def __init__(self, root: str | Path, *, tenant_id: str, project_id: str, agent: str, model, max_turns: int):
        from modeler_agents.run_store import FileRunStore

        self._runs = FileRunStore(root, project_id=project_id)
        self.run_id = self._runs.start_run(tenant_id=tenant_id, agent=agent, provider=model.provider, model=model.model,
                                           campaign_id=None, budget={"max_turns": max_turns},
                                           started_by=jobs.started_by.get())
        self.actor = f"agent:{self.run_id}"
        self._seq = 0

    def log_step(self, step: dict[str, Any]) -> None:
        self._seq += 1
        self._runs.record_step(run_id=self.run_id, seq=self._seq, kind=step.get("type", "step"), content=step,
                               usage=step.get("usage", {}))

    def finish(self, outcome, summary: dict[str, Any]) -> None:
        self._runs.finish_run(run_id=self.run_id, status=outcome.status, input_tokens=outcome.usage["input_tokens"],
                              output_tokens=outcome.usage["output_tokens"], cost_usd=0.0, summary=summary)


def recorded_usage(root: str | Path, since: datetime | None = None) -> list[dict[str, Any]]:
    """Every recorded run of every tenant, code-only runs included: its tokens, and what it would cost on each Claude
    model at list prices with its conversations cached (`modeler_agents.usage_report`; the admin console)."""
    from modeler_agents.usage_report import PRICES, cost, read_runs

    return [{"run_id": r.run_id, "tenant_id": r.tenant, "project_id": r.project, "agent": r.agent, "model": r.model,
             "status": r.status, "started_at": r.started_at.isoformat() if r.started_at else None,
             "started_by": r.started_by, "turns": len(r.turns), "input_tokens": r.input_tokens,
             "output_tokens": r.output_tokens, "usd": {m: cost(r, m, cached=True) for m in PRICES}}
            for r in read_runs(Path(root), since, code_runs=True)]


def claude_prices() -> dict[str, dict[str, float]]:
    """USD per million tokens of each Claude model the usage is priced at: input, cache write, cache read, output."""
    from modeler_agents.usage_report import PRICES

    return {m: dict(zip(("input", "cache_write_5m", "cache_read", "output"), p, strict=True)) for m, p in PRICES.items()}


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


def proposal_intake(model, *, library, brief, actor: str, context_note: str, max_turns: int, log_step, before_risk=None):
    """A1: read the proposal documents into the brief (the outcome carries the brief it produced). `before_risk`: code's
    reading of what A1 left empty, applied before A1 drafts the ICH M15 ratings."""
    from modeler_agents.proposal_intake import IntakeContext, run_proposal_intake

    ctx = IntakeContext(library=library, brief=brief, actor=actor)
    return run_proposal_intake(model, ctx, context_note=context_note, max_turns=max_turns, log_step=log_step,
                               before_risk=before_risk)


def literature_research(model, *, agent: Literal["A2", "A3"], ws, library, requirements, actor: str, drug: str,
                        max_turns: int, log_step, europe_pmc=None, brief=None):
    """A2 (parameter values) or A3 (observed clinical data) over the data plan's literature items. `brief`: the
    project's brief, whose facts (other names of the drug, routes, products, populations, pathways) shape the search."""
    from modeler_agents.evidence_agent import ResearchContext, run_research_per_input
    from modeler_agents.observed_data_agent import run_observed_data
    from modeler_agents.research_brief import project_facts
    from modeler_agents.sources import EuropePMC

    ctx = ResearchContext(ws=ws, library=library, requirements=requirements, actor=actor,
                          europe_pmc=europe_pmc or EuropePMC(), facts=project_facts(brief, drug))
    # A2 searches each open input in its own conversation, side by side (plan 2026-11-05 §3.3)
    runner = run_research_per_input if agent == "A2" else run_observed_data
    return runner(model, ctx, drug=drug, max_turns=max_turns, log_step=log_step)


def structured_clients() -> tuple[Any, Any, Any]:
    """The free structured sources' clients (PubChem, openFDA, ChEMBL); tests replace this to answer offline."""
    from modeler_agents.structured_sources import ChEMBL, OpenFDA, PubChem

    return PubChem(), OpenFDA(), ChEMBL()


def compound_sources(*, ws, library, requirements, drug: str, actor: str, log_step):
    """The compound's values from PubChem, the FDA label and ChEMBL, proposed by code (plan 2026-11-05 §3.3)."""
    from modeler_agents.compound_sources import read_compound_sources

    pubchem, openfda, chembl = structured_clients()
    return read_compound_sources(ws, library, requirements, drug=drug, actor=actor, pubchem=pubchem, openfda=openfda,
                                 chembl=chembl, log_step=log_step)


def sheet_triage(model, *, workbook, sheets, actor: str, max_turns: int, log_step, context: str = ""):
    """A4 on the sheets code left undecided: (context with the accepted and rejected classifications, outcome).
    `context`: what the delivery map says (plan 2026-11-10, R4), as for the readings below."""
    from modeler_agents.sheet_triage import TriageContext, run_triage

    ctx = TriageContext(workbook=workbook, sheets=sheets, actor=actor)
    return ctx, run_triage(model, ctx, max_turns=max_turns, log_step=log_step, context=context)


def sheet_reading(model, *, workbook, sheet: str, drug: str, actor: str, category: str, products, max_turns: int,
                  log_step, context: str = ""):
    """A4 reading one sheet: the reading code accepted (None when it accepted none), the agent's notes, what code
    refused and the outcome."""
    from modeler_agents.sheet_reader import read_sheet

    return read_sheet(model, workbook=workbook, sheet=sheet, drug=drug, actor=actor, category=category, products=products,
                      max_turns=max_turns, log_step=log_step, context=context)


def document_reading(model, *, ws, library, sid: str, drug: str, actor: str, run_id: str, max_turns: int, log_step,
                     context: str = ""):
    """A4 reading one client PDF or Word file (I4) and recording on it what code accepted: (context with what code
    accepted and refused, outcome)."""
    from modeler_agents.document_reader import read_and_record

    return read_and_record(model, ws, library, sid, actor=actor, drug=drug, run_id=run_id, max_turns=max_turns,
                           log_step=log_step, context=context)


def delivery_pass(model, *, ws, library, sids: list[str], drug: str, actor: str, run_id: str, log_step):
    """A4 mapping the files of a delivery together before each is read (plan 2026-11-10, R4): (context with what code
    accepted and refused, outcome); what code accepted is recorded on the delivery map."""
    from modeler_agents.delivery_pass import map_and_record

    return map_and_record(model, ws, library, sids, actor=actor, drug=drug, run_id=run_id, log_step=log_step)


def planning(model, *, plan, cpf, rows, actor: str, exploratory: bool, drug: str, max_turns: int, log_step):
    """A5 on the model plan: (context with the plan it drafted and its counts, outcome)."""
    from modeler_agents.planning_agent import PlanningContext, run_planning

    ctx = PlanningContext(plan=plan, cpf=cpf, rows=rows, actor=actor, exploratory=exploratory)
    return ctx, run_planning(model, ctx, drug=drug, max_turns=max_turns, log_step=log_step)
