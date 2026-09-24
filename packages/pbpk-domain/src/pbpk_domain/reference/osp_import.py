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

import json
import math
import os
import re
from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from pbpk_domain.cpf.models import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.system import PLASMA, Analyte, Formation, ModelSystem

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
    # harvested from the OSP model library snapshots (2026-09-24); units are the builder's (HARVESTED_PROCESSES)
    "MetabolizationIntrinsic_FirstOrder": {"Intrinsic clearance": ("cl_intrinsic", "l/min"),
                                           "Specific clearance": ("specific_clearance", "1/min")},
    "rCYP450_MM": {"In vitro Vmax/recombinant enzyme": ("vmax_recombinant", "pmol/min/pmol rec. enzyme"),
                   "Km": ("km", "µmol/l"), "kcat": ("kcat", "1/min")},
    "rCYP450_FirstOrder": {"In vitro CL/recombinant enzyme": ("cl_recombinant", "µl/min/pmol rec. enzyme"),
                           "CLspec/[Enzyme]": ("clspec", "l/µmol/min")},
    "LiverClearance": {"Plasma clearance": ("plasma_clearance", "ml/min/kg"), "Specific clearance": ("specific_clearance", "1/min"),
                       "Fraction unbound (experiment)": ("fu_experiment", None),
                       "Lipophilicity (experiment)": ("logp_experiment", "Log Units"),
                       "Blood/Plasma concentration ratio": ("bp_experiment", None)},
    "KidneyClearance": {"Plasma clearance": ("plasma_clearance", "ml/min/kg"), "Specific clearance": ("specific_clearance", "1/min"),
                        "Fraction unbound (experiment)": ("fu_experiment", None),
                        "Blood flow rate (kidney)": ("kidney_blood_flow", "l/min"), "Body weight": ("body_weight", "kg")},
    "ActiveTransportSpecific_Hill": {"Vmax": ("vmax", "µmol/l/min"), "Km": ("km", "µmol/l"),
                                     "Transporter concentration": ("transporter_conc", "µmol/l"),
                                     "Hill coefficient": ("hill", None)},
    "ActiveTransport_InVitro_VesicularAssay_MM": {"In vitro Vmax/transporter": ("vmax_vesicular", "pmol/min/pmol transporter"),
                                                  "Km": ("km", "µmol/l"), "kcat": ("kcat", "1/min")},
    "IrreversibleInhibition": {"kinact": ("kinact", "1/min"), "K_kinact_half": ("kinact_half", "µmol/l"),
                               "Ki": ("ki_irreversible", "µmol/l")},
    "MixedInhibition": {"Ki_c": ("ki_c", "µmol/l"), "Ki_u": ("ki_u", "µmol/l")},
    "NoncompetitiveInhibition": {"Ki": ("ki_noncompetitive", "µmol/l")},
}
_PROCESS_FAMILY = {
    "MetabolizationIntrinsic_FirstOrder": "elim.hepatic",
    "rCYP450_MM": "elim.hepatic",
    "rCYP450_FirstOrder": "elim.hepatic",
    "ActiveTransportSpecific_Hill": "transp",
    "ActiveTransport_InVitro_VesicularAssay_MM": "transp",
    "IrreversibleInhibition": "ddi.perp",
    "MixedInhibition": "ddi.perp",
    "NoncompetitiveInhibition": "ddi.perp",
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
    {"µmol/l": 1.0, "µM": 1.0, "pmol/l": 1e-6, "nmol/l": 1e-3, "nM": 1e-3, "mmol/l": 1e3},
    {"µmol/l/min": 1.0, "pmol/ml/min": 1e-3, "nmol/l/min": 1e-3},
    {"pmol/min/mg mic. protein": 1.0, "nmol/min/mg mic. protein": 1e3},
    {"pmol/min/pmol rec. enzyme": 1.0, "nmol/min/pmol rec. enzyme": 1e3},
    {"pmol/min/pmol transporter": 1.0, "nmol/min/pmol transporter": 1e3},
    {"1/min": 1.0, "1/h": 1.0 / 60.0, "1/s": 60.0},
    {"ml/min/kg": 1.0, "ml/h/kg": 1.0 / 60.0, "l/h/kg": 1000.0 / 60.0, "l/min/kg": 1000.0},
    {"l/min": 1.0, "ml/min": 1e-3, "l/h": 1.0 / 60.0},
    {"mg/ml": 1.0, "mg/l": 1e-3, "g/l": 1.0, "µg/ml": 1e-3, "µg/l": 1e-6, "mg/dl": 1e-2},
    {"cm/min": 1.0, "dm/min": 10.0, "µm/min": 1e-4, "cm/s": 60.0},
    {"µm": 1.0, "mm": 1e3, "nm": 1e-3, "cm": 1e4},
    {"": 1.0, "%": 1e-2},  # dimensionless fraction
)


def _convert(value: float, unit: str | None, target: str | None) -> float:
    src, dst = unit or "", target or ""
    if src == dst:
        return value
    for table in _SAME_DIMENSION:
        if src in table and dst in table:
            return value * table[src] / table[dst]
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
# Reported "Food state" words (every value in the OSP model library, 2026-09-24): a meal given is fed; "semifasted",
# "unknown" and mixed arms have no MS-01 class and fall back to the published simulation's meal state, noted.
_FOOD_STATE = {"fasted": "fasted", "fed": "fed", "breakfast": "fed", "light breakfast": "fed", "semifed": "fed"}
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


def _alternative_of(sim: dict[str, Any], compound: dict[str, Any], group: str) -> str | None:
    """The alternative of a property group one simulation uses: the one it lists, else the compound's default."""
    entry = next((c for c in sim.get("Compounds", []) if c.get("Name") == compound["Name"]), {})
    listed = next((a.get("AlternativeName") for a in entry.get("Alternatives", []) or []
                   if a.get("GroupName") == _ALTERNATIVE_GROUPS[group]), None)
    if listed:
        return listed
    alternatives = compound.get(group) or []
    default = next((a for a in alternatives if a.get("IsDefault")), alternatives[0] if len(alternatives) == 1 else None)
    return default.get("Name") if default else None


