"""Step 3 · Review & sign (docs/plans/2026-10-19-p0-p5-redesign.md §3.3): the one review D-27 relies on, read only.

- **The review table:** every model input with its value and unit, the kept source with its quote, grade and flags,
  who or what supplied it, and a confidence. The confidence is display only: it sums up the grade, the flags and how
  many other sources agree, and decides nothing (D-32 picks the value). The rows are the Inputs rows
  (`inputs_view.compound_rows`), so what is reviewed is what the CPF carries.
- **Credibility (ICH M15):** the campaign's time budget split across the stages exactly as the MAP signs it (MS-01's
  fractions; D-31: no per-stage overrides, more time is a larger budget signed again), and the limitations the MAP
  names (`plan.map_limitations`).
- **The estimation plan (R4b):** every numeric parameter fixed or estimated, its source, its bounds, the bounds MS-01
  §2.2 proposes (`estimation.proposed_bounds`, D-34) and what the validator says of them.
- **The validation plan (R4b):** what S4 and S5 judge under this MAP (`map.stage_coverage`), and what happens when
  validation fails (MS-01 §4, §6.6).
- **The acceptance criteria (R4b):** the limits of the chosen tier, as the MAP records them (`MapAcceptance`), from
  the ruleset UNVERIFIED until the SME signs; and the stricter internal target, if any (MS-01 §8), which the MAP
  records and the verdicts apply to the internal groups (R4d).
- **The applications (R4c):** each analysis template the MAP pins (the VBE crossover), its inputs as the template
  declares them and what is still missing; and each of the brief's applications with what the campaign does with it
  (`plan.APPLICATION_SUPPORT`), with the brief's prediction scenarios, which S6 does not simulate yet.

Each part reads the MAP this plan generates now (`campaign_map`), so the page shows what the signature would carry.
"""

from __future__ import annotations

from typing import Any, Literal

from modeler_project.brief import VALUED, ProjectBrief
from modeler_project.estimation import fit_findings, proposed_bounds
from modeler_project.estimation import rule as bounds_rule
from modeler_project.inputs import todo
from modeler_project.inputs_view import compound_rows
from modeler_project.plan import (
    APPLICATION_SUPPORT,
    ModelPlan,
    Violation,
    application_label,
    campaign_cpf,
    default_map,
    map_limitations,
    plan_split,
)
from modeler_project.workspace import Workspace
from pbpk_domain.acceptance import load_acceptance_ruleset, loosest_internal_target
from pbpk_domain.analysis_templates import load_template
from pbpk_domain.campaign.map import MapDocument, stage_coverage
from pbpk_domain.cpf.formulations import formulation_names
from pbpk_domain.cpf.models import CPF, ParameterStatus

Confidence = Literal["low", "medium", "high"]
Supplier = Literal["agent", "client file", "person", "system"]


def supplier(source: dict[str, Any]) -> Supplier:
    """Who or what supplied a value: an agent run, the client's file read by code (the template, cell by cell), a
    person who typed it, or the system (an import with no person behind it)."""
    by = source.get("proposed_by") or ""
    if by.startswith("agent:"):
        return "agent"
    if source.get("extraction") == "CELL" or source.get("source_type") == "CLIENT_FILE":
        return "client file"
    return "system" if by in ("", "system") else "person"


def _person(by: str | None) -> bool:
    return bool(by) and not by.startswith("agent:") and by != "system"


def confidence(state: str, source: dict[str, Any] | None, agreeing: int) -> Confidence | None:
    """Display only: low for a value held, in conflict, flagged or of grade D; high for grade A or B, unflagged, with
    at least one other source agreeing; medium otherwise. None when there is no value."""
    if source is None or state == "missing":
        return None
    if state in ("held", "conflict") or source.get("flags") or source.get("confidence") == "D":
        return "low"
    if source.get("confidence") in ("A", "B") and agreeing > 0:
        return "high"
    return "medium"


def review_rows(ws: Workspace) -> list[dict[str, Any]]:
    """Every model input as the review table shows it, in the Inputs page's order."""
    out = []
    for row in compound_rows(ws, todo(ws)):
        sources = row["sources"]
        kept = sources[0] if sources else (row["alternatives"][0] if row["alternatives"] else None)
        agreeing = max(len(sources) - 1, 0)
        out.append({
            "id": row["id"], "tab": row["tab"], "state": row["state"], "value": row["value"], "unit": row["unit"],
            "status": row["status"], "message": row["message"],
            "evidence_id": sources[0]["id"] if sources else None,
            "source": ({"type": kept["source_type"], **kept["source"]} if kept else None),
            "quote": kept["quote"] if kept else "", "grade": kept["confidence"] if kept else None,
            "flags": list(kept["flags"]) if kept else [],
            "supplied_by": supplier(kept) if kept else None,
            "changed_by_person": bool(kept) and (_person(kept.get("decided_by")) or supplier(kept) == "person"),
            "agreeing": agreeing, "alternatives": len(row["alternatives"]),
            "confidence": confidence(row["state"], kept, agreeing),
        })
    return out


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """The review table's filters, counted."""
    return {"all": len(rows), "flagged": sum(bool(r["flags"]) or r["state"] in ("held", "conflict") for r in rows),
            "by_person": sum(r["changed_by_person"] for r in rows),
            "from_agent": sum(r["supplied_by"] == "agent" for r in rows),
            "open": sum(r["state"] != "kept" for r in rows)}


