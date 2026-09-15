"""The engine catalog: what a specific engine image can build.

`harvest_catalog.R` exports one JSON per engine image (task T-02) describing the dimensions and units,
PK parameter names, species and populations the engine exposes, and — read from real OSP library
snapshots, never invented — the compound process types, formulation types, calculation methods,
expression-profile types and event templates it accepts, plus the simulation-level naming of process
selections. This module loads that JSON and answers the questions the CPF binding (T-03) and the builder
ask: does this image know this dimension/unit/process/PK parameter, and what are its parameter names.

The rule from the harvest carries through here: if the engine did not export it, the catalog does not
have it, and binding against it raises `NoEngineBindingError` instead of guessing.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def _norm(value: str | None) -> str | None:
    """Compatibility-fold for comparing engine units and names.

    NFKC so the MICRO SIGN (µ, U+00B5) the engine writes and the GREEK SMALL LETTER MU (μ, U+03BC) that
    literature and typed specs often use fold to the same unit; both sides of every comparison pass
    through here, so membership is stable regardless of which form a caller supplies.
    """
    return None if value is None else unicodedata.normalize("NFKC", value)


class NoEngineBindingError(LookupError):
    """A parameter, process, formulation, dimension or unit is not present in this engine's catalog."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class ParamSpec(_Model):
    name: str
    unit: str | None = None


class Dimension(_Model):
    name: str
    base_unit: str | None = None
    units: tuple[str, ...] = ()


class ProcessType(_Model):
    internal_name: str
    kind: str | None = None
    parameters: tuple[ParamSpec, ...] = ()
    seen_in: tuple[str, ...] = ()

    def parameter_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.parameters)


class FormulationType(_Model):
    internal_name: str
    parameters: tuple[ParamSpec, ...] = ()
    seen_in: tuple[str, ...] = ()


class CalculationMethods(_Model):
    compound: tuple[str, ...] = ()
    individual: tuple[str, ...] = ()


class ExpressionType(_Model):
    type: str
    fields: tuple[str, ...] = ()
    seen_in: tuple[str, ...] = ()


class EventTemplate(_Model):
    name: str
    seen_in: tuple[str, ...] = ()


class SelectionNaming(_Model):
    internal_name: str | None = None
    name: str | None = None
    molecule: str | None = None
    data_source: str | None = None
    systemic_process_type: str | None = None
    matches_molecule_dash_source: bool = False
    seen_in: str | None = None


class Fixture(_Model):
    name: str
    file: str
    sha256: str
    version: int | None = None
    roundtrip_ok: bool | None = None  # True/False on Linux; None when not verified (e.g. macOS harvest)


class EngineInfo(_Model):
    ospsuite: str
    parameter_identification: str | None = None
    rSharp: str | None = None
    r_version: str | None = None
    platform: str | None = None
    harvested_at: str | None = None
    snapshot_version: int | None = None


class Catalog(_Model):
    engine: EngineInfo
    dimensions: tuple[Dimension, ...] = ()
    pk_parameters: tuple[str, ...] = ()
    species: tuple[str, ...] = ()
    populations: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    process_types: tuple[ProcessType, ...] = ()
    formulation_types: tuple[FormulationType, ...] = ()
    calculation_methods: CalculationMethods = Field(default_factory=CalculationMethods)
    expression_types: tuple[ExpressionType, ...] = ()
    event_templates: tuple[EventTemplate, ...] = ()
    process_selection_naming: tuple[SelectionNaming, ...] = ()
    fixtures: tuple[Fixture, ...] = ()
    unresolved: tuple[str, ...] = ()

    # --- loading ---------------------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> Catalog:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    @classmethod
    def from_dict(cls, data: dict) -> Catalog:
        return cls.model_validate(data)

    # --- dimensions and units --------------------------------------------------------------------

    def _dimension(self, name: str) -> Dimension | None:
        target = _norm(name)
        return next((d for d in self.dimensions if _norm(d.name) == target), None)

    def has_dimension(self, name: str) -> bool:
        return self._dimension(name) is not None

    def units_for(self, dimension: str) -> tuple[str, ...]:
        dim = self._dimension(dimension)
        if dim is None:
            raise NoEngineBindingError(f"engine has no dimension {dimension!r}")
        return dim.units

    def is_unit(self, dimension: str, unit: str | None) -> bool:
        """True if `unit` is a valid unit of `dimension` in this engine.

        A dimensionless quantity is passed as None or "". The engine reports dimensionless by listing the
        empty-string unit "" among a dimension's units (e.g. Fraction = ["", "%"]); base_unit is not
        reported by ospsuite 12.4.4, so it is not relied on here.
        """
        dim = self._dimension(dimension)
        if dim is None:
            return False
        if unit is None or unit == "":
            return any(u == "" for u in dim.units)
        target = _norm(unit)
        return any(_norm(u) == target for u in dim.units)

    # --- processes, formulations, PK parameters --------------------------------------------------

    def process_type(self, internal_name: str) -> ProcessType | None:
        return next((p for p in self.process_types if p.internal_name == internal_name), None)

    def require_process_type(self, internal_name: str) -> ProcessType:
        found = self.process_type(internal_name)
        if found is None:
            raise NoEngineBindingError(
                f"engine catalog ({self.engine.ospsuite}) has no process type {internal_name!r}; "
                f"known: {', '.join(sorted(p.internal_name for p in self.process_types)) or '(none)'}"
            )
        return found

    def formulation_type(self, internal_name: str) -> FormulationType | None:
        return next((f for f in self.formulation_types if f.internal_name == internal_name), None)

    def require_formulation_type(self, internal_name: str) -> FormulationType:
        found = self.formulation_type(internal_name)
        if found is None:
            raise NoEngineBindingError(
                f"engine catalog ({self.engine.ospsuite}) has no formulation type {internal_name!r}; "
                f"known: {', '.join(sorted(f.internal_name for f in self.formulation_types)) or '(none)'}"
            )
        return found

    def has_pk_parameter(self, name: str) -> bool:
        return name in self.pk_parameters

    def has_species(self, species: str) -> bool:
        return species in self.species

    def has_population(self, species: str, population: str) -> bool:
        return population in self.populations.get(species, ())

    def has_calculation_method(self, method: str, *, kind: str) -> bool:
        if kind == "compound":
            return method in self.calculation_methods.compound
        if kind == "individual":
            return method in self.calculation_methods.individual
        raise ValueError(f"kind must be 'compound' or 'individual', got {kind!r}")

    # --- naming convention -----------------------------------------------------------------------

    def selection_pattern_confirmed(self) -> bool:
        """True if every harvested molecule-based process is named ``{molecule}-{data_source}``.

        This is the convention `validation.process_selection_for` relies on. If a future engine breaks
        it, this returns False and the observations are in `process_selection_naming` for inspection.
        """
        molecule_based = [
            s for s in self.process_selection_naming if s.molecule not in (None, "") and s.name is not None
        ]
        return bool(molecule_based) and all(s.matches_molecule_dash_source for s in molecule_based)

    # --- provenance ------------------------------------------------------------------------------

    def check_units(self, quantities: Iterable[tuple[str, str, str | None]]) -> list[str]:
        """Return one message per (label, dimension, unit) whose unit is not valid for the dimension."""
        problems = []
        for label, dimension, unit in quantities:
            if not self.is_unit(dimension, unit):
                problems.append(f"{label}: {unit!r} is not a unit of {dimension!r} in engine {self.engine.ospsuite}")
        return problems
