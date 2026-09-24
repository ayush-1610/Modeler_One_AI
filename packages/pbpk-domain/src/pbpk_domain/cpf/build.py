"""Regenerate a PK-Sim snapshot from a CPF plus a system and scenarios (MS-01 §2, task T-03).

The CPF is the only thing edited; every simulation is regenerated from it. This module turns the CPF's
canonical parameters into the compound the builder assembles, then combines that compound with the given
subjects and scenarios (protocol + optional formulation + simulation) into one snapshot. Parameters the
current builder cannot yet place (Michaelis-Menten, transporters, total/biliary clearance, DDI processes)
are reported in `unresolved` for the builder-coverage task (T-10); they are never silently dropped or
invented. `build → parse → build` is stable: the same CPF always yields the same snapshot.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus
from pbpk_domain.snapshot.builder import (
    HARVESTED_PROCESSES,
    HARVESTED_SYSTEMIC,
    CompetitiveInhibition,
    CompoundSpec,
    DissolvedFormulationSpec,
    ExpressionSpec,
    FirstOrderMetabolism,
    GlomerularFiltration,
    HarvestedProcess,
    Induction,
    IntravenousBolusProtocolSpec,
    IntravenousProtocolSpec,
    MealEventSpec,
    Measured,
    MichaelisMentenMetabolism,
    MicrosomalMichaelisMenten,
    OralProtocolSpec,
    ParticleFormulationSpec,
    SimulationSpec,
    SnapshotBuilder,
    SpecificBinding,
    SubjectSpec,
    TransporterMichaelisMenten,
    WeibullFormulationSpec,
)
from pbpk_domain.snapshot.models import Snapshot, ValueOrigin, value_origin_source
from pbpk_domain.system import ModelSystem

FormulationSpec = DissolvedFormulationSpec | WeibullFormulationSpec | ParticleFormulationSpec
ProtocolSpec = OralProtocolSpec | IntravenousProtocolSpec | IntravenousBolusProtocolSpec


class Scenario(BaseModel):
    """One simulation and the protocol (and optional formulation, meal events) it references."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    simulation: SimulationSpec
    protocol: ProtocolSpec
    formulation: FormulationSpec | None = None
    events: tuple[MealEventSpec, ...] = ()
    # A model system's other dosed compounds each get their own protocol (SimulationSpec.co_compounds names them).
    extra_protocols: tuple[ProtocolSpec, ...] = ()
    # a binned product's other bin formulations (the first is `formulation`)
    extra_formulations: tuple[FormulationSpec, ...] = ()


@dataclass(frozen=True)
class BuildReport:
    compound: str
    cpf_version: int
    bindings_used: tuple[str, ...]   # CPF parameter ids placed into the snapshot
    unresolved: tuple[str, ...]      # CPF parameter ids the current builder cannot place (need T-10)
    expression_profiles: tuple[str, ...] = ()  # proteins given a harvested expression profile on every subject
    missing_expression: tuple[str, ...] = ()   # proteins a process names but the library has no profile for
    expression_documents: tuple[str, ...] = ()  # proteins given the CPF's own published profile, not the library's


# Alternatives a published model selects per simulation by the product given and the food state: the values of each
# non-default alternative are `<id>@<alternative>` records (``phys.solubility.ref@Capsule fed``), and
# ``alt.select`` (JSON) lists the rules {group, formulation, food, alternative}: formulation is the CPF formulation a
# study is given ("*" for any, null for a dissolved or IV dose), food "fasted"/"fed". A study matching no rule uses
# the default alternative.
ALTERNATIVE_SEPARATOR = "@"
ALTERNATIVE_RULES = "alt.select"
_ALTERNATIVE_GROUP_NAMES = {"Solubility": "COMPOUND_SOLUBILITY", "IntestinalPermeability": "COMPOUND_INTESTINAL_PERMEABILITY"}


# CPF ids whose value is one alternative's (the default's): a simulation selecting another alternative of the group
# does not use them.
ALTERNATIVE_GROUP_OF_ID = {"phys.solubility.ref": "COMPOUND_SOLUBILITY", "phys.solubility.ref_ph": "COMPOUND_SOLUBILITY",
                           "perm.intestinal": "COMPOUND_INTESTINAL_PERMEABILITY"}


