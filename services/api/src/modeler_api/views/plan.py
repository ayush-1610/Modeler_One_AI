"""P5 answers of `plan_api`: the model plan page (the plan, the live validator, the diff, Overall Data, D1 / D2, the MAP).

The plan itself is the owner's content model (`modeler_project.plan.ModelPlan`, phase 9: stored content is described
by its owner's model); the rest is computed for the canvas.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from modeler_api.views.common import AgentsStatus, Number, StoredContent, VersionView, View
from modeler_api.views.escalations import SignatureView
from modeler_project.plan import Deviation, FitChoice, ModelPlan, Role, StudyView, Violation


class DiffRow(View):
    """A departure from the MS-01 default (`modeler_project.plan.diff`); `proposal` only on a pending A5 proposal."""

    kind: Literal["role", "fit", "structure"]
    target: str
    from_: str = Field(alias="from")
    to: str | bool | list[str] | None      # a role, a fit in words, or a structure value
    by: str
    reason: str
    status: Literal["APPLIED", "PENDING"]
    proposal: str | None = None


class OverallStudy(StudyView):
    """A study of Overall Data: what the plan knows about it, and where it is placed now."""

    role: Role
    userLocked: bool
    reason: str
    rationale: str


class ParameterRow(View):
    id: str
    value: Number | str | None
    unit: str | None
    status: str


class OverallData(View):
    studies: list[OverallStudy]
    parameters: list[ParameterRow]


class ParamNode(View):
    """A CPF parameter on D1 / D2, with its fit choice and the stages that may fit it; D2 nodes carry no source."""

    id: str
    value: Number | str | None
    unit: str | None
    status: str
    source: str | None = None
    fit: FitChoice | None
    candidate_at: list[str]


class Pathway(View):
    process: str
    kind: Literal["elimination", "transport", "other"]
    parameters: list[ParamNode]


class Disposition(View):
    """D1: binding and distribution, then each elimination / transport pathway."""

    binding: list[ParamNode]
    distribution: list[ParamNode]
    pathways: list[Pathway]
    informed_by: list[str]


class LaneParameter(View):
    id: str
    value: Number | str | None
    unit: str | None


class LaneStudy(View):
    study_id: str
    food_state: str
    role: Role


class Lane(View):
    name: str
    release: Number | str | None          # "dissolved (solution)", or the formulation's CPF type ("?" if unset)
    parameters: list[LaneParameter]
    studies: list[LaneStudy]


class DissolutionProfile(View):
    id: str
    label: str
    release_model: str | None


class Absorption(View):
    """D2: absorption parameters, one lane per formulation with its studies, and the dissolution profiles."""

    absorption: list[ParamNode]
    lanes: list[Lane]
    dissolution: list[DissolutionProfile]
    food_effect_in_question: bool
    measured_fed_solubility: bool


class MapVersion(VersionView):
    """The latest MAP version, its hash and the campaign inputs its signature staged."""

    campaign: StoredContent | None         # the staged inputs a campaign starts from (map_artifact.MapArtifact.campaign)
    map_sha256: str
    map_version: int | None
    supersedes: str | None


class PlanPage(View):
    plan: ModelPlan
    artifact: VersionView
    violations: list[Violation]
    blocking: int
    diff: list[DiffRow]
    overall_data: OverallData
    d1: Disposition
    d2: Absorption
    map: MapVersion | None
    signed: bool                           # D-14: once a MAP is signed, a change is a deviation
    deviations: list[Deviation]
    deviations_pending: int
    agents: AgentsStatus
    running: bool


class PlacementPreview(View):
    """A move's dry run: what the validator and the diff would say; nothing is saved."""

    violations: list[Violation]
    diff: list[DiffRow]
    deviation: bool


class PlanSigned(PlanPage):
    """The page after `plan:sign`, and the signature the MAP carries."""

    signature: SignatureView


class DraftStart(View):
    status: Literal["RUNNING"]



# --- Step 3 · Review & sign (redesign §3.3): the review table and credibility -------------------------------------


class ReviewSource(View):
    """Where the kept value comes from (the evidence item's source, with its type)."""

    type: str
    title: str
    authors: str | None = None
    year: int | None = None
    doi: str | None = None
    page: int | None = None
    locator: str | None = None


class ReviewRow(View):
    """One model input as the review table shows it (`modeler_project.review.review_rows`)."""

    id: str
    tab: str
    state: Literal["kept", "conflict", "held", "missing"]
    value: Number | str | None
    unit: str | None
    status: str | None
    message: str | None
    evidence_id: str | None                # the kept source, which "Exclude" sets aside with a reason
    source: ReviewSource | None
    quote: str
    grade: str | None
    flags: list[str]
    supplied_by: Literal["agent", "client file", "person", "system"] | None
    changed_by_person: bool
    agreeing: int                          # other sources within 10 % of the kept value (D-32)
    alternatives: int
    confidence: Literal["low", "medium", "high"] | None   # display only: grade, flags and agreement


class ReviewCounts(View):
    all: int
    flagged: int
    by_person: int
    from_agent: int
    open: int


class ReviewStudy(View):
    study_id: str
    role: Role | None
    role_by: str | None                    # "default", a person's id, or an agent run
    purpose: str | None
    origin: str | None
    blinded: bool
    excluded: str | None                   # why a person left it out
    demographics: str


