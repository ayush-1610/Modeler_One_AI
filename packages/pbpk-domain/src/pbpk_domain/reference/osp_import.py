"""Import a published OSP model snapshot as a CPF plus its clinical studies (plan Phase 4, the reference importer).

The OSP library models (Dapagliflozin, Rifampicin, …) are peer-reviewed PBPK models shipped with the clinical data
they were built and qualified on. Importing one gives the pipeline real data and a known-good parameter set: the
compound's parameters become CPF records (value, unit and provenance copied verbatim from the snapshot), its
formulations become ``form.*`` records, the individual's changed physiology becomes ``indiv.*`` records, and every
plasma dataset of the parent drug becomes a study in the shape the API's study upload accepts.

Nothing is invented. Every name, path and unit comes from the snapshot. A study's route, dose, formulation, food
state and regimen come from the dataset's own metadata (OSP ``ExtendedProperties``); where the dataset leaves one
open (``"."``), the simulation that the published model runs it in fills the gap and the study says so. Anything
the pipeline cannot use yet (urine/feces fractions, metabolites, a process type the builder cannot place) is
listed in ``skipped`` / ``unplaced`` with the reason, never dropped in silence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from pbpk_domain.cpf.models import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance

# Compound scalar properties: (snapshot group, snapshot parameter name, CPF id, unit the builder requires).
_ALTERNATIVE_PARAMETERS = (
    ("Lipophilicity", "Lipophilicity", "phys.logp", "Log Units"),
    ("FractionUnbound", "Fraction unbound (plasma, reference value)", "bind.fu", None),
    ("Solubility", "Solubility at reference pH", "phys.solubility.ref", "mg/ml"),
    ("Solubility", "Reference pH", "phys.solubility.ref_ph", None),
    ("IntestinalPermeability", "Specific intestinal permeability (transcellular)", "perm.intestinal", "cm/min"),
    ("Permeability", "Permeability", "perm.cellular", "cm/min"),
)
# The simulation-level alternative group each property group is selected by (as the snapshots name them).
_ALTERNATIVE_GROUPS = {
    "Lipophilicity": "COMPOUND_LIPOPHILICITY",
    "FractionUnbound": "COMPOUND_FRACTION_UNBOUND",
    "Solubility": "COMPOUND_SOLUBILITY",
    "IntestinalPermeability": "COMPOUND_INTESTINAL_PERMEABILITY",
    "Permeability": "COMPOUND_PERMEABILITY",
}
_HALOGENS = ("F", "Cl", "Br", "I")
_CALCULATION_METHODS = {
    "Cellular partition coefficient method": "dist.partition_method",
    "Cellular permeability": "dist.permeability_method",
}

# Process internal name -> {engine parameter -> (CPF id suffix, unit)}. Only the parameters `cpf.build._build_process`
# places, in the unit the builder's validators require (snapshot/builder.py); each process type here is one the
# builder can put back into a snapshot. A snapshot may display the same quantity in another unit of its dimension
# (the Rifampicin model writes one transporter concentration in µmol/l, another in nmol/l), so values are converted.
_PROCESS_PARAMETERS = {
    "MetabolizationSpecific_FirstOrder": {"CLspec/[Enzyme]": ("clspec", "l/µmol/min")},
    "MetabolizationSpecific_MM": {"Vmax": ("vmax", "µmol/l/min"), "Km": ("km", "µmol/l"), "kcat": ("kcat", "1/min"),
                                  "Enzyme concentration": ("enzyme_conc", "µmol/l")},
    "ActiveTransportSpecific_MM": {"Vmax": ("vmax", "µmol/l/min"), "Km": ("km", "µmol/l"), "kcat": ("kcat", "1/min"),
                                   "Transporter concentration": ("transporter_conc", "nmol/l")},
    "MetabolizationLiverMicrosomes_MM": {"Km": ("km", "µmol/l"), "kcat": ("kcat", "1/min"),
                                         "In vitro Vmax for liver microsomes": ("vmax_microsomes", "pmol/min/mg mic. protein"),
                                         "Content of CYP proteins in liver microsomes": ("microsomal_content",
                                                                                         "pmol/mg mic. protein")},
    "SpecificBinding": {"koff": ("koff", "1/min"), "Kd": ("kd", "nmol/l")},
    "CompetitiveInhibition": {"Ki": ("ki", "µmol/l")},
    "Induction": {"EC50": ("ec50", "µmol/l"), "Emax": ("emax", None)},
    "GlomerularFiltration": {"GFR fraction": ("gfr_fraction", None)},
}
_PROCESS_FAMILY = {
    "MetabolizationSpecific_FirstOrder": "elim.hepatic",
    "MetabolizationSpecific_MM": "elim.hepatic",
    "MetabolizationLiverMicrosomes_MM": "elim.hepatic",
    "ActiveTransportSpecific_MM": "transp",
    "SpecificBinding": "bind.specific",
    "CompetitiveInhibition": "ddi.perp",
    "Induction": "ddi.perp",
}
# Units of one dimension, each as a factor to that dimension's first unit; a rate unit ("…/min") converts with
# its amount's factor. Only these conversions are made; any other unit pair raises (never guessed).
_SAME_DIMENSION = (
    {"µmol/l": 1.0, "pmol/l": 1e-6, "nmol/l": 1e-3, "mmol/l": 1e3},
    {"mg/ml": 1.0, "mg/l": 1e-3, "g/l": 1.0, "µg/ml": 1e-3, "µg/l": 1e-6},
    {"cm/min": 1.0, "dm/min": 10.0, "µm/min": 1e-4, "cm/s": 60.0},
    {"": 1.0, "%": 1e-2},  # dimensionless fraction
)


def _convert(value: float, unit: str | None, target: str | None) -> float:
    src, dst = unit or "", target or ""
    if src == dst:
        return value
    rate = "/min"
    if src.endswith(rate) and dst.endswith(rate) and src.count("/") == 2 and dst.count("/") == 2:
        src, dst = src.removesuffix(rate), dst.removesuffix(rate)
    for table in _SAME_DIMENSION:
        if src in table and dst in table:
            return value * table[src] / table[dst]
    raise ReferenceImportError(f"cannot convert {unit!r} to {target!r}")

# A reported formulation, by the words it contains ("300 mg capsules Rimactan®" is a capsule, "Rifa 600 Dragees" a
# coated tablet); the first match wins and the study notes the words it was classified from.
_FORMULATION_WORDS = (("solution", "solution"), ("syrup", "solution"), ("injection", "solution"),
                      ("suspension", "suspension"), ("capsule", "ir_capsule"), ("tablet", "ir_tablet"),
                      ("tab", "ir_tablet"), ("dragee", "ir_tablet"))
# OSP "Times of Administration [h]" schedules: "(S0-T24-R14)" / "(S-0,T-24,R-7)" = start, interval, repetitions.
_SCHEDULE = re.compile(r"\(S-?(?P<start>[\d.]+)[-,]\s*T-?(?P<interval>[\d.]+)[-,]\s*R-?(?P<n>\d+)\)")
_INFUSION_IN_NAME = re.compile(r"(?P<value>[\d.]+)\s*(?P<unit>h|min) infusion")
# Co-medication named in a dataset's grouping: such an arm is not the drug alone and must not train it (MS-01 §3.2).
_CO_MEDICATION_WORDS = ("antacid",)
_DOSE = re.compile(r"^\s*(?P<value>[\d.]+)\s*(?P<unit>mg|µg|ug|mg/kg|µg/kg|ug/kg)\s*$")
_TO_MG = {"mg": 1.0, "µg": 1e-3, "ug": 1e-3, "mg/kg": 1.0, "µg/kg": 1e-3, "ug/kg": 1e-3}


class ReferenceImportError(ValueError):
    """The snapshot is not a single-compound model this importer can read."""


@dataclass(frozen=True)
class ReferenceImport:
    compound: str
    source: str                      # e.g. "OSP Dapagliflozin model"
    cpf: CPF
    studies: tuple[dict[str, Any], ...]  # rows in the API's StudyUpload shape
    skipped: tuple[str, ...]         # datasets not imported, each "name: reason"
    unplaced: tuple[str, ...]        # compound processes / parameters the builder cannot place
    notes: tuple[str, ...]           # assumptions the import made, one sentence each
    # study id -> the published simulation that runs its dataset, and the minutes its dose is given after that
    # simulation's time zero (e.g. the Dapagliflozin IV microdose at 60 min); what the round trip compares against.
    simulation_of: dict[str, str] = field(default_factory=dict)
    offset_min: dict[str, float] = field(default_factory=dict)
    # study id -> why the pipeline simulates it differently from the published simulation it is linked to (the study's
    # real regimen or meal where the published model approximates), so the round trip reports it as a choice.
    differs_by_design: dict[str, str] = field(default_factory=dict)


def _props(dataset: dict[str, Any]) -> dict[str, Any]:
    return {p["Name"]: p.get("Value") for p in dataset.get("ExtendedProperties", [])}


def _given(value: Any) -> str | None:
    """A metadata value, or None when the dataset leaves it open (OSP writes "." for not reported)."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", ".") else text


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class _Records:
    def __init__(self, source: str):
        self.source = source
        self.records: list[ParameterRecord] = []

    def provenance(self, parameter: dict[str, Any] | None) -> Provenance:
        origin = (parameter or {}).get("ValueOrigin") or {}
        kind = origin.get("Source") or "published model"
        detail = origin.get("Description")
        return Provenance(source_type=kind, reference=f"{self.source}" + (f": {detail}" if detail else ""))

    def add(self, pid: str, value: Any, *, unit: str | None = None, parameter: dict[str, Any] | None = None,
            binding: EngineBinding | None = None) -> None:
        origin = (parameter or {}).get("ValueOrigin") or {}
        identified = "ParameterIdentification" in (origin.get("Source"), origin.get("Method"))
        status = ParameterStatus.FITTED if identified else ParameterStatus.FIXED
        self.records.append(ParameterRecord(id=pid, value=value, unit=unit, status=status,
                                            provenance=self.provenance(parameter), engine_binding=binding))


