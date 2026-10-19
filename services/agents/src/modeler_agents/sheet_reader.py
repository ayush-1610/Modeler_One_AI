"""Agent A4 · Sheet reading (redesign §3.2, R3c): how to read one client sheet, proposed for a person to check.

Code fills the reading form first (`modeler_intake.sheet_form.suggest`); the agent corrects it with `propose_reading`.
Code checks every proposal before it is kept:
- the form is valid;
- every quote is in the cell it cites, and supports the value it is cited for;
- the units, LLOQ, dose and n each stand on a quote. A unit the sheet does not state is said to be unstated (the
  person sees it); an LLOQ, a dose or an n is never guessed;
- the reading applies to the sheet without a problem (`to_proposal`, `review_proposal`, as a confirmed reading would).

The agent hears what code read, or what to fix, and proposes again. Only a reading code accepts is kept, and nothing
enters the project until the person checks it and saves it (plan §10.1 step 4). The agent reads nothing into the
project itself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from modeler_agents.llm import ChatModel, LoopOutcome, Tool, run_tool_loop
from modeler_intake.citations import normalize_for_match
from modeler_intake.grid import WorkbookGrid, as_text
from modeler_intake.recipe_review import RecipeProposal, review_proposal
from modeler_intake.sheet_form import SheetForm, suggest, to_proposal
from modeler_intake.validate import CONCENTRATION_UNITS, TIME_UNITS, canonical_unit

SHOWN_ROWS = 40
MAX_ROWS_PER_READ = 60
SHOWN_COLUMNS = 30
QUOTED = ("value_unit", "time_unit", "lloq", "dose", "n", "strength_mg")   # each stands on a quote from the sheet
UNSTATABLE = ("value_unit", "time_unit")                    # … or, for a unit only, is said to be unstated

SYSTEM_PROMPT = """You read one sheet of a client's PBPK data workbook and say how to read it, by correcting a form that code filled in first. A program applies your form exactly as written and checks it; a scientist checks the result before anything is saved, so describe the sheet as it is.

