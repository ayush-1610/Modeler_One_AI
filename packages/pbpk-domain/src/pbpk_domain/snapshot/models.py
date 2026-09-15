"""Typed view over the PK-Sim project snapshot JSON.

Field names and aliases mirror snapshots written by PK-Sim 12.x (``Version`` 80), checked
against the OSP library Dapagliflozin model. Every model allows extra keys so that a
parse -> dump round trip is lossless for fields not typed here (for example the v13
top-level ``ApplicationName`` or building-block keys we do not use yet).

Serialize with :meth:`SnapshotModel.to_json_dict`, which only emits fields that were set,
so a dump never introduces keys PK-Sim did not write.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SnapshotModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_unset=True)


class ValueOrigin(SnapshotModel):
    source: str | None = Field(default=None, alias="Source")
    method: str | None = Field(default=None, alias="Method")
    description: str | None = Field(default=None, alias="Description")


class Quantity(SnapshotModel):
    value: float = Field(alias="Value")
    unit: str | None = Field(default=None, alias="Unit")


class Parameter(SnapshotModel):
    """A parameter addressed either by ``Name`` (inside a building block) or by ``Path``."""

    name: str | None = Field(default=None, alias="Name")
    path: str | None = Field(default=None, alias="Path")
    value: float | None = Field(default=None, alias="Value")
    unit: str | None = Field(default=None, alias="Unit")
    value_origin: ValueOrigin | None = Field(default=None, alias="ValueOrigin")


class ParameterAlternative(SnapshotModel):
    """A named alternative of a compound property group (e.g. Lipophilicity 'Optimized')."""

    name: str = Field(alias="Name")
    species: str | None = Field(default=None, alias="Species")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class PkaType(SnapshotModel):
    type: str = Field(alias="Type")  # "Acid" | "Base"
    pka: float = Field(alias="Pka")
    value_origin: ValueOrigin | None = Field(default=None, alias="ValueOrigin")


class CompoundProcess(SnapshotModel):
    internal_name: str = Field(alias="InternalName")
    data_source: str | None = Field(default=None, alias="DataSource")
    molecule: str | None = Field(default=None, alias="Molecule")
    metabolite: str | None = Field(default=None, alias="Metabolite")
    species: str | None = Field(default=None, alias="Species")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class Compound(SnapshotModel):
    name: str = Field(alias="Name")
    is_small_molecule: bool | None = Field(default=None, alias="IsSmallMolecule")
    plasma_protein_binding_partner: str | None = Field(default=None, alias="PlasmaProteinBindingPartner")
    lipophilicity: list[ParameterAlternative] = Field(default_factory=list, alias="Lipophilicity")
    fraction_unbound: list[ParameterAlternative] = Field(default_factory=list, alias="FractionUnbound")
    solubility: list[ParameterAlternative] = Field(default_factory=list, alias="Solubility")
    intestinal_permeability: list[ParameterAlternative] = Field(default_factory=list, alias="IntestinalPermeability")
    permeability: list[ParameterAlternative] = Field(default_factory=list, alias="Permeability")
    pka_types: list[PkaType] = Field(default_factory=list, alias="PkaTypes")
    processes: list[CompoundProcess] = Field(default_factory=list, alias="Processes")
    calculation_methods: list[str] = Field(default_factory=list, alias="CalculationMethods")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class OriginData(SnapshotModel):
    calculation_methods: list[str] = Field(default_factory=list, alias="CalculationMethods")
    species: str = Field(alias="Species")
    population: str | None = Field(default=None, alias="Population")
    gender: str | None = Field(default=None, alias="Gender")
    age: Quantity | None = Field(default=None, alias="Age")


class Individual(SnapshotModel):
    name: str = Field(alias="Name")
    seed: int | None = Field(default=None, alias="Seed")
    origin_data: OriginData = Field(alias="OriginData")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")
    expression_profiles: list[str] = Field(default_factory=list, alias="ExpressionProfiles")


class ExpressionProfile(SnapshotModel):
    type: str = Field(alias="Type")  # "Enzyme", "Transporter", ...
    species: str = Field(alias="Species")
    molecule: str = Field(alias="Molecule")
    category: str = Field(alias="Category")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")
    localization: str | None = Field(default=None, alias="Localization")
    ontogeny: dict[str, Any] | None = Field(default=None, alias="Ontogeny")

    @property
    def reference_name(self) -> str:
        """Name used by ``Individuals[].ExpressionProfiles`` to reference this profile."""
        return expression_profile_reference(self.molecule, self.species, self.category)


def expression_profile_reference(molecule: str, species: str, category: str) -> str:
    return f"{molecule}|{species}|{category}"


class Formulation(SnapshotModel):
    name: str = Field(alias="Name")
    formulation_type: str = Field(alias="FormulationType")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class SchemaItem(SnapshotModel):
    name: str = Field(alias="Name")
    application_type: str = Field(alias="ApplicationType")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class Schema(SnapshotModel):
    name: str = Field(alias="Name")
    schema_items: list[SchemaItem] = Field(default_factory=list, alias="SchemaItems")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class Protocol(SnapshotModel):
    """Simple protocols carry ``ApplicationType`` + ``Parameters``; advanced ones carry ``Schemas``."""

    name: str = Field(alias="Name")
    application_type: str | None = Field(default=None, alias="ApplicationType")
    dosing_interval: str | None = Field(default=None, alias="DosingInterval")
    time_unit: str | None = Field(default=None, alias="TimeUnit")
    schemas: list[Schema] = Field(default_factory=list, alias="Schemas")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class Event(SnapshotModel):
    name: str = Field(alias="Name")
    template: str | None = Field(default=None, alias="Template")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class AlternativeSelection(SnapshotModel):
    alternative_name: str = Field(alias="AlternativeName")
    group_name: str = Field(alias="GroupName")


class ProcessSelection(SnapshotModel):
    name: str = Field(alias="Name")
    molecule_name: str | None = Field(default=None, alias="MoleculeName")
    systemic_process_type: str | None = Field(default=None, alias="SystemicProcessType")


class FormulationSelection(SnapshotModel):
    name: str = Field(alias="Name")
    key: str = Field(alias="Key")  # "Formulation" for single-formulation protocols


class ProtocolSelection(SnapshotModel):
    name: str = Field(alias="Name")
    formulations: list[FormulationSelection] = Field(default_factory=list, alias="Formulations")


class SimulationCompound(SnapshotModel):
    name: str = Field(alias="Name")
    calculation_methods: list[str] = Field(default_factory=list, alias="CalculationMethods")
    alternatives: list[AlternativeSelection] = Field(default_factory=list, alias="Alternatives")
    processes: list[ProcessSelection] = Field(default_factory=list, alias="Processes")
    protocol: ProtocolSelection | None = Field(default=None, alias="Protocol")


class OutputInterval(SnapshotModel):
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")


class OutputMapping(SnapshotModel):
    path: str = Field(alias="Path")
    observed_data: str = Field(alias="ObservedData")
    scaling: str | None = Field(default=None, alias="Scaling")


class Simulation(SnapshotModel):
    name: str = Field(alias="Name")
    model: str | None = Field(default=None, alias="Model")
    observed_data: list[str] = Field(default_factory=list, alias="ObservedData")
    solver: dict[str, Any] = Field(default_factory=dict, alias="Solver")
    output_schema: list[OutputInterval] = Field(default_factory=list, alias="OutputSchema")
    parameters: list[Parameter] = Field(default_factory=list, alias="Parameters")
    output_selections: list[str] = Field(default_factory=list, alias="OutputSelections")
    output_mappings: list[OutputMapping] = Field(default_factory=list, alias="OutputMappings")
    individual: str | None = Field(default=None, alias="Individual")
    population: str | None = Field(default=None, alias="Population")
    compounds: list[SimulationCompound] = Field(default_factory=list, alias="Compounds")
    events: list[dict[str, Any]] = Field(default_factory=list, alias="Events")
    has_results: bool | None = Field(default=None, alias="HasResults")


class Snapshot(SnapshotModel):
    version: int = Field(alias="Version")
    application_name: str | None = Field(default=None, alias="ApplicationName")
    expression_profiles: list[ExpressionProfile] = Field(default_factory=list, alias="ExpressionProfiles")
    individuals: list[Individual] = Field(default_factory=list, alias="Individuals")
    populations: list[dict[str, Any]] = Field(default_factory=list, alias="Populations")
    compounds: list[Compound] = Field(default_factory=list, alias="Compounds")
    formulations: list[Formulation] = Field(default_factory=list, alias="Formulations")
    protocols: list[Protocol] = Field(default_factory=list, alias="Protocols")
    events: list[Event] = Field(default_factory=list, alias="Events")
    observer_sets: list[dict[str, Any]] = Field(default_factory=list, alias="ObserverSets")
    simulations: list[Simulation] = Field(default_factory=list, alias="Simulations")
    parameter_identifications: list[dict[str, Any]] = Field(default_factory=list, alias="ParameterIdentifications")
    observed_data: list[dict[str, Any]] = Field(default_factory=list, alias="ObservedData")

    @classmethod
    def load(cls, path: str | Path) -> Snapshot:
        return cls.model_validate_json(Path(path).read_bytes())

    def dump(self, path: str | Path) -> None:
        """Write the snapshot in PK-Sim key order (the form handed to the engine)."""
        Path(path).write_text(json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def canonical_bytes(self) -> bytes:
        """Sorted-key compact UTF-8 JSON. Used only for content hashing, never for engine input."""
        return json.dumps(
            self.to_json_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