def _selected_alternative(snapshot: dict[str, Any], compound: dict[str, Any], group: str) -> dict[str, Any] | None:
    """The alternative of a property group the model's simulations use (the only one, when there is one)."""
    alternatives = compound.get(group) or []
    if len(alternatives) == 1:
        return alternatives[0]
    chosen = {
        a.get("AlternativeName")
        for sim in snapshot.get("Simulations", [])
        for c in sim.get("Compounds", [])
        if c.get("Name") == compound["Name"]
        for a in c.get("Alternatives", [])
        if a.get("GroupName") == _ALTERNATIVE_GROUPS[group]
    }
    if len(chosen) == 1:
        return next((a for a in alternatives if a.get("Name") in chosen), None)
    return None


def _compound_records(snapshot: dict[str, Any], compound: dict[str, Any], out: _Records, notes: list[str]) -> None:
    for parameter in compound.get("Parameters", []):
        if parameter.get("Name") == "Molecular weight":
            out.add("phys.mw", parameter["Value"], unit=parameter.get("Unit"), parameter=parameter)
        elif parameter.get("Name") in _HALOGENS and parameter.get("Value"):
            out.add(f"phys.halogens.{parameter['Name']}", parameter["Value"], parameter=parameter)

    for group, name, pid, unit in _ALTERNATIVE_PARAMETERS:
        if not compound.get(group):
            continue
        alternative = _selected_alternative(snapshot, compound, group)
        if alternative is None:
            notes.append(f"{group}: several alternatives and no single one selected by the simulations; not imported.")
            continue
        parameter = next((p for p in alternative.get("Parameters", []) if p.get("Name") == name), None)
        if parameter is not None:
            value = _convert(float(parameter["Value"]), parameter.get("Unit"), unit)
            out.add(pid, value, unit=unit, parameter=parameter)

    if compound.get("PlasmaProteinBindingPartner"):
        out.add("bind.partner", compound["PlasmaProteinBindingPartner"])

    counts: dict[str, int] = {}
    for pka in compound.get("PkaTypes", []):
        kind = str(pka.get("Type", "")).lower()
        if kind not in ("acid", "base"):
            continue
        i = counts.get(kind, 0)
        counts[kind] = i + 1
        out.add(f"phys.pka.{kind}.{i}", pka["Pka"], parameter=pka)
    if not counts:
        out.add("phys.pka.neutral", 1.0)
        notes.append("The model defines no pKa; recorded as neutral.")

    for method in compound.get("CalculationMethods", []):
        for prefix, pid in _CALCULATION_METHODS.items():
            if method.startswith(prefix):
                out.add(pid, method)