class StageBudget(View):
    stage: str
    budget_seconds: int
    fraction: Number
    max_rounds: int


class ReviewRisk(View):
    """The ICH M15 model risk the MAP will carry, and what Start says of it."""

    tier: Literal["low", "medium", "high"] | None
    set_here: bool                         # changed on this page (the plan's own, with its reason)
    reason: str
    influence: str | None                  # the ratings and justification from Start
    consequence: str | None
    justification: str | None
    influence_text: str | None = None      # why each rating is what it is, as a person wrote or confirmed it at Start
    consequence_text: str | None = None


class BoundsProposalView(View):
    """The bounds MS-01 §2.2 proposes for a parameter (`estimation.proposed_bounds`, D-34), or why none."""

    lower: Number | None
    upper: Number | None
    scale: Literal["linear", "log"] | None
    basis: str
    note: str
    fixed: bool                            # MS-01 keeps it fixed (a measured fu)
    from_ms01: bool                        # False: the redesign's 0.1–10×, MS-01 giving no default


class EstimatedFit(View):
    stages: list[str]
    lower: Number
    upper: Number
    scale: Literal["linear", "log"]
    by: str
    reason: str


class DefaultFit(View):
    """The MS-01 §2.2 default the diagnosis may fit a candidate within, at its stages (D-37, `plan.default_fits`)."""

    stages: list[str]
    lower: Number
    upper: Number
    scale: Literal["linear", "log"]


class HeldFixed(View):
    """An MS-01 candidate a person keeps fixed (D-37)."""

    by: str
    reason: str


class BoundsFinding(View):
    severity: Literal["error", "warning"]
    rule: str
    message: str


class EstimationRow(View):
    """One numeric parameter of the estimation plan (`review.estimation_rows`): fixed (no fit) or estimated."""

    id: str
    value: Number
    unit: str | None
    status: str
    source: str | None
    grade: str | None
    estimated: EstimatedFit | None
    candidate_at: list[str]                # the stages MS-01 lets it be fitted at
    diagnosis_may_fit: DefaultFit | None   # no person's fit and not held: MS-01's default bounds it (D-37)
    held_fixed: HeldFixed | None           # a person keeps this candidate fixed (D-37)
    proposal: BoundsProposalView
    findings: list[BoundsFinding]


class RuleVersion(View):
    version: str
    status: str
    source: str


class ValidationStudy(View):
    study_id: str
    blinded: bool
    role: Role | None


class ValidationStage(View):
    """What S4 or S5 judges under the MAP this plan generates, and what happens when it fails (MS-01 §4, §6.6)."""

    stage: Literal["S4", "S5"]
    judges: str
    on_failure: str
    studies: list[ValidationStudy]
    skip_reason: str | None
    notes: list[str]


class Criterion(View):
    quantity: str
    max_fold: Number | None
    guest_delta: Number | None
    citation: str | None


class AcceptanceView(View):
    """The limits of the chosen tier as the MAP records them (UNVERIFIED ruleset), and the internal target (MS-01 §8)."""

    tier: Literal["low", "medium", "high"] | None
    ruleset: str
    status: str
    description: str | None
    pk_parameters: list[Criterion]
    ddi_ratios: list[Criterion]
    min_fraction_within: Number | None
    internal_target_pe: Number | None
    target_set_here: bool
    loosest_target_pe: Number | None       # the largest target no looser than the tier
    target_applied: bool                   # the verdicts apply it to the internal groups (since R4d)


class ApplicationInput(View):
    """One input an analysis template declares (`analysis_templates.TemplateInput`) and the value the plan holds."""

    id: str
    label: str
    kind: str
    required: bool
    default: Any = None
    unit: str | None
    note: str
    never_default: bool
    value: Any = None


class ApplicationLimits(View):
    id: str
    lower: Number
    upper: Number
    ci_level: Number
    verified: bool
    source: str


class PinnedApplication(View):
    template: str
    version: str
    status: str                            # the template's own (DRAFT until the SME approves it)
    inputs: list[ApplicationInput]
    problems: list[str]                    # what the validator still says of it (signing waits on these)
    formulations: list[str]                # the CPF's formulations, the choices of a formulation input
    limits: list[ApplicationLimits]


class ApplicationsView(View):
    pinned: list[PinnedApplication]
    addable: list[str]                     # templates the brief's applications offer, not yet in the plan


class ApplicationSupportRow(View):
    code: str
    label: str
    status: Literal["runs", "campaign", "partial", "not_supported"]
    reason: str


class ApplicationSupport(View):
    rows: list[ApplicationSupportRow]
    scenarios: list[dict[str, Any]]        # the brief's prediction scenarios, recorded; S6 does not simulate them yet


class ReviewPage(View):
    rows: list[ReviewRow]
    counts: ReviewCounts
    studies: list[ReviewStudy]
    risk: ReviewRisk
    budget_seconds: int
    stages: list[StageBudget]
    limitations: list[str]
    estimation: list[EstimationRow]
    bounds_rule: RuleVersion
    validation: list[ValidationStage]
    acceptance: AcceptanceView
    applications: ApplicationsView
    application_support: ApplicationSupport
