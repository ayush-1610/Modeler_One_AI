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
from dataclasses import dataclass
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
    "CompetitiveInhibition": {"Ki": ("ki", "µmol/l")},
    "Induction": {"EC50": ("ec50", "µmol/l"), "Emax": ("emax", None)},
    "GlomerularFiltration": {"GFR fraction": ("gfr_fraction", None)},
}
_PROCESS_FAMILY = {
    "MetabolizationSpecific_FirstOrder": "elim.hepatic",
    "MetabolizationSpecific_MM": "elim.hepatic",
    "ActiveTransportSpecific_MM": "transp",
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

_FORMULATION_KIND = {"solution": "solution", "suspension": "suspension", "tablet": "ir_tablet", "capsule": "ir_capsule"}
_REGIMEN = re.compile(r"\(S(?P<start>[\d.]+)-T(?P<interval>[\d.]+)-R(?P<n>\d+)\)")
_DOSE = re.compile(r"^\s*(?P<value>[\d.]+)\s*mg\s*$")


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
        status = ParameterStatus.FITTED if origin.get("Source") == "ParameterIdentification" else ParameterStatus.FIXED
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


def _process_records(compound: dict[str, Any], out: _Records, unplaced: list[str]) -> None:
    for process in compound.get("Processes", []):
        internal = process.get("InternalName")
        wanted = _PROCESS_PARAMETERS.get(internal)
        molecule = process.get("Molecule")
        label = f"{internal}" + (f" ({molecule})" if molecule else "")
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
    if len(individuals) != 1:
        notes.append(f"The model has {len(individuals)} individuals; no individual physiology imported.")
        return
    individual = individuals[0]
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
    """Observed dataset name -> how the published model simulates it: protocol, formulation, meal events."""
    protocols = {p["Name"]: p for p in snapshot.get("Protocols", [])}
    links: dict[str, dict[str, Any]] = {}
    for sim in snapshot.get("Simulations", []):
        entry = next((c for c in sim.get("Compounds", []) if c.get("Name") == compound), None)
        if entry is None:
            continue
        protocol_ref = entry.get("Protocol") or {}
        formulations = protocol_ref.get("Formulations") or []
        link = {
            "simulation": sim["Name"],
            "protocol": protocols.get(protocol_ref.get("Name"), {}),
            "formulation": formulations[0]["Name"] if formulations else None,
            "fed": bool(sim.get("Events")),
        }
        for name in sim.get("ObservedData", []):
            links.setdefault(name, link)
    return links


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
        return None, f"dose {props.get('Dose')!r} is not a single mg amount"

    said: list[str] = []
    row: dict[str, Any] = {
        "study_id": _slug(f"{props.get('Study Id', '')} {props.get('Grouping', '')}"),
        "n": int(float(props.get("N") or 1)),
        "dose_mg": float(dose.group("value")),
        "n_timepoints": len(dataset["BaseGrid"]["Values"]),
    }

    route = _given(props.get("Route"))
    if route == "IV":
        infusion = _infusion_time_min(link["protocol"]) if link else None
        if infusion is None:
            return None, "IV dataset with no linked protocol giving its infusion time"
        row.update(route="iv_infusion", infusion_time_min=infusion, formulation="solution")
    elif route == "PO":
        row["route"] = "oral"
    else:
        return None, f"route {route!r} is not IV or PO"

    # Regimen: a numeric administration time is a single dose given then; "(S0-T24-R14)" is a regular schedule.
    administered = props.get("Times of Administration [h]")
    shift_h = 0.0
    regimen = _REGIMEN.search(str(administered)) if administered is not None else None
    if regimen is not None:
        row.update(design="MD", dosing_interval_h=float(regimen.group("interval")), n_doses=int(regimen.group("n")))
        shift_h = float(regimen.group("start"))
    elif isinstance(administered, int | float):
        shift_h = float(administered)
    if shift_h:
        said.append(f"dose given at {shift_h:g} h in the study; times shifted so the dose is at 0")

    if row["route"] == "oral":
        stated = _given(props.get("Formulation"))
        linked_form = link.get("formulation") if link else None
        if linked_form is None:
            dissolved = [n for n, t in formulation_types.items() if t == "Dissolved"]
            if len(dissolved) == 1:
                linked_form = dissolved[0]
                said.append(f"no published simulation runs this dataset; simulated with {linked_form!r}")
        if stated is not None:
            kind = _FORMULATION_KIND.get(stated.lower())
            if kind is None:
                return None, f"formulation {stated!r} is not one the pipeline classifies"
        elif linked_form is not None and formulation_types.get(linked_form) == "Weibull":
            kind = "ir_tablet"
            said.append(f"formulation not reported; the published model uses the tablet {linked_form!r}")
        else:
            kind = "ir_tablet"
            said.append("formulation not reported; recorded as an immediate-release tablet, simulated as the "
                        f"published model does ({linked_form or 'Dissolved'})")
        row["formulation"] = kind
        if kind in ("ir_tablet", "ir_capsule") and linked_form is not None:
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
    if "t2dm" in grouping or "patient" in grouping:
        row["population_type"] = "patient"
    if "placebo" in grouping:
        said.append("control arm of a DDI study (perpetrator placebo): the drug given alone")

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
    _process_records(compound, records, unplaced)
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

    return ReferenceImport(compound=name, source=source, cpf=cpf, studies=tuple(studies), skipped=tuple(skipped),
                           unplaced=tuple(unplaced), notes=tuple(notes))