def _selected_interactions(snapshot: dict[str, Any], compound: str) -> set[str]:
    return {i.get("Name") for sim in snapshot.get("Simulations", []) for i in sim.get("Interactions", []) or []
            if i.get("CompoundName") == compound}


def _process_records(snapshot: dict[str, Any], compound: dict[str, Any], out: _Records, unplaced: list[str],
                     notes: list[str]) -> None:
    from pbpk_domain.snapshot.validation import INTERACTION_PROCESSES

    selected = _selected_interactions(snapshot, compound["Name"])
    not_selected: list[str] = []
    for process in compound.get("Processes", []):
        internal = process.get("InternalName")
        wanted = _PROCESS_PARAMETERS.get(internal)
        molecule = process.get("Molecule")
        label = f"{internal}" + (f" ({molecule})" if molecule else "")
        if internal in INTERACTION_PROCESSES and f"{molecule}-{process.get('DataSource')}" not in selected:
            # Defined for its victim drugs (DDI), selected in none of this model's own simulations: it cannot act on
            # the compound's own kinetics, so it is left for the DDI application (T-31), named here.
            not_selected.append(label)
            continue
        if wanted is None:
            unplaced.append(f"{label}: process type not placed by the builder yet")
            continue
        engine_process = f"{internal}:{molecule}" if molecule else internal
        if internal == "GlomerularFiltration":
            prefix = "elim.renal"
        else:
            prefix = f"{_PROCESS_FAMILY[internal]}.{molecule}"
        for parameter in process.get("Parameters", []):
            target = wanted.get(parameter.get("Name"))
            if target is None:
                continue
            suffix, unit = target
            value = _convert(float(parameter["Value"]), parameter.get("Unit"), unit)
            binding = EngineBinding(building_block="Compound", parameter=parameter["Name"], process=engine_process,
                                    data_source=process.get("DataSource"))
            out.add(f"{prefix}.{suffix}", value, unit=unit, parameter=parameter, binding=binding)
    if not_selected:
        notes.append("Interactions defined for victim drugs and selected in none of the model's simulations, left "
                     "for the DDI application: " + ", ".join(not_selected) + ".")


