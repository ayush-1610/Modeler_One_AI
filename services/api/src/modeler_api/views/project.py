"""Answers of `project_api`: the stale artifacts, the redesign's steps, artifacts and their history, impact, the audit trail, blinding (D-15)."""

from __future__ import annotations

from typing import Any

from modeler_api.views.common import ApprovalView, ChangeView, PhaseId, Ref, VersionView, View
from modeler_project.artifacts import ArtifactStatus
from modeler_project.formulation_way import FormulationLever
from modeler_project.steps import StepId, StepState


class StaleArtifact(View):
    ref: Ref
    reasons: list[str]


class StaleArtifacts(View):
    """What was made from inputs that have since changed, with why (shown on the History page)."""

    stale: list[StaleArtifact]


class FormulationWayView(View):
    """What gives a tablet study its formulation as the project stands (`modeler_project.formulation_way`): use a
    product's dissolution profile as its release (`products`: those whose profile can), add a product's dissolution data
    (`products`: those here), add a product (none is here), or choose the formulation a study used (several are in the
    model). `studies`: the tablet studies it is for; `ready`: the first product's profile can be used now (its product's
    dissolution data confirmed), else they are confirmed first."""

    way: FormulationLever
    products: list[str]
    studies: list[str]
    ready: bool


class StepRow(View):
    """One step of the redesigned flow (Start, Inputs, Review & sign, Run) and what it waits on; Inputs, while a tablet
    study has no formulation, with the lever that gives it one (the step bar and Review & sign name it: round 4)."""

    step: StepId
    label: str
    state: StepState
    reasons: list[str]
    formulation: FormulationWayView | None = None


class Steps(View):
    steps: list[StepRow]


class Artifacts(View):
    artifacts: list[VersionView]


class HistoryRow(View):
    """One version of an artifact, and the field changes from the previous one (blinded values left out)."""

    sha256: str
    created_by: str
    reason: str
    phase: PhaseId
    version: int
    status: ArtifactStatus
    created_at: str
    approvals: list[ApprovalView]
    changes: list[ChangeView]


class History(View):
    versions: list[HistoryRow]


class AuditEventView(View):
    seq: int
    occurred_at: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    before: Any
    after: Any
    reason: str | None
    row_hash: str


class AuditTrail(View):
    chain_verifies: bool
    first_broken_index: int | None
    events: list[AuditEventView]


class BlindingView(View):
    """`deps.blinding_view`: the project's setting (its own choice, or the default for its model risk) and its effect."""

    on: bool
    source: str
    reason: str
    by: str | None = None                 # a person's choice only
    at: str | None = None
    map_signed: bool
    blinded: list[str]
    external: list[str]