def alternative_rules(cpf: CPF) -> list[dict]:
    record = cpf.get(ALTERNATIVE_RULES)
    if record is None or record.status is ParameterStatus.MISSING or not isinstance(record.value, str):
        return []
    return json.loads(record.value)


def alternatives_for(cpf: CPF | None, formulation: str | None, food_state: str) -> dict[str, str]:
    """GroupName -> alternative a simulation of a study given ``formulation`` (None: dissolved or IV) in
    ``food_state`` selects: the rule for that formulation and food state, else the one for any formulation."""
    if cpf is None:
        return {}
    out: dict[str, str] = {}
    rules = alternative_rules(cpf)
    for group, group_name in _ALTERNATIVE_GROUP_NAMES.items():
        mine = [r for r in rules if r["group"] == group and r["food"] == food_state]
        exact = next((r for r in mine if r.get("formulation") == formulation), None)
        wildcard = next((r for r in mine if r.get("formulation") == "*"), None)
        chosen = exact or wildcard
        if chosen is not None:
            out[group_name] = chosen["alternative"]
    return out


# `bind.partner` of a published compound that does not set its plasma protein binding partner.
UNSPECIFIED_PARTNER = "unspecified"

# A CPF record choosing the individual's molecule a process selection runs on (``molecule.<selection>``, the
# selection name in `parameter`, the molecule as its value); harvested from the simulations' ``MoleculeName``.
PROCESS_SELECTION = "ProcessSelection"


def selected_molecules(cpf: CPF) -> dict[str, str]:
    """Selection name -> the individual's molecule it runs on, where the published model maps a process onto another
    molecule than the process names (OSP Dabigatran: ``ABCB1-FIT`` on ``P-gp``)."""
    return {eb.parameter: str(r.value) for r in cpf.parameters if (eb := r.engine_binding) is not None
            and r.status is not ParameterStatus.MISSING and eb.building_block == PROCESS_SELECTION}


def process_molecules(cpf: CPF) -> tuple[str, ...]:
    """The proteins (enzymes, transporters, binding partners) the CPF's processes act through, in CPF order: the
    individual's molecule a selection runs on where the CPF maps it (`selected_molecules`), else the process's own.
    Each needs an expression profile on the individual, or its process does nothing (MS-01 §S0)."""
    mapped = selected_molecules(cpf)
    seen: dict[str, None] = {}
    for record in cpf.parameters:
        eb = record.engine_binding
        if record.status is ParameterStatus.MISSING or eb is None or eb.process_internal_name is None:
            continue
        if eb.molecule:
            seen.setdefault(mapped.get(f"{eb.molecule}-{eb.data_source or ''}", eb.molecule), None)
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
    documents = expression_documents(cpf)
    return tuple(m for m in process_molecules(cpf) if m not in library and m not in documents)


def expression_parameters(cpf: CPF) -> dict[str, dict[str, ParameterRecord]]:
    """CPF records bound to an ExpressionProfile (``expr.*`` ids): molecule -> {profile parameter path: record}. They
    are the values a model's own profile sets differently from the harvested library (e.g. CYP3A4 ``t1/2 (liver)``)."""
    out: dict[str, dict[str, ParameterRecord]] = {}
    for record in cpf.parameters:
        eb = record.engine_binding
        if record.status is ParameterStatus.MISSING or eb is None or eb.building_block != "ExpressionProfile":
            continue
        out.setdefault(expression_molecule(eb.parameter), {})[eb.parameter] = record
    return out


# A published expression profile copied verbatim (``expr.profile.<molecule>``, the profile document as JSON, the
# molecule in `parameter`): the model's own localization, transport type, ontogeny and values. The library's copy
# comes from another model and can differ in all of them (OSP Clarithromycin's P-gp has no ontogeny, the library's
# has; Metformin leaves MATE1 unexpressed in brain and muscle where the library's copy expresses it).
PROFILE_DOCUMENT = "ExpressionProfileDocument"


