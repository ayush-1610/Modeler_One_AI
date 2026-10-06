"""Canonical records produced from client files. Every record keeps the cells it was read from."""

from __future__ import annotations

from pydantic import BaseModel, Field

from modeler_intake.recipe import Statistic

DISSOLUTION_ROLES = ("TEST", "RLD", "REFERENCE", "SOLUTION", "OTHER")   # the client-data template's product roles


class SourceRef(BaseModel):
    file_sha256: str
    recipe_id: str
    recipe_version: int
    cells: dict[str, str] = Field(description="field -> sheet!A1 reference")


class ConcentrationObservation(BaseModel):
    study_id: str
    analyte: str
    matrix: str
    series: str
    statistic: Statistic
    time: float
    time_unit: str
    value: float | None
    unit: str
    below_lloq: bool = False
    lloq: float | None = None
    sd: float | None = None
    n: int | None = None
    dose: float | None = None
    dose_unit: str | None = None
    route: str | None = None
    formulation: str | None = None
    food_state: str | None = None
    source: SourceRef


class DissolutionObservation(BaseModel):
    batch: str
    medium: str
    product: str = ""
    role: str = ""                      # one of DISSOLUTION_ROLES; empty when the recipe does not name it
    strength_mg: float | None = None
    volume_ml: float | None = None
    ph: float | None = None
    apparatus: str | None = None
    rpm: float | None = None
    vessel: str
    time: float
    time_unit: str
    percent_dissolved: float
    source: SourceRef
