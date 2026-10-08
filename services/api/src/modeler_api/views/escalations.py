"""Answers of the escalation routes (P6). They carry no envelope, as before (the owner's choice of 2026-10-08)."""

from __future__ import annotations

from modeler_api.views.common import View


class DecisionOption(View):
    action: str
    description: str
    required_signature: str


class DecisionOptions(View):
    options: list[DecisionOption]


class SignatureView(View):
    signature_id: str
    manifestation: str


class EscalationDecided(View):
    campaign_id: str
    stage: str
    action: str
    signature: SignatureView


class DeviationRecorded(View):
    campaign_id: str
    stage: str
    signature: SignatureView


class EscalationResolved(View):
    """A signed decision applied to a single-node campaign: the stage's new status (and the stages still to run)."""

    campaign_id: str
    stage: str
    action: str
    status: str
    remaining_stages: list[str] | None = None   # when the campaign continues
    note: str
    signature: SignatureView