def campaign_map(plan: ModelPlan, cpf: CPF, rows: list[dict[str, Any]]) -> MapDocument:
    """The MAP this plan generates now (as `map_from_plan`, but answering while the validator still blocks)."""
    doc, _ = default_map(campaign_cpf(plan, cpf), rows, plan.structure, split=plan_split(plan))
    return doc


def stage_budgets(plan: ModelPlan, doc: MapDocument) -> list[dict[str, Any]]:
    """Each stage's share of the campaign budget, as the MAP generated from this plan signs it (with a metabolite
    stage, SM takes its share and the rest scale down)."""
    total = plan.structure.campaign_budget_seconds
    return [{"stage": s.stage, "budget_seconds": s.budget_seconds, "fraction": round(s.budget_seconds / total, 4),
             "max_rounds": s.max_rounds} for s in doc.stage_plan]


def limitations(plan: ModelPlan, violations: list[Violation]) -> list[str]:
    return list(map_limitations(plan, violations))


# --- the estimation plan (R4b) ------------------------------------------------------------------------------------


def _source(row: dict[str, Any] | None, record: Any) -> tuple[str | None, str | None]:
    """The start value's source as the review table names it (citation and grade), else the CPF's provenance."""
    if row and row.get("source"):
        source = row["source"]
        title = source.get("title") or str(source.get("type", "")).lower().replace("_", " ")
        year = f" · {source['year']}" if source.get("year") else ""
        return f"{title}{year}", row.get("grade")
    provenance = record.provenance
    return ((provenance.reference or provenance.source_type) if provenance else None), None


def estimation_rows(plan: ModelPlan, cpf: CPF, table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every numeric parameter of the CPF, fixed or estimated: its start value and source, the plan's fit (stages,
    bounds, scale, who and why), the MS-01 stages it is a candidate at, the bounds MS-01 §2.2 proposes and what the
    validator says of the fit's bounds. The estimated first, then the MS-01 candidates, then the rest."""
    by_id = {r["id"]: r for r in table}
    candidates: dict[str, list[str]] = {}
    for stage, ids in plan.fit_candidates.items():
        for pid in ids:
            candidates.setdefault(pid, []).append(stage)
    out = []
    for record in cpf.parameters:
        if record.status is ParameterStatus.MISSING or not isinstance(record.value, int | float) or isinstance(record.value, bool):
            continue
        fit = plan.fits.get(record.id)
        source, grade = _source(by_id.get(record.id), record)
        findings = fit_findings(record, fit.lower, fit.upper) if fit else []
        out.append({
            "id": record.id, "value": record.value, "unit": record.unit, "status": record.status.value,
            "source": source, "grade": grade,
            "estimated": ({"stages": list(fit.stages), "lower": fit.lower, "upper": fit.upper, "scale": fit.scale,
                           "by": fit.by, "reason": fit.reason} if fit else None),
            "candidate_at": sorted(candidates.get(record.id, [])),
            "proposal": proposed_bounds(record).to_content(),
            "findings": [{"severity": sev, "rule": rule, "message": message} for sev, rule, message in findings],
        })
    return sorted(out, key=lambda r: (r["estimated"] is None, not r["candidate_at"], r["id"]))


def bounds_rule_view() -> dict[str, str]:
    current = bounds_rule()
    return {"version": current.version, "status": current.status, "source": current.source}


# --- the validation plan and the acceptance criteria (R4b) -------------------------------------------------------

JUDGES = {
    "S4": "Internal validation: the final model, simulated once against every study it was fitted to, each group judged "
          "against the tier's limits (MS-01 §4 S4). Never refitted.",
    "S5": "External validation: the studies kept out of fitting, judged against the tier's limits, fasted and fed as "
          "separate groups (MS-01 §4 S5, §8).",
}
ON_FAILURE = {
    "S4": "The campaign stops and asks you (an escalation): a failure here means a stage passed on stale values or the "
          "stages interact, so it is never refitted (MS-01 §4 S4).",
    "S5": "The campaign stops and you choose a path (MS-01 §6.6), signed as a deviation from the MAP: record a limitation "
          "and narrow the context of use; learn, moving the study to internal validation and refitting, once per class "
          "and only when another external study of its class exists; bring new evidence; or stop. With no other study "
          "of its class, external validation of that class is not achievable, and the MAP says so.",
}


