"""Regenerate a PK-Sim snapshot from a CPF plus a system and scenarios (MS-01 §2, task T-03).

The CPF is the only thing edited; every simulation is regenerated from it. This module turns the CPF's
canonical parameters into the compound the builder assembles, then combines that compound with the given
subjects and scenarios (protocol + optional formulation + simulation) into one snapshot. Parameters the
current builder cannot yet place (Michaelis-Menten, transporters, total/biliary clearance, DDI processes)
are reported in `unresolved` for the builder-coverage task (T-10); they are never silently dropped or
invented. `build → parse → build` is stable: the same CPF always yields the same snapshot.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus
from pbpk_domain.snapshot.builder import (
    CompetitiveInhibition,
    CompoundSpec,
    DissolvedFormulationSpec,
    FirstOrderMetabolism,
    GlomerularFiltration,
    Induction,
    IntravenousProtocolSpec,
    MealEventSpec,
    Measured,
    MichaelisMentenMetabolism,
    OralProtocolSpec,
    SimulationSpec,
    SnapshotBuilder,
    SpecificBinding,
    SubjectSpec,
    TransporterMichaelisMenten,
    WeibullFormulationSpec,
)
from pbpk_domain.snapshot.models import Snapshot, ValueOrigin

FormulationSpec = DissolvedFormulationSpec | WeibullFormulationSpec
ProtocolSpec = OralProtocolSpec | IntravenousProtocolSpec


class Scenario(BaseModel):
    """One simulation and the protocol (and optional formulation, meal events) it references."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    simulation: SimulationSpec
    protocol: ProtocolSpec
    formulation: FormulationSpec | None = None
    events: tuple[MealEventSpec, ...] = ()


@dataclass(frozen=True)
class BuildReport:
    compound: str
    cpf_version: int
    bindings_used: tuple[str, ...]   # CPF parameter ids placed into the snapshot
    unresolved: tuple[str, ...]      # CPF parameter ids the current builder cannot place (need T-10)


def _origin(record: ParameterRecord) -> ValueOrigin | None:
    prov = record.provenance
    if prov is None:
        return None
    return ValueOrigin(source=prov.source_type, description=prov.reference)


def _measured(record: ParameterRecord) -> Measured:
    return Measured(value=record.numeric_value, unit=record.unit, origin=_origin(record))


def _data_source(record: ParameterRecord) -> str:
    eb = record.engine_binding
    if eb is not None and eb.data_source:
        return eb.data_source
    if record.provenance is not None and record.provenance.reference:
        return record.provenance.reference
    if record.provenance is not None:
        return record.provenance.source_type
    return "CPF"


def _measured_of(params: dict[str, ParameterRecord], engine_param: str) -> Measured | None:
    record = params.get(engine_param)
    return _measured(record) if record is not None else None


def _group_data_source(params: dict[str, ParameterRecord]) -> str:
    for record in params.values():
        if record.engine_binding is not None and record.engine_binding.data_source:
            return record.engine_binding.data_source
    return _data_source(next(iter(params.values())))


# Build one compound process from the CPF records that bind to it (keyed by engine parameter name).
# Returns None when the required parameters for that process type are not all present. Every internal name
# here comes from the harvested catalog (T-02); any other process type falls through to `unresolved`.
def _build_process(internal_name: str, molecule: str | None, params: dict[str, ParameterRecord]):
    ds = _group_data_source(params)
    if internal_name == "MetabolizationSpecific_FirstOrder":
        clspec = _measured_of(params, "CLspec/[Enzyme]")
        return FirstOrderMetabolism(molecule=molecule, data_source=ds, clearance_per_enzyme=clspec) if clspec and molecule else None
    if internal_name == "MetabolizationSpecific_MM":
        vmax, km = _measured_of(params, "Vmax"), _measured_of(params, "Km")
        if vmax and km and molecule:
            return MichaelisMentenMetabolism(
                molecule=molecule, data_source=ds, vmax=vmax, km=km,
                kcat=_measured_of(params, "kcat"), enzyme_concentration=_measured_of(params, "Enzyme concentration"),
            )
        return None
    if internal_name == "ActiveTransportSpecific_MM":
        vmax, km = _measured_of(params, "Vmax"), _measured_of(params, "Km")
        if vmax and km and molecule:
            return TransporterMichaelisMenten(
                molecule=molecule, data_source=ds, vmax=vmax, km=km,
                kcat=_measured_of(params, "kcat"), transporter_concentration=_measured_of(params, "Transporter concentration"),
            )
        return None
    if internal_name == "CompetitiveInhibition":
        ki = _measured_of(params, "Ki")
        return CompetitiveInhibition(molecule=molecule, data_source=ds, ki=ki) if ki and molecule else None
    if internal_name == "Induction":
        ec50, emax = _measured_of(params, "EC50"), _measured_of(params, "Emax")
        return Induction(molecule=molecule, data_source=ds, ec50=ec50, emax=emax) if ec50 and emax and molecule else None
    if internal_name == "SpecificBinding":
        koff, kd = _measured_of(params, "koff"), _measured_of(params, "Kd")
        return SpecificBinding(molecule=molecule, data_source=ds, koff=koff, kd=kd) if koff and kd and molecule else None
    if internal_name == "GlomerularFiltration":
        gfr = _measured_of(params, "GFR fraction")
        return GlomerularFiltration(data_source=ds, gfr_fraction=gfr) if gfr else None
    return None


