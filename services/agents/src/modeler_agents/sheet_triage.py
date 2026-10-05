"""Agent A4 · Sheet triage (plan §10.1 step 3, §14.2): what a client workbook's undecided sheets hold.

Code triages every sheet first (`modeler_intake.triage`); A4 sees only the sheets code left OTHER. It reads each
sheet's first rows and classifies it with `classify_sheet`, quoting the header cell that shows what the sheet holds.
Code checks the quote against that cell before the classification is recorded; a person can change any of them. A4
never reads data out of a sheet: that is a mapping recipe a person confirms.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from modeler_agents.llm import ChatModel, Tool, run_tool_loop
from modeler_intake.grid import WorkbookGrid
from modeler_intake.triage import HEADER_ROWS, SheetCategory, SheetTriage, quote_in_header

SYSTEM_PROMPT = f"""You sort the sheets of a client's PBPK data workbook into categories, so a scientist knows where to look.

Categories: {", ".join(c.value for c in SheetCategory)}.
PK_INDIVIDUAL: concentration-time data per subject. PK_SUMMARY: mean/median concentration-time data. PK_PARAMETERS: NCA results (AUC, Cmax, tmax, half-life). DISSOLUTION: % dissolved over time (vessels, media, apparatus). PRODUCT_INFO: product, batch, strength, particle size. STUDIES: study design, dosing, populations. DEMOGRAPHICS: subjects' age, weight, sex. BIOANALYTICAL: LLOQ, assay validation. PHYSCHEM_INVITRO: logP, pKa, solubility, fu, permeability, clearance in vitro. URINE_FECES: excretion. OTHER: anything else.

For each sheet shown, call classify_sheet once with the category and the header cell (e.g. Sheet1!B3) whose text shows it, quoting that cell's text exactly. Only cells in the first {HEADER_ROWS} rows count. If no cell shows what the sheet holds, use OTHER with an empty quote and say why in the note. Classify every sheet, calling several tools in one turn, then answer with one line per sheet."""


@dataclass
class TriageContext:
    workbook: WorkbookGrid
    sheets: list[str]
    actor: str
    accepted: list[SheetTriage] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)


def classify_sheet(ctx: TriageContext, *, sheet: str, category: str, cell: str = "", quote: str = "", note: str = "") -> str:
    if sheet not in ctx.sheets:
        return f"REJECTED: {sheet!r} is not one of the sheets to classify ({', '.join(ctx.sheets)})"
    try:
        chosen = SheetCategory(category)
    except ValueError:
        return f"REJECTED: {category!r} is not a category"
    if chosen is not SheetCategory.OTHER and not quote_in_header(ctx.workbook, sheet, cell, quote):
        ctx.rejected.append({"sheet": sheet, "category": category, "cell": cell, "quote": quote})
        return f"REJECTED QUOTE_NOT_FOUND: {cell} does not contain {quote!r} within the first {HEADER_ROWS} rows of {sheet}"
    ctx.accepted = [t for t in ctx.accepted if t.sheet != sheet]
    ctx.accepted.append(SheetTriage(sheet, chosen, evidence_cell=cell if quote else "", evidence_quote=quote,
                                    by=ctx.actor, note=note))
    return f"RECORDED {sheet}: {chosen.value}"


def _show(workbook: WorkbookGrid, sheets: list[str]) -> str:
    return "\n\n".join(f"## Sheet: {name}\n{workbook.sheets[name].preview(max_rows=HEADER_ROWS, max_columns=20)}" for name in sheets)


def run_triage(model: ChatModel, ctx: TriageContext, *, max_turns: int = 6,
               log_step: Callable[[dict[str, Any]], None] = lambda s: None):
    tool = Tool(
        name="classify_sheet", description="Record what one sheet holds, quoting the header cell that shows it.",
        parameters={"type": "object", "required": ["sheet", "category"], "properties": {
            "sheet": {"type": "string"}, "category": {"type": "string", "enum": [c.value for c in SheetCategory]},
            "cell": {"type": "string", "description": "Sheet!A1 reference of the deciding header cell"},
            "quote": {"type": "string", "description": "that cell's text, exactly"},
            "note": {"type": "string"}}},
        handler=lambda **kw: classify_sheet(ctx, **kw))
    user = f"Workbook {ctx.workbook.file_name}. Classify these sheets:\n\n{_show(ctx.workbook, ctx.sheets)}"
    return run_tool_loop(model, system=SYSTEM_PROMPT, user=user, tools=[tool], max_turns=max_turns, log_step=log_step)
