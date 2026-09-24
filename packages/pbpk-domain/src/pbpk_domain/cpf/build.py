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
    MicrosomalMichaelisMenten,
    OralProtocolSpec,
    SimulationSpec,
    SnapshotBuilder,
    SpecificBinding,
    SubjectSpec,
    TransporterMichaelisMenten,
    WeibullFormulationSpec,
)
from pbpk_domain.snapshot.models import Snapshot, ValueOrigin, value_origin_source

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
    expression_profiles: tuple[str, ...] = ()  # proteins given a harvested expression profile on every subject
    missing_expression: tuple[str, ...] = ()   # proteins a process names but the library has no profile for


def process_molecules(cpf: CPF) -> tuple[str, ...]:
    """The proteins (enzymes, transporters, binding partners) the CPF's processes act through, in CPF order.
    Each needs an expression profile on the individual, or its process does nothing (MS-01 §S0)."""
    seen: dict[str, None] = {}
    for record in cpf.parameters:
        eb = record.engine_binding
        if record.status is ParameterStatus.MISSING or eb is None or eb.process_internal_name is None:
            continue
        if eb.molecule:
            seen.setdefault(eb.molecule, None)
    return tuple(seen)


def unplaceable_parameters(cpf: CPF) -> tuple[str, ...]:
    """Process parameters (elimination, transport) the builder cannot place in the model — the S0 check.

    Each one is a pathway the CPF says exists but the simulation would not contain (a missing clearance makes
    every exposure wrong while the run looks valid), so a campaign must not start with any."""
    _compound, _used, unresolved = _compound_from_cpf(cpf)
    return tuple(unresolved)


def missing_expression_profiles(cpf: CPF) -> tuple[str, ...]:
    """Process proteins with no harvested expression profile — the S0 readiness check."""
    from pbpk_domain.expression import expression_library

    library = expression_library()
    return tuple(m for m in process_molecules(cpf) if m not in library)


def _with_expression(subjects: Sequence[SubjectSpec], molecules: Sequence[str]) -> tuple[list[SubjectSpec], list[str], list[str]]:
    """Every subject gets the harvested profile of every process protein it does not already express."""
    from pbpk_domain.expression import library_expression

    specs, placed, missing = [], [], []
    for molecule in molecules:
        spec = library_expression(molecule)
        if spec is None:
            missing.append(molecule)
        else:
            specs.append(spec)
            placed.append(molecule)
    out = []
    for subject in subjects:
        have = {e.molecule for e in subject.expression}
        extra = [e for e in specs if e.molecule not in have]
        out.append(subject.model_copy(update={"expression": [*subject.expression, *extra]}) if extra else subject)
    return out, placed, missing


def individual_parameters(cpf: CPF) -> dict[str, ParameterRecord]:
    """CPF records bound to the Individual building block, keyed by their full PK-Sim path (``indiv.*`` ids).

    These are physiology values a model changed from the database default — e.g. the published Dapagliflozin
    model's ``Organism|Liver|EHC continuous fraction`` — and apply to every subject the CPF is simulated in."""
    out: dict[str, ParameterRecord] = {}
    for record in cpf.parameters:
        eb = record.engine_binding
        if record.status is ParameterStatus.MISSING or eb is None or eb.building_block != "Individual":
            continue
        out[eb.parameter] = record
    return out


def simulation_parameters(cpf: CPF) -> dict[str, ParameterRecord]:
    """CPF records bound to the Simulation building block (``sim.*`` ids), keyed by full path; they apply to every
    simulation, as the published Dapagliflozin model sets ``Dapagliflozin|logP (veg.oil/water)`` in each of its."""
    out: dict[str, ParameterRecord] = {}
    for record in cpf.parameters:
        eb = record.engine_binding
        if record.status is ParameterStatus.MISSING or eb is None or eb.building_block != "Simulation":
            continue
        out[eb.parameter] = record
    return out


def _with_individual_parameters(subjects: Sequence[SubjectSpec], cpf: CPF) -> tuple[list[SubjectSpec], list[str]]:
    records = individual_parameters(cpf)
    if not records:
        return list(subjects), []
    overrides = {path: _measured(record) for path, record in records.items()}
    out = [s.model_copy(update={"parameters": {**s.parameters, **overrides}}) for s in subjects]
    return out, [r.id for r in records.values()]


# CPF id prefixes that must reach the engine as a process; anything here that the builder does not place
# changes the model's behaviour (e.g. a missing clearance), so it is reported rather than dropped quietly.
_PROCESS_FAMILIES = ("elim.", "transp.")


def _origin(record: ParameterRecord) -> ValueOrigin | None:
    prov = record.provenance
    if prov is None:
        return None
    # ValueOrigin.Source is coerced to the OSP enum by the model; keep the exact CPF source label (e.g.
    # "measured", "assumed") in the description so a reviewer still sees it when the enum is coarser.
    raw = prov.source_type
    description = prov.reference or None
    if raw and value_origin_source(raw) != raw:
        description = raw if not description else f"{raw} — {description}"
    return ValueOrigin(source=raw, description=description)


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
    if internal_name == "MetabolizationLiverMicrosomes_MM":
        km, kcat = _measured_of(params, "Km"), _measured_of(params, "kcat")
        if km and kcat and molecule:
            return MicrosomalMichaelisMenten(
                molecule=molecule, data_source=ds, km=km, kcat=kcat,
                in_vitro_vmax=_measured_of(params, "In vitro Vmax for liver microsomes"),
                microsomal_content=_measured_of(params, "Content of CYP proteins in liver microsomes"),
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

    # A process-family parameter with no engine binding is placed by nothing above: without this it would be
    # dropped in silence and the model would simply not eliminate the drug. Report it so S0/the round sees it.
    placed = set(used)
    unbound = [
        record.id
        for record in cpf.parameters
        if record.id.startswith(_PROCESS_FAMILIES)
        and record.status is not ParameterStatus.MISSING
        and record.value is not None
        and record.id not in placed
    ]

    return CompoundSpec(**fields), used, sorted(set(unresolved) | set(unbound))


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
    # Each process's protein must be expressed in the individual, or the process eliminates nothing.
    subjects, expressed, missing = _with_expression(subjects, process_molecules(cpf))
    subjects, individual_used = _with_individual_parameters(subjects, cpf)
    sim_records = simulation_parameters(cpf)
    if sim_records:
        overrides = {path: _measured(record) for path, record in sim_records.items()}
        scenarios = [s.model_copy(update={"simulation": s.simulation.model_copy(
            update={"parameters": {**s.simulation.parameters, **overrides}})}) for s in scenarios]
    used = [*used, *individual_used, *(r.id for r in sim_records.values())]

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
        expression_profiles=tuple(expressed),
        missing_expression=tuple(missing),
    )
    return snapshot, report
