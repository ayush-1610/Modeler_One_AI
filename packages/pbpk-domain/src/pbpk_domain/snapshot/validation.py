"""Referential-integrity checks for PK-Sim snapshots.

Naming conventions used here were read from a PK-Sim 12 snapshot:
- individuals reference expression profiles as ``Molecule|Species|Category``
- simulations select molecule-based processes as ``{Molecule}-{DataSource}``
- glomerular filtration is selected as ``Glomerular Filtration-{DataSource}`` with ``SystemicProcessType: GFR``
Other systemic process types are not checked until their naming is harvested from an engine catalog.
"""

from __future__ import annotations

from pbpk_domain.issues import Issue
from pbpk_domain.snapshot.models import CompoundProcess, ProcessSelection, Protocol, Snapshot

# Processes a simulation selects as interactions (Simulations[].Interactions with the compound's name), not among
# the compound's own processes — as the OSP Rifampicin reference snapshot selects its inhibition and induction.
INTERACTION_PROCESSES = ("CompetitiveInhibition", "UncompetitiveInhibition", "NoncompetitiveInhibition",
                         "MixedInhibition", "IrreversibleInhibition", "Induction")


def interaction_selection_for(process: CompoundProcess, compound: str) -> dict | None:
    if process.internal_name not in INTERACTION_PROCESSES or not process.molecule:
        return None
    return {"Name": f"{process.molecule}-{process.data_source or ''}", "MoleculeName": process.molecule,
            "CompoundName": compound}


def process_selection_for(process: CompoundProcess) -> ProcessSelection | None:
    if process.internal_name in INTERACTION_PROCESSES:
        return None  # selected as an interaction of the simulation (interaction_selection_for)
    data_source = process.data_source or ""
    if process.internal_name == "GlomerularFiltration":
        return ProcessSelection(name=f"Glomerular Filtration-{data_source}", systemic_process_type="GFR")
    if process.molecule:
        return ProcessSelection(name=f"{process.molecule}-{data_source}", molecule_name=process.molecule)
    return None


def is_oral(protocol: Protocol) -> bool:
    if protocol.application_type == "Oral":
        return True
    return any(item.application_type == "Oral" for schema in protocol.schemas for item in schema.schema_items)


def validate_references(snapshot: Snapshot) -> list[Issue]:
    issues: list[Issue] = []

    individuals = {i.name for i in snapshot.individuals}
    populations = {p.get("Name") for p in snapshot.populations}
    protocols = {p.name: p for p in snapshot.protocols}
    formulations = {f.name for f in snapshot.formulations}
    observed = {o.get("Name") for o in snapshot.observed_data}
    events = {e.name for e in snapshot.events}
    profiles = {p.reference_name for p in snapshot.expression_profiles}
    compound_processes = {
        c.name: {sel.name for p in c.processes if (sel := process_selection_for(p)) is not None}
        for c in snapshot.compounds
    }

    for individual in snapshot.individuals:
        for ref in individual.expression_profiles:
            if ref not in profiles:
                issues.append(
                    Issue("UNKNOWN_EXPRESSION_PROFILE", f"Individuals[{individual.name}]", f"no expression profile {ref!r}")
                )

    for sim in snapshot.simulations:
        loc = f"Simulations[{sim.name}]"
        if sim.individual is None and sim.population is None:
            issues.append(Issue("MISSING_SUBJECT", loc, "simulation has neither an individual nor a population"))
        if sim.individual is not None and sim.individual not in individuals:
            issues.append(Issue("UNKNOWN_INDIVIDUAL", loc, f"no individual {sim.individual!r}"))
        if sim.population is not None and sim.population not in populations:
            issues.append(Issue("UNKNOWN_POPULATION", loc, f"no population {sim.population!r}"))

        for sc in sim.compounds:
            if sc.name not in compound_processes:
                issues.append(Issue("UNKNOWN_COMPOUND", loc, f"no compound {sc.name!r}"))
            else:
                known = compound_processes[sc.name]
                for sel in sc.processes:
                    if sel.systemic_process_type not in (None, "GFR"):
                        continue
                    if sel.name not in known:
                        issues.append(
                            Issue("UNKNOWN_PROCESS", f"{loc}.Compounds[{sc.name}]", f"no process named {sel.name!r}")
                        )
            if sc.protocol is None:
                continue
            protocol = protocols.get(sc.protocol.name)
            if protocol is None:
                issues.append(Issue("UNKNOWN_PROTOCOL", loc, f"no protocol {sc.protocol.name!r}"))
                continue
            if is_oral(protocol) and not sc.protocol.formulations:
                issues.append(
                    Issue("ORAL_WITHOUT_FORMULATION", loc, f"oral protocol {protocol.name!r} has no formulation mapped")
                )
            for fs in sc.protocol.formulations:
                if fs.name not in formulations:
                    issues.append(Issue("UNKNOWN_FORMULATION", loc, f"no formulation {fs.name!r}"))

        for name in sim.observed_data:
            if name not in observed:
                issues.append(Issue("UNKNOWN_OBSERVED_DATA", loc, f"no observed data {name!r}"))
        for mapping in sim.output_mappings:
            if mapping.observed_data not in observed:
                issues.append(
                    Issue("UNKNOWN_OBSERVED_DATA", f"{loc}.OutputMappings", f"no observed data {mapping.observed_data!r}")
                )
        for event in sim.events:
            name = event.get("Name")
            if name is not None and name not in events:
                issues.append(Issue("UNKNOWN_EVENT", loc, f"no event {name!r}"))

    return issues
