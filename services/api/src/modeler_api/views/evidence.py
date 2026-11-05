"""P2 answers of `evidence_api`: the literature evidence page, a research start, a correction.

A stored item or dataset is answered with its owner's content model (`modeler_project.evidence.EvidenceItem`,
`modeler_project.datasets.ObservedDataset`; phase 9e).
"""

from __future__ import annotations

from pydantic import Field

from modeler_api.views.common import AgentsStatus, DataPlanStatus, RunSummary, StoredContent, VersionView, View
from modeler_project.evidence import EvidenceItem


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
    evidence: list[EvidenceItem]           # each item with its review flags
    datasets: list[StoredContent]          # external values withheld until the MAP is signed (D-15): a redacted row
                                           # has no values and carries `blinded`, so it is not an ObservedDataset
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


class LiteratureRun(View):
    """Where the literature agent stands (plan 2026-11-05 §3.3): searching or not, its latest run, the turns it has
    taken of its budget, and the values it has proposed so far (they flow into the inputs when it finishes)."""

    running: bool
    run: RunSummary | None
    turns: int
    max_turns: int | None
    proposed: int


class PublishedModelTaken(View):
    """What taking a published OSP model as a source proposed: its values and datasets, those it had already given,
    and what it left out, with why."""

    template_id: str
    model: str
    values: int
    datasets: int
    already: int
    skipped: list[str]


class EvidenceChoice(EvidencePage):
    """A value kept for its parameter: the ids of the other values it rejected, and the page."""

    rejected: list[str]


class EvidenceCorrection(EvidencePage):
    """A corrected copy of a value, and the page."""

    corrected: EvidenceItem