def _selected_alternative(snapshot: dict[str, Any], compound: dict[str, Any], group: str) -> dict[str, Any] | None:
    """The alternative of a property group the model uses: the only one, else the one most of the compound's own
    simulations use (the studies simulated with another are labelled by the importer)."""
    alternatives = compound.get(group) or []
    if len(alternatives) == 1:
        return alternatives[0]
    used = Counter(n for sim in _own_simulations(snapshot, compound["Name"])
                   if (n := _alternative_of(sim, compound, group)) is not None)
    if not used:
        return None
    ranked = used.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None  # a tie: no majority to import
    return next((a for a in alternatives if a.get("Name") == ranked[0][0]), None)


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
        table = next((p for p in alternative.get("Parameters", []) if p.get("Name") == "Solubility table"), None)
        if group == "Solubility" and name == "Solubility at reference pH" and table is not None and table.get("TableFormula"):
            formula = table["TableFormula"]
            y_unit = formula.get("YUnit") or table.get("Unit")
            doc = {"value": _convert(float(table["Value"]), table.get("Unit"), "mg/l"),
                   "points": [[float(q["X"]), _convert(float(q["Y"]), y_unit, "mg/l")] for q in formula.get("Points", [])]}
            out.add("phys.solubility.table", json.dumps(doc), unit="mg/l", parameter=table)
        if len(compound.get(group) or []) > 1:
            note = f"{group}: alternative {alternative.get('Name')!r} imported (used by most of the compound's simulations)."
            if note not in notes:
                notes.append(note)

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


def _dosed(sim: dict[str, Any]) -> list[str]:
    """The compounds a simulation doses (those with a protocol); the others are metabolites it forms."""
    return [c["Name"] for c in sim.get("Compounds", []) if c.get("Protocol")]


# The compounds of the model system being imported (import_osp_system); None for a single-compound import.
_MEMBERS: ContextVar[frozenset[str] | None] = ContextVar("osp_system_members", default=None)


def _own_simulations(snapshot: dict[str, Any], compound: str) -> list[dict[str, Any]]:
    """The simulations that dose the compound and no other drug (its own kinetics, not a DDI arm); all simulations
    that dose it when there is none such. Inside a system import: the simulations the compound takes part in (dosed or
    formed) that dose only compounds of the system."""
    members = _MEMBERS.get()
    if members is not None:
        return [s for s in snapshot.get("Simulations", []) if _dosed(s) and set(_dosed(s)) <= members
                and any(c.get("Name") == compound for c in s.get("Compounds", []))]
    dosing = [s for s in snapshot.get("Simulations", []) if compound in _dosed(s)]
    alone = [s for s in dosing if _dosed(s) == [compound]]
    return alone or dosing


def _selected_interactions(snapshot: dict[str, Any], compound: str) -> set[str]:
    """The compound's interactions its own simulations select. One selected only in a DDI arm (a perpetrator's
    inhibition of the victim drug's enzyme) is not part of the compound's own model."""
    return {i.get("Name") for sim in _own_simulations(snapshot, compound) for i in sim.get("Interactions", []) or []
            if i.get("CompoundName") == compound}


def _selection_name(process: dict[str, Any]) -> str:
    """How a simulation selects a compound process (harvested: molecule-based, GFR, total hepatic, renal)."""
    ds = process.get("DataSource")
    internal = process.get("InternalName")
    if process.get("Molecule"):
        return f"{process['Molecule']}-{ds}"
    return {"GlomerularFiltration": f"Glomerular Filtration-{ds}", "LiverClearance": f"Total Hepatic Clearance-{ds}",
            "KidneyClearance": f"Renal Clearances-{ds}"}.get(internal, f"{internal}-{ds}")


def _selected_processes(snapshot: dict[str, Any], compound: str) -> set[str] | None:
    """The process names the compound's own simulations select; None when they select none (nothing to go by)."""
    names = {p.get("Name") for sim in _own_simulations(snapshot, compound) for c in sim.get("Compounds", [])
             if c.get("Name") == compound for p in c.get("Processes", []) or [] if p.get("Name")}
    return names or None


def _parent_compound(snapshot: dict[str, Any], wanted: str | None) -> dict[str, Any]:
    """The compound to import: the one named (case-insensitive), the only one, or the one most simulations dose."""
    compounds = snapshot.get("Compounds") or []
    if not compounds:
        raise ReferenceImportError("the snapshot has no compound")
    if wanted is not None:
        match = [c for c in compounds if c["Name"].lower() == wanted.lower()]
        if not match:
            raise ReferenceImportError(f"no compound {wanted!r} in the snapshot ({', '.join(c['Name'] for c in compounds)})")
        return match[0]
    if len(compounds) == 1:
        return compounds[0]
    dosed = [n for s in snapshot.get("Simulations", []) for n in _dosed(s)]
    return max(compounds, key=lambda c: dosed.count(c["Name"]))


def _feedback(snapshot: dict[str, Any], parent: dict[str, Any], sim: dict[str, Any]) -> list[str]:
    """Metabolites a simulation forms that act on a protein the parent is cleared or transported by (e.g. hydroxy-
    itraconazole inhibiting CYP3A4). The pipeline simulates the parent alone, so such a curve differs by design."""
    from pbpk_domain.snapshot.validation import INTERACTION_PROCESSES

    own = {p.get("Molecule") for p in parent.get("Processes", []) if p.get("Molecule")
           and p.get("InternalName") not in INTERACTION_PROCESSES}
    by_name = {c["Name"]: c for c in snapshot.get("Compounds", [])}
    selected = {(i.get("CompoundName"), i.get("MoleculeName")) for i in sim.get("Interactions", []) or []}
    out = []
    for entry in sim.get("Compounds", []):
        other = by_name.get(entry["Name"])
        if other is None or other["Name"] == parent["Name"] or entry.get("Protocol"):
            continue
        hit = sorted({p["Molecule"] for p in other.get("Processes", []) if p.get("InternalName") in INTERACTION_PROCESSES
                      and p.get("Molecule") in own and (other["Name"], p["Molecule"]) in selected})
        if hit:
            out.append(f"metabolite {other['Name']} acts on {', '.join(hit)}, which clears the parent")
    return out