def _simulation_parameter_records(snapshot: dict[str, Any], compound: str, out: _Records, notes: list[str]) -> None:
    """Compound values the published simulations set themselves (e.g. ``<Compound>|logP (veg.oil/water)``). One that
    every simulation sets to the same value is part of the model and becomes a ``sim.*`` record; one that varies
    between simulations is named, not imported."""
    sims = [s for s in snapshot.get("Simulations", []) if any(c.get("Name") == compound for c in s.get("Compounds", []))]
    values: dict[str, list[dict[str, Any]]] = {}
    for sim in sims:
        for parameter in sim.get("Parameters", []) or []:
            path = parameter.get("Path") or ""
            if path.startswith(f"{compound}|"):
                values.setdefault(path, []).append(parameter)
    for path, found in values.items():
        distinct = {(p.get("Value"), p.get("Unit")) for p in found}
        if len(found) == len(sims) and len(distinct) == 1:
            parameter = found[0]
            out.add(f"sim.{path}", parameter["Value"], unit=parameter.get("Unit"), parameter=parameter,
                    binding=EngineBinding(building_block="Simulation", parameter=path))
        else:
            notes.append(f"Simulation parameter {path!r} differs between the published simulations; not imported.")


def _formulation_records(snapshot: dict[str, Any], out: _Records, unplaced: list[str]) -> None:
    from pbpk_domain.cpf.formulations import DISSOLVED, WEIBULL, WEIBULL_PARAMETERS

    engine_to_key = {v: k for k, v in WEIBULL_PARAMETERS.items()}
    for formulation in snapshot.get("Formulations", []):
        name, kind = formulation.get("Name"), formulation.get("FormulationType")
        if kind == "Formulation_Dissolved":
            out.add(f"form.{name}.type", DISSOLVED)
        elif kind == "Formulation_Tablet_Weibull":
            out.add(f"form.{name}.type", WEIBULL)
            for parameter in formulation.get("Parameters", []):
                key = engine_to_key.get(parameter.get("Name"))
                if key is not None:
                    out.add(f"form.{name}.weibull.{key}", parameter["Value"], unit=parameter.get("Unit"),
                            parameter=parameter)
        else:
            unplaced.append(f"formulation {name!r} ({kind}): type not placed by the builder yet")


