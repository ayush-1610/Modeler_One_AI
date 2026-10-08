"""Mapping recipes: a confirmed, reusable description of how to read one client file layout.

A recipe is proposed by the Data Mapping agent or written by a person, confirmed by a person, and then
applied by deterministic code. The same layout arriving again is recognised by its header fingerprint
and read without AI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, Field, model_validator

RecordType = Literal["concentration_time", "dissolution"]
Statistic = Literal["individual", "arithmetic_mean", "geometric_mean", "median"]
ColumnRole = Literal["time", "value", "subject_id", "group", "sd", "n"]

DEFAULT_BELOW_LLOQ_TOKENS = ["BLQ", "BQL", "<LLOQ", "LLOQ", "NQ", "ND", "BLOQ"]

# The values a table states once for every row (coupling C9: the one list the recipe, its review, `apply` and the
# sheet form share). A proposal may name only these keys; the numeric ones are stored as numbers.
ConstantKey = Literal[
    "study_id", "analyte", "matrix", "dose", "dose_unit", "route", "formulation", "food_state", "n",
    "batch", "medium", "ph", "apparatus", "rpm", "product", "role", "strength_mg", "volume_ml",
]
CONSTANT_KEYS: tuple[str, ...] = get_args(ConstantKey)
NUMERIC_CONSTANTS = frozenset({"dose", "n", "ph", "rpm", "strength_mg", "volume_ml"})


class ColumnMapping(BaseModel):
    column: str = Field(pattern=r"^[A-Z]{1,3}$", description="Spreadsheet column letter")
    role: ColumnRole
    series_label: str | None = Field(
        default=None, description="For wide layouts: the subject, group or vessel this value column belongs to"
    )


class TableMapping(BaseModel):
    record_type: RecordType
    sheet: str
    header_rows: int = Field(ge=0, description="Rows above the data that form the header (used for the fingerprint)")
    first_data_row: int = Field(ge=1)
    last_data_row: int | None = Field(default=None, description="Inclusive; None stops at the first empty row")
    columns: list[ColumnMapping] = Field(min_length=2)
    time_row: int | None = Field(
        default=None, ge=1,
        description="Times across the top (one row per subject or vessel): the row that holds the sampling times; each "
        "value column then takes its time from that row. None: one row per time point, read from the time column",
    )
    time_unit: str
    value_unit: str = Field(description="Concentration unit, or '%' for dissolution")
    statistic: Statistic = "individual"
    lloq: float | None = Field(default=None, gt=0)
    below_lloq_tokens: list[str] = Field(default_factory=lambda: list(DEFAULT_BELOW_LLOQ_TOKENS))
    missing_tokens: list[str] = Field(default_factory=list, description="Cell texts that mean no sample (e.g. NS, NR, -): skipped")
    decimal_comma: bool = False
    constants: dict[str, str | float] = Field(
        default_factory=dict,
        description="Values that apply to every row: " + ", ".join(CONSTANT_KEYS),
    )

    @model_validator(mode="after")
    def _layout(self) -> TableMapping:
        roles = [c.role for c in self.columns]
        if self.time_row is None and roles.count("time") != 1:
            raise ValueError("exactly one time column is required (or time_row, for times across the top)")
        if self.time_row is not None:
            if "time" in roles:
                raise ValueError("with times across the top (time_row) the times come from that row: map no time column")
            if {"sd", "n"} & set(roles):
                raise ValueError("sd and n columns need one row per time point (times down a column)")
            if self.time_row >= self.first_data_row:
                raise ValueError("time_row must be above the first data row")
        if "value" not in roles:
            raise ValueError("at least one value column is required")
        return self


class MappingRecipe(BaseModel):
    recipe_id: str
    version: int = 1
    description: str = ""
    tables: list[TableMapping] = Field(min_length=1)
    fingerprints: dict[str, str] = Field(default_factory=dict, description="sheet -> header fingerprint, set on confirmation")
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None

    @property
    def confirmed(self) -> bool:
        return self.confirmed_by is not None and self.confirmed_at is not None