def expression_documents(cpf: CPF) -> dict[str, dict]:
    """Molecule -> the published profile document the CPF carries for it."""
    out: dict[str, dict] = {}
    for record in cpf.parameters:
        eb = record.engine_binding
        if record.status is not ParameterStatus.MISSING and eb is not None and eb.building_block == PROFILE_DOCUMENT \
                and isinstance(record.value, str):
            out[eb.parameter] = json.loads(record.value)
    return out


def _document_spec(molecule: str, doc: dict) -> ExpressionSpec:
    from pbpk_domain.expression import DEFAULT_CATEGORY

    return ExpressionSpec(type=doc["Type"], molecule=molecule, species=doc.get("Species", "Human"),
                          category=DEFAULT_CATEGORY, harvested=doc)


def _document_ids(cpf: CPF, expressed: Sequence[str]) -> list[str]:
    return [r.id for r in cpf.parameters if r.engine_binding is not None
            and r.engine_binding.building_block == PROFILE_DOCUMENT and r.engine_binding.parameter in expressed]


def expression_molecule(path: str) -> str:
    """The protein an expression-profile parameter belongs to: ``CYP3A4|t1/2 (liver)`` or
    ``Organism|Liver|Pericentral|Intracellular|CYP3A4|Relative expression``."""
    parts = path.split("|")
    return parts[-2] if parts[0] == "Organism" else parts[0]


def _override_profile(spec: ExpressionSpec, values: dict[str, Measured]) -> ExpressionSpec:
    """The harvested profile with the given values for the paths they set (added when the library has no such path)."""
    doc = dict(spec.harvested or {})
    params = [dict(q) for q in doc.get("Parameters", [])]
    by_path = {q.get("Path"): q for q in params}
    for path, measured in values.items():
        entry = {"Path": path, "Value": measured.value}
        if measured.unit:
            entry["Unit"] = measured.unit
        if path in by_path:
            if by_path[path].get("Value") == entry["Value"] and by_path[path].get("Unit") == entry.get("Unit"):
                continue  # the published entry already has it: keep it with its value origin
            by_path[path].clear()
            by_path[path].update(entry)
        else:
            params.append(entry)
    doc["Parameters"] = params
    return spec.model_copy(update={"harvested": doc})


def _with_expression(subjects: Sequence[SubjectSpec], molecules: Sequence[str],
                     overrides: dict[str, dict[str, ParameterRecord]] | None = None,
                     documents: dict[str, dict] | None = None,
                     ) -> tuple[list[SubjectSpec], list[str], list[str]]:
    """Every subject gets the profile of every process protein it does not already express: the CPF's own published
    profile document when it carries one, else the harvested library's, with the CPF's ``expr.*`` values applied; a
    subject with its own published physiology gets its own documents and values instead, under a profile category
    named after it."""
    from pbpk_domain.expression import library_expression

    cpf_values = {m: {path: _measured(r) for path, r in recs.items()} for m, recs in (overrides or {}).items()}
    library, placed, missing = {}, [], []
    for molecule in molecules:
        doc = (documents or {}).get(molecule)
        spec = _document_spec(molecule, doc) if doc is not None else library_expression(molecule)
        if spec is None:
            missing.append(molecule)
        else:
            library[molecule] = spec
            placed.append(molecule)
    shared = [_override_profile(s, cpf_values[m]) if m in cpf_values else s for m, s in library.items()]
    out = []
    for subject in subjects:
        have = {e.molecule for e in subject.expression}
        if subject.own_physiology:
            own: dict[str, dict[str, Measured]] = {}
            for path, measured in subject.expression_overrides.items():
                own.setdefault(expression_molecule(path), {})[path] = measured
            # its own category for every profile: its own published documents where it has them, else the shared
            # ones (which carry the main individual's CPF values), with its own values on top
            base = {m: (_document_spec(m, subject.expression_documents[m]) if m in subject.expression_documents else s)
                    for m, s in library.items()}
            specs = [(_override_profile(s, own[m]) if m in own else s).model_copy(update={"category": subject.name})
                     for m, s in base.items()]
        else:
            specs = shared
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
        if eb.parameter == INDIVIDUAL_SEED:
            continue  # the individual's Seed, not a physiology path (individual_seed)
        out[eb.parameter] = record
    return out