def _process_records(snapshot: dict[str, Any], compound: dict[str, Any], out: _Records, unplaced: list[str],
                     notes: list[str]) -> None:
    from pbpk_domain.snapshot.validation import INTERACTION_PROCESSES

    selected = _selected_interactions(snapshot, compound["Name"])
    used = _selected_processes(snapshot, compound["Name"])
    not_selected: list[str] = []
    unused: list[str] = []
    planned: list[tuple[dict[str, Any], str, str, dict]] = []
    derived: set[str] = set()
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
        if internal not in INTERACTION_PROCESSES and used is not None and _selection_name(process) not in used:
            unused.append(f"{label} [{process.get('DataSource')}]")  # an alternative pathway no simulation uses
            continue
        if wanted is None:
            unplaced.append(f"{label}: process type not placed by the builder yet")
            continue
        if internal == "GlomerularFiltration":
            prefix = "elim.renal"
        elif internal == "LiverClearance":
            prefix = "elim.hepatic.total"
        elif internal == "KidneyClearance":
            prefix = "elim.renal.total"
        else:
            prefix = f"{_PROCESS_FAMILY[internal]}.{molecule}"
        planned.append((process, internal, prefix, wanted))
    # Two pathways of one family on one protein (Alprazolam: CYP3A4 alpha-OH and 4-OH) would share ids: those
    # processes' ids name their data source, e.g. elim.hepatic.CYP3A4@alpha-OH pathway.kcat.
    ids = Counter(f"{prefix}.{suffix}" for process, _i, prefix, wanted in planned
                  for q in process.get("Parameters", []) if (suffix := (wanted.get(q.get("Name")) or (None,))[0]))
    for process, internal, prefix, wanted in planned:
        molecule = process.get("Molecule")
        engine_process = f"{internal}:{molecule}" if molecule else internal
        suffixes = [wanted[q["Name"]][0] for q in process.get("Parameters", []) if q.get("Name") in wanted]
        if any(ids[f"{prefix}.{s}"] > 1 for s in suffixes):
            prefix = f"{prefix}@{str(process.get('DataSource')).replace('.', '')}"
        for parameter in process.get("Parameters", []):
            target = wanted.get(parameter.get("Name"))
            if target is None:
                derived.add(f"{parameter.get('Name')} ({internal})")
                continue
            suffix, unit = target
            value = _convert(float(parameter["Value"]), parameter.get("Unit"), unit)
            binding = EngineBinding(building_block="Compound", parameter=parameter["Name"], process=engine_process,
                                    data_source=process.get("DataSource"))
            out.add(f"{prefix}.{suffix}", value, unit=unit, parameter=parameter, binding=binding)
    if derived:
        notes.append("Process values PK-Sim derives from the imported inputs, not imported: " + ", ".join(sorted(derived)) + ".")
    if unused:
        notes.append("Processes defined but selected in none of the compound's own simulations, not imported: "
                     + ", ".join(unused) + ".")
    if not_selected:
        notes.append("Interactions defined for victim drugs and selected in none of the model's simulations, left "
                     "for the DDI application: " + ", ".join(not_selected) + ".")


def _simulation_parameter_records(snapshot: dict[str, Any], compound: str, out: _Records, notes: list[str]) -> None:
    """Compound values the published simulations set themselves: ``<Compound>|logP (veg.oil/water)``, or a path
    through the compound such as ``Neighborhoods|Duodenum_int_Duodenum_cell|<Compound>|P (interstitial->intracellular)``
    (a gut-wall permeability identified by PI). One that the simulations setting it all set to the same value, in at
    least half of the simulations, is part of the model and becomes a ``sim.*`` record (the simulations that leave it
    at the default are named); one that varies between simulations is named, not imported."""
    sims = [s for s in snapshot.get("Simulations", []) if any(c.get("Name") == compound for c in s.get("Compounds", []))]
    values: dict[str, list[dict[str, Any]]] = {}
    without: dict[str, list[str]] = {}
    for sim in sims:
        for parameter in sim.get("Parameters", []) or []:
            path = parameter.get("Path") or ""
            if compound in path.split("|")[:-1] and not path.startswith(("Events|", "Applications|")):
                values.setdefault(path, []).append(parameter)
    for path, found in values.items():
        distinct = {(p.get("Value"), p.get("Unit")) for p in found}
        if len(distinct) == 1 and 2 * len(found) >= len(sims):
            parameter = found[0]
            out.add(f"sim.{path}", parameter["Value"], unit=parameter.get("Unit"), parameter=parameter,
                    binding=EngineBinding(building_block="Simulation", parameter=path))
            setting = {id(p) for p in found}
            for sim in sims:
                if not any(id(p) in setting for p in sim.get("Parameters", []) or []):
                    without.setdefault(sim.get("Name", "?"), []).append(path)
        else:
            notes.append(f"Simulation parameter {path!r} differs between the published simulations; not imported.")
    for name, paths in without.items():
        notes.append(f"Published simulation {name!r} leaves {len(paths)} simulation parameter(s) at the default "
                     f"(e.g. {paths[0]!r}); it is regenerated with the model's value.")


def _formulation_records(snapshot: dict[str, Any], out: _Records, unplaced: list[str]) -> None:
    from pbpk_domain.cpf.formulations import (
        DISSOLVED,
        PARTICLE_BINS,
        PARTICLE_PARAMETERS,
        PARTICLES,
        WEIBULL,
        WEIBULL_PARAMETERS,
    )

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
        elif kind == "Formulation_Particles":
            values = {q.get("Name"): q for q in formulation.get("Parameters", [])}
            distribution = float((values.get("Type of particle size distribution") or {}).get("Value") or 0.0)
            if distribution != 0.0:
                unplaced.append(f"formulation {name!r}: particle size distribution type {distribution:g} (only "
                                "monodisperse, type 0, is placed)")
                continue
            out.add(f"form.{name}.type", PARTICLES)
            for key, (engine, unit) in PARTICLE_PARAMETERS.items():
                parameter = values.get(engine)
                if parameter is not None and parameter.get("Value") is not None:
                    out.add(f"form.{name}.particles.{key}", _convert(float(parameter["Value"]), parameter.get("Unit"), unit),
                            unit=unit, parameter=parameter)
        else:
            unplaced.append(f"formulation {name!r} ({kind}): type not placed by the builder yet")
    for product, bins in _binned_products(snapshot).items():
        out.add(f"form.{product}.type", PARTICLE_BINS)
        out.add(f"form.{product}.bins", json.dumps([{"formulation": b, "fraction": f} for b, f in bins]))


def _bin_items(protocol: dict[str, Any]) -> list[tuple[str, float]] | None:
    """A protocol that gives several formulations at the same moment: [(formulation key, dose)] of its first dose."""
    schemas = protocol.get("Schemas") or []
    if not schemas:
        return None
    items = [(i.get("FormulationKey"), next((float(q["Value"]) for q in i.get("Parameters", []) if q.get("Name") == "InputDose"), None),
              next((float(q["Value"]) for q in i.get("Parameters", []) if q.get("Name") == "Start time"), 0.0))
             for i in schemas[0].get("SchemaItems", [])]
    first = [(key, dose) for key, dose, start in items if start == items[0][2]] if items else []
    if len({key for key, _d in first}) < 2 or any(key is None or dose is None for key, dose in first):
        return None
    return first


def _binned_products(snapshot: dict[str, Any]) -> dict[str, tuple[tuple[str, float], ...]]:
    """Products the published protocols give as several particle-size bins at once (OSP Ketoconazole
    "PD_tablet_3Bins_B1..B3"): named by the bins' common prefix, each bin with its mass fraction of the dose."""
    protocols = {p["Name"]: p for p in snapshot.get("Protocols", [])}
    products: dict[str, tuple[tuple[str, float], ...]] = {}
    for sim in snapshot.get("Simulations", []):
        for entry in sim.get("Compounds", []):
            ref = entry.get("Protocol") or {}
            key_to_name = {f.get("Key"): f.get("Name") for f in ref.get("Formulations", []) or []}
            bins = _split(protocols.get(ref.get("Name"), {}), key_to_name)
            if bins is None:
                continue
            if bins in products.values():
                continue  # the same split (the published protocols round it differently: each kept exact)
            names = [b for b, _f in bins]
            base = os.path.commonprefix(names).rstrip("_-B ") or "+".join(names)
            taken = [n for n in products if n == base or n.startswith(f"{base} (")]
            products[base if not taken else f"{base} ({len(taken) + 1})"] = bins
    return products