def _individual_records(snapshot: dict[str, Any], out: _Records, notes: list[str]) -> None:
    individuals = snapshot.get("Individuals", [])
    if not individuals:
        return
    # The individual most of the published simulations use; any simulation on another one is named.
    used = [s.get("Individual") for s in snapshot.get("Simulations", []) if s.get("Individual")]
    main = max(individuals, key=lambda i: used.count(i["Name"]))
    others = sorted({f"{s['Name']} ({s['Individual']})" for s in snapshot.get("Simulations", [])
                     if s.get("Individual") and s["Individual"] != main["Name"]})
    if others:
        notes.append(f"Individual physiology imported from {main['Name']!r}; these published simulations use another "
                     "individual and are regenerated with the main one: " + "; ".join(others) + ".")
    individual = main
    for parameter in individual.get("Parameters", []):
        path = parameter.get("Path")
        if not path or parameter.get("Value") is None:
            continue
        out.add(f"indiv.{path}", parameter["Value"], unit=parameter.get("Unit"), parameter=parameter,
                binding=EngineBinding(building_block="Individual", parameter=path))
    origin = individual.get("OriginData", {})
    notes.append(
        f"Studies are simulated in the pipeline's standard individual ({origin.get('Population')}, "
        f"{origin.get('Gender')}, {origin.get('Age', {}).get('Value')} years in the published model); the published "
        "individual's changed physiology is carried as indiv.* records."
    )


def _simulation_links(snapshot: dict[str, Any], compound: str) -> dict[str, dict[str, Any]]:
    """Observed dataset name -> how the published model simulates it: protocol, formulation, meal events, infusion.

    A dataset is linked by the simulation that lists it, else by the published parameter identification that fits it
    against a simulation's output (``ParameterIdentifications[].OutputMappings``: the paper's own fitting design)."""
    protocols = {p["Name"]: p for p in snapshot.get("Protocols", [])}
    individuals = {i["Name"]: i for i in snapshot.get("Individuals", [])}
    by_sim: dict[str, dict[str, Any]] = {}
    links: dict[str, dict[str, Any]] = {}
    for sim in snapshot.get("Simulations", []):
        entry = next((c for c in sim.get("Compounds", []) if c.get("Name") == compound), None)
        if entry is None:
            continue
        protocol_ref = entry.get("Protocol") or {}
        formulations = protocol_ref.get("Formulations") or []
        infusion = next((float(p["Value"]) * (60.0 if p.get("Unit") == "h" else 1.0)
                         for p in sim.get("Parameters", []) or []
                         if str(p.get("Path", "")).endswith("|Application_1|ProtocolSchemaItem|Infusion time")), None)
        individual = individuals.get(sim.get("Individual"), {})
        origin = individual.get("OriginData", {})
        link = {
            "demographics": {"population": origin.get("Population"), "sex": origin.get("Gender"),
                             "age_years": (origin.get("Age") or {}).get("Value")} if origin else None,
            "simulation": sim["Name"],
            "protocol": protocols.get(protocol_ref.get("Name"), {}),
            "formulation": formulations[0]["Name"] if formulations else None,
            "fed": bool(sim.get("Events")),
            "infusion_min": infusion,
        }
        by_sim[sim["Name"]] = link
        for name in sim.get("ObservedData", []):
            links.setdefault(name, link)
    for pi in snapshot.get("ParameterIdentifications", []) or []:
        for mapping in pi.get("OutputMappings", []) or []:
            sim_name = str(mapping.get("Path", "")).split("|", 1)[0]
            if sim_name in by_sim and mapping.get("ObservedData"):
                links.setdefault(mapping["ObservedData"], by_sim[sim_name])
    return links


