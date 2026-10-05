"""Agent A5 · Planning (plan §11.1, §14.2; T-50): explains the model plan and proposes departures from MS-01.

The default plan is code's (MS-01 §3.3 split, the MAP's stage rules). A5 reads it through `get_plan`, writes one
rationale sentence for every assignment and structure choice (`explain`), and may propose a departure
(`propose_role`, `propose_fit`) only with a reason. Code checks each proposal before it reaches the person: a move onto
a person's (userLocked) choice is refused, and so is one that breaks an MS-01 rule. Accepted or not is the person's
decision in the diff view; A5 never changes the plan itself.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from modeler_agents.llm import ChatModel, LoopOutcome, Tool, run_tool_loop
from modeler_project.plan import ROLES, ModelPlan, add_proposal, place, set_fit, validate
from pbpk_domain.cpf.models import CPF

SYSTEM_PROMPT = """You are the planning agent of a PBPK modeling platform (PK-Sim, OSP). The model is developed stage by stage under the MS-01 standard: S1 trains distribution and elimination on IV studies, S2 absorption on fasted oral studies, S3 formulation and fed effects; S4 re-simulates every training study (internal validation), S5 judges external studies, S6 verifies applications (DDI, pharmacogenomics, special populations, preclinical).

Code has already computed the default plan from MS-01 rules. Your job:
1. Call get_plan.
2. For EVERY study, call explain(target=<study id>, rationale=<one or two sentences>): why this study has this role, from its class, dose, food state, information score and origin. Also explain each structure choice (target "structure:food_effect_in_question" etc.) and each fit candidate you consider important.
3. Only if you have a scientific reason, propose a departure with propose_role or propose_fit, always with the reason. A person decides; a study a person placed is not yours to move. Do not propose a fit for a parameter that no training study informs.

