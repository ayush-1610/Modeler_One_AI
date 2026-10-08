"""Review of a proposed mapping recipe: applied and validated by code, never saved here.

A proposal comes from the Data Mapping agent (`modeler_agents.data_mapping`) or from the guided sheet form
(`sheet_form.to_proposal`). Every unit, LLOQ, dose or study identifier it reports must cite a cell whose text contains
the quoted evidence, otherwise the proposal is flagged. A person confirms the recipe before it is saved and reused.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openpyxl.utils.cell import coordinate_from_string
from pydantic import BaseModel, Field, ValidationError

from modeler_intake.apply import apply_recipe
from modeler_intake.citations import normalize_for_match
from modeler_intake.grid import WorkbookGrid, as_text
from modeler_intake.recipe import (
    DEFAULT_BELOW_LLOQ_TOKENS,
    NUMERIC_CONSTANTS,
    ColumnMapping,
    ColumnRole,
    ConstantKey,
    MappingRecipe,
    RecordType,
    Statistic,
    TableMapping,
)
from modeler_intake.records import ConcentrationObservation, DissolutionObservation
from modeler_intake.validate import validate_concentrations, validate_dissolution
from pbpk_domain.issues import Issue


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
    time_row: int | None = None
    time_unit: str
    value_unit: str
    statistic: Statistic = "individual"
    lloq: float | None = None
    below_lloq_tokens: list[str] = Field(default_factory=list)
    missing_tokens: list[str] = Field(default_factory=list)
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
        constants: dict[str, str | float] = {}
        for c in table.constants:
            if not c.value.strip():
                continue  # a blank constant is one the sheet does not state
            try:
                constants[c.key] = float(c.value) if c.key in NUMERIC_CONSTANTS else c.value
            except ValueError as exc:
                raise ValueError(f"{table.sheet}: constant {c.key} must be a number, not {c.value!r}") from exc
        tables.append(
            TableMapping(
                record_type=table.record_type,
                sheet=table.sheet,
                header_rows=table.header_rows,
                first_data_row=table.first_data_row,
                last_data_row=table.last_data_row,
                columns=[ColumnMapping(**c.model_dump()) for c in table.columns],
                time_row=table.time_row,
                time_unit=table.time_unit,
                value_unit=table.value_unit,
                statistic=table.statistic,
                lloq=table.lloq,
                below_lloq_tokens=table.below_lloq_tokens or list(DEFAULT_BELOW_LLOQ_TOKENS),
                missing_tokens=table.missing_tokens,
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