def _dose_times(administered: Any) -> list[float] | None:
    """Dose times (h) from OSP "Times of Administration [h]": a number, "0-24-48", "(S0-T24-R14)" or a mix."""
    if administered is None:
        return None
    if isinstance(administered, int | float):
        return [float(administered)]
    text = str(administered)
    times: list[float] = []
    for match in _SCHEDULE.finditer(text):
        start, interval, n = float(match.group("start")), float(match.group("interval")), int(match.group("n"))
        times.extend(start + k * interval for k in range(n))
    rest = _SCHEDULE.sub(" ", text)
    for token in re.split(r"[-\s]+", rest):
        if token:
            try:
                times.append(float(token))
            except ValueError:
                return None
    return sorted(set(times)) or None


def _protocol_dose_times(protocol: dict[str, Any]) -> list[float] | None:
    """Dose times (h) of a published protocol: a simple one-dose protocol, or schemas repeated at an interval."""
    def hours(params: list[dict[str, Any]], name: str, default: float = 0.0) -> float:
        p = next((q for q in params if q.get("Name") == name), None)
        if p is None:
            return default
        return float(p["Value"]) / (60.0 if p.get("Unit") == "min" else 1.0)

    if not protocol:
        return None
    if not protocol.get("Schemas"):
        return [hours(protocol.get("Parameters", []), "Start time")] if protocol.get("DosingInterval") == "Single" else None
    times: list[float] = []
    for schema in protocol["Schemas"]:
        params = schema.get("Parameters", [])
        start = hours(params, "Start time")
        n = int(next((q["Value"] for q in params if q.get("Name") == "NumberOfRepetitions"), 1))
        interval = hours(params, "TimeBetweenRepetitions")
        for item in schema.get("SchemaItems", []):
            item_start = hours(item.get("Parameters", []), "Start time")
            times.extend(start + item_start + k * interval for k in range(n))
    return sorted(set(times))


def _infusion_time_min(protocol: dict[str, Any]) -> float | None:
    items = [protocol, *[i for s in protocol.get("Schemas", []) for i in s.get("SchemaItems", [])]]
    for item in items:
        for parameter in item.get("Parameters", []):
            if parameter.get("Name") == "Infusion time":
                value, unit = float(parameter["Value"]), parameter.get("Unit", "min")
                return value * (60.0 if unit == "h" else 1.0)
    return None