Call several tools per turn. Finish with a short summary of the plan and of any departures you proposed."""


@dataclass
class PlanningContext:
    plan: ModelPlan
    cpf: CPF
    rows: list[dict[str, Any]]
    actor: str
    exploratory: bool = False
    explained: int = 0
    proposed: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)


def get_plan(ctx: PlanningContext) -> str:
    plan = ctx.plan
    studies = [{"study_id": s.study_id, "class": s.study_class, "score": s.score, "route": s.route, "dose_mg": s.dose_mg,
                "formulation": s.formulation, "food_state": s.food_state, "design": s.design, "n": s.n, "origin": s.origin,
                "profile": s.evaluable, "role": plan.placements[s.study_id].role, "default_role": s.default_role,
                "placed_by_person": plan.placements[s.study_id].userLocked} for s in plan.studies]
    parameters = [{"id": p.id, "value": p.value, "unit": p.unit, "status": p.status.value,
                   "source": p.provenance.reference if p.provenance else None} for p in ctx.cpf.parameters]
    return json.dumps({"roles": list(ROLES), "studies": studies, "parameters": parameters,
                       "fit_candidates": {k: list(v) for k, v in plan.fit_candidates.items()},
                       "fits": {k: v.model_dump() for k, v in plan.fits.items()},
                       "structure": plan.structure.model_dump(exclude={"locked", "reasons"}),
                       "default_rationale": list(plan.default_rationale), "limitations": list(plan.default_limitations),
                       "violations": [v.message for v in validate(plan, ctx.cpf, ctx.rows, exploratory=ctx.exploratory)]},
                      default=str)


def explain(ctx: PlanningContext, *, target: str, rationale: str) -> str:
    if not rationale.strip():
        return "REJECTED: an empty rationale"
    known = {s.study_id for s in ctx.plan.studies} | {p.id for p in ctx.cpf.parameters}
    if target not in known and not target.startswith("structure:"):
        return f"REJECTED: {target!r} is neither a study, a parameter nor structure:<key>"
    ctx.plan = ctx.plan.model_copy(update={"rationale": {**ctx.plan.rationale, target: rationale.strip()}})
    ctx.explained += 1
    return f"RECORDED rationale for {target}"


def _new_errors(ctx: PlanningContext, changed: ModelPlan, target: str) -> list[str]:
    before = {v.id for v in validate(ctx.plan, ctx.cpf, ctx.rows, exploratory=ctx.exploratory) if v.severity == "error"}
    return [v.message for v in validate(changed, ctx.cpf, ctx.rows, exploratory=ctx.exploratory)
            if v.severity == "error" and v.id not in before and v.target == target]


def propose_role(ctx: PlanningContext, *, study_id: str, role: str, reason: str) -> str:
    if study_id not in ctx.plan.placements:
        return f"REJECTED: no study {study_id}"
    if role not in ROLES:
        return f"REJECTED: {role!r} is not a role ({', '.join(ROLES)})"
    if not ctx.plan.placements[study_id].userLocked:
        errors = _new_errors(ctx, place(ctx.plan, study_id, role, by=ctx.actor, reason=reason or "-"), study_id)
        if errors:
            ctx.refused.append(f"{study_id} → {role}")
            return "REFUSED by the MS-01 rules: " + "; ".join(errors)
    ctx.plan, answer = add_proposal(ctx.plan, "role", study_id, {"role": role}, reason=reason, by=ctx.actor)
    (ctx.proposed if answer.startswith("PROPOSED") else ctx.refused).append(f"{study_id} → {role}")
    return answer


def propose_fit(ctx: PlanningContext, *, parameter: str, stages: list[str], lower: float, upper: float,
                scale: str = "linear", reason: str = "") -> str:
    if ctx.cpf.get(parameter) is None:
        return f"REJECTED: {parameter} is not a CPF parameter"
    fit = {"stages": tuple(stages), "lower": float(lower), "upper": float(upper), "scale": scale}
    try:
        changed = set_fit(ctx.plan, parameter, fit, by=ctx.actor, reason=reason or "-")
    except ValueError as exc:
        return f"REJECTED: {exc}"
    errors = _new_errors(ctx, changed, parameter)
    if errors:
        ctx.refused.append(f"fit {parameter}")
        return "REFUSED by the MS-01 rules: " + "; ".join(errors)
    ctx.plan, answer = add_proposal(ctx.plan, "fit", parameter, fit, reason=reason, by=ctx.actor)
    (ctx.proposed if answer.startswith("PROPOSED") else ctx.refused).append(f"fit {parameter}")
    return answer


def build_tools(ctx: PlanningContext) -> list[Tool]:
    return [
        Tool("get_plan", "The default plan, studies, parameters, fit candidates and current violations.",
             {"type": "object", "properties": {}}, lambda: get_plan(ctx)),
        Tool("explain", "Record the rationale for one study's role, a parameter, or structure:<key>.",
             {"type": "object", "required": ["target", "rationale"],
              "properties": {"target": {"type": "string"}, "rationale": {"type": "string"}}},
             lambda **kw: explain(ctx, **kw)),
        Tool("propose_role", "Propose a different role for a study, with the reason (a person decides).",
             {"type": "object", "required": ["study_id", "role", "reason"],
              "properties": {"study_id": {"type": "string"}, "role": {"type": "string", "enum": list(ROLES)},
                             "reason": {"type": "string"}}},
             lambda **kw: propose_role(ctx, **kw)),
        Tool("propose_fit", "Propose fitting a parameter in S1-S3 within bounds, with the reason (a person decides).",
             {"type": "object", "required": ["parameter", "stages", "lower", "upper", "reason"],
              "properties": {"parameter": {"type": "string"}, "stages": {"type": "array", "items": {"type": "string"}},
                             "lower": {"type": "number"}, "upper": {"type": "number"},
                             "scale": {"type": "string", "enum": ["linear", "log"]}, "reason": {"type": "string"}}},
             lambda **kw: propose_fit(ctx, **kw)),
    ]


def run_planning(model: ChatModel, ctx: PlanningContext, *, drug: str, max_turns: int = 20,
                 log_step: Callable[[dict[str, Any]], None] = lambda s: None) -> LoopOutcome:
    user = (f"Drug: {drug}. {len(ctx.plan.studies)} studies are planned. Explain every assignment and propose departures "
            "only with a reason. Start with get_plan.")
    return run_tool_loop(model, system=SYSTEM_PROMPT, user=user, tools=build_tools(ctx), max_turns=max_turns,
                         log_step=log_step)