def _binned_product_of(snapshot: dict[str, Any], protocol_ref: dict[str, Any]) -> str | None:
    """The binned product a simulation's protocol gives, by its bins and fractions."""
    protocols = {p["Name"]: p for p in snapshot.get("Protocols", [])}
    key_to_name = {f.get("Key"): f.get("Name") for f in protocol_ref.get("Formulations", []) or []}
    bins = _split(protocols.get(protocol_ref.get("Name"), {}), key_to_name)
    if bins is None:
        return None
    return next((name for name, known in _binned_products(snapshot).items() if known == bins), None)


def _split(protocol: dict[str, Any], key_to_name: dict[str, str]) -> tuple[tuple[str, float], ...] | None:
    """A binned protocol's bins and their mass fractions of the dose (12 digits: the published splits differ in the
    7th, and each is reproduced)."""
    items = _bin_items(protocol) if len(key_to_name) > 1 else None
    if not items:
        return None
    total = sum(dose for _k, dose in items)
    return tuple((key_to_name.get(key, key), round(dose / total, 12)) for key, dose in items)


def _individual_records(snapshot: dict[str, Any], out: _Records, notes: list[str]) -> None:
    main = _main_individual(snapshot)
    if main is None:
        return
    # Any simulation on another individual is named; its studies carry that individual (published_individual).
    others = sorted({f"{s['Name']} ({s['Individual']})" for s in snapshot.get("Simulations", [])
                     if s.get("Individual") and s["Individual"] != main["Name"]})
    if others:
        notes.append(f"Individual physiology imported from {main['Name']!r}; these published simulations use another "
                     "individual, which their studies carry as their own: " + "; ".join(others) + ".")
    individual = main
    for parameter in individual.get("Parameters", []):
        path = parameter.get("Path")
        if not path or parameter.get("Value") is None:
            continue
        out.add(f"indiv.{path}", parameter["Value"], unit=parameter.get("Unit"), parameter=parameter,
                binding=EngineBinding(building_block="Individual", parameter=path))
    if individual.get("Seed") is not None:
        out.add("indiv.seed", int(individual["Seed"]), binding=EngineBinding(building_block="Individual", parameter="Seed"))
    _expression_records(snapshot, individual, out, notes)
    origin = individual.get("OriginData", {})
    notes.append(
        f"Studies are simulated in the pipeline's standard individual ({origin.get('Population')}, "
        f"{origin.get('Gender')}, {origin.get('Age', {}).get('Value')} years in the published model); the published "
        "individual's changed physiology is carried as indiv.* records."
    )


_TIME_TO_MIN = {"min": 1.0, "h": 60.0, "day(s)": 1440.0}


def _profile_value(parameter: dict[str, Any]) -> float:
    return float(parameter["Value"]) * _TIME_TO_MIN.get(parameter.get("Unit") or "", 1.0)


