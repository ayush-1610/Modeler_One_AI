"""Data Mapping Agent: proposes how to read a client spreadsheet.

Claude proposes a mapping recipe; deterministic code applies and validates it; a person confirms before the
recipe is saved and reused. Every unit, LLOQ, dose or study identifier the model reports must cite a cell
whose text contains the quoted evidence, otherwise the proposal is flagged. Anything the file does not state
becomes a question for the reviewer instead of a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from openpyxl.utils.cell import coordinate_from_string
from pydantic import BaseModel, Field, ValidationError

from modeler_agents.citations import normalize_for_match
from modeler_intake.apply import apply_recipe
from modeler_intake.grid import WorkbookGrid, as_text
from modeler_intake.recipe import (
    DEFAULT_BELOW_LLOQ_TOKENS,
    ColumnMapping,
    ColumnRole,
    MappingRecipe,
    RecordType,
    Statistic,
    TableMapping,
)
from modeler_intake.records import ConcentrationObservation, DissolutionObservation
from modeler_intake.validate import validate_concentrations, validate_dissolution
from pbpk_domain.issues import Issue

ConstantKey = Literal[
    "study_id", "analyte", "matrix", "dose", "dose_unit", "route", "formulation", "food_state", "n",
    "batch", "medium", "ph", "apparatus", "rpm",
]
NUMERIC_CONSTANTS = {"dose", "n", "ph", "rpm"}

SYSTEM_PROMPT = """You read laboratory and clinical spreadsheets for a PBPK modeling platform and describe, as a mapping recipe, where the concentration-time or dissolution data are and how to read them.

The sheets are shown with 1-based row numbers and column letters. A deterministic program will apply your recipe exactly as written, and a scientist will review the result before it is used, so describe the file as it is.

