"""P2 answers of `evidence_api`: the literature evidence page, a research start, a stored item or dataset."""

from __future__ import annotations

from pydantic import Field

from modeler_api.views.common import AgentsStatus, DataPlanStatus, RunSummary, StoredContent, VersionView, View


class Blinded(View):
    blinded: list[str]


class CoverageRow(View):
    """One data-plan item and the evidence that covers it (`evidence_register.Coverage`)."""

    req_id: str
    label: str
    target: str
    criticality: str
    applies: str
    provider: str
    status: str
    accepted: list[str]
    proposed: list[str]


class EvidencePage(View):
    data_plan: DataPlanStatus
    evidence: list[StoredContent]          # each item with its review flags
    datasets: list[StoredContent]          # external values withheld until the MAP is signed (D-15)
    blinding: Blinded
    coverage: list[CoverageRow]
    blocking: list[str]
    access_requests: list[StoredContent]
    register_: VersionView | None = Field(alias="register")  # "register" would shadow the class method
    agents: AgentsStatus
    running: bool
    runs: list[RunSummary]


class ResearchStart(View):
    started: bool
    provider: str
    model: str


class EvidenceChoice(EvidencePage):
    """A value kept for its parameter: the ids of the other values it rejected, and the page."""

    rejected: list[str]


class EvidenceCorrection(EvidencePage):
    """A corrected copy of a value, and the page."""

    corrected: StoredContent
