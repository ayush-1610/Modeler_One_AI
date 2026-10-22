"""Answers of `project_api`: the stale artifacts, the redesign's steps, artifacts and their history, impact, the audit trail, blinding (D-15)."""

from __future__ import annotations

from typing import Any

from modeler_api.views.common import ApprovalView, ChangeView, PhaseId, Ref, VersionView, View
from modeler_project.artifacts import ArtifactStatus
from modeler_project.steps import StepId, StepState


class StaleArtifact(View):
    ref: Ref
    reasons: list[str]


class StaleArtifacts(View):
    """What was made from inputs that have since changed, with why (shown on the History page)."""

    stale: list[StaleArtifact]


class StepRow(View):
    """One step of the redesigned flow (Start, Inputs, Review & sign, Run) and what it waits on."""

    step: StepId
    label: str
    state: StepState
    reasons: list[str]


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
