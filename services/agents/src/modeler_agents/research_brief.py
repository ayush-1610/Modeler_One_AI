"""What A2 is told before it searches (docs/plans/2026-11-03-inputs-and-client-data.md; the owner, 2026-11-03: "fetch the
compound's parameters properly and in the project's context, with better tasks, so that every input is found and
filled").

Code, not the agent, works out three things and hands them over:

* **the project's context** from the brief: the drug and its other names and codes, its modality and BCS class, the
  routes, products and populations of the scenarios, the applications and the pathways the proposal names, so that the
  agent looks for values that fit this project (a human value, the dosage form, the pathways that matter);
* **each input's status** from the evidence register: missing, conflicting, held only by a weak or predicted value, given
  by the client (a cross-check), or already covered by a measured value (searched last, only for a better source). The
  inputs are handed over in that order, so the turns go where the model is weakest;
* **where each kind of PBPK input is usually found**, with the terms that find it (`SEARCH_HINTS`), so a search does not
  depend on the agent knowing the field's vocabulary.

Nothing here decides a value: it shapes the search. Every value the agent proposes is still checked by code against
the page it read (`evidence_agent.propose_value`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from modeler_project.evidence import EvidenceItem, EvidenceState, SourceType
from modeler_project.requirements import RequirementItem

# Where an input is usually reported, and the words that find it (by CPF id family, longest prefix first).
SEARCH_HINTS: tuple[tuple[str, str], ...] = (
    ("phys.mw", "molecular weight of the free base; PubChem or the label's description section"),
    ("phys.logp", "\"logP\", \"log D7.4\", \"octanol/water partition coefficient\", \"lipophilicity\"; FDA chemistry or biopharmaceutics review"),
    ("phys.pka", "\"pKa\", \"dissociation constant\", \"ionization\"; say which is acidic and which basic"),
    ("phys.solubility", "\"aqueous solubility\", \"solubility at pH\", \"FaSSIF\", \"FeSSIF\", \"BCS class\"; biopharmaceutics review, EPAR quality section"),
    ("bind.fu", "\"plasma protein binding\", \"fraction unbound\", \"% bound\", \"equilibrium dialysis\", \"ultrafiltration\"; label section 12.3"),
    ("bind.partner", "\"bound to albumin\", \"alpha-1-acid glycoprotein\", \"binding protein\"; with the protein binding data"),
    ("dist.bp_ratio", "\"blood-to-plasma ratio\", \"blood/plasma concentration ratio\", \"red blood cell partitioning\""),
    ("perm.", "\"Caco-2\", \"apparent permeability\", \"Papp\", \"efflux ratio\", \"PAMPA\", \"human jejunal permeability (Peff)\""),
    ("elim.fe_urine", "\"excreted unchanged in urine\", \"[14C] mass balance\", \"human ADME study\", \"recovery in urine\""),
    ("elim.renal", "\"renal clearance\", \"glomerular filtration\", \"active tubular secretion\", \"CLR\""),
    ("elim.fm", "\"fraction metabolised\", \"reaction phenotyping\", \"recombinant CYP\", \"chemical inhibition\", \"DDI with ketoconazole / rifampicin\""),
    ("elim.hepatic", "\"intrinsic clearance\", \"human liver microsomes\", \"hepatocytes\", \"Km\", \"Vmax\", \"CLint\", \"fu,inc\"; record the enzyme and the system"),
    ("elim.biliary", "\"biliary excretion\", \"bile\", \"enterohepatic\", \"faecal recovery of unchanged drug\""),
    ("elim", "\"clearance\", \"elimination pathways\", \"[14C] mass balance\", \"metabolism\", \"major metabolites\"; FDA clinical pharmacology review"),
    ("trans.", "\"transporter substrate\", \"OATP1B1\", \"P-gp\", \"BCRP\", \"OAT\", \"OCT\", \"Km\", \"efflux ratio\""),
    ("form.", "\"dissolution\", \"release profile\", \"% dissolved\", \"disintegration\"; for the project's own product, the client's data first"),
)
REGULATORY = ("Regulatory documents are the first place to look: \"<drug> clinical pharmacology biopharmaceutics review\" (FDA "
              "Drugs@FDA), \"<drug> EPAR scientific discussion\" (EMA), and the US label's section 12.3 (pharmacokinetics).")
STATUS_ORDER = ("missing", "conflict", "weak", "client", "covered")
STATUS_TEXT = {
    "missing": "no value yet: find one",
    "conflict": "sources more than 2-fold apart: find the primary source that settles it",
    "weak": "only a weak or predicted value: find a measured value from a primary source",
    "client": "the client gives it: find a literature value to cross-check it",
    "covered": "covered by a measured value: only a better (regulatory or primary) source is worth adding",
}


def hint_for(target: str, label: str = "") -> str:
    """The terms that find an input; for one no family names, its own label with the drug's names."""
    found = next((hint for prefix, hint in SEARCH_HINTS if target.startswith(prefix)), "")
    return found or (f"\"{label}\" with every name of the drug; regulatory reviews and the label" if label else "")


