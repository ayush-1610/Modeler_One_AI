"""The ledger's field vocabulary (docs/plans/2026-11-12-intake-contracts.md §4.3).

Names are the client-data template's column names (`client_template.SHEETS`) wherever one exists, so the ledger and
the no-AI path say the same thing. Nothing here is a PK-Sim name.

A value's unit class is its FIELD's, never guessed from the unit text (the concentration table reads "µm" and "mm" as
molar concentrations). A unit is checked against the existing table of its class only: concentration
`validate.CONCENTRATION_UNITS`, time `validate.TIME_UNITS`, percentage `validate.FRACTION_UNITS`, mass the dose units
today's fact check accepts (`document_reading._MG_PER` and "mg/kg", imported, never retyped). A class with no table
(ratio, other, none) keeps its unit unchecked. No unit table is added here.

`cue` and `choice_cues` are reading checks (which words a sentence or a cell must carry to state a field or a choice),
not reconciliation rules.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from modeler_intake import recipe
from modeler_intake.citations import normalize_for_match
from modeler_intake.client_template import FORMULATIONS, PK_PARAMETERS, ROLES, ROUTES, USES
from modeler_intake.document_reading import _CONC_UNIT, _DOSE_UNIT, _MG_PER, _dose_unit, name_key, supports_choice
from modeler_intake.validate import CONCENTRATION_UNITS, FRACTION_UNITS, TIME_UNITS, canonical_unit
from pbpk_domain import parameters
from pbpk_domain.campaign.split import SpecialPopulation

Statistic = recipe.Statistic                      # individual | arithmetic_mean | geometric_mean | median
SpreadKind = Literal["SD", "SE", "CV%", "geoSD", "geoCV%"]     # a CI or a min-max pair is an interval, not a spread
IntervalKind = Literal["CI", "range"]
UnitClass = Literal["mass", "concentration", "time", "percentage", "ratio", "other", "none"]
TableKind = Literal["pk_individual", "pk_summary", "pk_parameters", "dissolution", "study_design", "demographics",
                    "product_batch", "bioanalytical", "physchem_invitro", "excretion", "composition", "ddi_relation",
                    "not_data", "unknown"]
DocumentRole = Literal["client_template", "data_workbook", "concentration_listing", "study_report", "synopsis",
                       "bioanalytical_report", "dissolution_report", "certificate_of_analysis", "product_information", "other"]

# triage.SheetCategory value -> TableKind (OTHER -> unknown)
KIND_OF_CATEGORY: Mapping[str, TableKind] = MappingProxyType({
    "PK_INDIVIDUAL": "pk_individual", "PK_SUMMARY": "pk_summary", "PK_PARAMETERS": "pk_parameters",
    "DISSOLUTION": "dissolution", "PRODUCT_INFO": "product_batch", "STUDIES": "study_design",
    "DEMOGRAPHICS": "demographics", "BIOANALYTICAL": "bioanalytical", "PHYSCHEM_INVITRO": "physchem_invitro",
    "URINE_FECES": "excretion", "OTHER": "unknown",
})


class FieldDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    value: Literal["number", "integer", "choice", "name", "text"]
    level: Literal["study", "arm", "product", "batch", "analyte", "observation", "compound", "condition", "label"]
    unit_class: UnitClass = "none"
    choices: tuple[str, ...] = ()
    cue: str = ""                                               # regex of the label a sentence must carry
    choice_cues: dict[str, str] = Field(default_factory=dict)  # choice -> regex stating it, for the choices supports_choice lacks


def _f(name: str, value: Literal["number", "integer", "choice", "name", "text"],
       level: Literal["study", "arm", "product", "batch", "analyte", "observation", "compound", "condition", "label"],
       unit_class: UnitClass = "none", choices: tuple[str, ...] = (), cue: str = "",
       choice_cues: dict[str, str] | None = None) -> tuple[str, FieldDef]:
    return name, FieldDef(name=name, value=value, level=level, unit_class=unit_class, choices=choices, cue=cue,
                          choice_cues=dict(choice_cues or ()))


_AGE = r"\bage[ds]?\b|\byears?\b|\byrs?\b"
_FEMALE = r"\bfemales?\b|\bwom[ae]n\b"
_DOSE = r"\bdos(?:e|es|ed|ing)\b|\badminist"
_PK_CUE = {"AUC_last": r"\bauc", "AUC_inf": r"\bauc", "Cmax": r"\bc\s?max\b", "tmax": r"\bt\s?max\b",
           "t_half": r"\bt\s?1/2\b|\bt½|half[- ]life", "Ctrough": r"\bc\s?trough\b|\btrough\b",
           "CL/F": r"\bcl\s?/\s?f\b|clearance", "Vz/F": r"\bvz?\s?/\s?f\b|volume of distribution"}

FIELDS: Mapping[str, FieldDef] = MappingProxyType(dict((
    # study and arm
    _f("study_id", "name", "study", cue=r"\bstudy\b|\bprotocol\b|\btrial\b"),
    _f("treatment", "name", "arm", cue=r"\barms?\b|\btreatments?\b|\bcohorts?\b|\bgroups?\b|\bperiods?\b"),
    _f("reference", "text", "study", cue=r"\bprotocol\b|\breport\b|\breference\b"),
    _f("design", "choice", "study", choices=("SD", "MD")),
    _f("crossover", "choice", "study", choices=("yes", "no"),
       choice_cues={"yes": r"\bcross-?over\b", "no": r"\bparallel\b"}),
    _f("population", "choice", "study", choices=("healthy", "patient"),
       choice_cues={"healthy": r"\bhealthy\b(?: volunteers?)?", "patient": r"\bpatients?\b"}),
    _f("special_population", "choice", "study", choices=tuple(p.value for p in SpecialPopulation),
       choice_cues={"pediatric": r"\bpa?ediatric\b", "hepatic_impairment": r"\bhepatic\b",
                    "renal_impairment": r"\brenal\b", "pregnancy": r"\bpregnan(?:t|cy)\b", "elderly": r"\belderly\b"}),
    _f("species", "name", "study", cue=r"\bspecies\b|\bhumans?\b|\brats?\b|\bmice\b|\bmouse\b|\bdogs?\b|\bmonkeys?\b"),
    _f("n", "integer", "arm", cue=r"\bsubjects?\b|\bvolunteers?\b|\bpatients?\b|\bparticipants?\b|\bn\s*="),
    _f("n_evaluable", "integer", "arm", cue=r"\bevaluable\b|\bcompleted\b|\banaly[sz]ed\b"),
    _f("age_mean", "number", "study", cue=_AGE),
    _f("age_min", "number", "study", cue=_AGE),
    _f("age_max", "number", "study", cue=_AGE),
    _f("weight_mean_kg", "number", "study", "other", cue=r"\bweight\b|\bkg\b"),
    _f("height_mean_cm", "number", "study", "other", cue=r"\bheight\b|\bcm\b"),
    _f("percent_female", "number", "study", "percentage", cue=_FEMALE),
    _f("n_female", "integer", "study", cue=_FEMALE),
    _f("child_pugh", "choice", "study", choices=("A", "B", "C"),
       choice_cues={c: rf"\bchild[- ]pugh\s+(?:class\s+)?{c}\b|\bclass\s+{c}\b" for c in "ABC"}),
    _f("egfr", "number", "study", "other", cue=r"\begfr\b|glomerular"),
    _f("gestational_week", "number", "study", cue=r"gestation"),
    _f("ethnicity", "text", "study", cue=r"ethnic|\brace\b"),
    _f("genotype", "text", "study", cue=r"genotype|\bpoor metaboli[sz]ers?\b|\bextensive metaboli[sz]ers?\b|\*\d"),
    _f("co_medication", "text", "study", cue=r"co-?medicat|co-?administ|concomitant|\bwith\b"),
    _f("route", "choice", "arm", choices=(*ROUTES, "other")),
    _f("dose", "number", "arm", "mass", cue=_DOSE),
    _f("dose_unit", "choice", "arm", choices=("mg", "mg/kg")),
    _f("salt_or_base", "choice", "arm", choices=("base", "salt"),
       choice_cues={"salt": r"\bsalt\b", "base": r"\b(?:free )?base\b"}),
    _f("infusion_time_min", "number", "arm", "time", cue=r"infus"),
    _f("dosing_interval_h", "number", "arm", "time", cue=r"\bevery\b|\binterval\b|\bq\s?\d+\s?h\b|\bdaily\b"),
    _f("n_doses", "integer", "arm", cue=r"\bdoses\b|\btimes\b"),
    _f("food_state", "choice", "arm", choices=("fasted", "fed")),
    _f("meal_type", "text", "arm", cue=r"\bmeal\b|breakfast"),
    _f("meal_kcal", "number", "arm", "other", cue=r"kcal|calori"),
    _f("meal_fat_g", "number", "arm", "mass", cue=r"\bfat\b"),
    _f("formulation", "choice", "arm", choices=FORMULATIONS),
    _f("intended_use", "choice", "study", choices=USES),
    _f("lloq", "number", "study", "concentration", cue=r"\blloq\b|lower limit of quantif"),
    _f("matrix", "choice", "label", choices=("plasma", "blood", "serum", "urine", "feces"),
       choice_cues={"plasma": r"\bplasma\b", "blood": r"\b(?:whole )?blood\b", "serum": r"\bserum\b",
                    "urine": r"\burine\b", "feces": r"\bf(?:a)?eces\b"}),
    # labels: written on EntityRef as they are written
    _f("subject", "name", "label", cue=r"\bsubjects?\b|\bpatients?\b|\bid\b"),
    _f("period", "name", "label", cue=r"\bperiods?\b"),
    _f("sequence", "name", "label", cue=r"\bsequences?\b"),
    _f("occasion", "name", "label", cue=r"\bday\b|\bvisits?\b|\boccasions?\b"),
    _f("vessel", "name", "label", cue=r"\bvessels?\b"),
    # analyte
    _f("analyte", "name", "analyte", cue=r"\banalytes?\b|\bmetabolites?\b|\bparent\b"),
    _f("analyte_role", "choice", "analyte", choices=("parent", "metabolite", "enantiomer", "sum"),
       choice_cues={"parent": r"\bparent\b", "metabolite": r"\bmetabolites?\b", "enantiomer": r"\benantiomers?\b",
                    "sum": r"\b(?:sum|total)\b"}),
    _f("molecular_weight", "number", "analyte", "other", cue=r"molecular weight|\bmw\b|g/mol"),
    # product and batch
    _f("product", "name", "product", cue=r"\bproducts?\b|\btablets?\b|\bcapsules?\b|\bformulations?\b"),
    _f("product_role", "choice", "product", choices=ROLES),
    _f("batch", "name", "batch", cue=r"\bbatch(?:es)?\b|\blots?\b"),
    _f("strength_mg", "number", "product", "mass", cue=r"strength|\btablets?\b|\bcapsules?\b"),
    _f("dosage_form", "text", "product", cue=r"dosage form|\btablets?\b|\bcapsules?\b|\bsolution\b|\bsuspension\b"),
    _f("release", "choice", "product", choices=("IR", "DR", "ER"),
       choice_cues={"IR": r"\bimmediate\b", "DR": r"\bdelayed\b", "ER": r"\b(?:extended|prolonged)\b"}),
    _f("particle_size_d10_um", "number", "product", "other", cue=r"\bd\s?10\b|particle size"),
    _f("particle_size_d50_um", "number", "product", "other", cue=r"\bd\s?50\b|particle size"),
    _f("particle_size_d90_um", "number", "product", "other", cue=r"\bd\s?90\b|particle size"),
    _f("particle_size_method", "text", "product", cue=r"particle size|laser|diffraction|microscop"),
    _f("polymorph", "text", "product", cue=r"polymorph|\bform\b|crystal"),
    _f("salt_form", "text", "product", cue=r"\bsalt\b"),
    # conditions: what tells two runs or intervals apart
    _f("apparatus", "text", "condition", cue=r"apparatus|\busp\b|paddle|basket"),
    _f("medium", "text", "condition", cue=r"\bmedi(?:um|a)\b|buffer|\bhcl\b|fassif|fessif"),
    _f("surfactant", "text", "condition", cue=r"surfactant|\bsls\b|polysorbate|tween"),
    _f("rpm", "number", "condition", "other", cue=r"\brpm\b"),
    _f("volume_ml", "number", "condition", "other", cue=r"\bml\b|volume"),
    _f("temperature_c", "number", "condition", "other", cue=r"°\s?c\b|temperature"),
    _f("ph", "number", "condition", cue=r"\bph\b"),
    _f("interval_start_h", "number", "condition", "time", cue=r"interval|\bfrom\b|collection"),
    _f("interval_end_h", "number", "condition", "time", cue=r"interval|\bto\b|collection"),
    _f("cumulative", "choice", "condition", choices=("yes", "no"),
       choice_cues={"yes": r"\bcumulative\b", "no": r"\bper interval\b"}),
    _f("component", "name", "condition", cue=r"\bcomponents?\b|excipients?|ingredients?"),
    # observations
    _f("concentration", "number", "observation", "concentration", cue=r"concentration"),
    _f("percent_dissolved", "number", "observation", "percentage", cue=r"dissol|releas"),
    _f("excretion.amount", "number", "observation", "other", cue=r"excret|amount|recover"),
    _f("excretion.fraction", "number", "observation", "percentage", cue=r"excret|fraction|recover"),
    *(_f(f"pk.{p}", "number", "observation", "other", cue=_PK_CUE[p]) for p in PK_PARAMETERS),
    _f("composition.amount", "number", "observation", "mass", cue=r"composition|per tablet|per capsule|mg/tablet"),
    # relations: the other arm in Fact.relation, the interval in Fact.interval
    *(_f(f"relation.{kind}.{p}", "number", "observation", "ratio", cue=r"ratio|\bgmr\b|\bvs\.?\b|versus")
      for kind in ("ddi_ratio", "test_vs_reference") for p in PK_PARAMETERS),
    # links: the value is the other file's study label or protocol
    _f("link.study_id", "name", "study", cue=r"\bstudy\b"),
    _f("link.protocol", "name", "study", cue=r"\bprotocol\b"),
    _f("link.cross_reference", "name", "study", cue=r"\bsee\b|\breport\b|\brefer"),
)))

CONDITION_FIELDS: tuple[str, ...] = ("medium", "ph", "apparatus", "rpm", "volume_ml", "temperature_c", "surfactant",
                                     "interval_start_h", "interval_end_h", "cumulative", "component")
LABEL_FIELDS: tuple[str, ...] = ("subject", "period", "sequence", "occasion", "vessel", "matrix")
LEGACY_FACT_NAMES: Mapping[str, str] = MappingProxyType({"weight_mean_kg": "weight_mean", "percent_female": "female_percent"})

# The mass table: document_reading._MG_PER, never retyped
MASS_UNITS: Mapping[str, float] = MappingProxyType(_MG_PER)
# The five choice fields whose cues are document_reading's (supports_choice); every other choice field has its own
_SUPPORTED = ("route", "food_state", "formulation", "design", "product_role")
_OTHER = re.compile(r"\bother\b", re.IGNORECASE)
_TOKEN = re.compile(r"[^\W_]+")


@lru_cache(maxsize=1)
def _cpf_ids() -> tuple[frozenset[str], tuple[str, ...]]:
    """The CPF parameter registry's exact ids (phys.logp, alt.select ...) and its family keys ("phys.", "elim.hepatic.",
    "sim[" ...): an id is the registry's when it is an exact id or a member of a family."""
    rules = parameters.registry().parameters
    exact = frozenset(r.key for r in rules if not r.is_family and r.suffix is None)
    families = tuple(sorted({r.key for r in rules if r.is_family}))
    return exact, families


