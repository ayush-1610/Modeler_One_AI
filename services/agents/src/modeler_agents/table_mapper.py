"""Agent A4 · Table mapper (contracts §6.2, plan §7.4): what each row and column of a table is, for code to read.

The model maps a table the rules and the mapping cache did not: it proposes a mapping spec v2 (`MappingSpec`) and code
executes it. It never sees a number of the table's body: `map_table` receives the table already redacted
(`modeler_intake.mapping.redact.redact`: its context lines and header words verbatim, every body digit "#") and never
a grid or a source document. It never types a number: a constant's value, a unit and every value are read by code at
the cites the spec names.

Code checks every proposal before it is kept, through `check`, a closure over the region's grid that stays in L2/L3
(`validate_spec`): each cite exists, each constant and unit is written at its cite, the layout is coherent. The model
hears "ACCEPTED", or "REJECTED: ..." with every finding message redacted digit by digit (`redact_findings`), and
proposes again. A table that holds no data is answered with `not_data` and a reason. Only a spec code accepted, in a
conversation the model ended itself (status COMPLETED), is returned; the pipeline stores it in the mapping cache as a
proposal (evidence level `new_mapping`) until a person approves it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict, ValidationError

from modeler_agents.llm import ChatModel, Tool, run_tool_loop
from modeler_intake import fields
from modeler_intake.client_template import PK_PARAMETERS
from modeler_intake.mapping.redact import redact_findings
from modeler_intake.mapping_spec import CellForm, Layout, MappingSpec, RedactedTable, Role
from modeler_intake.source_model import Finding

_KINDS = [k for k in get_args(fields.TableKind) if k not in ("not_data", "unknown")]

SYSTEM_PROMPT = f"""You map one table of a client's PBPK data file: you say what each row and column of the table is, and a program reads every value. You never see the table's numbers: every digit of its body is shown as #, and the program reads each number from its own cell. You never type a number.

