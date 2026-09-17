"""Strategist agent (task T-15, decision D7): choose among the diagnostics ruleset's permitted actions.

The diagnostics ruleset (MS-01 §5, `pbpk_domain.diagnostics`) decides *which* actions are permitted this round;
the strategist only chooses among them and writes the rationale — it can never add an action. A structured-output
call proposes ``{action_id, rationale, parameters_to_fit, bounds_override}``; the proposal is validated and, on
anything invalid or absent — no model configured, an action outside the permitted set, an already-tried action, a
malformed bound — the choice falls back to the first not-yet-tried permitted action (the deterministic path, which
needs no model and is what the workflow uses today). ``action_id`` is the hard safety constraint; parameters and
bounds are advisory and re-validated against the CPF by the fitting step. Every proposal and rejection is handed to
``log_step`` for the append-only ``agent_runs``/``agent_steps`` ledger.

Only `llm_decider` touches the Anthropic SDK, and it imports it lazily, so `decide` and the whole deterministic path
import without the SDK or an API key.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

SYSTEM_PROMPT = """You are the strategist for an automated PBPK modelling loop built on PK-Sim.

Each round a deterministic diagnostics ruleset gives you an ordered list of PERMITTED actions for the current stage. \
Your only job is to choose exactly one of them and explain why in one or two sentences a PBPK scientist would accept.

Rules you must follow:
- Choose action_id verbatim from the permitted list. Never invent an action or choose one that is not listed.
- The list is already ordered by the ruleset's preference; choose the first one unless the round's evidence gives a \
specific reason to prefer another permitted action, which you must state.
- You may name the parameters_to_fit and, only when you have a mechanistic reason, a bounds_override for them; leave \
these empty otherwise. A separate validated step checks bounds against the compound's plausibility ranges.
- Prefer the smallest change that addresses the evidence. If nothing in the evidence justifies a choice, take the \
first permitted action."""


class StrategistProposal(BaseModel):
    """Structured output the model returns (validated before use)."""
    action_id: str
    rationale: str = ""
    parameters_to_fit: list[str] = Field(default_factory=list)
    bounds_override: dict[str, list[float]] | None = None


@dataclass(frozen=True)
class StrategyContext:
    stage: str
    permitted_actions: tuple[str, ...]
    actions_tried: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    causes: tuple[str, ...] = ()
    compound: str = ""


@dataclass(frozen=True)
class StrategistChoice:
    action_id: str | None
    rationale: str
    parameters_to_fit: tuple[str, ...] = ()
    bounds_override: dict[str, tuple[float, float]] | None = None
    source: Literal["strategist", "fallback", "none"] = "fallback"


class StrategistDecider(Protocol):
    def propose(self, ctx: StrategyContext) -> StrategistProposal | None: ...


def available_actions(ctx: StrategyContext) -> tuple[str, ...]:
    """Permitted actions not yet tried this stage, in the ruleset's order."""
    tried = set(ctx.actions_tried)
    return tuple(a for a in ctx.permitted_actions if a not in tried)


def default_parameters(action: str) -> tuple[str, ...]:
    """The parameters an action fits, from the action string (advisory; the fit step resolves placeholders)."""
    op, _, target = action.partition(" ")
    if op == "fit":
        return (target,)
    if op == "switch" and target.endswith(".mm"):  # switch dominant enzyme to Michaelis-Menten -> fit Km and Vmax
        root = target[:-3]
        return (f"{root}.km", f"{root}.vmax")
    return ()


def _clean_override(override: dict[str, list[float]] | None, params: tuple[str, ...]) -> dict[str, tuple[float, float]] | None:
    if not override:
        return None
    out: dict[str, tuple[float, float]] = {}
    for name, bound in override.items():
        if name not in params or not isinstance(bound, (list, tuple)) or len(bound) != 2:
            continue
        lo, hi = bound
        if all(isinstance(x, (int, float)) and math.isfinite(x) for x in (lo, hi)) and lo < hi:
            out[name] = (float(lo), float(hi))
    return out or None