def field(name: str) -> FieldDef | None:
    """The field of that name: one of FIELDS (also "pk.<parameter>" and the relation fields), or a CPF id as the
    requirement templates' target writes it (level compound, unit class other): an exact id of the parameter registry
    or a member of one of its families (an `@<alternative>` stays on). The registry knows a family's members only by
    its key, so "phys.<anything>" is a field as "food.fed_solubility_factor" is; "alt.<anything>" is not ("alt.select"
    is an exact id, not a family)."""
    found = FIELDS.get(name)
    if found is not None:
        return found
    if not re.fullmatch(r"[A-Za-z0-9_.\[\]@-]+", name):
        return None
    base = name.partition("@")[0]
    exact, families = _cpf_ids()
    if base in exact or any(base.startswith(key) and len(base) > len(key) for key in families):
        return FieldDef(name=name, value="number", level="compound", unit_class="other")
    return None


_lookup = field


# A value's time is not a field: its unit is named by the mapping roles that read it (mapping_spec.Role)
_TIME_ROLES = ("time", "time_actual")


def unit_class(field: str) -> UnitClass:
    """The FIELD's declared unit class ("none" for an unknown field); never inferred from the unit text. The mapping
    roles "time" and "time_actual" (a value's nominal and actual time, which are not fields) are of class time."""
    if field in _TIME_ROLES:
        return "time"
    found = _lookup(field)
    return found.unit_class if found is not None else "none"