What you are shown: the file's name and role; the table's size; its context lines (its caption and up to 3 lines above and below it, verbatim, each with its place: "caption 1", "above 1" is the line directly above, "below 1" the line directly below); its header band (its first rows, a cell that writes a value shown with its digits as #); some of its body rows (every digit as #); and, for each column, how many body cells hold a number, a text or nothing, with its distinct texts. Rows and columns are numbered from 1 at the table's top-left corner.

Call propose_mapping with one spec, a JSON object:
- kind: one of {", ".join(_KINDS)}.
- layout: {" | ".join(get_args(Layout))}. long: one row per value (a record table, one row per study or product, is long with one value column per field). wide_series: times down a column, one value column per series. wide_times: times across a header row (time_row), one row per series. key_value: a label column (role parameter) says what each row is, and keys map its labels to fields.
- header_rows; first_data_row; last_data_row (leave it out: to the table's end).
- columns: one entry for each column, {{"column": c, "role": ...}}. Roles: {", ".join(get_args(Role))}. A value column has a field (or the spec's field). A spread, n, lloq or interval column names the value column it qualifies with "of" when there are several. spread_kind: SD, SE, CV%, geoSD or geoCV% (a CI or a min-max pair is an interval_low / interval_high pair, with "level" citing where its confidence level is written). A condition column names its condition: one of {", ".join(fields.CONDITION_FIELDS)}. cell_form, when a value cell also writes its spread, interval or unit: {" | ".join(repr(f) for f in get_args(CellForm) if f != "value")}. In wide_series, "series" cites the header cell that names the column and "series_role" says what it names (subject, vessel, analyte, condition ...). An ignore column says why its cells are not data (reason).
- field: the default field of the value columns: concentration, percent_dissolved, excretion.amount, excretion.fraction, composition.amount, pk.<parameter> ({", ".join(PK_PARAMETERS)}), or a study, product, batch or condition field (dose, n, strength_mg, batch, ph ...).
- time_row (wide_times); keys (key_value): [{{"pattern": a regular expression matched against the whole label, case aside, "field": ..., "statistic"?, "spread_kind"?}}].
- Units as the table writes them, each with its cite: value_unit with value_unit_cite, time_unit with time_unit_cite, a column's own unit with unit and unit_cite. A unit the table does not write is left out, never assumed.
- statistic (individual, arithmetic_mean, geometric_mean, median) when the table states it; lloq: the cite where the table's LLOQ is written; time_reference (first_dose, last_dose, occasion_dose) with time_reference_cite when the table states it.
- below_lloq_tokens (BLQ, <LLOQ, ND ...) and missing_tokens (NS, NR ...): the words that stand where a number stands. Never a number.
- row_rules: rows told apart by the text of one of their cells, {{"column": c, "pattern": a regular expression matched against the whole cell, case aside, "role": ...}}: arithmetic_mean, geometric_mean or median rows; spread rows (with spread_kind); n rows; interval_low and interval_high rows; or exclude with a reason (a CV% row that restates the SD and the mean). A value takes one spread and one n: when a table gives two (SD and CV% rows or columns), map one and exclude or ignore the other with a reason. An SD, N or CI row qualifies the statistic row of its own time and labels.
- Patterns are short and flat: no repeated group that itself repeats or holds an alternation, no backreference, at most 3 repeats such as + or *; no padding is needed, since a pattern is matched against the whole text, case aside.
- A statistic or spread_kind you type must agree with the header or label that writes it ("Geometric mean" is geometric_mean, "SEM" is SE).
- constants: facts stated once for the whole table, each {{"field": ..., "cite": ...}} where code reads it: study_id, treatment, dose, food_state, route, analyte, matrix, n, lloq ... For a name (study_id, treatment, analyte, product, batch) add a pattern, a regular expression with exactly one group that matches the cited text once (its group is the name), unless the whole cited text is the name; you may add text, the name as you read it, which code compares with its own reading. A number (a dose, an n, an LLOQ) is read by code from its cite: give no text and no pattern.
- A cite is {{"row": r, "column": c}}, a cell of the table, or {{"near": "caption" | "above" | "below", "line": k}}, a context line. An LLOQ column may carry its own unit and unit_cite.
- questions (optional): what a person should check, as short sentences. Leave not_data_reason out: call not_data instead.

Code checks each spec on the table: every cite exists, every constant and unit is written at its cite, the layout holds together. It answers ACCEPTED, or REJECTED with what to fix (its digits shown as #): fix it and propose again. Every cell that holds a number must end as a value, a time, a spread, an n, an LLOQ, an interval bound, a label, a condition, a header, a constant or a unit, or be excluded with a reason: map every column. When the table holds no data (contents, instructions, a legend), call not_data with the reason instead. Once code answers ACCEPTED, stop and answer with one line on what the table holds."""

PROMPT_SHA256 = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()

_SPEC_TOOL = {
    "type": "object", "required": ["spec"],
    "properties": {"spec": {"type": "object", "description": "a mapping spec v2 (the system prompt says its fields)"}}}
_NOT_DATA_TOOL = {
    "type": "object", "required": ["reason"],
    "properties": {"reason": {"type": "string", "description": "why the table holds no data"}}}


class TableMapping(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: MappingSpec | None                 # the spec code accepted, in a conversation the model ended: else None
    rejected: tuple[str, ...]                # every "REJECTED: ..." answer, in order
    status: str                              # the loop's: COMPLETED, INCOMPLETE or LLM_UNAVAILABLE
    usage: dict[str, int]
    prompt_sha256: str


@dataclass
class _Mapping:
    check: Callable[[MappingSpec], tuple[Finding, ...]]
    accepted: MappingSpec | None = None
    rejected: list[str] = field(default_factory=list)

    def reject(self, findings: list[Finding]) -> str:
        answer = redact_findings(findings)
        self.rejected.append(answer)
        return answer

    def judge(self, spec: MappingSpec) -> str:
        found = list(self.check(spec))
        found += [f for f in _typed_numbers(spec) if (f.code, f.location) not in {(g.code, g.location) for g in found}]
        errors = [f for f in found if f.severity == "error"]
        if errors:
            return self.reject(errors)
        self.accepted = spec
        warnings = [f for f in found if f.severity != "error"]
        if not warnings:
            return "ACCEPTED"
        notes = "\n".join(f"- {f.code} at {f.location[:80]}: {_redacted(f.message)}" for f in warnings)
        return f"ACCEPTED (a person will see these notes):\n{notes}"


def _redacted(message: str) -> str:
    """A finding's message as `redact_findings` writes it: every digit run "#", at most 200 characters."""
    return re.sub(r"\d+", "#", unicodedata.normalize("NFKC", message))[:200]


def _typed_numbers(spec: MappingSpec) -> list[Finding]:
    """A number the model typed: a constant of a number field with a text or a pattern. Code reads every number from its
    cite, so this is refused whatever the region's check says (`validate_spec` finds it too: NUMBER_TYPED)."""
    out = []
    for i, constant in enumerate(spec.constants):
        definition = fields.field(constant.field)
        if definition is not None and definition.value in ("number", "integer") and (
                constant.text is not None or constant.pattern is not None):
            out.append(Finding(code="NUMBER_TYPED", location=f"constants[{i}] ({constant.field})",
                               message="a number is read by code from its cite: give no text and no pattern"))
    return out


def propose_mapping(ctx: _Mapping, *, spec: Any) -> str:
    if not isinstance(spec, dict):
        return ctx.reject([Finding(code="INVALID_SPEC", location="spec", message="the spec is a JSON object")])
    try:
        parsed = MappingSpec.model_validate(spec)
    except ValidationError as exc:
        return ctx.reject([Finding(code="INVALID_SPEC", location=".".join(str(p) for p in e["loc"]) or "spec",
                                   message=e["msg"]) for e in exc.errors()[:12]])
    if parsed.kind == "not_data":
        return ctx.reject([Finding(code="LAYOUT", location="kind", message="a table that holds no data: call not_data")])
    return ctx.judge(parsed)


def not_data(ctx: _Mapping, *, reason: Any) -> str:
    if not isinstance(reason, str) or not reason.strip():
        return ctx.reject([Finding(code="REASON_MISSING", location="reason", message="say why the table holds no data")])
    return ctx.judge(MappingSpec(kind="not_data", layout="long", header_rows=0, first_data_row=1,
                                 not_data_reason=reason.strip()))


def _cells(row: tuple[str, ...]) -> str:
    return " | ".join(text.replace("\n", " ") or "·" for text in row)


def render(table: RedactedTable) -> str:
    """The table as the model is shown it (the user message's body): nothing but what `redact` let through."""
    title = (f"File: {table.file_name} (document role: {table.document_role}). Table {table.region_id}: {table.n_rows} "
             f"rows, {table.n_cols} columns; kind by rule: {table.kind_by_rule}.")
    lines = [title, "", 'Context lines (verbatim; cite one as {"near": ..., "line": ...}):']
    lines += [f"  {c.near} {c.line}: {c.text}" for c in table.context] or ["  (none)"]
    lines += ["", f"Header band (rows 1-{table.header_rows}; a bare number shown as #):" if table.header_rows else
              "Header band: none (no row above the first row of numbers)"]
    lines += [f"  row {r}: {_cells(row)}" for r, row in enumerate(table.header, start=1)]
    lines += ["", "Body rows (every digit shown as #; · an empty cell):"]
    lines += [f"  row {r}: {_cells(row)}" for r, row in zip(table.body_rows, table.body, strict=True)]
    lines += ["", "Columns over all body rows (numbers, texts, empty; distinct texts):"]
    lines += [f"  column {p.column}: {p.numbers} numbers, {p.texts} texts, {p.empty} empty"
              + (f"; texts: {', '.join(p.distinct_texts)}" if p.distinct_texts else "") for p in table.profile]
    return "\n".join(lines)


def map_table(model: ChatModel, *, table: RedactedTable, check: Callable[[MappingSpec], tuple[Finding, ...]],
              max_turns: int = 4, log_step: Callable[[dict[str, Any]], None] = lambda step: None,
              context: str = "") -> TableMapping:
    """Ask the model for a mapping of one redacted table; code's `check` judges every proposal (module docstring).
    `context` (what else is known of the delivery) is appended to the user message: never a table's text."""
    ctx = _Mapping(check=check)
    tools = [
        Tool(name="propose_mapping", description="Propose how to read the table: a mapping spec v2. Code checks it on the "
             "table and answers ACCEPTED or REJECTED with what to fix.", parameters=_SPEC_TOOL,
             handler=lambda **kw: propose_mapping(ctx, **kw)),
        Tool(name="not_data", description="Say that the table holds no data (contents, instructions, a legend), and why.",
             parameters=_NOT_DATA_TOOL, handler=lambda **kw: not_data(ctx, **kw)),
    ]
    user = "Map this table.\n\n" + render(table)
    if context:
        user += f"\n\n{context}"
    outcome = run_tool_loop(model, system=SYSTEM_PROMPT, user=user, tools=tools, max_turns=max_turns, log_step=log_step)
    spec = ctx.accepted if outcome.status == "COMPLETED" else None
    return TableMapping(spec=spec, rejected=tuple(ctx.rejected), status=outcome.status, usage=dict(outcome.usage),
                        prompt_sha256=PROMPT_SHA256)
