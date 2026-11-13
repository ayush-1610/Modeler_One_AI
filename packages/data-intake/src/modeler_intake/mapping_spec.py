"""Mapping spec v2 and what executing it gives (docs/plans/2026-11-12-intake-contracts.md §4.4). Models only.

A new model beside `recipe.py`: the v1 recipe, `apply.py` and stored recipes are untouched and stay readable. Every
coordinate is RELATIVE TO THE REGION: a cell is (row, column) with row 1, column 1 its top-left; a line of its context
is (`near`, `line`). No `Cite` holds an absolute locator, so a cached spec reads each new region's own cells and lines,
does not depend on the sheet name or on where the table sits, and one executor serves sheet, PDF and Word tables.

The LLM's only table output is a `MappingSpec`; code executes it (D3). The model never types a number: a constant's
value is ALWAYS what code reads from the cited text on each use, and a unit is the unit token code finds at its cite.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modeler_intake.fields import DocumentRole, IntervalKind, SpreadKind, Statistic, TableKind
from modeler_intake.source_model import Finding

Layout = Literal["long", "wide_series", "wide_times", "key_value"]
# long: one row per value; a record table (one row per study or product, one column per field: the template's Studies
# and Product sheets) is long with one value column per field. wide_series: times down a column, one value column per
# series. wide_times: times across the header (time_row), one row per series. key_value: a label column says what each
# row is (keys).
Role = Literal["time", "time_actual", "time_unit", "value", "spread", "spread_kind", "statistic", "n", "lloq", "blq_flag",
               "interval_low", "interval_high", "subject", "arm", "period", "sequence", "occasion", "study", "analyte",
               "matrix", "product", "batch", "vessel", "other_arm", "parameter", "condition", "unit", "ignore"]
# time: the nominal time; time_actual: the actual sampling time beside it; time_unit, unit, statistic, spread_kind,
# blq_flag: a column that states it row by row (the template's time_unit, unit, statistic, variability_kind, blq_flag)
CellForm = Literal["value", "value (spread)", "value ± spread", "value (low-high)", "value unit"]


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Cite(_B):
    """Where a thing is stated, relative to the region: exactly one of (row and column) or near."""

    row: int | None = None                  # a cell of the region
    column: int | None = None
    near: Literal["caption", "above", "below"] | None = None     # a context line
    line: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def _one_place(self) -> Cite:
        cell = self.row is not None and self.column is not None
        if cell == (self.near is not None) or (not cell and (self.row is not None or self.column is not None)):
            raise ValueError("a cite is a cell (row and column) or a context line (near and line), exactly one")
        return self


class ColumnMap(_B):
    column: int
    role: Role
    field: str | None = None                # a value column's field; None: MappingSpec.field
    condition: str | None = None            # role condition, or series_role condition: a fields.CONDITION_FIELDS name
    unit: str | None = None                 # per-column unit: must be a unit code finds at the cite
    unit_cite: Cite | None = None
    statistic: Statistic | None = None
    spread_kind: SpreadKind | None = None
    of: int | None = None                   # spread, n, lloq, interval_*: the value column they qualify
    cell_form: CellForm = "value"           # a value cell that also writes its spread, interval or unit: code splits it
    lloq: Cite | None = None                # this column's own LLOQ (a metabolite's assay); wins over MappingSpec.lloq
    level: Cite | None = None               # interval columns and "value (low-high)": where the CI level is written
    series: Cite | None = None              # wide_series: the header cell naming this column
    series_role: Role | None = None
    reason: str = ""                        # role ignore: why its cells are not data


class RowRule(_B):
    """Rows told apart by the text of one of their cells (fullmatch, case-insensitive)."""

    column: int
    pattern: str
    role: Literal["exclude", "arithmetic_mean", "geometric_mean", "median", "spread", "n", "interval_low", "interval_high"]
    spread_kind: SpreadKind | None = None
    reason: str = ""                        # required for exclude


class KeyMap(_B):
    pattern: str
    field: str
    statistic: Statistic | None = None
    spread_kind: SpreadKind | None = None


class Constant(_B):
    """A fact stated once for the whole table: a title's study id and dose, a footnote's LLOQ."""

    field: str
    cite: Cite
    # name and text fields: a regex with one group that must match the cited text exactly once (its group is the value);
    # None: the whole cited text. Never for a number (read_constant) or a choice (fields.read_choice)
    pattern: str | None = None
    # the model's reading of a name or choice: compared with code's at proposal (CONSTANT_NOT_STATED), then dropped:
    # MappingCache stores the spec with text None, and the value is ALWAYS what code reads from the cited text on each use
    text: str | None = None


class MappingSpec(_B):
    # read by its alias or its name: a body dumped without by_alias reads back too (canonical() writes the alias)
    model_config = ConfigDict(frozen=True, extra="forbid", validate_by_name=True)

    schema_id: Literal["mapping/2"] = Field(default="mapping/2", alias="schema")
    kind: TableKind
    layout: Layout
    header_rows: int = Field(ge=0)
    first_data_row: int = Field(ge=1)
    last_data_row: int | None = None                             # None: the region's end
    columns: tuple[ColumnMap, ...] = ()
    time_row: int | None = None                                  # wide_times
    keys: tuple[KeyMap, ...] = ()                                # key_value
    field: str | None = None                                     # default field of the value columns
    time_unit: str | None = None
    time_unit_cite: Cite | None = None
    value_unit: str | None = None
    value_unit_cite: Cite | None = None
    time_reference: Literal["first_dose", "last_dose", "occasion_dose"] | None = None
    time_reference_cite: Cite | None = None
    # None: not stated; code sets "individual" only for a table with a subject column, never by default
    statistic: Statistic | None = None
    lloq: Cite | None = None                                     # one LLOQ for the table: code reads number and unit
    below_lloq_tokens: tuple[str, ...] = ()
    missing_tokens: tuple[str, ...] = ()                         # the decimal convention is code's, per region (§6.2)
    row_rules: tuple[RowRule, ...] = ()
    constants: tuple[Constant, ...] = ()
    not_data_reason: str = ""                                    # required when kind == "not_data"
    questions: tuple[str, ...] = ()


class ExtractedRow(_B):
    """One value, long form, with the locator of every cell it was read from."""

    field: str
    # role -> the label as written: study, arm, period, sequence, occasion, subject, analyte, matrix, product, batch,
    # vessel, other_arm
    labels: dict[str, str]
    label_locators: dict[str, str] = Field(default_factory=dict)          # role -> the cell (or context line) that wrote it
    conditions: dict[str, str] = Field(default_factory=dict)              # CONDITION_FIELDS name -> as written (2 media,
    condition_locators: dict[str, str] = Field(default_factory=dict)      # 2 intervals, 2 pH: never a conflict)
    time: float | None = None                                             # nominal time
    time_unit: str | None = None
    time_locator: str | None = None
    time_actual: float | None = None
    time_actual_locator: str | None = None
    value: float | None = None
    text_value: str | None = None
    verbatim: str
    locator: str
    unit: str | None = None
    unit_locator: str | None = None
    censored: bool = False
    lloq: float | None = None
    lloq_unit: str | None = None
    lloq_locator: str | None = None
    uloq: float | None = None                                             # above the range (">1000"): value None, the limit kept
    statistic: Statistic | None = None
    spread: float | None = None
    spread_kind: SpreadKind | None = None
    spread_verbatim: str | None = None
    spread_locator: str | None = None
    interval: tuple[float, float] | None = None
    interval_kind: IntervalKind | None = None
    interval_level: float | None = None
    interval_locators: tuple[str, str] | None = None
    n: int | None = None
    n_locator: str | None = None


class ExtractedConstant(_B):
    # a constant of a condition field goes into every row's conditions, of a label field (matrix ...) into every row's
    # labels, with its locator; only the others are listed here (D4 writes them as scalar facts)
    field: str
    value: float | str
    unit: str | None = None
    verbatim: str
    locator: str


class CellUse(_B):
    row: int
    column: int
    locator: str
    numeric: bool                           # has_number(text); a merged copy is never numeric (its origin counts once)
    use: Literal["value", "time", "spread", "n", "lloq", "interval", "label", "condition", "header", "constant", "unit",
                 "missing", "excluded", "unaccounted"]
    rule: str = ""                          # which rule or token put it there ("missing_token:NS", "row_rule:cv ?%", "column:ignore")


class ExtractResult(_B):
    rows: tuple[ExtractedRow, ...]
    constants: tuple[ExtractedConstant, ...]
    cell_use: tuple[CellUse, ...]           # one entry for EVERY non-empty cell of the region (in memory; stored compactly)
    cited: tuple[str, ...] = ()             # the context lines' locators the constants read (they leave the outside count)
    decimal: Literal["point", "comma"] = "point"     # the region's convention, decided by code
    findings: tuple[Finding, ...]


class MappingError(ValueError):
    """A spec that cannot be executed on this grid (an error-severity finding of validate_spec)."""


class ColumnProfile(_B):
    column: int
    numbers: int
    texts: int
    empty: int
    distinct_texts: tuple[str, ...]         # at most 12, redacted


class ContextLine(_B):
    near: Literal["caption", "above", "below"]
    line: int
    text: str                               # verbatim, at most 200 characters


class RedactedTable(_B):
    """Everything the table mapper is shown of one table."""

    region_id: str
    file_name: str
    document_role: DocumentRole
    kind_by_rule: TableKind
    n_rows: int
    n_cols: int
    # the caption and the lines above and below (RegionGrid's): the model cites a constant by its (near, line), code reads it
    context: tuple[ContextLine, ...]
    header_rows: int
    header: tuple[tuple[str, ...], ...]                                     # the header band (§6.2), bare numbers redacted
    body_rows: tuple[int, ...]
    body: tuple[tuple[str, ...], ...]                                       # the first 5 and last 3 body rows, redacted
    profile: tuple[ColumnProfile, ...]                                      # over all body rows


class ProseParagraph(_B):
    index: int
    text: str
    locator: str                            # a `range` of §4.1; never a table's text
    heading: str = ""                       # the heading above it, where a label may stand
    heading_locator: str | None = None


class ProseFact(_B):
    field: str
    value: float | str                      # the value CODE parsed from the clause (§6.2), never the model's
    unit: str | None = None                 # parsed by code from the clause
    quote: str
    study_label: str | None = None
    arm_label: str | None = None
    locator: str                            # the span of the value itself inside the paragraph
    study_locator: str | None = None        # the spans where the labels are written
    arm_locator: str | None = None


# field, value, quote, paragraph, study, arm
ProseCheck = Callable[[str, Any, str, int, str | None, str | None], ProseFact]