@lru_cache(maxsize=1)
def _mass_table() -> Mapping[str, str]:
    table = {unit: unit for unit in (*_MG_PER, "mg/kg")}
    table.update({alias: _dose_unit(alias) for alias in ("ug", "mcg", "μg")})
    return MappingProxyType(table)


def unit_table(unit_class: UnitClass) -> Mapping[str, str] | None:
    """The existing table of a unit class (alias -> canonical spelling); None for a class with no table."""
    if unit_class == "concentration":
        return MappingProxyType(CONCENTRATION_UNITS)
    if unit_class == "time":
        return MappingProxyType(TIME_UNITS)
    if unit_class == "percentage":
        return MappingProxyType(FRACTION_UNITS)
    if unit_class == "mass":
        return _mass_table()
    return None


def known_unit(field: str, unit: str) -> str | None:
    """The canonical spelling of `unit` in the table of the field's class; None outside it, None for an empty unit (a
    unit that is missing is not known: UNIT_MISSING), and None when the class has no table (then the unit is kept and
    reported UNIT_NOT_CHECKED, never failed). Only `is None` means "not known": the percentage class's table writes a
    fraction of 1 ("fraction", "frac") with the canonical spelling "" (validate.FRACTION_UNITS), which is falsy."""
    if not unit or not unit.strip():
        return None
    cls = unit_class(field)
    if cls == "mass":
        folded = _dose_unit(unit)
        return folded if folded in _mass_table().values() else None
    table = unit_table(cls)
    return None if table is None else canonical_unit(unit, dict(table))