def _build_processes(cpf: CPF) -> tuple[list, list[str], list[str]]:
    """Group process-bound CPF records by (process internal name, molecule) and build each process.
    Returns (process specs, used ids, unresolved ids)."""
    groups: dict[tuple[str, str | None], dict[str, ParameterRecord]] = defaultdict(dict)
    order: list[tuple[str, str | None]] = []
    for record in cpf.parameters:
        if record.status is ParameterStatus.MISSING or record.engine_binding is None:
            continue
        internal = record.engine_binding.process_internal_name
        if internal is None:
            continue  # a compound scalar binding (mw, logp, …), handled by id elsewhere
        key = (internal, record.engine_binding.molecule)
        if key not in groups:
            order.append(key)
        groups[key][record.engine_binding.parameter] = record

    processes: list = []
    used: list[str] = []
    unresolved: list[str] = []
    for internal, molecule in order:
        params = groups[(internal, molecule)]
        spec = _build_process(internal, molecule, params)
        if spec is None:
            unresolved.extend(r.id for r in params.values())
        else:
            processes.append(spec)
            used.extend(r.id for r in params.values())
    return processes, used, unresolved


def _compound_from_cpf(cpf: CPF) -> tuple[CompoundSpec, list[str], list[str]]:
    used: list[str] = []

    def take(param_id: str) -> ParameterRecord | None:
        record = cpf.get(param_id)
        if record is None or record.status is ParameterStatus.MISSING:
            return None
        used.append(param_id)
        return record

    fields: dict = {"name": cpf.compound}
    for param_id, key, required in (
        ("phys.mw", "molecular_weight", True),
        ("phys.logp", "lipophilicity", True),
        ("bind.fu", "fraction_unbound", True),
        ("phys.solubility.ref", "solubility", False),
        ("perm.intestinal", "intestinal_permeability", False),
        ("perm.cellular", "permeability", False),
    ):
        record = take(param_id)
        if record is None:
            if required:
                raise ValueError(f"CPF for {cpf.compound} is missing required parameter {param_id!r} (run S0 completeness first)")
            continue
        fields[key] = _measured(record)

    ref_ph = take("phys.solubility.ref_ph")
    if ref_ph is not None:
        fields["solubility_reference_ph"] = ref_ph.numeric_value

    partner = take("bind.partner")
    if partner is not None and isinstance(partner.value, str):
        fields["binding_partner"] = partner.value

    # Calculation methods: the CPF stores engine-exact method names (validated against the catalog).
    methods = []
    for param_id in ("dist.partition_method", "dist.permeability_method"):
        record = take(param_id)
        if record is not None and isinstance(record.value, str):
            methods.append(record.value)
    if methods:
        fields["calculation_methods"] = tuple(methods)

    # pKa: ids "phys.pka.{acid|base}.{i}".
    pka: list[dict] = []
    for record in cpf.with_prefix("phys.pka"):
        if record.status is ParameterStatus.MISSING or record.value is None:
            continue
        parts = record.id.split(".")
        if len(parts) >= 3 and parts[2] in ("acid", "base"):
            pka.append({"type": parts[2].capitalize(), "pka": record.numeric_value, "origin": _origin(record)})
            used.append(record.id)
    if pka:
        fields["pka"] = pka

    # Halogens: ids "phys.halogens.{F|Cl|Br|I}".
    halogens: dict[str, int] = {}
    for record in cpf.with_prefix("phys.halogens"):
        atom = record.id.rsplit(".", 1)[-1]
        if atom in ("F", "Cl", "Br", "I") and record.value is not None:
            halogens[atom] = int(record.numeric_value)
            used.append(record.id)
    if halogens:
        fields["halogens"] = halogens

    # Compound processes (metabolism, transport, inhibition, induction, binding, GFR), grouped by process.
    processes, process_used, unresolved = _build_processes(cpf)
    used.extend(process_used)
    if processes:
        fields["processes"] = processes

    return CompoundSpec(**fields), used, sorted(set(unresolved))


def build_from_cpf(
    cpf: CPF,
    subjects: Sequence[SubjectSpec],
    scenarios: Sequence[Scenario],
    *,
    snapshot_version: int | None = None,
) -> tuple[Snapshot, BuildReport]:
    """Build one snapshot from a CPF, a set of subjects, and a set of scenarios.

    Raises SnapshotBuildError (referential problems) or ValueError (missing required CPF parameters).
    """
    compound, used, unresolved = _compound_from_cpf(cpf)

    builder = SnapshotBuilder(snapshot_version) if snapshot_version is not None else SnapshotBuilder()
    builder.add_compound(compound)
    for subject in subjects:
        builder.add_subject(subject)

    seen_protocols: set[str] = set()
    seen_formulations: set[str] = set()
    seen_events: set[str] = set()
    for scenario in scenarios:
        if scenario.protocol.name not in seen_protocols:
            builder.add_protocol(scenario.protocol)
            seen_protocols.add(scenario.protocol.name)
        if scenario.formulation is not None and scenario.formulation.name not in seen_formulations:
            builder.add_formulation(scenario.formulation)
            seen_formulations.add(scenario.formulation.name)
        for event in scenario.events:
            if event.name not in seen_events:
                builder.add_event(event)
                seen_events.add(event.name)
        builder.add_simulation(scenario.simulation)

    snapshot = builder.build()
    report = BuildReport(
        compound=cpf.compound,
        cpf_version=cpf.version,
        bindings_used=tuple(dict.fromkeys(used)),
        unresolved=tuple(unresolved),
    )
    return snapshot, report