# `Individuals[].Seed`: PK-Sim draws the individual's organ-volume percentiles from it, so the published individual is
# reproduced only with its own seed (the round trip showed `Organism|Stomach|Volume|Percentile` 0.50086 vs 0.50032 and
# a systematic ~5e-5 difference in every curve with the campaign's seed).
INDIVIDUAL_SEED = "Seed"


def individual_seed(cpf: CPF) -> ParameterRecord | None:
    return next((r for r in cpf.parameters if r.engine_binding is not None and r.status is not ParameterStatus.MISSING
                 and r.engine_binding.building_block == "Individual" and r.engine_binding.parameter == INDIVIDUAL_SEED), None)


def simulation_parameters(cpf: CPF, route: str | None = None) -> dict[str, ParameterRecord]:
    """CPF records bound to the Simulation building block (``sim.*`` ids), keyed by full path, for a simulation dosed
    by ``route`` ("oral", "iv"; None: mixed or unknown): the records for every simulation, as the published
    Dapagliflozin model sets ``Dapagliflozin|logP (veg.oil/water)`` in each of its, and that route's own records
    (``sim[oral].*``: OSP Alfentanil's gut-wall permeabilities, set only in its oral simulations)."""
    out: dict[str, ParameterRecord] = {}
    scoped: dict[str, ParameterRecord] = {}
    for record in cpf.parameters:
        eb = record.engine_binding
        if record.status is ParameterStatus.MISSING or eb is None or eb.building_block != "Simulation":
            continue
        if eb.route is None:
            out[eb.parameter] = record
        elif eb.route == route:
            scoped[eb.parameter] = record
    return {**out, **scoped}


def scenario_route(scenario: Scenario) -> str | None:
    return {"oral": "oral", "intravenous": "iv", "intravenous_bolus": "iv"}.get(scenario.protocol.kind)


def _with_simulation_parameters(scenarios: Sequence[Scenario], cpf: CPF) -> tuple[list[Scenario], list[str]]:
    """Each scenario with the CPF's simulation-level values for its route; the ids placed."""
    out, used = [], []
    for scenario in scenarios:
        records = simulation_parameters(cpf, scenario_route(scenario))
        if records:
            overrides = {path: _measured(record) for path, record in records.items()}
            scenario = scenario.model_copy(update={"simulation": scenario.simulation.model_copy(
                update={"parameters": {**scenario.simulation.parameters, **overrides}})})
            used.extend(r.id for r in records.values())
        out.append(scenario)
    return out, list(dict.fromkeys(used))


def _with_individual_parameters(subjects: Sequence[SubjectSpec], cpf: CPF) -> tuple[list[SubjectSpec], list[str]]:
    records = individual_parameters(cpf)
    seed = individual_seed(cpf)
    if not records and seed is None:
        return list(subjects), []
    overrides = {path: _measured(record) for path, record in records.items()}
    update: dict = {}
    if seed is not None:
        update["seed"] = int(seed.numeric_value)
    # A subject with its own published physiology carries that individual's complete parameter set (and seed) instead.
    out = [s if s.own_physiology else s.model_copy(update={"parameters": {**s.parameters, **overrides}, **update})
           for s in subjects]
    return out, [r.id for r in records.values()] + ([seed.id] if seed is not None else [])


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
        vmax = _measured_of(params, "In vitro Vmax for liver microsomes")
        if km and (kcat or vmax) and molecule:
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
    if internal_name in HARVESTED_PROCESSES:
        systemic = internal_name in HARVESTED_SYSTEMIC
        if systemic == bool(molecule):
            return None
        return HarvestedProcess(internal_name=internal_name, molecule=molecule, data_source=ds,
                                parameters={name: _measured(record) for name, record in params.items()})
    return None