def _unique(found: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(found))


def units_in(field: str, text: str) -> tuple[str, ...]:
    """The units of the field's class a text writes, as written and in order (code's reading of a cited header, title
    or clause): concentration through document_reading._CONC_UNIT, mass through _DOSE_UNIT, time and percentage by
    token through their table. A class with no table: () (a typed unit must then be in the cited text verbatim)."""
    cls = unit_class(field)
    if cls == "concentration":
        return _unique([m.group(1) for m in _CONC_UNIT.finditer(text)])
    if cls == "mass":
        return _unique([m.group(1) for m in _DOSE_UNIT.finditer(text)])
    if cls == "time":
        return _unique([t for t in _TOKEN.findall(text) if canonical_unit(t, TIME_UNITS) is not None])
    if cls == "percentage":
        found = [m.group(0) for m in re.finditer(r"%|\bpercent\b|\bfraction\b|\bfrac\b", text, re.IGNORECASE)]
        return _unique(found)
    return ()


def read_choice(field: str, text: str) -> str | None:
    """The one choice a text states: the whole text equal to a choice (name_key); else document_reading.supports_choice
    for route, food_state, formulation, design and product_role (its cues), FieldDef.choice_cues for every other
    choice field; None when none or several match. "other" only when the text holds the word "other"."""
    found = _lookup(field)
    if found is None or found.value != "choice" or not name_key(text):
        return None
    whole = [c for c in found.choices if name_key(c) == name_key(text)]
    if len(whole) == 1:
        return whole[0]
    normalized = normalize_for_match(text)
    matches = []
    for choice in found.choices:
        if choice.lower() == "other":
            hit = _OTHER.search(normalized) is not None
        elif field in _SUPPORTED:
            hit = supports_choice(choice, text)
        else:
            cue = found.choice_cues.get(choice)
            hit = cue is not None and re.search(cue, normalized, re.IGNORECASE) is not None
        if hit:
            matches.append(choice)
    return matches[0] if len(matches) == 1 else None
