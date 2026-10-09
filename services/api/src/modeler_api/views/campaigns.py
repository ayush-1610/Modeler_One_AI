"""Answers about campaigns (phase 9d): the monitor and its review inbox (the orchestrator's records,
`modeler_storage.records`), the S7 package, a generated MAP, a campaign start and a signature.

A campaign start and a signature answer without the envelope, as they always have (the owner's choice of 2026-10-08,
shapes kept).
"""

from __future__ import annotations

from typing import Any

from modeler_api.views.common import View
from modeler_storage.records import CampaignRecord, EscalationRecord
from pbpk_domain.campaign.map import MapDocument


class Campaigns(View):
    campaigns: list[CampaignRecord]


class Escalations(View):
    escalations: list[EscalationRecord]


class ReportIssue(View):
    kind: str
    location: str
    detail: str


class CampaignPackage(View):
    """The S7 package: the reproduction verdict, whether it may be exported (D13), hashes and the downloadable artifacts.
    Server paths are never sent."""

    exportable: bool
    reproduction: dict[str, Any] | None     # {passes, compared, failures} (package_activities)
    data_bundle_sha256: str | None
    package_sha256: str | None
    files: int | None
    report_notes: list[str]
    report_issues: list[ReportIssue]
    artifacts: list[str]
    pksim_projects: list[str]
    project_notes: list[str]


class MapGenerated(View):
    question_id: str
    map: MapDocument


class CampaignStarted(View):
    campaign_id: str
    status: str
    status_url: str


class SignatureCreated(View):
    """A Part 11 signature, from the token's step-up (never a password)."""

    signature_id: str
    manifestation: str
    record_sha256: str
    auth_method: str
    signed_by: str
