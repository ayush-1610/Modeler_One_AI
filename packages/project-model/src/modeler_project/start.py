"""Step 1 · Start (docs/plans/2026-10-19-p0-p5-redesign.md §3.1): the drug, the short brief and the data checklist.

Start replaces P0 and P1. The brief keeps one record per field (`modeler_project.brief`); Start shows the few that shape
the model and keeps everything else the proposal says as notes, never required. What Start still needs is computed
here, for the page and for the step bar, from what is filled; nothing is approved (D-27).

- **Scope gates (D-28).** Modality, model type, site of action and formulation type are asked at Start, with the routes
  of the scenarios, and what the builder cannot model is refused there, "not supported yet", before any data work. The
  builder makes full (whole-body) PBPK models of systemic small molecules with dissolved, Weibull and particle
  formulations, given IV or orally (`feasibility.BUILDER_ROUTES`). Support is added one product type at a time, with
  the SME.
- **Model risk (ICH M15 §2.1.5).** The person rates model influence and decision consequence; the ratings bound the risk
  (`brief_ops.allowed_risks`), and the person sets it with the reasons.
- **The data checklist** is the requirement matrix, re-derived on every brief change (`brief_ops.save_brief`), with what
  the client is expected to send ticked off from the reconciliation of their files. Feasibility warnings sit beside the
  brief field they concern.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from modeler_project.artifacts import ArtifactKind, ArtifactStatus
from modeler_project.brief import FIELDS, ProjectBrief, definition_of
from modeler_project.brief_ops import allowed_risks, risk_problem
from modeler_project.feasibility import BUILDER_ROUTES, check
from modeler_project.requirements import RequirementMatrix
from modeler_project.workspace import Workspace

MAIN = "main"

# The short brief, block by block in the page's order (map rows p1-pubchem, p1-mw, p1-qoi, p1-cou, p1-apps, p1-m15,
# p1-risk, p1-modality, p1-bcs, p1-scope). Of each scenario only the route and food state are asked (p1-scen-route).
IDENTITY = ("drug.name", "drug.pubchem_cid", "drug.smiles", "drug.inchikey", "drug.mw_free_base")
QUESTION = ("qoi.text", "qoi.context_of_use", "qoi.applications")
RISK = ("m15.influence", "m15.influence_rating", "m15.consequence", "m15.consequence_rating", "acceptance.tier")
GATES = ("drug.modality", "scope.model_structure", "scope.site_of_action", "scope.formulation_types")
SCOPE = ("drug.bcs_class", "scope.pathways", "scope.pathways_stated", "scope.nonlinearity", "scope.ehc")
SCENARIO_FIELDS = ("route", "food_state")
# Everything else the proposal says (p1-title, p1-type, p1-admin, p1-drugother, p1-prodother, p1-scen-dose,
# p1-scope-other), kept for the report and never required. Products move to Inputs and populations to Review & sign
# when those steps are rebuilt (R3, R4); until then they are kept with the notes.
NOTES = tuple(f.id for f in FIELDS if f.id not in {*IDENTITY, *QUESTION, *RISK, *GATES, *SCOPE})
NOTE_GROUPS = ("products", "populations", "data_plan")

OPTION_LABELS: dict[str, dict[str, str]] = {
    "drug.modality": {"small_molecule": "Small molecule", "large_molecule": "Large molecule (biologic)", "other": "Other"},
    "scope.model_structure": {"full_pbpk": "Full (whole-body) PBPK", "minimal_pbpk": "Minimal PBPK", "other": "Other"},
    "scope.site_of_action": {"systemic": "Systemic", "local": "Local (gut lumen, lung, skin, eye…)"},
    "scope.formulation_types": {
        "iv_solution": "IV solution (infusion or bolus)", "oral_solution": "Oral solution",
        "oral_suspension": "Oral suspension", "ir_solid": "Immediate-release tablet or capsule",
        "er_solid": "Extended-release tablet or capsule", "dr_solid": "Delayed-release (enteric-coated)",
        "other": "Other (inhaled, dermal, depot injection, implant…)",
    },
    "scope.pathways": {
        "hepatic_metabolism": "Hepatic metabolism", "gut_wall_metabolism": "Gut-wall metabolism",
        "renal_filtration": "Renal filtration", "renal_secretion": "Renal tubular secretion",
        "biliary_excretion": "Biliary excretion", "transporter_mediated": "Transporter uptake or efflux", "other": "Other",
    },
}

# What the builder makes today (D-28), as the feasibility check knows it: updated with the builder, never by guesswork.
# Solutions are dissolved, a suspension dissolves as particles, IR and ER solids release by Weibull or particle
# dissolution; a delayed (enteric) release needs a harvested lag / pH-dependent model first.
SUPPORTED: dict[str, frozenset[str]] = {
    "drug.modality": frozenset({"small_molecule"}),
    "scope.model_structure": frozenset({"full_pbpk"}),
    "scope.site_of_action": frozenset({"systemic"}),
    "scope.formulation_types": frozenset({"iv_solution", "oral_solution", "oral_suspension", "ir_solid", "er_solid"}),
}
_WHY = {
    "drug.modality": "the builder makes PBPK models of small molecules",
    "scope.model_structure": "the builder makes full (whole-body) PBPK models",
    "scope.site_of_action": "the builder models systemic exposure",
    "scope.formulation_types": "the builder models dissolved, particle and Weibull formulations",
}
# The brief field each feasibility line concerns (`FeasibilityLine.needed_because`). The modality and the routes are
# scope gates, so their lines are not repeated beside them.
_CONCERNS = {
    "products": "products", "scope.pathways_stated": "scope.pathways", "scope.parent_metabolite": "scope.parent_metabolite",
    "scope.pd": "scope.pd", "populations": "populations", "qoi.applications": "qoi.applications",
    "food effect / fed scenario": "scenarios",
}

GateState = Literal["supported", "not_supported", "unset"]


class Gate(BaseModel):
    """One scope gate: a brief field (or the scenarios' routes) and whether the builder makes what it says."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    state: GateState
    message: str = ""


class Risk(BaseModel):
    """The ICH M15 model risk as Start asks for it: the person's two ratings, what they admit, and the risk set."""

    model_config = ConfigDict(frozen=True)

    influence: str | None
    consequence: str | None
    allowed: tuple[str, ...]          # () until both are rated
    suggested: str | None             # the one risk the ratings admit when they agree
    tier: str | None
    reasons: str
    problem: str | None               # the risk set is outside what the ratings admit


class ChecklistItem(BaseModel):
    """One applicable item of the data checklist (PK-Sim columns are not shown at Start, map row p1-pksim-cols)."""

    model_config = ConfigDict(frozen=True)

    req_id: str
    label: str
    group: str
    criticality: str
    applies: str                      # yes | undetermined
    condition: str                    # what decides an undetermined item
    provider: str
    provider_source: str              # override | data_plan[i] | template default
    provider_statement: str
    cross_check: bool
    needed_for: tuple[str, ...]
    status: str                       # a client item: what arrived (DELIVERED, PARTIAL, MISSING, …); else the item's
    delivered: tuple[str, ...]
    detail: str


class Checklist(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int | None
    stale: bool                       # derived from an older brief (a project started before every edit re-derived it)
    templates: tuple[str, ...]
    items: tuple[ChecklistItem, ...]
    expected_from_client: int
    delivered_by_client: int


def _values(brief: ProjectBrief, path: str) -> list[str]:
    value = brief.value(path)
    if value in (None, "", []):
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def scenario_count(brief: ProjectBrief) -> int:
    return len(brief.groups.get("scenarios", ()))


def gates(brief: ProjectBrief) -> list[Gate]:
    """The scope gates of D-28, each supported, not supported yet, or not set."""
    out = []
    for path in GATES:
        label = definition_of(path).label
        values = _values(brief, path)
        refused = [v for v in values if v not in SUPPORTED[path]]
        if not values:
            out.append(Gate(id=path, label=label, state="unset", message=f"{label}: not set yet"))
        elif refused:
            names = ", ".join(OPTION_LABELS[path].get(v, v) for v in refused)
            out.append(Gate(id=path, label=label, state="not_supported", message=f"Not supported yet: {names} ({_WHY[path]})"))
        else:
            out.append(Gate(id=path, label=label, state="supported"))
    routes = [r for i in range(scenario_count(brief)) if (r := brief.value(f"scenarios[{i}].route"))]
    refused = sorted({r for r in routes if r not in BUILDER_ROUTES})
    if not routes:
        out.append(Gate(id="scenarios.route", label="Routes", state="unset",
                        message="Routes: add the route of each scenario to simulate"))
    elif refused:
        out.append(Gate(id="scenarios.route", label="Routes", state="not_supported",
                        message=f"Not supported yet: {', '.join(r.replace('_', ' ') for r in refused)} administration "
                                "(the builder makes IV and oral administrations)"))
    else:
        out.append(Gate(id="scenarios.route", label="Routes", state="supported"))
    return out


def risk(brief: ProjectBrief) -> Risk:
    allowed = allowed_risks(brief)
    tier = brief.value("acceptance.tier")
    return Risk(influence=brief.value("m15.influence_rating"), consequence=brief.value("m15.consequence_rating"),
                allowed=allowed, suggested=allowed[0] if len(allowed) == 1 else None, tier=tier,
                reasons=brief.get("acceptance.tier").note if tier else "",
                problem=risk_problem(brief, tier) if tier else None)


def missing(brief: ProjectBrief) -> list[str]:
    """What Start still needs, in the page's order; empty when Start is done. Open questions are shown, not counted:
    a question on a field that Start needs is already counted as that field."""
    out = [f"{definition_of(p).label}: not set yet" for p in ("drug.name", *QUESTION) if not _values(brief, p)]
    if not (brief.value("m15.influence_rating") and brief.value("m15.consequence_rating")):
        out.append("Model influence and decision consequence: not rated yet")
    model_risk = risk(brief)
    if model_risk.tier is None:
        out.append("Model risk: not set yet")
    elif model_risk.problem:
        out.append(f"Model risk: {model_risk.problem}")
    out += [g.message for g in gates(brief) if g.state != "supported"]
    for i in range(scenario_count(brief)):
        if brief.value(f"scenarios[{i}].route") == "oral" and not brief.value(f"scenarios[{i}].food_state"):
            out.append(f"Scenario {i + 1}: food state not set (oral)")
    return out


def warnings(brief: ProjectBrief) -> dict[str, list[str]]:
    """Feasibility warnings by the brief field they concern (map row p1-feasibility): what the builder supports only in
    part, needs harvested first, or does not make. Lines that say "supported" or "undetermined" are not shown."""
    out: dict[str, list[str]] = {}
    for line in check(brief).lines:
        where = _CONCERNS.get(line.needed_because)
        if where is None or line.status in ("SUPPORTED", "UNDETERMINED"):
            continue
        status = line.status.lower().replace("_", " ")
        out.setdefault(where, []).append(f"{line.feature}: {status}" + (f" ({line.route})" if line.route else ""))
    return out


def checklist(ws: Workspace) -> Checklist:
    """The applicable items of the latest requirement matrix, with what the client's files delivered for each."""
    from modeler_project.client_data import reconcile

    version = ws.latest(ArtifactKind.REQUIREMENTS, MAIN)
    if version is None:
        return Checklist(version=None, stale=False, templates=(), items=(), expected_from_client=0, delivered_by_client=0)
    matrix = RequirementMatrix.from_content(version.content)
    arrived = {row.req_id: row for row in reconcile(ws, matrix).rows}
    items = []
    for item in matrix.items:
        if item.applies == "no":
            continue
        row = arrived.get(item.req_id)
        items.append(ChecklistItem(
            req_id=item.req_id, label=item.label, group=item.group, criticality=item.criticality, applies=item.applies,
            condition=item.condition_text, provider=item.provider, provider_source=item.provider_source,
            provider_statement=item.provider_statement, cross_check=item.cross_check, needed_for=item.needed_for,
            status=row.status if row else item.status, delivered=tuple(row.delivered) if row else (),
            detail=row.detail if row else ""))
    client = [i for i in items if i.provider == "CLIENT"]
    return Checklist(version=version.version, stale=ws.status(version) is ArtifactStatus.STALE, templates=matrix.templates,
                     items=tuple(items), expected_from_client=len(client),
                     delivered_by_client=sum(i.status == "DELIVERED" for i in client))