def _build_processes(cpf: CPF) -> tuple[list, list[str], list[str]]:
    """Group process-bound CPF records by (process internal name, molecule) and build each process.
    Returns (process specs, used ids, unresolved ids)."""
    # One process per (type, molecule, data source): a protein can carry two pathways (Alprazolam CYP3A4).
    groups: dict[tuple[str, str | None, str | None], dict[str, ParameterRecord]] = defaultdict(dict)
    order: list[tuple[str, str | None, str | None]] = []
    for record in cpf.parameters:
        if record.status is ParameterStatus.MISSING or record.engine_binding is None:
            continue
        internal = record.engine_binding.process_internal_name
        if internal is None:
            continue  # a compound scalar binding (mw, logp, …), handled by id elsewhere
        key = (internal, record.engine_binding.molecule, record.engine_binding.data_source)
        if key not in groups:
            order.append(key)
        groups[key][record.engine_binding.parameter] = record

    processes: list = []
    used: list[str] = []
    unresolved: list[str] = []
    for internal, molecule, source in order:
        params = groups[(internal, molecule, source)]
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

    table = take("phys.solubility.table")
    if table is not None and "solubility" not in fields:
        doc = json.loads(str(table.value))
        fields["solubility_table"] = tuple((float(x), float(y)) for x, y in doc["points"])
        fields["solubility_table_value"] = float(doc["value"])
    ref_ph = take("phys.solubility.ref_ph")
    if ref_ph is not None:
        fields["solubility_reference_ph"] = ref_ph.numeric_value

    # further alternatives the simulations select by product and food state (`alternatives_for`)
    solubility_alts: dict[str, tuple[Measured, float]] = {}
    permeability_alts: dict[str, Measured] = {}
    default_ph = fields.get("solubility_reference_ph", 7.0)
    for record in cpf.parameters:
        base, sep, name = record.id.partition(ALTERNATIVE_SEPARATOR)
        if not sep or record.status is ParameterStatus.MISSING:
            continue
        if base == "phys.solubility.ref":
            ph = take(f"phys.solubility.ref_ph{ALTERNATIVE_SEPARATOR}{name}")
            solubility_alts[name] = (_measured(take(record.id)), ph.numeric_value if ph is not None else default_ph)
        elif base == "perm.intestinal":
            permeability_alts[name] = _measured(take(record.id))
    if solubility_alts:
        fields["solubility_alternatives"] = solubility_alts
    if permeability_alts:
        fields["intestinal_permeability_alternatives"] = permeability_alts
    take(ALTERNATIVE_RULES)  # applied per scenario by `alternatives_for`

    partner = take("bind.partner")
    if partner is not None and isinstance(partner.value, str):
        # UNSPECIFIED_PARTNER: the published compound leaves it unset; so does the snapshot (PK-Sim's default applies)
        fields["binding_partner"] = None if partner.value == UNSPECIFIED_PARTNER else partner.value

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

    mapped = selected_molecules(cpf)
    if mapped:
        fields["selected_molecules"] = mapped
        used.extend(r.id for r in cpf.parameters if r.engine_binding is not None
                    and r.engine_binding.building_block == PROCESS_SELECTION and r.status is not ParameterStatus.MISSING)
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
    expr_records = expression_parameters(cpf)
    documents = expression_documents(cpf)
    subjects, expressed, missing = _with_expression(subjects, process_molecules(cpf), expr_records, documents)
    subjects, individual_used = _with_individual_parameters(subjects, cpf)
    scenarios, sim_used = _with_simulation_parameters(scenarios, cpf)
    expr_used = [r.id for m in expressed for r in expr_records.get(m, {}).values()] + _document_ids(cpf, expressed)
    used = [*used, *individual_used, *expr_used, *sim_used]

    builder = SnapshotBuilder(snapshot_version) if snapshot_version is not None else SnapshotBuilder()
    builder.add_compound(compound)
    for subject in subjects:
        builder.add_subject(subject)

    seen_protocols: set[str] = set()
    seen_formulations: set[str] = set()
    seen_events: set[str] = set()
    for scenario in scenarios:
        for protocol in (scenario.protocol, *scenario.extra_protocols):
            if protocol.name not in seen_protocols:
                builder.add_protocol(protocol)
                seen_protocols.add(protocol.name)
        for formulation in ([scenario.formulation] if scenario.formulation is not None else []) + list(scenario.extra_formulations):
            if formulation.name not in seen_formulations:
                builder.add_formulation(formulation)
                seen_formulations.add(formulation.name)
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
        expression_documents=tuple(m for m in expressed if m in documents),
    )
    return snapshot, report


