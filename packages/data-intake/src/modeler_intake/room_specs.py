"""What the Data room's agents may say (plan 2026-11-21 v2 §9): descriptions and quoted facts, never typed numbers.

An agent reads a delivery and answers in these forms only:
- `QuestionCard`: what the project must answer, the products compared, the checklist of inputs;
- `FileTriage`: what a file is for;
- `TableDescription`: where a table is (a part of a file, a range of its lines) and what each cell position means
  (code then reads every value from the cells it names, `modeler_project.dataroom.extract`);
- `Fact`: one value with the verbatim quote it was read from (code checks the quote is in the file and the value in the
  quote).

Nothing here computes; the vocabulary is open (an unknown role or field is kept, shown as context, used by nothing) so a
new kind of delivery is read without a code change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Area = Literal["A", "B", "C", "D"]   # A formulation and manufacturing · B in vitro · C drug substance and disposition · D clinical
Purpose = Literal["used", "context", "not_needed"]
TableKind = Literal["concentrations", "pk_parameters", "demographics", "disposition", "dissolution", "composition",
                    "solubility", "particle_size", "physchem", "be_statistics", "process", "other"]

TOPICS = ("question", "clinical_design", "clinical_concentrations", "clinical_pk", "clinical_demographics",
          "clinical_disposition", "bioanalysis", "dosing_and_meals", "be_statistics", "composition", "manufacturing",
          "dissolution", "solubility", "particle_size", "drug_substance", "adme", "label", "literature", "regulatory",
          "quality_paperwork", "other")

# Fact fields the assembly uses (any other dotted field is kept as context). `subject` says what the fact is about:
# a study id, a product, a batch, a treatment code, a subject number.
FIELDS: dict[str, str] = {
    # the question
    "question.regulator": "the agency the work answers", "question.approach": "PBPK, PBBM, IVIVC, VBE …",
    "question.text": "what must be answered", "question.context_of_use": "how the model will be used",
    # products and batches (subject: the product as written)
    "product.name": "a product compared", "product.role": "reference / test / original / reformulated",
    "product.strength": "strength per unit", "product.dosage_form": "tablet, capsule …",
    "product.release": "immediate, delayed, extended …", "product.manufacturer": "who makes it",
    "product.batch": "a batch or lot number as written", "product.coating": "film coat …",
    "product.core_weight": "core tablet weight", "product.composition_change": "what changed between products",
    "batch.use": "BE study, dissolution, stability … (subject: the batch)", "batch.api_batch": "the drug-substance batch used",
    # drug substance (subject: the drug)
    "substance.mw": "molecular weight", "substance.salt": "salt form", "substance.dose_basis": "dose as base or salt",
    "substance.pka": "pKa and type", "substance.logp": "log P", "substance.logd": "log D at a pH",
    "substance.solubility": "solubility (with pH or medium, temperature)", "substance.particle_size": "d10/d50/d90",
    "substance.solid_form": "polymorph", "substance.melting_point": "melting point",
    "substance.permeability": "permeability (Caco-2, MDCK, Peff)", "substance.bcs": "BCS class",
    # ADME and disposition (subject: the drug)
    "adme.fu": "fraction unbound / protein binding", "adme.bp_ratio": "blood-to-plasma ratio", "adme.vd": "volume of distribution",
    "adme.cl": "clearance", "adme.bioavailability": "absolute bioavailability", "adme.tmax": "tmax",
    "adme.half_life": "half-life", "adme.metabolism": "enzymes and fm", "adme.excretion": "urine / faeces recovery",
    "adme.food_effect": "food effect on exposure", "adme.ddi": "interaction", "adme.transporters": "transporters",
    # clinical study (subject: the study id)
    "study.id": "study number", "study.title": "title", "study.design": "crossover / parallel, periods, sequences",
    "study.blinding": "open / blind", "study.n_planned": "subjects planned", "study.n_dosed": "subjects dosed (per period)",
    "study.n_completed": "subjects completed", "study.completed_subjects": "the subject numbers that completed",
    "study.statistical_set": "the subject numbers in the client's statistical analysis",
    "study.excluded_subjects": "subject numbers left out, each with its reason", "study.population": "healthy / patients",
    "study.sex": "male / female / both", "study.ethnicity": "ethnicity", "study.age": "age (mean, SD, range)",
    "study.weight": "weight (mean, SD, range)", "study.height": "height", "study.bmi": "BMI", "study.dose": "dose per unit and per administration",
    "study.route": "oral, IV …", "study.regimen": "single / multiple, interval, number of doses",
    "study.fasting": "fasting before and after dosing", "study.fed": "fed: the meal before dosing",
    "study.meal_times": "meals after dosing, hours", "study.meal_composition": "kcal, fat, protein, carbohydrate",
    "study.water": "water with the dose (mL)", "study.comedication": "other drugs given (time, dose)",
    "study.washout": "washout between periods", "study.sampling_times": "sampling times (h)",
    "study.analyte": "what was measured", "study.matrix": "plasma, serum, blood, urine", "study.lloq": "lower limit of quantification",
    "study.bioanalytical_method": "LC-MS/MS …", "study.treatment_code": "a treatment code and what it means (subject: the code)",
    "study.be_result": "test/reference ratio and 90 % CI per metric", "study.dates": "dosing dates",
    # dissolution method (subject: the batch or the table)
    "dissolution.apparatus": "USP 1 basket, USP 2 paddle …", "dissolution.speed": "rpm", "dissolution.volume": "mL",
    "dissolution.medium": "medium with pH and surfactant", "dissolution.temperature": "°C", "dissolution.units": "tablets per batch",
    "dissolution.f2": "f2 between two batches (subject: 'batch A vs batch B in medium')",
}

ROLES: dict[str, tuple[str, ...]] = {
    # "time" is the nominal (scheduled) time; an "actual_time" column is kept as context
    "concentrations": ("subject", "sequence", "period", "treatment", "time", "actual_time", "value", "statistic", "analyte",
                       "matrix", "dose", "group"),
    "pk_parameters": ("subject", "sequence", "period", "treatment", "cmax", "tmax", "auc_t", "auc_inf", "t_half",
                      "lambda_z", "statistic", "group"),
    "demographics": ("subject", "sex", "age", "weight", "height", "bmi", "race", "smoking", "group"),
    "disposition": ("subject", "status", "reason", "period"),
    "dissolution": ("unit", "time", "value", "statistic", "batch", "medium"),
    "composition": ("component", "function", "grade", "specification", "amount", "percent"),
    "solubility": ("medium", "ph", "solubility", "dose_volume", "temperature"),
    "particle_size": ("batch", "d10", "d50", "d90", "api_batch", "remark"),
    "physchem": ("property", "value"),
    "be_statistics": ("parameter", "ratio", "ci_low", "ci_high", "statistic"),
    "process": ("step", "parameter", "value"),
}


class _B(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChecklistItem(_B):
    id: str = Field(description="short id, e.g. B-dissolution-all-media")
    label: str
    area: Area
    why: str = ""
    required: bool = True
    topics: list[str] = Field(default_factory=list)


class ProductRef(_B):
    name: str = Field(description="as the files name it")
    role: Literal["reference", "test", "original", "reformulated", "other"] = Field(
        description="the product's part in the comparison: reference, test, original, reformulated or other")
    note: str = ""


class QuestionCard(_B):
    question: str
    regulator: str = ""
    approach: str = ""
    context_of_use: str = ""
    products: list[ProductRef] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    quotes: list[Fact] = Field(default_factory=list, description="the facts the card rests on, each quoted")


class FileTriage(_B):
    path: str
    purpose: Purpose
    topics: list[str] = Field(default_factory=list)
    reason: str = Field(description="one plain sentence: what the file is and why it is (not) needed")
    study: str = ""
    products: list[str] = Field(default_factory=list)


class Fact(_B):
    field: str = Field(description="a dotted field from the vocabulary, or a new dotted name")
    subject: str = Field(default="", description="what the fact is about, as written (a study, product, batch, code, subject)")
    value: str = Field(description="the value exactly as written in the file")
    unit: str = ""
    quote: str = Field(description="the verbatim text from the file that contains the value (one to three lines)")
    file: str = ""
    part: str = Field(default="", description="where: p<page>, sheet:<name> or body")
    product: str = Field(default="", description="the product (as named on the question card) the fact concerns, if any")
    note: str = ""


class ColumnSpec(_B):
    index: int = Field(description="1-based position of the cell in a line (cells are separated by ' | ')")
    role: str
    label: str = Field(default="", description="the column's header as written")
    unit: str = ""
    time: float | None = Field(default=None, description="for a column whose header is a time: that time, in time_unit")
    group: str = Field(default="", description="a side-by-side block this column belongs to (a batch, a treatment), as written")


class TableDescription(_B):
    """Where a table is (a part of a file and a range of its lines) and what its cells mean. Code reads every value."""

    file: str
    kind: TableKind
    about: str = Field(default="", description="study, product or batch the whole table belongs to, as written")
    part: str = Field(description="p<page>, sheet:<name> or body")
    header_lines: list[int] = Field(default_factory=list, description="the lines that hold the headers")
    first_line: int = Field(description="first data line")
    last_line: int = Field(description="last data line (inclusive)")
    skip_lines: list[int] = Field(default_factory=list, description="lines inside the range that are not data (a repeated header, a subtotal)")
    summary_lines: dict[str, int] = Field(default_factory=dict, description="the client's own summary lines, e.g. {'mean': 25, 'rsd': 26}")
    columns: list[ColumnSpec]
    time_unit: str = ""
    value_unit: str = ""
    missing_tokens: list[str] = Field(default_factory=lambda: [".", "-", "—", "NA", "N/A", "NR", "ND", "NS", "M"])
    blq_tokens: list[str] = Field(default_factory=lambda: ["BLQ", "BQL", "<LLOQ", "< LLOQ", "<LOQ", "BLOQ", "LLOQ"])
    zero_means_blq: bool = Field(default=False, description="true when the file writes concentrations below the LLOQ as 0")
    constants: dict[str, str] = Field(default_factory=dict, description="values every row shares (analyte, matrix, medium, batch …), each also given as a Fact")
    note: str = ""


class Extraction(_B):
    """An extractor's answer for one file."""

    file: str
    tables: list[TableDescription] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list, description="checklist ids looked for in this file and not there")


QuestionCard.model_rebuild()