def _main_individual(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """The individual most of the published simulations use."""
    individuals = snapshot.get("Individuals", [])
    if not individuals:
        return None
    used = [s.get("Individual") for s in snapshot.get("Simulations", []) if s.get("Individual")]
    return max(individuals, key=lambda i: used.count(i["Name"]))


def _expression_differences(snapshot: dict[str, Any], individual: dict[str, Any], notes: list[str] | None = None,
                            ) -> list[dict[str, Any]]:
    """The numeric values of an individual's expression profiles that differ from the harvested library the builder
    uses (`pbpk_domain.expression`), as the snapshot's own parameter entries."""
    from pbpk_domain.expression import expression_library

    library = expression_library()
    profiles = {f"{p.get('Molecule')}|{p.get('Species')}|{p.get('Category')}": p for p in snapshot.get("ExpressionProfiles", [])}
    out: list[dict[str, Any]] = []
    for ref in individual.get("ExpressionProfiles", []) or []:
        profile = profiles.get(ref)
        if profile is None:
            continue
        molecule = profile["Molecule"]
        entry = library.get(molecule)
        if entry is None:
            if notes is not None:
                notes.append(f"Expression profile {molecule!r} of the published individual is not in the harvested "
                             "library; S0 reports it as missing.")
            continue
        base = {q["Path"]: q for q in entry["profile"].get("Parameters", []) if q.get("Value") is not None}
        for parameter in profile.get("Parameters", []) or []:
            path = parameter.get("Path")
            if not path or parameter.get("Value") is None:
                continue
            known = base.get(path)
            if known is not None and math.isclose(_profile_value(known), _profile_value(parameter), rel_tol=1e-12):
                continue
            out.append(parameter)
    return out


def _expression_records(snapshot: dict[str, Any], individual: dict[str, Any], out: _Records, notes: list[str]) -> None:
    """The published individual's expression profiles where they differ from the harvested library: each differing
    numeric value (a reference concentration, a turnover half-life, a relative expression) becomes an ``expr.<path>``
    record bound to the ExpressionProfile building block. The published Midazolam and Rifampicin models set CYP3A4
    ``t1/2 (liver)`` to 36 h where the library's copy (from the Dapagliflozin model) has 37 h."""
    for parameter in _expression_differences(snapshot, individual, notes):
        path = parameter["Path"]
        out.add(f"expr.{path}", parameter["Value"], unit=parameter.get("Unit"), parameter=parameter,
                binding=EngineBinding(building_block="ExpressionProfile", parameter=path))


def _published_individual(snapshot: dict[str, Any], individual: dict[str, Any]) -> dict[str, Any]:
    """A study's own individual (StudyRecord.published_individual): its complete physiology overrides and its
    expression values that differ from the library."""
    def entries(parameters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {p["Path"]: {"value": float(p["Value"]), "unit": p.get("Unit")}
                for p in parameters if p.get("Path") and p.get("Value") is not None}

    return {"name": individual["Name"], "seed": individual.get("Seed"), "parameters": entries(individual.get("Parameters") or []),
            "expression": entries(_expression_differences(snapshot, individual))}


_BODY = {"Weight": ("weight_kg", "kg"), "Height": ("height_cm", "cm")}


def _demographics(origin: dict[str, Any]) -> dict[str, Any] | None:
    if not origin:
        return None
    demo = {"population": origin.get("Population"), "sex": origin.get("Gender"),
            "age_years": (origin.get("Age") or {}).get("Value")}
    for key, (field_name, unit) in _BODY.items():
        quantity = origin.get(key) or {}
        if quantity.get("Value") is not None and quantity.get("Unit") == unit:
            demo[field_name] = float(quantity["Value"])
    return demo

def _simulation_links(snapshot: dict[str, Any], compound: str) -> dict[str, dict[str, Any]]:
    """Observed dataset name -> how the published model simulates it: protocol, formulation, meal events, infusion.

    A dataset is linked by the simulation that lists it, else by the published parameter identification that fits it
    against a simulation's output (``ParameterIdentifications[].OutputMappings``: the paper's own fitting design)."""
    protocols = {p["Name"]: p for p in snapshot.get("Protocols", [])}
    individuals = {i["Name"]: i for i in snapshot.get("Individuals", [])}
    main = _main_individual(snapshot)
    by_sim: dict[str, dict[str, Any]] = {}
    links: dict[str, dict[str, Any]] = {}
    members = _MEMBERS.get()
    for sim in snapshot.get("Simulations", []):
        if members is None:
            entry = next((c for c in sim.get("Compounds", []) if c.get("Name") == compound), None)
        else:  # a system: the simulation's first dosed member carries the protocol the study is read from
            entry = next((c for c in sim.get("Compounds", []) if c.get("Protocol") and c.get("Name") in members), None)
        if entry is None:
            continue
        protocol_ref = entry.get("Protocol") or {}
        formulations = protocol_ref.get("Formulations") or []
        infusion = next((float(p["Value"]) * (60.0 if p.get("Unit") == "h" else 1.0)
                         for p in sim.get("Parameters", []) or []
                         if str(p.get("Path", "")).endswith("|Application_1|ProtocolSchemaItem|Infusion time")), None)
        individual = individuals.get(sim.get("Individual"), {})
        link = {
            "demographics": _demographics(individual.get("OriginData", {})),
            "published_individual": (_published_individual(snapshot, individual)
                                     if individual and main is not None and individual["Name"] != main["Name"] else None),
            "simulation": sim["Name"],
            "protocol": protocols.get(protocol_ref.get("Name"), {}),
            # a binned protocol is its product (never its first bin alone, which would put the whole dose in one bin)
            "formulation": (_binned_product_of(snapshot, protocol_ref) if len(formulations) > 1 else
                            formulations[0]["Name"]) if formulations else None,
            "fed": bool(sim.get("Events")),
            "infusion_min": infusion,
        }
        if members is None:
            link["co_dosed"] = [n for n in _dosed(sim) if n != compound]
            parent = next((c for c in snapshot.get("Compounds", []) if c["Name"] == compound), {})
            link["feedback"] = _feedback(snapshot, parent, sim)
        else:
            link["co_dosed"] = [n for n in _dosed(sim) if n not in members]
            parent = next((c for c in snapshot.get("Compounds", []) if c["Name"] == entry["Name"]), {})
            link["feedback"] = []  # the system simulates the metabolites: no parent-only approximation to label
            link["doses"] = {c["Name"]: _protocol_dose(protocols.get((c.get("Protocol") or {}).get("Name"), {}))
                             for c in sim.get("Compounds", []) if c.get("Protocol") and c["Name"] in members}
            link["compounds"] = [c["Name"] for c in sim.get("Compounds", []) if c["Name"] in members]
        # a property alternative this simulation uses that differs from the one imported
        for group in _ALTERNATIVE_GROUPS:
            if len(parent.get(group) or []) > 1:
                mine, imported = _alternative_of(sim, parent, group), _selected_alternative(snapshot, parent, group)
                if mine and imported is not None and mine != imported.get("Name"):
                    link["feedback"].append(f"the published simulation uses the {group} alternative {mine!r}; "
                                            f"the model imports {imported.get('Name')!r}")
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


# Reported "Route" values across the OSP model library (2026-09-24). "EM"/"PM" (a genotype filed as a route), "na" and
# none fall back to the published simulation's protocol; bolus, intracolonic and mixed routes are not placed.
_ROUTE_WORDS = {"po": "PO", "oral": "PO", "capsule": "PO", "iv": "IV"}
_INFUSION_ROUTE = re.compile(r"^(iv_)?(?P<value>[\d.]+)[- ]?min[_ ]infusion$")
_PROTOCOL_ROUTE = {"Oral": "PO", "Intravenous": "IV"}
_NAMED_DOSE = r"(?<!\d)(?<!\d\.){value}\s*mg(?![a-z/])"


def _route(reported: Any) -> tuple[str | None, float | None]:
    """(PO | IV | None, infusion minutes named in the route)."""
    text = str(reported or "").strip().lower()
    if text in _ROUTE_WORDS:
        return _ROUTE_WORDS[text], None
    infusion = _INFUSION_ROUTE.match(text)
    if infusion is not None:
        return "IV", float(infusion.group("value"))
    return None, None


def _application_type(protocol: dict[str, Any]) -> str | None:
    types = {i.get("ApplicationType") for i in [protocol, *[i for s in protocol.get("Schemas", []) for i in s.get("SchemaItems", [])]]
             if i.get("ApplicationType")}
    return types.pop() if len(types) == 1 else None


def _protocol_dose(protocol: dict[str, Any]) -> tuple[float, bool] | None:
    """The one dose a published protocol gives (every administration the same), in mg or mg/kg; a binned product's
    dose is the sum of its bins given at the same moment."""
    bins = _bin_items(protocol)
    if bins:
        units = {q.get("Unit") for s in protocol.get("Schemas", []) for i in s.get("SchemaItems", [])
                 for q in i.get("Parameters", []) if q.get("Name") == "InputDose"}
        return (sum(d for _k, d in bins), units == {"mg/kg"}) if units <= {"mg", "mg/kg"} and len(units) == 1 else None
    doses = {(float(q["Value"]), q.get("Unit")) for i in [protocol, *[i for s in protocol.get("Schemas", []) for i in s.get("SchemaItems", [])]]
             for q in i.get("Parameters", []) if q.get("Name") == "InputDose"}
    if len(doses) != 1:
        return None
    value, unit = doses.pop()
    return (value, unit == "mg/kg") if unit in ("mg", "mg/kg") else None


def _dataset_dose(name: str, props: dict[str, Any], link: dict[str, Any] | None, said: list[str]) -> tuple[float, bool] | str:
    """(dose, per kg) from the dataset's "Dose" (with a unit; a bare number only when the dataset name repeats it
    in mg), else from the linked published protocol; or the reason there is none."""
    reported = props.get("Dose")
    dose = _DOSE.match(str(reported or ""))
    if dose is not None:
        return float(dose.group("value")) * _TO_MG[dose.group("unit")], dose.group("unit").endswith("/kg")
    try:
        bare = float(str(reported))
    except ValueError:
        bare = None
    if bare is not None:
        text = f"{name} {props.get('Grouping', '')} {props.get('Sheet', '')}".lower()
        if re.search(_NAMED_DOSE.format(value=re.escape(f"{bare:g}")), text):
            said.append(f"dose {reported!r} has no unit; mg as the dataset's name gives it")
            return bare, False
    published = _protocol_dose(link["protocol"]) if link else None
    if published is None and link:
        doses = sorted({float(q["Value"]) for i in [link["protocol"], *[i for s in link["protocol"].get("Schemas", [])
                        for i in s.get("SchemaItems", [])]] for q in i.get("Parameters", []) if q.get("Name") == "InputDose"})
        if len(doses) > 1:
            return (f"dose not reported and the published protocol gives different doses ({', '.join(f'{d:g}' for d in doses)}"
                    " mg: a loading dose); such regimens are not placed yet")
    if published is not None:
        said.append(f"dose {reported!r} not usable; {published[0]:g} {'mg/kg' if published[1] else 'mg'} as in the "
                    "published simulation")
        return published
    return f"dose {reported!r} is not a single mg / µg amount (or per kg)"


def _study(dataset: dict[str, Any], link: dict[str, Any] | None, formulation_types: dict[str, str]) -> tuple[dict | None, str]:
    """One plasma dataset -> (StudyUpload row, "") or (None, reason it cannot be used)."""
    props = _props(dataset)
    column = next((c for c in dataset.get("Columns", []) if c.get("DataInfo", {}).get("Origin") == "Observation"), None)
    if column is None or not column.get("Unit"):
        return None, "no observed concentration column with a unit"
    said: list[str] = []
    dose = _dataset_dose(dataset["Name"], props, link, said)
    if isinstance(dose, str):
        return None, dose
    row: dict[str, Any] = {
        # the study and its arm; a dataset that names neither is identified by its own name
        "study_id": _slug(f"{props.get('Study Id', '')} {props.get('Grouping', '')}") or _slug(dataset["Name"]),
        "n": int(float(props.get("N") or 1)),
        "dose_mg": dose[0],
        "dose_per_kg": dose[1],
        "n_timepoints": len(dataset["BaseGrid"]["Values"]),
    }

    route, infusion_named = _route(props.get("Route"))
    if route is None and link is not None:
        route = _PROTOCOL_ROUTE.get(_application_type(link["protocol"]) or "")
        if route is not None:
            said.append(f"route {props.get('Route')!r} not usable; {route} as in the published simulation")
    if route is None:
        return None, f"route {props.get('Route')!r} is not IV or PO"
    if route == "IV":
        if infusion_named is not None and not (link and (link.get("infusion_min") or _infusion_time_min(link["protocol"]))):
            said.append(f"infusion time {infusion_named:g} min from the reported route")
        # The infusion time the published simulation uses, else its protocol's, else the one the dataset names.
        infusion = (link.get("infusion_min") or _infusion_time_min(link["protocol"])) if link else None
        if infusion is None:
            infusion = infusion_named
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
    if doses is None and link is not None and (published := _protocol_dose_times(link["protocol"])):
        doses = published
        said.append(f"administration times not reported; the schedule of the published protocol "
                    f"{link['protocol'].get('Name')!r}")
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
        elif linked_form is not None and formulation_types.get(linked_form) in ("Particles", "ParticleBins") \
                and (named := next((k for word, k in _FORMULATION_WORDS if word in linked_form.lower()), None)):
            kind = named
            said.append(f"formulation not reported; the published model gives {linked_form!r} (classified {kind})")
        else:
            kind = "ir_tablet"
            said.append("formulation not reported; recorded as an immediate-release tablet, simulated as the "
                        f"published model does ({linked_form or 'Dissolved'})")
        row["formulation"] = kind
        if linked_form is not None and (kind in ("ir_tablet", "ir_capsule", "other")
                                        or formulation_types.get(linked_form) in ("Particles", "ParticleBins")):
            # a particle formulation is simulated as published even for a solution (dissolution limited by solubility)
            row["formulation_name"] = linked_form

    reported = _given(props.get("Food state"))
    food = _FOOD_STATE.get(reported.lower()) if reported is not None else None
    if food is None:
        food = "fed" if link and link.get("fed") else "fasted"
        said.append(f"food state {'not reported' if reported is None else repr(reported) + ' has no MS-01 class'}; "
                    f"{food} as in the published simulation")
    elif food == "fed" and reported.lower() != "fed":
        said.append(f"reported {reported!r}: a meal was given, classified fed")
    if food == "fed" and link is not None and not link.get("fed"):
        said.append("reported fed; the published model simulates it without a meal")
    row["food_state"] = food

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
    if (link or {}).get("published_individual"):
        row["published_individual"] = link["published_individual"]
    co_medication = next((w for w in _CO_MEDICATION_WORDS if w in grouping), None)
    if (link or {}).get("co_dosed"):
        # the published simulation doses another drug with it: a DDI arm, never the drug alone (MS-01 §3.2)
        co_medication = ", ".join(link["co_dosed"])
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


def import_osp_snapshot(snapshot: dict[str, Any], *, source: str | None = None, compound: str | None = None,
                        ) -> ReferenceImport:
    """Turn a published OSP model snapshot into a CPF and its plasma studies for one compound: ``compound``, the only
    one, or the one most of the simulations dose. The other compounds (metabolites, co-administered drugs) are named;
    a study simulated with another dosed drug is a DDI arm (co_medication), one whose metabolites act on the parent's
    clearance differs by design from the parent-only simulation the pipeline builds."""
    parent = _parent_compound(snapshot, compound)
    compound = parent
    name = compound["Name"]
    source = source or f"OSP {name} model"

    records = _Records(source)
    notes: list[str] = []
    others = [c["Name"] for c in snapshot.get("Compounds", []) if c["Name"] != name]
    if others:
        notes.append(f"Imported {name!r}; the snapshot's other compounds are not simulated (metabolites and "
                     f"co-administered drugs are simulated with the parent in a later step): {', '.join(others)}.")
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
    # The published model's own mapping of a dataset onto the parent's plasma output: it identifies the data where the
    # dataset's "Molecule" is a variant or garbled name ("voriconazole" for Voriconazole1, "Fluvoxaminekjujhöjö").
    mapped_to_parent = {m.get("ObservedData") for s in [*snapshot.get("Simulations", []), *(snapshot.get("ParameterIdentifications") or [])]
                        for m in s.get("OutputMappings", []) or []
                        if f"|{name}|Plasma" in str(m.get("Path", "")) and "PeripheralVenousBlood" in str(m.get("Path", ""))}
    renamed: set[str] = set()
    for dataset in snapshot.get("ObservedData", []):
        props = _props(dataset)
        label = dataset["Name"]
        molecule = str(props.get("Molecule") or "")
        # the same name up to case, digits and punctuation ("voriconazole" for the compound "Voriconazole1")
        same = re.sub(r"[^a-z]", "", molecule.lower()) == re.sub(r"[^a-z]", "", name.lower()) and bool(molecule)
        if not same and label not in mapped_to_parent:
            skipped.append(f"{label}: data for {props.get('Molecule')}, not the parent drug")
            continue
        if molecule != name:
            renamed.add(molecule or "(none)")
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
            why.extend(link.get("feedback") or [])
            if why:
                differs_by_design[row["study_id"]] = "; ".join(why)
        row.pop("_offset_min", None)

    if renamed:
        notes.append(f"Datasets named for {', '.join(sorted(renamed))} are taken as {name} data: the published model maps "
                     "them onto its plasma output.")
    return ReferenceImport(compound=name, source=source, cpf=cpf, studies=tuple(studies), skipped=tuple(skipped),
                           unplaced=tuple(unplaced), notes=tuple(notes), simulation_of=simulation_of,
                           offset_min=offset_min, differs_by_design=differs_by_design)


# --- model systems: parent, enantiomers, metabolites (docs/plans/2026-09-24-multi-compound.md) -------------------


@dataclass(frozen=True)
class SystemImport:
    system: ModelSystem
    source: str
    studies: tuple[dict[str, Any], ...]  # StudyUpload rows, each with its analyte and product
    skipped: tuple[str, ...]
    unplaced: tuple[str, ...]
    notes: tuple[str, ...]
    simulation_of: dict[str, str] = field(default_factory=dict)
    offset_min: dict[str, float] = field(default_factory=dict)
    differs_by_design: dict[str, str] = field(default_factory=dict)


_STEREO = re.compile(r"^(?:[RS]|\(?[+-]\)?|es|rac)-?", re.IGNORECASE)


def _stem(name: str) -> str:
    """A compound name without its stereo prefix ("R-Verapamil", "S-Warfarin" -> "verapamil", "warfarin")."""
    return _STEREO.sub("", name, count=1).lower()


def _observer_compounds(observer_set: dict[str, Any], names: set[str]) -> set[str]:
    refs = {r.get("Path", "") for o in observer_set.get("Observers", []) for r in (o.get("Formula") or {}).get("References", [])}
    return {n for n in names if any(f"|{n}|" in ref for ref in refs)}


def _system_members(snapshot: dict[str, Any], main: str, parents: tuple[str, ...] | None) -> tuple[list[str], list[str]]:
    """(parents, metabolites) of the system around ``main``: its enantiomer family (same name after an R-/S- prefix),
    the compounds a published sum observer adds to it, and everything they form. A drug dosed only with it in DDI arms
    (a victim or perpetrator) is not a member."""
    names = {c["Name"] for c in snapshot.get("Compounds", [])}
    dosed = {n for s in snapshot.get("Simulations", []) for n in _dosed(s)}
    if parents is None:
        chosen = {main} | {n for n in dosed if _stem(n) == _stem(main)}
        for observer_set in snapshot.get("ObserverSets", []) or []:
            linked = _observer_compounds(observer_set, names)
            if linked & chosen:
                chosen |= linked & dosed
    else:
        unknown = [p for p in parents if p not in names]
        if unknown:
            raise ReferenceImportError(f"no compound {', '.join(map(repr, unknown))} in the snapshot")
        chosen = set(parents)
    compounds = {c["Name"]: c for c in snapshot.get("Compounds", [])}
    members, grew = set(chosen), True
    while grew:
        grew = False
        for name in list(members):
            for process in compounds[name].get("Processes", []):
                formed = process.get("Metabolite")
                if formed in compounds and formed not in members:
                    members.add(formed)
                    grew = True
    order = [c["Name"] for c in snapshot.get("Compounds", [])]
    return [n for n in order if n in chosen], [n for n in order if n in members - chosen]


def _formation(snapshot: dict[str, Any], members: set[str]) -> list[Formation]:
    out = []
    for compound in snapshot.get("Compounds", []):
        if compound["Name"] not in members:
            continue
        for process in compound.get("Processes", []):
            if process.get("Metabolite") in members and process.get("Molecule"):
                out.append(Formation(compound=compound["Name"], internal_name=process["InternalName"],
                                     molecule=process["Molecule"], data_source=process.get("DataSource") or "",
                                     metabolite=process["Metabolite"]))
    return out


def _system_analytes(snapshot: dict[str, Any], members: set[str]) -> tuple[dict[str, Analyte], dict[str, dict[str, Any]]]:
    """Each member's plasma, and each published sum observer the system's simulations select, at the output path the
    published simulations read it (an observer's path is never composed: Verapamil's sums sit under different
    compounds, Dabigatran's `SUM` formula uses a MOLECULE placeholder)."""
    analytes = {n: Analyte(name=n, kind="compound", compound=n, output_path=PLASMA.format(compound=n))
                for n in [c["Name"] for c in snapshot.get("Compounds", [])] if n in members}
    sims = [s for s in snapshot.get("Simulations", []) if _dosed(s) and set(_dosed(s)) <= members]
    selected = {o.get("Name") for s in sims for o in s.get("ObserverSets", []) or []}
    outputs = [p for s in sims for p in (s.get("OutputSelections") or []) if isinstance(p, str)]
    observers: dict[str, dict[str, Any]] = {}
    for observer_set in snapshot.get("ObserverSets", []) or []:
        if observer_set.get("Name") not in selected:
            continue
        for observer in observer_set.get("Observers", []):
            path = next((p for p in outputs if p.startswith("Organism|PeripheralVenousBlood|") and p.endswith(f"|{observer['Name']}")), None)
            if path is None:
                continue  # an observer the published simulations never output (urine fractions, …)
            observers[observer_set["Name"]] = observer_set
            analytes[observer["Name"]] = Analyte(name=observer["Name"], kind="observer", observer=observer_set["Name"],
                                                 output_path=path)
    return analytes, observers


def _analyte_of(label: str, molecule: str, analytes: dict[str, Analyte], observers: dict[str, dict[str, Any]],
                mapped: dict[str, str]) -> str | None:
    """The analyte a dataset measures: a member compound, an observer (by its set or observer name), or what the
    published model maps it onto."""
    by_lower = {a.lower(): a for a in analytes}
    if molecule.lower() in by_lower:
        return by_lower[molecule.lower()]
    for set_name, doc in observers.items():
        if molecule.lower() == set_name.lower():
            return next((o["Name"] for o in doc.get("Observers", []) if o["Name"] in analytes), None)
    path = mapped.get(label)
    return next((a.name for a in analytes.values() if path and path.endswith(a.output_path)), None)


def import_osp_system(snapshot: dict[str, Any], *, source: str | None = None,
                      parents: tuple[str, ...] | None = None) -> SystemImport:
    """Turn a published OSP model snapshot into a model system — a CPF per compound, the formation links, the products
    the studies administer, the published sum observers — and its plasma studies, each with its analyte. The main
    parent is the compound most simulations dose; ``parents`` names the dosed compounds explicitly."""
    main = _parent_compound(snapshot, None)["Name"]
    parent_names, metabolite_names = _system_members(snapshot, main, parents)
    members = frozenset(parent_names + metabolite_names)
    compounds = {c["Name"]: c for c in snapshot.get("Compounds", [])}
    source = source or f"OSP {main} model"
    notes: list[str] = []
    unplaced: list[str] = []
    token = _MEMBERS.set(members)
    try:
        cpfs = []
        for name in [c["Name"] for c in snapshot.get("Compounds", []) if c["Name"] in members]:
            records = _Records(source)
            _compound_records(snapshot, compounds[name], records, notes)
            _process_records(snapshot, compounds[name], records, unplaced, notes)
            _simulation_parameter_records(snapshot, name, records, notes)
            if name == parent_names[0]:  # shared by the system: the formulations and the published individual
                _formulation_records(snapshot, records, unplaced)
                _individual_records(snapshot, records, notes)
            cpfs.append(CPF(compound=name, parameters=tuple(records.records), note=f"Imported from the {source} snapshot"))
        links = _simulation_links(snapshot, main)
    finally:
        _MEMBERS.reset(token)
    others = [n for n in compounds if n not in members]
    if others:
        notes.append(f"Not part of the {main} system (co-administered in DDI arms, or unrelated): {', '.join(others)}.")
    analytes, observers = _system_analytes(snapshot, set(members))
    mapped = {m.get("ObservedData"): str(m.get("Path", "")) for s in [*snapshot.get("Simulations", []),
              *(snapshot.get("ParameterIdentifications") or [])] for m in s.get("OutputMappings", []) or []}

    formulation_types = {r.id.split(".")[1]: str(r.value) for r in cpfs[0].parameters
                         if r.id.startswith("form.") and r.id.endswith(".type")}
    products: dict[str, dict[str, float]] = {}
    studies: list[dict[str, Any]] = []
    skipped: list[str] = []
    seen: set[str] = set()
    simulation_of: dict[str, str] = {}
    offset_min: dict[str, float] = {}
    differs_by_design: dict[str, str] = {}
    for dataset in snapshot.get("ObservedData", []):
        props = _props(dataset)
        label = dataset["Name"]
        analyte = _analyte_of(label, str(props.get("Molecule") or ""), analytes, observers, mapped)
        if analyte is None:
            skipped.append(f"{label}: data for {props.get('Molecule')}, not a compound or sum of the system")
            continue
        compartment = props.get("Compartment")
        said: list[str] = []
        if compartment is None and not props.get("Organ") and analytes[analyte].kind == "observer":
            # the published sum observer is defined on peripheral venous plasma (its ContainerCriteria)
            compartment = "Plasma"
            said.append(f"compartment not reported; plasma, where the published {analyte!r} observer is defined")
        if compartment in ("Urine", "Feces"):
            skipped.append(f"{label}: {compartment} fraction data (excreta need task T-11)")
            continue
        if compartment != "Plasma":
            skipped.append(f"{label}: {compartment} data; only plasma concentrations are compared")
            continue
        link = links.get(label)
        if (link is None or not link.get("doses")) and len(parent_names) == 1:
            link = None  # one parent: the reported dose is the parent's, as in a single-compound import
        elif link is None or not link.get("doses"):
            skipped.append(f"{label}: no published simulation of the system runs it (which compounds it doses is unknown)")
            continue
        row, reason = _study(dataset, link, formulation_types)
        if row is None:
            skipped.append(f"{label}: {reason}")
            continue
        if row["study_id"] in seen:  # one study measured on several analytes (the sum and the metabolite)
            row["study_id"] = f"{row['study_id']}-{_slug(analyte)}"
        if row["study_id"] in seen:
            skipped.append(f"{label}: duplicate study id {row['study_id']!r}")
            continue
        product = (_product(link, row, products) if link is not None
                   else _product({"doses": {parent_names[0]: (row["dose_mg"], bool(row.get("dose_per_kg")))}}, row, products))
        if isinstance(product, str) and product.startswith("!"):
            skipped.append(f"{label}: {product[1:]}")
            continue
        seen.add(row["study_id"])
        row["analyte"] = analyte
        row["product"] = product
        if said:  # recorded with the study's other import notes, in its reference
            row["reference"] = f"{row.get('reference', '')} Import: {'; '.join(said)}.".strip()
        studies.append(row)
        if link is None:
            row.pop("_offset_min", None)
            continue
        simulation_of[row["study_id"]] = link["simulation"]
        offset_min[row["study_id"]] = row.pop("_offset_min", 0.0)
        published_doses = _protocol_dose_times(link["protocol"]) or []
        why = []
        if published_doses and len(published_doses) != (row.get("n_doses") or 1):
            why.append(f"{row.get('n_doses') or 1} dose(s) as the study gave them; the published simulation gives "
                       f"{len(published_doses)}")
        if row.get("food_state") == "fed" and not link.get("fed"):
            why.append("simulated fed as reported; the published simulation has no meal")
        if why:
            differs_by_design[row["study_id"]] = "; ".join(why)

    roles = {c.compound: ("parent" if any(c.compound in f for f in products.values()) else "metabolite") for c in cpfs}
    dosed_without_study = [n for n in parent_names if roles[n] != "parent"]
    if dosed_without_study:
        notes.append(f"Dosed in the published model but in no imported study: {', '.join(dosed_without_study)}.")
    if not products:
        raise ReferenceImportError(f"no study of the {main} system could be imported")
    system = ModelSystem(name=main, compounds=tuple(cpfs), roles=roles,
                         formation=tuple(f for f in _formation(snapshot, set(members))),
                         products=products, observers=observers, analytes=analytes, source=source)
    return SystemImport(system=system, source=source, studies=tuple(studies), skipped=tuple(skipped),
                        unplaced=tuple(dict.fromkeys(unplaced)), notes=tuple(dict.fromkeys(notes)),
                        simulation_of=simulation_of, offset_min=offset_min, differs_by_design=differs_by_design)


def _product(link: dict[str, Any], row: dict[str, Any], products: dict[str, dict[str, float]]) -> str:
    """The product a study administers, from the published protocols of its dosed compounds: each compound's dose as a
    fraction of the study's reported dose (carrying the modeller's salt and enantiomer split). Returns the product name,
    registering it, or "!reason" when the doses cannot be related."""
    fractions: dict[str, float] = {}
    for compound, dose in (link.get("doses") or {}).items():
        if dose is None:
            return f"!the published protocol of {compound} gives no single dose"
        value, per_kg = dose
        if per_kg != bool(row.get("dose_per_kg")):
            return f"!the published protocol of {compound} doses per {'kg' if per_kg else 'subject'}, the study the other way"
        fractions[compound] = round(value / row["dose_mg"], 9)
    for name, known in products.items():
        if known == fractions:
            return name
    # named by what it doses and how much of the reported dose each compound gets (the published protocols round the
    # split differently, e.g. 0.462875 and 0.4628836 of a verapamil HCl dose; each is kept exact)
    name = " + ".join(f"{compound} {fraction:.6g}" for compound, fraction in fractions.items())
    products[name] = fractions
    return name
