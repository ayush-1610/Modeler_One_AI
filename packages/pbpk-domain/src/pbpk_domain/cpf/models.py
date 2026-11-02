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
from typing import Literal

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


class FitGroup(BaseModel):
    """Parameters fitted as one (PI-4 B, docs/plans/2026-11-02-pi-4b-relative-group.md): each member is simulated at
    f x its current value, so the split between them is kept and the data estimate only the factor f ("Use as Factor"
    in the OSP desktop). A person chooses a group and signs it with the MAP: why the members are fitted as one
    (``reason``) and where their split comes from (``split_source``, e.g. the in vitro fractions metabolised). The
    factor's bounds contain 1, the members' current values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    members: tuple[str, ...] = Field(min_length=2)
    lower: float = 0.1
    upper: float = 10.0
    scale: Scale = Scale.LOG
    reason: str = Field(min_length=1)
    split_source: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> FitGroup:
        if len(set(self.members)) != len(self.members):
            raise ValueError(f"fit group {self.name!r} names a member twice")
        if not 0 < self.lower <= 1 <= self.upper or self.lower == self.upper:
            raise ValueError(f"fit group {self.name!r}: its factor's bounds must satisfy 0 < lower <= 1 <= upper "
                             f"(the members' current values are factor 1), not [{self.lower:g}, {self.upper:g}]")
        return self


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: str  # e.g. "measured", "predicted", "ParameterIdentification", "IVIVE", "client"
    reference: str | None = None
    run: str | None = None
    supersedes: str | None = None  # id/version of the value this one replaced
    method: str | None = None      # PK-Sim ValueOrigin.Method (harvested values only: InVitro, InVivo, Assumption …)
    evidence: str | None = None    # the accepted evidence item (id@version) the value came from (P4 assembly)


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
    Individual, Simulation and ExpressionProfile bindings carry the full PK-Sim path in `parameter`. A Simulation
    binding's `route` limits it to the simulations dosed that way (the published model sets it only there).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    building_block: str
    parameter: str
    process: str | None = None
    data_source: str | None = None
    route: Literal["oral", "iv"] | None = None

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
    # parameters fitted as one through a factor (PI-4 B2): chosen by a person, signed with the MAP
    fit_groups: tuple[FitGroup, ...] = ()

    @model_validator(mode="after")
    def _unique_ids(self) -> CPF:
        ids = [p.id for p in self.parameters]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate parameter ids in CPF: {', '.join(sorted(dupes))}")
        names = [g.name for g in self.fit_groups]
        if len(set(names)) != len(names):
            raise ValueError("two fit groups share a name")
        if clash := set(names) & set(ids):
            raise ValueError(f"a fit group is named like a parameter: {', '.join(sorted(clash))}")
        seen: dict[str, str] = {}
        for group in self.fit_groups:
            for member in group.members:
                if member not in ids:
                    raise ValueError(f"fit group {group.name!r}: no parameter {member!r} in the CPF")
                if member in seen:
                    raise ValueError(f"{member} is in two fit groups ({seen[member]}, {group.name})")
                seen[member] = group.name
        return self

    def group_of(self, param_id: str) -> FitGroup | None:
        return next((g for g in self.fit_groups if param_id in g.members), None)

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
            fit_groups=self.fit_groups,
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