def validation_plan(doc: MapDocument, studies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What S4 and S5 judge under this MAP, which studies, and what happens when a validation fails."""
    by_id = {s["study_id"]: s for s in studies}
    out = []
    for stage in ("S4", "S5"):
        coverage = stage_coverage(doc, stage)
        out.append({
            "stage": stage, "judges": JUDGES[stage], "on_failure": ON_FAILURE[stage],
            "studies": [{"study_id": sid, "blinded": bool(by_id.get(sid, {}).get("blinded")),
                         "role": by_id.get(sid, {}).get("role")} for sid in coverage.studies],
            "skip_reason": coverage.skip_reason, "notes": list(coverage.notes),
        })
    return out


def _criteria(block: dict[str, Any], ruleset: dict[str, Any]) -> list[dict[str, Any]]:
    """Each quantity's limit (a fold, or Guest's δ for DDI ratios) and the source the ruleset cites for it."""
    sources = ruleset.get("sources", {})
    return [{"quantity": quantity, "max_fold": c.get("max_fold"), "guest_delta": c.get("guest_delta"),
             "citation": sources.get(c.get("source", ""), c.get("source"))} for quantity, c in block.items()]


def acceptance(plan: ModelPlan, doc: MapDocument) -> dict[str, Any]:
    """The limits every round is judged by at the chosen tier, as the MAP records them, and the internal target. With
    no tier set there are no criteria: the tier is never assumed."""
    tier = plan.structure.model_risk
    ruleset = load_acceptance_ruleset()
    criteria = doc.acceptance.criteria if tier else None
    target = plan.structure.internal_target_pe
    return {
        "tier": tier, "ruleset": doc.acceptance.ruleset, "status": str(ruleset.get("status", "")),
        "description": criteria.get("description") if criteria else None,
        "pk_parameters": _criteria((criteria or {}).get("pk_parameters", {}), ruleset),
        "ddi_ratios": _criteria((criteria or {}).get("ddi_ratios", {}), ruleset),
        "min_fraction_within": criteria.get("min_fraction_within") if criteria else None,
        "internal_target_pe": target, "target_set_here": "internal_target_pe" in plan.structure.locked,
        "loosest_target_pe": round(loosest_internal_target(tier), 1) if tier else None,
        "target_applied": True,
    }


# the templates a person may add on Review & sign, and the brief applications that make each one offered
_ADDABLE = {"vbe-crossover": ("APP-11", "APP-14")}


def applications(plan: ModelPlan, cpf: CPF, violations: list[Violation]) -> dict[str, Any]:
    """The analysis templates the MAP pins, each with its inputs as the template declares them, the person's values,
    what the validator still says of it, and the choices its inputs take (the CPF's formulations, the template's
    limits); and the templates the brief's applications would let a person add."""
    pinned = []
    for application in plan.structure.applications:
        template = load_template(application.template)
        pinned.append({
            "template": template.id, "version": application.template_version, "status": template.status,
            "inputs": [{**spec.model_dump(mode="json"), "value": application.inputs.get(spec.id)} for spec in template.inputs],
            "problems": [v.message for v in violations
                         if v.rule == "application" and v.target.split(":", 1)[0] == application.template],
            "formulations": sorted(formulation_names(cpf)),
            "limits": [{"id": key, **limit.model_dump(mode="json")} for key, limit in template.limits.items()],
        })
    present = {a.template for a in plan.structure.applications}
    codes = set(plan.structure.application_codes)
    addable = [t for t, apps in _ADDABLE.items() if t not in present and codes & set(apps)]
    return {"pinned": pinned, "addable": addable}


def _scenario(item: dict[str, Any]) -> dict[str, Any]:
    return {key: record.value for key, record in item.items() if record.status in VALUED}


def application_support(plan: ModelPlan, brief: ProjectBrief | None) -> dict[str, Any]:
    """Each of the brief's applications with what the campaign does with it, and the brief's prediction scenarios:
    recorded, but S6 does not simulate them yet (it simulates the validated studies)."""
    rows = []
    for code in plan.structure.application_codes:
        status, reason = APPLICATION_SUPPORT.get(code, ("not_supported", "the campaign does not know this application"))
        rows.append({"code": code, "label": application_label(code), "status": status, "reason": reason})
    scenarios = [_scenario(item) for item in (brief.groups.get("scenarios", ()) if brief else ())]
    return {"rows": rows, "scenarios": [s for s in scenarios if s]}