@dataclass(frozen=True)
class ProjectFacts:
    """The facts of the brief that tell the agent which values fit this project."""

    drug: str
    names: tuple[str, ...] = ()
    modality: str = ""
    bcs: str = ""
    routes: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    populations: tuple[str, ...] = ()
    applications: tuple[str, ...] = ()
    pathways: tuple[str, ...] = ()
    question: str = ""

    def text(self) -> str:
        lines = [f"Drug: {self.drug}" + (f" (also: {', '.join(self.names)})" if self.names else "")]
        for label, values in (("Modality", (self.modality,)), ("BCS class", (self.bcs,)), ("Routes", self.routes),
                              ("Products", self.products), ("Populations", self.populations),
                              ("Applications", self.applications), ("Pathways the proposal names", self.pathways)):
            shown = [v for v in values if v]
            if shown:
                lines.append(f"{label}: {', '.join(shown)}")
        if self.question:
            lines.append(f"Question of interest: {self.question}")
        return "\n".join(lines)


def _value(record: Any) -> Any:
    return getattr(record, "value", None) if record is not None else None


def _texts(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, list | tuple):
        return tuple(str(v) for v in value if v not in (None, ""))
    return (str(value),)


def project_facts(brief: Any, drug: str) -> ProjectFacts:
    """The brief's facts the search needs, or just the drug's name when there is no brief."""
    if brief is None:
        return ProjectFacts(drug=drug)
    fields = brief.fields
    rows = lambda group, name: tuple(dict.fromkeys(
        v for row in brief.groups.get(group, ()) for v in _texts(_value(row.get(name)))))
    return ProjectFacts(
        drug=drug or str(_value(fields.get("drug.name")) or ""),
        names=tuple(dict.fromkeys(_texts(_value(fields.get("drug.code"))) + _texts(_value(fields.get("drug.synonyms")))[:6])),
        modality=str(_value(fields.get("drug.modality")) or ""), bcs=str(_value(fields.get("drug.bcs_class")) or ""),
        routes=rows("scenarios", "route"), products=rows("products", "name"), populations=rows("scenarios", "population"),
        applications=_texts(_value(fields.get("qoi.applications"))), pathways=_texts(_value(fields.get("scope.pathways"))),
        question=str(_value(fields.get("qoi.text")) or "")[:300])


@dataclass
class InputStatus:
    status: str
    known: list[str] = field(default_factory=list)


def _family(requirement: RequirementItem) -> str:
    return requirement.target.split("{", 1)[0].rstrip(".")


def statuses(requirements: list[RequirementItem], evidence: list[EvidenceItem]) -> dict[str, InputStatus]:
    """Each requirement's status from the values already in the register (rejected ones do not count)."""
    out: dict[str, InputStatus] = {}
    live = [e for e in evidence if e.state is not EvidenceState.REJECTED]
    for r in requirements:
        base = _family(r)
        mine = [e for e in live if e.req_id == r.req_id or e.target == base or e.target.startswith(base + ".")]
        known = [f"{e.target} = {e.value}{(' ' + e.unit) if e.unit else ''} ({e.source_type.value.lower()}, grade {e.confidence})"
                 for e in mine][:4]
        numbers = [float(e.value_pksim) for e in mine if isinstance(e.value_pksim, int | float) and e.value_pksim > 0]
        measured = [e for e in mine if e.source_type not in (SourceType.PREDICTED, SourceType.ASSUMPTION)
                    and e.confidence in ("A", "B")]
        if not mine:
            status = "missing"
        elif numbers and max(numbers) / min(numbers) > 2.0:
            status = "conflict"
        elif all(e.provider == "CLIENT" for e in mine) and r.cross_check:
            status = "client"
        elif not measured:
            status = "weak"
        else:
            status = "covered"
        out[r.req_id] = InputStatus(status=status, known=known)
    return out


def ordered(requirements: list[RequirementItem], status: dict[str, InputStatus]) -> list[RequirementItem]:
    """The inputs in the order to work on them: missing first (required before optional), covered last."""
    weight = {"REQUIRED": 0, "CONDITIONAL": 1, "OPTIONAL": 2}
    return sorted(requirements, key=lambda r: (STATUS_ORDER.index(status[r.req_id].status) if r.req_id in status else 0,
                                               weight.get(r.criticality, 3), r.req_id))


def task(facts: ProjectFacts, requirements: list[RequirementItem], status: dict[str, InputStatus]) -> str:
    """The opening message: the project, what to find in which order, and the rule that every input ends with a value
    or a "not found"."""
    counts = {s: sum(1 for r in requirements if status.get(r.req_id, InputStatus("missing")).status == s) for s in STATUS_ORDER}
    shown = ", ".join(f"{n} {s}" for s, n in counts.items() if n)
    return (f"{facts.text()}\n\n"
            f"Find values for the {len(requirements)} inputs list_requirements gives ({shown}), in the order it lists them: "
            "the missing ones first. Look for values that fit this project: human data, the routes and dosage forms above, "
            "the pathways that matter. Every input must end with at least one proposed value or a mark_not_found that "
            "says what you searched; do not stop while one is left. "
            f"{REGULATORY.replace('<drug>', facts.drug)} Start with list_requirements.")


def follow_up(requirements: list[RequirementItem]) -> str:
    """The second pass, on what the first left without a value or a "not found"."""
    listed = "; ".join(f"{r.req_id} ({r.label})" for r in requirements)
    return (f"These inputs still have neither a proposed value nor a mark_not_found: {listed}. For each, search with the "
            "hints list_requirements gives (other names of the drug, regulatory reviews, the label), then propose a value "
            "or call mark_not_found with what you searched.")
