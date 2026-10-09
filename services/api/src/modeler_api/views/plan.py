"""P5 answers of `plan_api`: the model plan page (the plan, the live validator, the diff, Overall Data, D1 / D2, the MAP).

The plan itself is the owner's content model (`modeler_project.plan.ModelPlan`, phase 9: stored content is described
by its owner's model); the rest is computed for the canvas.
"""

from __future__ import annotations

from typing import Literal

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