The form (rows are the sheet's own 1-based row numbers, columns are letters):
- kind: concentration_time or dissolution. layout: times_down (a time column, one row per time) or times_across (the times in a header row, one row per subject or vessel).
- header_row; first_data_row; last_data_row (set it when footnotes or summary rows follow the data without an empty row; otherwise null).
- times_down: time_column; value_columns (one per subject or vessel when they are columns, else the one value column); subject_column when a column names the subject (long form); group_column for a period or treatment column.
- times_across: header_row is the row holding the times, value_columns are the time columns, subject_column names each row.
- statistic: individual, arithmetic_mean, geometric_mean or median. For summary values, sd_column and n_column when the sheet has them; an n stated elsewhere goes in constants.n. A CV is not an SD.
- mean_column or mean_row: the sheet's own mean profile next to individual subjects (mean_statistic, mean_sd_column, mean_n).
- time_unit (h or min); value_unit as written (ng/mL, µg/L, nmol/L …; % for dissolution); lloq; below_lloq_tokens (BLQ, <LLOQ …); missing_tokens (NS, NR …: no sample); decimal_comma (true when numbers are written 12,5).
- constants: study_id, analyte, matrix, dose, dose_unit, route, formulation, food_state; for dissolution role, product, batch, medium, ph, rpm, volume_ml, strength_mg, apparatus.

Rules:
- Use only what the sheet and its file name state. value_unit, time_unit, lloq, constants.dose, constants.n and constants.strength_mg each need an evidence entry {cell, quote, supports, field, value}: the cell (Sheet!A1) whose text contains the quote exactly, field naming what it supports (value_unit, time_unit, lloq, dose, n or strength_mg) and value its value in the form. A dissolution reading is in % and needs no quote for it. A unit the sheet does not state: keep the starting form's and list the field in unstated. Never guess an LLOQ, a dose, an n or a strength: leave it empty and say so in notes.
- Call read_rows to see rows beyond those shown.
- Call propose_reading with the whole form. Code applies it and answers with what it read, or with the problems to fix; fix them and propose again. Check what it read against the sheet: a column of identical numbers is probably not a concentration.
- Stop once code accepts a reading, answering with one line on what the sheet holds."""


@dataclass
class ReadingContext:
    workbook: WorkbookGrid
    sheet: str
    start: SheetForm                    # code's first filling
    start_notes: list[str]
    actor: str
    form: SheetForm | None = None       # the last reading code accepted
    notes: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


@dataclass
class Reading:
    form: SheetForm | None              # None: no reading code accepted
    notes: list[str]
    rejected: list[str]
    outcome: LoopOutcome


# --- what code checks ------------------------------------------------------------------------------------------------

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_UNIT_TOKEN = re.compile(r"[A-Za-zµμ]+\s*/\s*[A-Za-z]+|[A-Za-zµμ]+|%")


def _form_value(form: SheetForm, name: str) -> str:
    if name in ("value_unit", "time_unit"):
        return getattr(form, name)
    if name == "lloq":
        return f"{form.lloq:g}" if form.lloq is not None else ""
    return str(form.constants.get(name, "")).strip()


def _same_number(a: str, b: str) -> bool:
    try:
        return float(a.replace(",", ".")) == float(b.replace(",", "."))
    except ValueError:
        return False


def _unit_of(kind: str, name: str, text: str) -> str | None:
    if name == "value_unit" and kind == "dissolution":
        return "%" if text.strip() == "%" else None
    return canonical_unit(text, CONCENTRATION_UNITS if name == "value_unit" else TIME_UNITS)


def _supports(form: SheetForm, name: str, quote: str, value: str) -> bool:
    """Whether a quote states this value: the unit among its words, or the number among its numbers."""
    if name in ("value_unit", "time_unit"):
        unit = _unit_of(form.kind, name, value)
        return unit is not None and any(_unit_of(form.kind, name, t) == unit for t in _UNIT_TOKEN.findall(quote))
    return any(_same_number(n, value) for n in _NUMBER.findall(quote))


_CELL = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d+)")


def _cell_text(workbook: WorkbookGrid, ref: str) -> str | None:
    sheet, _, coordinate = ref.partition("!")
    match = _CELL.fullmatch(coordinate.strip())
    if sheet not in workbook.sheets or match is None:
        return None
    return as_text(workbook.sheets[sheet].cell(int(match.group(2)), match.group(1).upper()).value)


def check_reading(workbook: WorkbookGrid, form: SheetForm, unstated: list[str]) -> list[str]:
    """What stops a reading before it is applied: a quote not in its cell or not stating its value, and a value that
    should stand on a quote and does not."""
    problems = []
    for e in form.evidence:
        text = _cell_text(workbook, e.cell)
        if text is None:
            problems.append(f"evidence {e.cell}: no such cell (write it as Sheet!A1)")
        elif not normalize_for_match(e.quote) or normalize_for_match(e.quote) not in normalize_for_match(text):
            problems.append(f"evidence {e.cell}: the cell says {text[:120]!r}, which does not contain {e.quote!r}")
        elif e.field in QUOTED and not _supports(form, e.field, e.quote, _form_value(form, e.field)):
            problems.append(f"evidence {e.cell}: {e.quote!r} does not state {e.field} {_form_value(form, e.field) or '(empty)'}")
    for name in QUOTED:
        value = _form_value(form, name)
        if not value:
            continue
        if name == "value_unit" and form.kind == "dissolution":
            if value != "%":
                problems.append(f"value_unit {value!r}: a dissolution reading is in % dissolved")
            continue
        if name in ("value_unit", "time_unit") and _unit_of(form.kind, name, value) is None:
            problems.append(f"{name} {value!r} is not a unit code knows")
        elif not any(e.field == name for e in form.evidence) and not (name in UNSTATABLE and name in unstated):
            problems.append(f"{name} {value}: cite the cell that states it (an evidence entry with field {name!r})"
                            + (", or list it in unstated" if name in UNSTATABLE else ", or leave it empty: it is never guessed"))
    return problems


def _canonical_evidence(form: SheetForm) -> SheetForm:
    """Each checked quote carries its value as the form writes it, so the recipe keeps it (`sheet_form._still_true`)."""
    evidence = [e.model_copy(update={"value": _form_value(form, e.field)}) if e.field in QUOTED else e for e in form.evidence]
    return form.model_copy(update={"evidence": evidence})


def _summary(review) -> str:
    if review.dissolution:
        vessels = sorted({r.vessel for r in review.dissolution})
        times = sorted({r.time for r in review.dissolution})
        return f"{len(vessels)} vessels ({', '.join(vessels[:12])}) at {len(times)} times ({', '.join(f'{t:g}' for t in times[:12])})"
    records = review.concentrations
    series: dict[tuple[str, str], list] = {}
    for r in records:
        series.setdefault((r.statistic, r.series), []).append(r)
    lines = []
    for (statistic, name), points in list(series.items())[:8]:
        points = sorted(points, key=lambda r: r.time)
        shown = ", ".join(f"{r.time:g} {r.time_unit}: {'BLQ' if r.below_lloq else f'{r.value:g}'}" for r in points[:8])
        lines.append(f"  {name} ({statistic.replace('_', ' ')}, {len(points)} points, {points[0].unit}): {shown}")
    more = f"\n  … and {len(series) - 8} more series" if len(series) > 8 else ""
    return f"{len(series)} series:\n" + "\n".join(lines) + more


def propose_reading(ctx: ReadingContext, *, form: dict[str, Any], unstated: list[str] | None = None,
                    notes: list[str] | None = None) -> str:
    unstated = [u for u in unstated or [] if u in UNSTATABLE]
    try:
        reading = SheetForm.model_validate({**form, "sheet": ctx.sheet})
    except ValidationError as exc:
        problems = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:8]]
        ctx.rejected.append("; ".join(problems))
        return "REJECTED: the form is not valid:\n- " + "\n- ".join(problems)
    problems = check_reading(ctx.workbook, reading, unstated)
    review = None
    if not problems:
        reading = _canonical_evidence(reading)
        try:
            proposal = RecipeProposal.model_validate(to_proposal(reading, ctx.workbook.sheets[ctx.sheet]))
        except (ValueError, KeyError) as exc:
            problems = [f"the form cannot be applied: {exc}"]
        else:
            review = review_proposal(ctx.workbook, proposal, recipe_id=f"reading-{ctx.sheet}")
            problems = [f"{i.code} {i.location}: {i.message}" for i in review.issues[:10]]
            if not problems and not (review.concentrations or review.dissolution):
                problems = ["the form reads no values"]
    if problems or review is None:
        ctx.rejected.append("; ".join(problems))
        return "REJECTED: fix these and propose again:\n- " + "\n- ".join(problems)
    ctx.form = reading
    ctx.notes = [*(notes or []), *(f"The {u.replace('_', ' ')} is not written in the sheet: {getattr(reading, u)} is assumed; "
                                   "check it." for u in unstated)]
    return f"ACCEPTED. Code read {_summary(review)}\nIf this is not what the sheet holds, propose again; otherwise stop."


def read_rows(ctx: ReadingContext, *, first_row: int, last_row: int) -> str:
    grid = ctx.workbook.sheets[ctx.sheet]
    first = max(1, int(first_row))
    last = min(grid.max_row, int(last_row), first + MAX_ROWS_PER_READ - 1)
    if first > grid.max_row:
        return f"the sheet has {grid.max_row} rows"
    return grid.preview(max_rows=last - first + 1, max_columns=SHOWN_COLUMNS, first_row=first)


# --- the run ---------------------------------------------------------------------------------------------------------


def _user(ctx: ReadingContext, drug: str) -> str:
    grid = ctx.workbook.sheets[ctx.sheet]
    start = json.dumps(ctx.start.model_dump(mode="json"), ensure_ascii=False)
    return (f"File {ctx.workbook.file_name}, sheet {ctx.sheet} ({grid.max_row} rows, {grid.max_column} columns). "
            f"The drug: {drug or 'not given'}.\n\n## The sheet, rows 1-{min(grid.max_row, SHOWN_ROWS)}\n"
            f"{grid.preview(max_rows=SHOWN_ROWS, max_columns=SHOWN_COLUMNS)}\n\n## Code's first filling of the form\n{start}\n\n"
            "## What code found or did not find\n" + "\n".join(f"- {n}" for n in ctx.start_notes or ["(nothing to add)"]))


def read_sheet(model: ChatModel, *, workbook: WorkbookGrid, sheet: str, drug: str = "", actor: str,
               category: str = "", products: list[dict[str, str]] | None = None, max_turns: int = 8,
               log_step: Callable[[dict[str, Any]], None] = lambda s: None) -> Reading:
    """Propose the reading of one sheet, starting from code's first filling; only a reading code accepts is returned."""
    start, start_notes = suggest(workbook.sheets[sheet], category=category, filename=workbook.file_name, drug=drug,
                                 products=products or [])
    ctx = ReadingContext(workbook=workbook, sheet=sheet, start=start, start_notes=start_notes, actor=actor)
    tools = [
        Tool(name="propose_reading",
             description="Propose the whole reading form; code checks the quotes, applies the form and says what it read.",
             parameters={"type": "object", "required": ["form"], "properties": {
                 "form": {"type": "object", "description": "the reading form: the same fields as code's first filling"},
                 "unstated": {"type": "array", "items": {"type": "string", "enum": list(UNSTATABLE)},
                              "description": "units the sheet does not write (the starting form's are kept)"},
                 "notes": {"type": "array", "items": {"type": "string"},
                           "description": "what the person should check or add (e.g. an LLOQ the sheet does not state)"}}},
             handler=lambda **kw: propose_reading(ctx, **kw)),
        Tool(name="read_rows", description=f"Show rows of the sheet (at most {MAX_ROWS_PER_READ} at a time).",
             parameters={"type": "object", "required": ["first_row", "last_row"], "properties": {
                 "first_row": {"type": "integer"}, "last_row": {"type": "integer"}}},
             handler=lambda **kw: read_rows(ctx, **kw)),
    ]
    outcome = run_tool_loop(model, system=SYSTEM_PROMPT, user=_user(ctx, drug), tools=tools, max_turns=max_turns,
                            log_step=log_step)
    return Reading(ctx.form, ctx.notes, ctx.rejected, outcome)