def _study(dataset: dict[str, Any], link: dict[str, Any] | None, formulation_types: dict[str, str]) -> tuple[dict | None, str]:
    """One plasma dataset -> (StudyUpload row, "") or (None, reason it cannot be used)."""
    props = _props(dataset)
    column = next((c for c in dataset.get("Columns", []) if c.get("DataInfo", {}).get("Origin") == "Observation"), None)
    if column is None or not column.get("Unit"):
        return None, "no observed concentration column with a unit"
    dose = _DOSE.match(str(props.get("Dose", "")))
    if dose is None:
        return None, f"dose {props.get('Dose')!r} is not a single mg / µg amount (or per kg)"

    said: list[str] = []
    row: dict[str, Any] = {
        "study_id": _slug(f"{props.get('Study Id', '')} {props.get('Grouping', '')}"),
        "n": int(float(props.get("N") or 1)),
        "dose_mg": float(dose.group("value")) * _TO_MG[dose.group("unit")],
        "dose_per_kg": dose.group("unit").endswith("/kg"),
        "n_timepoints": len(dataset["BaseGrid"]["Values"]),
    }

    route = _given(props.get("Route"))
    if route == "IV":
        # The infusion time the published simulation uses, else its protocol's, else the one the dataset names.
        infusion = (link.get("infusion_min") or _infusion_time_min(link["protocol"])) if link else None
        if infusion is None:
            named = _INFUSION_IN_NAME.search(str(props.get("Grouping", "")))
            if named is not None:
                infusion = float(named.group("value")) * (60.0 if named.group("unit") == "h" else 1.0)
                said.append(f"infusion time {infusion:g} min from the dataset's description")
        if infusion is None:
            return None, "IV dataset with no infusion time (no linked protocol, none in its description)"
        row.update(route="iv_infusion", infusion_time_min=infusion, formulation="solution")
    elif route == "PO":
        row["route"] = "oral"
    else:
        return None, f"route {route!r} is not IV or PO"

    # Regimen: the dataset's own administration times, else the linked published protocol's. One dose is a single
    # dose given then (times are shifted to it); a regular schedule is a multiple-dose study; an irregular one cannot
    # be placed by the builder (regular schedules only) and is named.
    doses = _dose_times(props.get("Times of Administration [h]"))
    if doses is None:
        return None, f"administration times {props.get('Times of Administration [h]')!r} could not be read"
    if len(doses) == 1 and link is not None:
        # Only when the dataset was sampled after the second dose: a day-1 profile the paper fitted against a
        # multiple-dose simulation is still a single-dose profile (and is classified as one).
        linked = _protocol_dose_times(link["protocol"])
        last_h = max(float(t) for t in dataset["BaseGrid"]["Values"]) * (1 / 60.0 if dataset["BaseGrid"].get("Unit") == "min" else 1.0)
        if linked and len(linked) > 1 and last_h > linked[1]:
            doses = linked
            said.append(f"dosing schedule from the published protocol {link['protocol'].get('Name')!r}")
    shift_h = doses[0]
    multiple = len(doses) > 1
    if multiple:
        gaps = {round(b - a, 6) for a, b in pairwise(doses)}
        if len(gaps) != 1:
            return None, f"irregular dosing schedule (doses at {', '.join(f'{d:g}' for d in doses)} h)"
        row.update(design="MD", dosing_interval_h=gaps.pop(), n_doses=len(doses))
    if shift_h:
        said.append(f"first dose at {shift_h:g} h in the study; times shifted so it is at 0")

    if row["route"] == "oral":
        stated = _given(props.get("Formulation"))
        linked_form = link.get("formulation") if link else None
        if linked_form is None:
            dissolved = [n for n, t in formulation_types.items() if t == "Dissolved"]
            if len(dissolved) == 1:
                linked_form = dissolved[0]
                said.append(f"no published simulation runs this dataset; simulated with {linked_form!r}")
        if stated is not None:
            kind = next((k for word, k in _FORMULATION_WORDS if word in stated.lower()), None)
            if kind is None:
                # A product name that does not say its form (e.g. "Dormicum") is not guessed: the study is judged
                # (PO-OTHER, external validation only) but never trains absorption or release.
                kind = "other"
                said.append(f"formulation {stated!r} does not name its form; recorded as other (validation only)")
            elif stated.lower() not in ("solution", "suspension", "tablet", "capsule"):
                said.append(f"formulation {stated!r} classified as {kind}")
        elif linked_form is not None and formulation_types.get(linked_form) == "Weibull":
            kind = "ir_tablet"
            said.append(f"formulation not reported; the published model uses the tablet {linked_form!r}")
        else:
            kind = "ir_tablet"
            said.append("formulation not reported; recorded as an immediate-release tablet, simulated as the "
                        f"published model does ({linked_form or 'Dissolved'})")
        row["formulation"] = kind
        if kind in ("ir_tablet", "ir_capsule", "other") and linked_form is not None:
            row["formulation_name"] = linked_form

    food = _given(props.get("Food state"))
    if food is None:
        food = "Fed" if link and link.get("fed") else "Fasted"
        said.append(f"food state not reported; {food.lower()} as in the published simulation")
    elif food.lower() == "fed" and link is not None and not link.get("fed"):
        said.append("reported fed; the published model simulates it without a meal")
    row["food_state"] = food.lower()

    grouping = str(props.get("Grouping", "")).lower()
    if "renal impairment" in grouping:
        row["special_population"] = "renal_impairment"
    if "liver disease" in grouping or "hepatic impairment" in grouping:
        row["special_population"] = "hepatic_impairment"
    if "t2dm" in grouping or "patient" in grouping:
        row["population_type"] = "patient"
    if "placebo" in grouping:
        said.append("control arm of a DDI study (perpetrator placebo): the drug given alone")
    demographics = (link or {}).get("demographics")
    if demographics and all(demographics.values()):
        row["demographics"] = demographics  # the individual the published simulation uses for this study
    co_medication = next((w for w in _CO_MEDICATION_WORDS if w in grouping), None)
    if co_medication is not None:
        row["co_medication"] = co_medication

    times = [float(t) - shift_h for t in dataset["BaseGrid"]["Values"]]
    values = [float(v) for v in column["Values"]]
    keep = [(t, v) for t, v in zip(times, values, strict=True) if t >= 0 and v > 0]
    if len(keep) < 3:
        return None, "fewer than 3 positive observations after the dose"
    row["profile"] = {
        "times": [t for t, _ in keep], "values": [v for _, v in keep],
        "time_unit": dataset["BaseGrid"].get("Unit", "h"), "unit": column["Unit"],
    }
    row["n_timepoints"] = len(keep)
    row["_offset_min"] = shift_h * 60.0

    source = " ".join(str(props.get(k)) for k in ("Source",) if _given(props.get(k)))
    reference = f"{props.get('Study Id', '')} — {props.get('Grouping', '')}"
    if _given(props.get("Reference")):
        reference += f" ({props['Reference']}" + (f", {source}" if source else "") + ")"
    if said:
        reference += ". Import: " + "; ".join(said) + "."
    row["reference"] = reference
    return row, ""


