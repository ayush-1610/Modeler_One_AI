"""The CPF document and its parameter record (MS-01 §2.1).

A ParameterRecord is one row of §2.2: an identifier, a value in the unit PK-Sim stores, a status, an
optional fit policy (which stages may fit it and within which bounds), a plausibility range that fitting
must never exceed, provenance, and the engine binding that says where the value lives in a PK-Sim
snapshot. The CPF is an immutable, versioned collection of these records for one compound; any change
produces a new version with a higher number, so the history of every value is a chain of versions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ParameterStatus(str, Enum):
    FIXED = "FIXED"          # measured/known; never fitted
    FITTED = "FITTED"        # identified by parameter identification
    DERIVED = "DERIVED"      # computed by PK-Sim from other parameters
    PREDICTED = "PREDICTED"  # in silico prediction; may be fitted if a policy allows
    MISSING = "MISSING"      # not yet available (blocks S0 if required)


class Scale(str, Enum):
    LINEAR = "linear"
    LOG = "log"


class FitPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: tuple[str, ...] = ()  # stages where this parameter may be fitted, e.g. ("S1", "S2")
    lower: float
    upper: float
    scale: Scale = Scale.LINEAR

    @model_validator(mode="after")
    def _bounds(self) -> FitPolicy:
        if not self.lower < self.upper:
            raise ValueError("fit policy lower bound must be below upper bound")
        if self.scale is Scale.LOG and self.lower <= 0:
            raise ValueError("log-scaled fit policy needs a positive lower bound")
        return self


class Plausibility(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lower: float
    upper: float
    source: str = ""

    @model_validator(mode="after")
    def _bounds(self) -> Plausibility:
        if not self.lower < self.upper:
            raise ValueError("plausibility lower bound must be below upper bound")
        return self


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: str  # e.g. "measured", "predicted", "ParameterIdentification", "IVIVE", "client"
    reference: str | None = None
    run: str | None = None
    supersedes: str | None = None  # id/version of the value this one replaced


class Uncertainty(BaseModel):
    """A fitted parameter's precision, from the parameter identification's confidence-interval estimate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sd: float | None = None
    cv_percent: float | None = None
    ci95_lower: float | None = None
    ci95_upper: float | None = None
    method: str = "hessian"


class EngineBinding(BaseModel):
    """Where a parameter lives in a PK-Sim snapshot (MS-01 §2.1).

    `building_block` is Compound/Individual/Formulation/Protocol. For a compound process the `process`
    field carries the process internal name and, for molecule-based processes, the molecule after a
    colon, e.g. "MetabolizationSpecific_FirstOrder:CYP3A4"; `parameter` is the engine parameter name.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    building_block: str
    parameter: str
    process: str | None = None
    data_source: str | None = None

    @property
    def process_internal_name(self) -> str | None:
        if self.process is None:
            return None
        return self.process.split(":", 1)[0]

    @property
    def molecule(self) -> str | None:
        if self.process is None or ":" not in self.process:
            return None
        return self.process.split(":", 1)[1]


class ParameterRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    value: float | str | None = None  # numeric for quantities; a string for categorical params (methods, partner)
    unit: str | None = None            # the unit PK-Sim stores this in; None means dimensionless or categorical
    status: ParameterStatus
    fitted_at_stage: str | None = None
    fit_policy: FitPolicy | None = None
    plausibility: Plausibility | None = None
    provenance: Provenance | None = None
    engine_binding: EngineBinding | None = None
    uncertainty: Uncertainty | None = None  # set when the value was fitted: SD, CV and 95 % CI (MS-01 S4 table)

    @model_validator(mode="after")
    def _consistency(self) -> ParameterRecord:
        if self.status is ParameterStatus.MISSING:
            if self.value is not None:
                raise ValueError(f"{self.id}: MISSING parameter must not carry a value")
        elif self.value is None:
            raise ValueError(f"{self.id}: {self.status.value} parameter must carry a value")
        if (
            self.fit_policy is not None
            and self.plausibility is not None
            and (self.fit_policy.lower < self.plausibility.lower or self.fit_policy.upper > self.plausibility.upper)
        ):
            raise ValueError(f"{self.id}: fit policy bounds must lie within the plausibility range")
        return self

    @property
    def numeric_value(self) -> float:
        if not isinstance(self.value, int | float):
            raise TypeError(f"{self.id}: value {self.value!r} is not numeric")
        return float(self.value)

    @property
    def is_fittable(self) -> bool:
        return self.fit_policy is not None and bool(self.fit_policy.stage)

    def fittable_at(self, stage: str) -> bool:
        return self.fit_policy is not None and stage in self.fit_policy.stage


class CPF(BaseModel):
    """An immutable, versioned parameter document for one compound."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    compound: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    parameters: tuple[ParameterRecord, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    note: str | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> CPF:
        ids = [p.id for p in self.parameters]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate parameter ids in CPF: {', '.join(sorted(dupes))}")
        return self

    def get(self, param_id: str) -> ParameterRecord | None:
        return next((p for p in self.parameters if p.id == param_id), None)

    def require(self, param_id: str) -> ParameterRecord:
        found = self.get(param_id)
        if found is None:
            raise KeyError(f"CPF for {self.compound} has no parameter {param_id!r}")
        return found

    def with_prefix(self, prefix: str) -> tuple[ParameterRecord, ...]:
        return tuple(p for p in self.parameters if p.id == prefix or p.id.startswith(prefix + "."))

    def replace(self, *records: ParameterRecord, note: str | None = None) -> CPF:
        """Return a new CPF (version + 1) with the given records replacing same-id records (or added)."""
        by_id = {p.id: p for p in self.parameters}
        for r in records:
            by_id[r.id] = r
        return CPF(
            compound=self.compound,
            version=self.version + 1,
            parameters=tuple(by_id.values()),
            note=note,
        )

    def fittable_at(self, stage: str) -> tuple[ParameterRecord, ...]:
        return tuple(p for p in self.parameters if p.fittable_at(stage))

    @staticmethod
    def json_schema() -> dict:
        return CPF.model_json_schema()

    @staticmethod
    def write_json_schema(path) -> None:
        from pathlib import Path

        Path(path).write_text(json.dumps(CPF.model_json_schema(), indent=2), encoding="utf-8")
