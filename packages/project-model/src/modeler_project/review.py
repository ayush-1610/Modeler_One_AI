"""Step 3 · Review & sign (docs/plans/2026-10-19-p0-p5-redesign.md §3.3): the one review D-27 relies on, read only.

- **The review table:** every model input with its value and unit, the kept source with its quote, grade and flags,
  who or what supplied it, and a confidence. The confidence is display only: it sums up the grade, the flags and how
  many other sources agree, and decides nothing (D-32 picks the value). The rows are the Inputs rows
  (`inputs_view.compound_rows`), so what is reviewed is what the CPF carries.
- **Credibility (ICH M15):** the campaign's time budget split across the stages exactly as the MAP signs it (MS-01's
  fractions; D-31: no per-stage overrides, more time is a larger budget signed again), and the limitations the MAP
  names (`plan.map_limitations`).
"""

from __future__ import annotations

from typing import Any, Literal

from modeler_project.inputs import todo
from modeler_project.inputs_view import compound_rows
from modeler_project.plan import ModelPlan, Violation, campaign_cpf, default_map, map_limitations, plan_split
from modeler_project.workspace import Workspace
from pbpk_domain.cpf.models import CPF

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


def stage_budgets(plan: ModelPlan, cpf: CPF, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each stage's share of the campaign budget, as the MAP generated from this plan signs it (with a metabolite
    stage, SM takes its share and the rest scale down)."""
    doc, _ = default_map(campaign_cpf(plan, cpf), rows, plan.structure, split=plan_split(plan))
    total = plan.structure.campaign_budget_seconds
    return [{"stage": s.stage, "budget_seconds": s.budget_seconds, "fraction": round(s.budget_seconds / total, 4),
             "max_rounds": s.max_rounds} for s in doc.stage_plan]


def limitations(plan: ModelPlan, violations: list[Violation]) -> list[str]:
    return list(map_limitations(plan, violations))