def build_from_system(
    system: ModelSystem,
    subjects: Sequence[SubjectSpec],
    scenarios: Sequence[Scenario],
    *,
    snapshot_version: int | None = None,
) -> tuple[Snapshot, BuildReport]:
    """Build one snapshot from a model system: every compound from its own CPF, each formation link set on the process
    that forms the metabolite (and so selected with its `MetaboliteName`), the proteins of every compound expressed,
    the individual and the formulations from the CPF that carries them, each compound's simulation-level values in the
    simulations it takes part in, and the published sum observers the scenarios select."""
    compounds, used, unresolved = [], [], []
    for cpf in system.compounds:
        compound, cpf_used, cpf_unresolved = _compound_from_cpf(cpf)
        forms = {(f.internal_name, f.molecule, f.data_source): f.metabolite for f in system.formed_by(cpf.compound)}
        if forms:
            compound = compound.model_copy(update={"processes": [
                p.model_copy(update={"metabolite": forms[key]})
                if (key := (getattr(p, "internal_name", None) or p.kind, getattr(p, "molecule", None), p.data_source)) in forms
                else p for p in compound.processes]})
        compounds.append(compound)
        used.extend(cpf_used)
        unresolved.extend(cpf_unresolved)

    molecules = tuple(dict.fromkeys(m for cpf in system.compounds for m in process_molecules(cpf)))
    expr_records: dict[str, dict[str, ParameterRecord]] = {}
    for cpf in system.compounds:
        for molecule, records in expression_parameters(cpf).items():
            expr_records.setdefault(molecule, {}).update(records)
    documents: dict[str, dict] = {}
    for cpf in system.compounds:
        documents.update({m: d for m, d in expression_documents(cpf).items() if m not in documents})
    subjects, expressed, missing = _with_expression(subjects, molecules, expr_records, documents)
    for cpf in system.compounds:
        subjects, individual_used = _with_individual_parameters(subjects, cpf)
        used.extend(individual_used)
        used.extend(_document_ids(cpf, expressed))
    used.extend(r.id for m in expressed for r in expr_records.get(m, {}).values())

    scenarios = list(scenarios)
    for cpf in system.compounds:
        taking = [i for i, s in enumerate(scenarios)
                  if cpf.compound in (s.simulation.compound, *(c.name for c in s.simulation.co_compounds))]
        updated, sim_used = _with_simulation_parameters([scenarios[i] for i in taking], cpf)
        for i, scenario in zip(taking, updated, strict=True):
            scenarios[i] = scenario
        used.extend(sim_used)

    builder = SnapshotBuilder(snapshot_version) if snapshot_version is not None else SnapshotBuilder()
    for compound in compounds:
        builder.add_compound(compound)
    for subject in subjects:
        builder.add_subject(subject)
    for name in dict.fromkeys(n for s in scenarios for n in s.simulation.observer_sets):
        builder.add_observer_set(system.observers[name])
    seen_protocols: set[str] = set()
    seen_formulations: set[str] = set()
    seen_events: set[str] = set()
    for scenario in scenarios:
        for protocol in (scenario.protocol, *scenario.extra_protocols):
            if protocol.name not in seen_protocols:
                builder.add_protocol(protocol)
                seen_protocols.add(protocol.name)
        for formulation in ([scenario.formulation] if scenario.formulation is not None else []) + list(scenario.extra_formulations):
            if formulation.name not in seen_formulations:
                builder.add_formulation(formulation)
                seen_formulations.add(formulation.name)
        for event in scenario.events:
            if event.name not in seen_events:
                builder.add_event(event)
                seen_events.add(event.name)
        builder.add_simulation(scenario.simulation)
    snapshot = builder.build()
    report = BuildReport(compound=system.name, cpf_version=max(c.version for c in system.compounds),
                         bindings_used=tuple(dict.fromkeys(used)), unresolved=tuple(unresolved),
                         expression_profiles=tuple(expressed), missing_expression=tuple(missing),
                         expression_documents=tuple(m for m in expressed if m in documents))
    return snapshot, report