def import_osp_snapshot(snapshot: dict[str, Any], *, source: str | None = None) -> ReferenceImport:
    """Turn one published single-compound OSP model snapshot into a CPF and its plasma studies."""
    compounds = snapshot.get("Compounds") or []
    if len(compounds) != 1:
        raise ReferenceImportError(f"expected one compound in the snapshot, found {len(compounds)}")
    compound = compounds[0]
    name = compound["Name"]
    source = source or f"OSP {name} model"

    records = _Records(source)
    notes: list[str] = []
    unplaced: list[str] = []
    _compound_records(snapshot, compound, records, notes)
    _process_records(snapshot, compound, records, unplaced, notes)
    _simulation_parameter_records(snapshot, name, records, notes)
    _formulation_records(snapshot, records, unplaced)
    _individual_records(snapshot, records, notes)
    cpf = CPF(compound=name, parameters=tuple(records.records), note=f"Imported from the {source} snapshot")

    formulation_types = {
        r.id.split(".")[1]: str(r.value) for r in cpf.parameters if r.id.startswith("form.") and r.id.endswith(".type")
    }
    links = _simulation_links(snapshot, name)
    studies: list[dict[str, Any]] = []
    skipped: list[str] = []
    seen: set[str] = set()
    simulation_of: dict[str, str] = {}
    offset_min: dict[str, float] = {}
    differs_by_design: dict[str, str] = {}
    for dataset in snapshot.get("ObservedData", []):
        props = _props(dataset)
        label = dataset["Name"]
        if props.get("Molecule") != name:
            skipped.append(f"{label}: data for {props.get('Molecule')}, not the parent drug")
            continue
        compartment = props.get("Compartment")
        if compartment in ("Urine", "Feces"):
            skipped.append(f"{label}: {compartment} fraction data (excreta need task T-11)")
            continue
        if compartment != "Plasma":
            skipped.append(f"{label}: {compartment} data; only plasma concentrations are compared")
            continue
        row, reason = _study(dataset, links.get(label), formulation_types)
        if row is None:
            skipped.append(f"{label}: {reason}")
            continue
        if row["study_id"] in seen:
            skipped.append(f"{label}: duplicate study id {row['study_id']!r}")
            continue
        seen.add(row["study_id"])
        studies.append(row)
        link = links.get(label)
        if link is not None:
            simulation_of[row["study_id"]] = link["simulation"]
            offset_min[row["study_id"]] = row.pop("_offset_min", 0.0)
            published_doses = _protocol_dose_times(link["protocol"]) or []
            ours_doses = row.get("n_doses") or 1
            why = []
            if published_doses and len(published_doses) != ours_doses:
                why.append(f"{ours_doses} dose(s) as the study gave them; the published simulation gives "
                           f"{len(published_doses)}")
            if row.get("food_state") == "fed" and not link.get("fed"):
                why.append("simulated fed as reported; the published simulation has no meal")
            if why:
                differs_by_design[row["study_id"]] = "; ".join(why)
        row.pop("_offset_min", None)

    return ReferenceImport(compound=name, source=source, cpf=cpf, studies=tuple(studies), skipped=tuple(skipped),
                           unplaced=tuple(unplaced), notes=tuple(notes), simulation_of=simulation_of,
                           offset_min=offset_min, differs_by_design=differs_by_design)
