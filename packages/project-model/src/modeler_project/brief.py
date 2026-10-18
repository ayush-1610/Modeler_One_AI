"""The Project Brief: one fixed structure for every project (plan §6, review layer L1).

Every field is a record, not a bare value: the value (and unit), its status, the citations it was read from, a
confidence grade and who changed it. What a document does not state is MISSING with a question, never inferred.
Lists of things (products, scenarios, populations, data-plan statements) are groups whose items carry the same
records per sub-field. Paths address both: ``drug.salt_form``, ``products[0].role``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pbpk_domain.campaign.split import FormulationKind
from pbpk_domain.m15 import Rating, allowed_model_risk

BRIEF_SCHEMA = "brief/1"


class FieldStatus(StrEnum):
    ENTERED = "ENTERED"            # typed by a person at project start (the drug name)
    EXTRACTED = "EXTRACTED"        # stated in an uploaded document; quote verified on the cited page
    RETRIEVED = "RETRIEVED"        # from a database record (e.g. PubChem), the record cited
    COMPUTED = "COMPUTED"          # derived by code from other fields (e.g. MW from the structure, RDKit)
    EDITED = "EDITED"              # changed by a person; the reason is in `note`
    CONFIRMED = "CONFIRMED"        # reviewed and kept as it was
    MISSING = "MISSING"            # not stated anywhere yet; a question is raised
    NOT_APPLICABLE = "NOT_APPLICABLE"


VALUED = {FieldStatus.ENTERED, FieldStatus.EXTRACTED, FieldStatus.RETRIEVED, FieldStatus.COMPUTED,
          FieldStatus.EDITED, FieldStatus.CONFIRMED}


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    locator: str = ""        # "Table 2", "Figure 3", "Sheet!B4", "PubChem CID 9887712"
    source: str = ""         # document name or record title, for display


class FieldRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any = None
    unit: str | None = None
    status: FieldStatus = FieldStatus.MISSING
    citations: tuple[Citation, ...] = ()
    confidence: Literal["A", "B", "C", "D"] | None = None
    note: str = ""
    by: str | None = None
    at: datetime | None = None


Kind = Literal["text", "number", "enum", "list", "bool", "multi"]


@dataclass(frozen=True)
class FieldDef:
    id: str
    section: str
    label: str
    kind: Kind = "text"
    required: bool = False
    options: tuple[str, ...] = ()
    unit: str | None = None
    help: str = ""


@dataclass(frozen=True)
class GroupDef:
    id: str
    section: str
    label: str
    fields: tuple[FieldDef, ...]
    required: bool = False   # at least one item


SECTIONS = {
    "A": "Project", "B": "Drug substance", "C": "Products", "D": "Question and context of use (ICH M15)",
    "E": "Scenarios to simulate", "F": "Populations", "G": "Model scope", "H": "Data plan",
    "I": "Assumptions, exclusions, risks", "J": "Open questions",
}

APPLICATIONS = (
    "APP-01 model build and verification", "APP-02 FIH translation", "APP-03 enzyme DDI", "APP-04 transporter DDI",
    "APP-05 pharmacogenomics", "APP-06 pediatric extrapolation", "APP-07 hepatic impairment",
    "APP-08 renal impairment", "APP-09 pregnancy and lactation", "APP-10 geriatrics, obesity, ethnicity",
    "APP-11 absorption and formulation", "APP-12 food effect", "APP-13 pH-dependent DDI",
    "APP-14 virtual bioequivalence", "APP-15 tissue exposure", "APP-16 large molecules", "APP-17 PK/PD",
    "APP-18 dose and regimen", "APP-19 chemical risk",
)
PRODUCT_ROLES = ("TEST", "RLD", "REFERENCE", "SOLUTION", "OTHER")
PROVIDERS = ("CLIENT", "LITERATURE", "SPONSOR_TO_MEASURE", "PREDICT", "NOT_STATED")
PURPOSES = ("model_building", "internal_validation", "external_validation", "application_verification", "supportive")
DATA_CATEGORIES = (
    "physchem", "binding", "in_vitro_adme", "clinical_pk_iv", "clinical_pk_oral", "clinical_pk_fed",
    "clinical_pk_md", "clinical_pk_special", "clinical_ddi", "dissolution", "rld_data", "bioanalytical",
    "urine_feces", "formulation", "other",
)
ROUTES = ("iv_bolus", "iv_infusion", "oral", "subcutaneous", "intramuscular", "dermal", "inhalation", "other")
RATINGS = tuple(r.value for r in Rating)
# The formulation types the MS-01 split knows (pbpk_domain.campaign.split), then the product types the builder cannot
# model yet, which the Start screen refuses (D-28). Support is added one product type at a time, with the SME.
FORMULATIONS_BUILT = tuple(k.value for k in FormulationKind if k is not FormulationKind.OTHER)
FORMULATIONS_NOT_BUILT = ("liposome", "amorphous_solid_dispersion", "long_acting_injectable", "inhaled", "dermal", "other")
FORMULATION_TYPES = FORMULATIONS_BUILT + FORMULATIONS_NOT_BUILT
OPTION_LABELS: dict[str, dict[str, str]] = {
    "scope.formulation_types": {
        "solution": "solution", "suspension": "suspension", "ir_tablet": "immediate-release tablet",
        "ir_capsule": "immediate-release capsule", "mr": "modified release", "liposome": "liposome",
        "amorphous_solid_dispersion": "amorphous solid dispersion", "long_acting_injectable": "long-acting injectable",
        "inhaled": "inhaled product", "dermal": "dermal product", "other": "other"},
    "scope.pbpk_model": {"full": "full PBPK (whole body)", "minimal": "minimal PBPK"},
}

FIELDS: tuple[FieldDef, ...] = (
    # A · project
    FieldDef("proj.title", "A", "Project title", required=True),
    FieldDef("proj.client", "A", "Client / sponsor", help="confidential"),
    FieldDef("proj.type", "A", "Project type", "enum", True,
             ("new_drug_ind", "nda", "505b2", "generic_anda", "biowaiver", "lifecycle_change", "research", "other")),
    FieldDef("proj.agencies", "A", "Regulatory agencies", "multi",
             options=("FDA", "EMA", "PMDA", "CDSCO", "Health Canada", "TGA", "NMPA", "MHRA", "other")),
    FieldDef("proj.deliverables", "A", "Deliverables", "list"),
    FieldDef("proj.milestones", "A", "Milestones and dates", "list"),
    # B · drug substance
    FieldDef("drug.name", "B", "Drug (INN)", required=True),
    FieldDef("drug.code", "B", "Development code"),
    FieldDef("drug.synonyms", "B", "Synonyms", "list"),
    FieldDef("drug.salt_form", "B", "Salt / solid form"),
    FieldDef("drug.dose_basis", "B", "Doses expressed as", "enum", options=("free_base", "salt", "unknown")),
    FieldDef("drug.cas", "B", "CAS number"),
    FieldDef("drug.pubchem_cid", "B", "PubChem CID"),
    FieldDef("drug.smiles", "B", "SMILES"),
    FieldDef("drug.inchikey", "B", "InChIKey"),
    FieldDef("drug.mw_free_base", "B", "Molecular weight (free base)", "number", unit="g/mol"),
    FieldDef("drug.mw_salt", "B", "Molecular weight (salt)", "number", unit="g/mol"),
    FieldDef("drug.modality", "B", "Modality", "enum", True, ("small_molecule", "large_molecule", "other")),
    FieldDef("drug.bcs_class", "B", "BCS class (as stated)", "enum", options=("I", "II", "III", "IV", "unknown")),
    FieldDef("drug.bddcs_class", "B", "BDDCS class (as stated)", "enum", options=("1", "2", "3", "4", "unknown")),
    FieldDef("drug.therapeutic_area", "B", "Therapeutic area"),
    # D · question and context of use
    FieldDef("qoi.text", "D", "Question of interest", required=True),
    FieldDef("qoi.context_of_use", "D", "Context of use", required=True),
    FieldDef("qoi.decision", "D", "Decision the model informs"),
    FieldDef("qoi.applications", "D", "Applications", "multi", True, APPLICATIONS),
    FieldDef("m15.influence", "D", "Model influence (description; rating is human-only)"),
    FieldDef("m15.consequence", "D", "Consequence of a wrong decision (description; rating is human-only)"),
    FieldDef("m15.influence_rating", "D", "Model influence", "enum", options=RATINGS,
             help="ICH M15 §2.1.5: how much the model's evidence weighs in the decision; rated by a person"),
    FieldDef("m15.consequence_rating", "D", "Decision consequence", "enum", options=RATINGS,
             help="ICH M15 §2.1.5: what a wrong decision would mean for the patient; rated by a person"),
    FieldDef("acceptance.stated", "D", "Acceptance criteria as written in the proposal"),
    FieldDef("acceptance.tier", "D", "Model risk tier (human-confirmed)", "enum", options=RATINGS),
    FieldDef("m15.risk_justification", "D", "Why this model risk",
             help="required when influence and consequence differ (ICH M15 §2.1.5)"),
    FieldDef("acceptance.internal_target_pe", "D", "Internal target: absolute prediction error at most", "number",
             unit="%", help="optional, stricter than the tier (MS-01 §8), e.g. 10"),
    # G · model scope
    FieldDef("scope.platform", "G", "Platform and version", help="e.g. PK-Sim 12.3 (OSP Suite)"),
    FieldDef("scope.model_type", "G", "Model type", "enum", options=("small_molecule", "large_molecule")),
    FieldDef("scope.pbpk_model", "G", "PBPK model", "enum", options=("full", "minimal"),
             help="full: the whole-body PK-Sim model; a minimal PBPK model is not supported yet"),
    FieldDef("scope.site_of_action", "G", "Site of action", "enum", options=("systemic", "local")),
    FieldDef("scope.formulation_types", "G", "Formulation types", "multi", options=FORMULATION_TYPES),
    FieldDef("scope.parent_metabolite", "G", "Analytes modeled", "enum", options=("parent_only", "parent_and_metabolites")),
    FieldDef("scope.pathways_stated", "G", "Elimination / transport pathways stated", "list"),
    FieldDef("scope.nonlinearity", "G", "Nonlinearity stated (saturation, auto-induction)"),
    FieldDef("scope.ddi", "G", "DDI role and partners"),
    FieldDef("scope.ehc", "G", "Enterohepatic recycling stated", "bool"),
    FieldDef("scope.pd", "G", "PK/PD in scope", "bool"),
    # I · assumptions, exclusions, risks
    FieldDef("notes.assumptions", "I", "Assumptions", "list"),
    FieldDef("notes.exclusions", "I", "Exclusions", "list"),
    FieldDef("notes.risks", "I", "Risks", "list"),
)

GROUPS: tuple[GroupDef, ...] = (
    GroupDef("products", "C", "Products", (
        FieldDef("name", "C", "Product", required=True),
        FieldDef("role", "C", "Role", "enum", True, PRODUCT_ROLES),
        FieldDef("dosage_form", "C", "Dosage form"),
        FieldDef("strength", "C", "Strength", "number", unit="mg"),
        FieldDef("release", "C", "Release", "enum", options=("IR", "DR", "ER", "unknown")),
        FieldDef("manufacturer", "C", "Manufacturer"),
        FieldDef("batches", "C", "Batches / lots"),
        FieldDef("attributes", "C", "Stated attributes (particle size, polymorph, excipients)"),
    ), required=True),
    GroupDef("scenarios", "E", "Scenarios", (
        FieldDef("population", "E", "Population", required=True),
        FieldDef("route", "E", "Route", "enum", True, ROUTES),
        FieldDef("dose", "E", "Dose", "number", True, unit="mg"),
        FieldDef("regimen", "E", "Regimen (SD / MD)"),
        FieldDef("dosing_interval_h", "E", "Dosing interval", "number", unit="h"),
        FieldDef("n_doses", "E", "Number of doses", "number"),
        FieldDef("infusion_time_min", "E", "Infusion time", "number", unit="min"),
        FieldDef("product", "E", "Product"),
        FieldDef("food_state", "E", "Food state", "enum", options=("fasted", "fed")),
        FieldDef("meal", "E", "Meal"),
        FieldDef("co_medication", "E", "Co-medication"),
        FieldDef("outputs", "E", "Outputs of interest"),
        FieldDef("trial_design", "E", "Virtual trial design"),
    ), required=True),
    GroupDef("populations", "F", "Populations", (
        FieldDef("kind", "F", "Kind", "enum", True,
                 ("healthy", "patient", "pediatric", "hepatic_impairment", "renal_impairment", "pregnancy", "elderly",
                  "ethnic", "genotype", "preclinical")),
        FieldDef("age_range", "F", "Age range"),
        FieldDef("sex", "F", "Sex"),
        FieldDef("ethnicity", "F", "Ethnicity / PK-Sim population"),
        FieldDef("impairment_class", "F", "Impairment class (Child-Pugh, eGFR)"),
        FieldDef("genotype", "F", "Genotype / phenotype"),
        FieldDef("species", "F", "Species"),
    )),
    GroupDef("data_plan", "H", "Data plan (who provides what)", (
        FieldDef("item", "H", "Data item as stated", required=True),
        FieldDef("category", "H", "Category", "enum", True, DATA_CATEGORIES),
        FieldDef("provider", "H", "Provider", "enum", True, PROVIDERS),
        FieldDef("purpose", "H", "Purpose", "enum", options=PURPOSES),
        FieldDef("due_date", "H", "Due date"),
        FieldDef("format", "H", "Format"),
    ), required=True),
)

FIELD_BY_ID = {f.id: f for f in FIELDS}

# The short brief of the Start screen (redesign §3.1): what the model, the MAP and the scope gates read. Everything else
# is a proposal note, kept for the report and never required.
SHORT_BRIEF = (
    "drug.name", "drug.pubchem_cid", "drug.smiles", "drug.inchikey", "drug.mw_free_base",
    "qoi.text", "qoi.context_of_use", "qoi.applications",
    "m15.influence", "m15.influence_rating", "m15.consequence", "m15.consequence_rating", "acceptance.tier",
    "m15.risk_justification",
    "drug.modality", "scope.pbpk_model", "scope.site_of_action", "scope.formulation_types", "drug.bcs_class",
    "scope.pathways_stated", "scope.nonlinearity", "scope.ehc",
)
SHORT_GROUP_FIELDS = {"scenarios": ("route", "food_state")}
# What Start needs before the inputs are worth gathering. The model risk (RISK_FIELDS) and the scope gates
# (`feasibility.scope_gates`) are checked on their own, with their own reasons.
START_REQUIRED = ("drug.name", "qoi.text", "qoi.context_of_use", "qoi.applications")
RISK_FIELDS = ("m15.influence_rating", "m15.consequence_rating", "acceptance.tier")
GROUP_BY_ID = {g.id: g for g in GROUPS}
_PATH = re.compile(r"^(?P<group>[a-z_]+)\[(?P<index>\d+)\]\.(?P<field>[a-z0-9_]+)$")


class Question(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    field: str
    question: str
    answer: str = ""
    status: Literal["open", "answered", "accepted_as_limitation"] = "open"
    raised_by: str = "system"


class ProjectBrief(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: str = Field(default=BRIEF_SCHEMA, alias="schema")
    drug_name: str = Field(min_length=1)
    fields: dict[str, FieldRecord] = Field(default_factory=dict)
    groups: dict[str, tuple[dict[str, FieldRecord], ...]] = Field(default_factory=dict)
    questions: tuple[Question, ...] = ()

    def to_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

    @classmethod
    def from_content(cls, content: dict[str, Any]) -> ProjectBrief:
        return cls.model_validate(content)

    def get(self, path: str) -> FieldRecord:
        group, index, sub = parse_path(path)
        if group is None:
            return self.fields.get(sub, FieldRecord())
        items = self.groups.get(group, ())
        return items[index].get(sub, FieldRecord()) if index < len(items) else FieldRecord()

    def value(self, path: str) -> Any:
        record = self.get(path)
        return record.value if record.status in VALUED else None


class BriefPathError(ValueError):
    pass


def parse_path(path: str) -> tuple[str | None, int, str]:
    """``drug.name`` → (None, 0, "drug.name"); ``products[1].role`` → ("products", 1, "role")."""
    match = _PATH.match(path)
    if match:
        group, sub = match["group"], match["field"]
        definition = GROUP_BY_ID.get(group)
        if definition is None or sub not in {f.id for f in definition.fields}:
            raise BriefPathError(f"unknown brief field {path!r}")
        return group, int(match["index"]), sub
    if path not in FIELD_BY_ID:
        raise BriefPathError(f"unknown brief field {path!r}")
    return None, 0, path


def definition_of(path: str) -> FieldDef:
    group, _, sub = parse_path(path)
    if group is None:
        return FIELD_BY_ID[sub]
    return next(f for f in GROUP_BY_ID[group].fields if f.id == sub)


def coerce(definition: FieldDef, value: Any) -> Any:
    """Normalize a proposed value to the field's kind; raises ValueError with a reason the agent or user can act on."""
    if value is None:
        return None
    if definition.kind == "number":
        if isinstance(value, bool):
            raise ValueError(f"{definition.label}: a number is required")
        if isinstance(value, int | float):
            return float(value)
        text = str(value).strip().replace(",", "")
        match = re.match(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", text)
        if not match:
            raise ValueError(f"{definition.label}: {value!r} is not a number")
        return float(match.group(0))
    if definition.kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes", "y", "1"):
            return True
        if text in ("false", "no", "n", "0"):
            return False
        raise ValueError(f"{definition.label}: yes or no")
    if definition.kind == "enum":
        text = str(value).strip()
        for option in definition.options:
            if text.lower() == option.lower():
                return option
        raise ValueError(f"{definition.label}: {value!r} is not one of {', '.join(definition.options)}")
    if definition.kind in ("list", "multi"):
        items = list(value) if isinstance(value, list | tuple) else [v.strip() for v in str(value).split(";") if v.strip()]
        if definition.kind == "multi":
            out = []
            for item in items:
                matched = next((o for o in definition.options if o.lower() == str(item).strip().lower()
                                or o.lower().startswith(str(item).strip().lower() + " ")), None)
                if matched is None:
                    raise ValueError(f"{definition.label}: {item!r} is not one of {', '.join(definition.options)}")
                out.append(matched)
            return list(dict.fromkeys(out))
        return [str(i) for i in items]
    return str(value).strip()


def empty_brief(drug_name: str, *, by: str) -> ProjectBrief:
    """A brief with the drug name as entered and every other field MISSING (the manual path starts here)."""
    now = datetime.now(UTC)
    fields = {f.id: FieldRecord() for f in FIELDS}
    fields["drug.name"] = FieldRecord(value=drug_name.strip(), status=FieldStatus.ENTERED, by=by, at=now,
                                      note="entered at project start")
    return ProjectBrief(drug_name=drug_name.strip(), fields=fields, groups={g.id: () for g in GROUPS})


def set_record(brief: ProjectBrief, path: str, record: FieldRecord) -> ProjectBrief:
    """Return a new brief with `path` set to `record` (a group item is created when the index is the next one)."""
    group, index, sub = parse_path(path)
    if group is None:
        return brief.model_copy(update={"fields": {**brief.fields, sub: record}})
    items = list(brief.groups.get(group, ()))
    if index > len(items):
        raise BriefPathError(f"{path}: add {group}[{len(items)}] first")
    if index == len(items):
        items.append({})
    items[index] = {**items[index], sub: record}
    return brief.model_copy(update={"groups": {**brief.groups, group: tuple(items)}})


def remove_item(brief: ProjectBrief, group: str, index: int) -> ProjectBrief:
    items = list(brief.groups.get(group, ()))
    if not 0 <= index < len(items):
        raise BriefPathError(f"no {group}[{index}]")
    del items[index]
    return brief.model_copy(update={"groups": {**brief.groups, group: tuple(items)}})


def add_question(brief: ProjectBrief, field: str, question: str, *, raised_by: str) -> ProjectBrief:
    if any(q.field == field and q.status == "open" for q in brief.questions):
        return brief
    q = Question(id=f"q{len(brief.questions) + 1}", field=field, question=question.strip(), raised_by=raised_by)
    return brief.model_copy(update={"questions": (*brief.questions, q)})


@dataclass(frozen=True)
class BriefIssue:
    code: str
    path: str
    message: str


def validate_brief(brief: ProjectBrief) -> list[BriefIssue]:
    """What blocks approval of the brief: required fields still missing, records that contradict their status."""
    issues: list[BriefIssue] = []

    def check(path: str, definition: FieldDef, record: FieldRecord) -> None:
        if record.status is FieldStatus.MISSING and record.value not in (None, "", []):
            issues.append(BriefIssue("MISSING_WITH_VALUE", path, "a missing field carries a value"))
        if record.status in (FieldStatus.EXTRACTED, FieldStatus.RETRIEVED) and not record.citations:
            issues.append(BriefIssue("NO_CITATION", path, "an extracted value must cite its source"))
        if definition.required and record.status is FieldStatus.MISSING:
            issues.append(BriefIssue("REQUIRED_MISSING", path, f"{definition.label} is required "
                                     "(fill it, or mark it not applicable with a reason)"))
        if record.status in VALUED and record.value not in (None, "", []):
            try:
                coerce(definition, record.value)
            except ValueError as exc:
                issues.append(BriefIssue("INVALID_VALUE", path, str(exc)))

    for definition in FIELDS:
        check(definition.id, definition, brief.fields.get(definition.id, FieldRecord()))
    for group in GROUPS:
        items = brief.groups.get(group.id, ())
        if group.required and not items:
            issues.append(BriefIssue("REQUIRED_MISSING", group.id, f"at least one entry in {group.label} is required"))
        for index, item in enumerate(items):
            for definition in group.fields:
                check(f"{group.id}[{index}].{definition.id}", definition, item.get(definition.id, FieldRecord()))
    for q in brief.questions:
        if q.status == "open":
            issues.append(BriefIssue("OPEN_QUESTION", q.field, f"open question: {q.question}"))
    return issues


@dataclass(frozen=True)
class RiskCheck:
    allowed: tuple[str, ...] | None    # the tiers ICH M15 admits for the two ratings; None until both are rated
    problems: tuple[str, ...]          # what Start still needs on the model risk
    refused: str | None                # a tier outside `allowed`: an edit that leads here is refused


def admitted_tiers() -> dict[str, list[str]]:
    """Every pair of ratings ("influence/consequence") with the tiers ICH M15 §2.1.5 admits for it: the picker shows
    them as the person rates, so the rule lives here only."""
    return {f"{i}/{c}": [r.value for r in allowed_model_risk(Rating(i), Rating(c))] for i in RATINGS for c in RATINGS}


def risk_check(brief: ProjectBrief) -> RiskCheck:
    """The model risk as ICH M15 §2.1.5 builds it: influence and consequence, each rated by a person, then the tier.
    Equal ratings give that tier; different ones admit any tier between them, and the choice is justified. The tier
    is never assumed (R0): until it is set, Start waits on it and the plan refuses the signature."""
    influence, consequence, tier = (brief.value(p) for p in RISK_FIELDS)
    allowed = (tuple(r.value for r in allowed_model_risk(Rating(influence), Rating(consequence)))
               if influence in RATINGS and consequence in RATINGS else None)
    problems = [f"{FIELD_BY_ID[p].label}: not rated yet" for p, v in zip(RISK_FIELDS[:2], (influence, consequence),
                                                                         strict=True) if v is None]
    refused = None
    if tier is None:
        problems.append("Model risk: not set yet (it is never assumed)")
    elif allowed is not None and tier not in allowed:
        refused = (f"with model influence {influence} and decision consequence {consequence}, ICH M15 §2.1.5 admits a "
                   f"model risk of {' to '.join(dict.fromkeys((allowed[0], allowed[-1])))}, not {tier}")
        problems.append(f"Model risk: {refused}")
    elif allowed is not None and len(allowed) > 1 and not brief.value("m15.risk_justification"):
        problems.append(f"Why this model risk: influence and consequence differ, so say why it is {tier}")
    return RiskCheck(allowed=allowed, problems=tuple(problems), refused=refused)


def catalog() -> dict[str, Any]:
    """The schema as the web form renders it."""
    def field_view(f: FieldDef) -> dict[str, Any]:
        return {"id": f.id, "section": f.section, "label": f.label, "kind": f.kind, "required": f.required,
                "options": list(f.options), "option_labels": OPTION_LABELS.get(f.id, {}), "unit": f.unit, "help": f.help}

    return {
        "schema": BRIEF_SCHEMA, "sections": SECTIONS, "short_brief": list(SHORT_BRIEF),
        "short_group_fields": {g: list(f) for g, f in SHORT_GROUP_FIELDS.items()},
        "fields": [field_view(f) for f in FIELDS],
        "groups": [{"id": g.id, "section": g.section, "label": g.label, "required": g.required,
                    "fields": [field_view(f) for f in g.fields]} for g in GROUPS],
    }


def all_paths(brief: ProjectBrief) -> Iterable[str]:
    yield from (f.id for f in FIELDS)
    for group in GROUPS:
        for index in range(len(brief.groups.get(group.id, ()))):
            for f in group.fields:
                yield f"{group.id}[{index}].{f.id}"