- Use only information present in the file for units, LLOQ, dose, study identifier, analyte, matrix, batch, medium, pH and apparatus. For each of these, add an evidence entry with the cell reference and the exact text from that cell.
- If something needed is not in the file (for example the LLOQ, the dose, or the number of subjects behind mean values), leave it empty and add a question for the reviewer. Do not infer it.
- Wide layouts, with one column per subject or vessel: one value column per subject or vessel, with series_label set to its identifier from the header.
- Long layouts: map the subject or group column with role subject_id or group.
- If the sheet reports individual values and also mean/SD columns, map only the individual values. If it reports only aggregated values, set statistic accordingly and map the SD and N columns when present.
- The data block ends at the first empty row. If footnotes or summary rows follow without an empty row, set last_data_row.
- Text such as BLQ or <0.5 in value cells marks values below the limit of quantification; list the tokens used in the file."""


class Evidence(BaseModel):
    cell: str = Field(description="Cell reference such as PK_SAD!A12")
    quote: str = Field(description="Exact text from that cell")
    supports: str = Field(description="What the text supports, e.g. 'value unit ng/mL' or 'LLOQ 0.5 ng/mL'")


class ConstantProposal(BaseModel):
    key: ConstantKey
    value: str


class ColumnProposal(BaseModel):
    column: str
    role: ColumnRole
    series_label: str | None = None


class TableProposal(BaseModel):
    record_type: RecordType
    sheet: str
    header_rows: int
    first_data_row: int
    last_data_row: int | None = None
    columns: list[ColumnProposal]
    time_unit: str
    value_unit: str
    statistic: Statistic = "individual"
    lloq: float | None = None
    below_lloq_tokens: list[str] = Field(default_factory=list)
    decimal_comma: bool = False
    constants: list[ConstantProposal] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class RecipeProposal(BaseModel):
    tables: list[TableProposal]
    questions_for_reviewer: list[str] = Field(default_factory=list)


@dataclass
class MappingReview:
    recipe: MappingRecipe | None
    concentrations: list[ConcentrationObservation] = field(default_factory=list)
    dissolution: list[DissolutionObservation] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    @property
    def ready_for_confirmation(self) -> bool:
        return self.recipe is not None and not self.issues and not self.questions


def to_recipe(proposal: RecipeProposal, recipe_id: str, description: str = "") -> MappingRecipe:
    tables = []
    for table in proposal.tables:
        constants: dict[str, str | float] = {
            c.key: float(c.value) if c.key in NUMERIC_CONSTANTS else c.value for c in table.constants
        }
        tables.append(
            TableMapping(
                record_type=table.record_type,
                sheet=table.sheet,
                header_rows=table.header_rows,
                first_data_row=table.first_data_row,
                last_data_row=table.last_data_row,
                columns=[ColumnMapping(**c.model_dump()) for c in table.columns],
                time_unit=table.time_unit,
                value_unit=table.value_unit,
                statistic=table.statistic,
                lloq=table.lloq,
                below_lloq_tokens=table.below_lloq_tokens or list(DEFAULT_BELOW_LLOQ_TOKENS),
                decimal_comma=table.decimal_comma,
                constants=constants,
            )
        )
    return MappingRecipe(recipe_id=recipe_id, description=description, tables=tables)


def check_evidence(workbook: WorkbookGrid, proposal: RecipeProposal) -> list[Issue]:
    issues = []
    for table in proposal.tables:
        for item in table.evidence:
            sheet, _, coordinate = item.cell.partition("!")
            if sheet not in workbook.sheets or not coordinate:
                issues.append(Issue("INVALID_EVIDENCE", item.cell, "cell reference does not exist in the file"))
                continue
            column, row = coordinate_from_string(coordinate)
            text = as_text(workbook.sheets[sheet].cell(row, column).value)
            if not normalize_for_match(item.quote) or normalize_for_match(item.quote) not in normalize_for_match(text):
                issues.append(Issue("INVALID_EVIDENCE", item.cell, f"cell text does not contain {item.quote!r} (supports: {item.supports})"))
    return issues


def review_proposal(workbook: WorkbookGrid, proposal: RecipeProposal, recipe_id: str) -> MappingReview:
    """Apply and validate a proposal without saving it. The reviewer sees records, issues and open questions."""
    try:
        recipe = to_recipe(proposal, recipe_id)
    except (ValidationError, ValueError) as exc:
        return MappingReview(None, issues=[Issue("INVALID_RECIPE", recipe_id, str(exc))], questions=proposal.questions_for_reviewer)

    issues = check_evidence(workbook, proposal)
    try:
        result = apply_recipe(workbook, recipe)
    except KeyError as exc:
        return MappingReview(None, issues=[*issues, Issue("UNKNOWN_SHEET", recipe_id, str(exc))], questions=proposal.questions_for_reviewer)

    issues += result.issues + validate_concentrations(result.concentrations) + validate_dissolution(result.dissolution)
    fingerprints = {t.sheet: workbook.header_fingerprint(t.sheet, t.header_rows) for t in recipe.tables}
    return MappingReview(
        recipe=recipe.model_copy(update={"fingerprints": fingerprints}),
        concentrations=result.concentrations,
        dissolution=result.dissolution,
        issues=issues,
        questions=proposal.questions_for_reviewer,
    )


def propose_mapping(workbook: WorkbookGrid, llm: Any, *, recipe_id: str, context: str = "") -> MappingReview:
    sheets = "\n\n".join(f"## Sheet: {name}\n{grid.preview(max_rows=80, max_columns=26)}" for name, grid in workbook.sheets.items())
    response = llm.client.messages.parse(
        model=llm.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"File: {workbook.file_name}\n{context}\n\n{sheets}".strip()}],
        output_format=RecipeProposal,
        **llm.request_options,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return MappingReview(None, issues=[Issue("NO_PROPOSAL", workbook.file_name, f"model stopped with {response.stop_reason}")])
    return review_proposal(workbook, response.parsed_output, recipe_id)