def _fallback_rationale(ctx: StrategyContext, action: str) -> str:
    cause = ctx.causes[0] if ctx.causes else "the round's evidence"
    return f"First not-yet-tried permitted action for {ctx.stage} addressing {cause} (deterministic choice)."


def decide(
    ctx: StrategyContext,
    *,
    decider: StrategistDecider | None = None,
    log_step: Callable[[dict[str, Any]], None] | None = None,
) -> StrategistChoice:
    """Choose one permitted action. Uses ``decider`` when given and its proposal is valid; otherwise the first
    not-yet-tried permitted action. Never returns an action outside ``ctx.permitted_actions``."""
    available = available_actions(ctx)
    if not available:
        return StrategistChoice(None, "no permitted action left to try", source="none")
    first = available[0]

    def fallback(reason: str | None) -> StrategistChoice:
        if log_step and reason:
            log_step({"event": "fallback", "stage": ctx.stage, "reason": reason, "action_id": first})
        return StrategistChoice(first, _fallback_rationale(ctx, first), default_parameters(first), None, "fallback")

    if decider is None:
        return fallback(None)

    try:
        proposal = decider.propose(ctx)
    except Exception as exc:  # noqa: BLE001 - any model/transport failure must fall back, never stall the durable loop
        return fallback(f"strategist call failed: {exc}")
    if proposal is None:
        return fallback("strategist returned no proposal")
    if log_step:
        log_step({"event": "proposal", "stage": ctx.stage, "proposal": proposal.model_dump()})
    if proposal.action_id not in available:
        if log_step:
            log_step({"event": "rejected", "stage": ctx.stage, "action_id": proposal.action_id,
                      "reason": "action not in the permitted, not-yet-tried set", "permitted": list(available)})
        return fallback(f"proposed action {proposal.action_id!r} is not a permitted, untried action")

    params = tuple(proposal.parameters_to_fit) or default_parameters(proposal.action_id)
    override = _clean_override(proposal.bounds_override, params)
    rationale = proposal.rationale.strip() or _fallback_rationale(ctx, proposal.action_id)
    return StrategistChoice(proposal.action_id, rationale, params, override, "strategist")


def _render_task(ctx: StrategyContext) -> str:
    lines = [f"Stage: {ctx.stage}"]
    if ctx.compound:
        lines.append(f"Compound: {ctx.compound}")
    if ctx.causes:
        lines.append("Diagnosed cause(s): " + "; ".join(ctx.causes))
    if ctx.evidence:
        lines.append("Evidence: " + ", ".join(ctx.evidence))
    if ctx.actions_tried:
        lines.append("Already tried this stage: " + ", ".join(ctx.actions_tried))
    permitted = available_actions(ctx)
    lines.append("Permitted actions (choose exactly one action_id, verbatim):")
    lines += [f"  {i + 1}. {a}" for i, a in enumerate(permitted)]
    return "\n".join(lines)


def _parsed_proposal(message: Any) -> StrategistProposal | None:
    for block in getattr(message, "content", []) or []:
        parsed = getattr(block, "parsed_output", None)
        if isinstance(parsed, StrategistProposal):
            return parsed
    return None


def llm_decider(llm: Any, *, max_tokens: int = 1024) -> StrategistDecider:
    """A decider backed by a structured-output call. ``llm`` is a `modeler_agents.providers.LLMConfig`."""

    class _LLMDecider:
        def propose(self, ctx: StrategyContext) -> StrategistProposal | None:
            if not available_actions(ctx):
                return None
            message = llm.client.beta.messages.parse(
                model=llm.model,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _render_task(ctx)}],
                output_format=StrategistProposal,
                **getattr(llm, "request_options", {}),
                **getattr(llm, "beta_options", {}),
            )
            return _parsed_proposal(message)

    return _LLMDecider()
