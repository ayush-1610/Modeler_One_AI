"""P0/P1 answers of `brief_api`: project start, documents, the brief page, an extraction start, an agent run."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from modeler_api.views.common import AgentsStatus, DocumentView, ImpactView, RunSummary, VersionView, View


class ExtractionStart(View):
    started: bool
    agents: bool
    problem: str | None


class ClientFileStarted(View):
    """A client file given at project start: read into Inputs at once (a filled template), triaged, or refused with the
    reason."""

    file: str
    id: str | None
    template: bool
    problem: str | None


class ProjectStarted(View):
    project_id: str
    name: str
    documents: list[DocumentView]
    client_files: list[ClientFileStarted]
    brief_version: int
    extraction: ExtractionStart | None


class Documents(View):
    documents: list[DocumentView]


class ContributionView(View):
    """One thing the project took from a document (`library.Contribution`)."""

    kind: Literal["value", "dataset", "brief"]
    target: str
    value: str
    state: str
    page: int | None
    step: Literal["start", "inputs"]


class RelatesToView(View):
    """What a document relates to (`documents.RelatesTo`): a step and, optionally, a task within it."""

    step: Literal["start", "inputs", "review", "run"]
    task: str


class WithdrawalView(View):
    """Who withdrew a document, when and why (`documents.Withdrawal`)."""

    by: str
    at: str
    reason: str


class RetrievalView(View):
    """Where an agent took a document from, and what of it is held (`documents.Retrieval`; open-access full text only)."""

    source: str
    held: Literal["full_text", "abstract", "page"]
    url: str
    doi: str
    pmid: str
    pmcid: str
    by: str
    at: str


class LibraryRowView(View):
    """One document of the project library (`library.LibraryRow`), with what it contributed."""

    sha256: str
    name: str
    role: str
    format: str
    n_pages: int
    size_bytes: int
    added_at: str
    added_by: str
    source: Literal["person", "agent", "system"]
    versions: int
    contributions: list[ContributionView]
    relates_to: RelatesToView | None
    withdrawn: WithdrawalView | None
    retrieved: RetrievalView | None


class LibraryPage(View):
    documents: list[LibraryRowView]


class LibraryEntryView(View):
    """A document's entry in the library after a change: what it relates to, and its withdrawal if withdrawn."""

    sha256: str
    relates_to: RelatesToView | None
    withdrawn: WithdrawalView | None
    retrieved: RetrievalView | None


class FigureView(View):
    """An image placed on a PDF page (`modeler_intake.documents.PdfFigure`): its box as fractions of the page as shown."""

    page: int
    name: str
    box: list[float]          # left, top, right, bottom
    width: int
    height: int


class DocumentFigures(View):
    sha256: str
    figures: list[FigureView]


class DocumentPage(View):
    sha256: str
    name: str
    page: int
    n_pages: int
    text: str


class BriefIssue(View):
    code: str
    path: str
    message: str


class BriefSummary(View):
    by_status: dict[str, int]
    groups: dict[str, int]
    open_questions: int


class CatalogField(View):
    id: str
    section: str
    label: str
    kind: str
    required: bool
    options: list[str]
    option_labels: dict[str, str]
    unit: str | None
    help: str


class CatalogGroup(View):
    id: str
    section: str
    label: str
    required: bool
    fields: list[CatalogField]


class BriefCatalog(View):
    """The brief's schema as the web form renders it (`modeler_project.brief.catalog`)."""

    schema_: str = Field(alias="schema")
    sections: dict[str, str]
    short_brief: list[str]                       # the Start screen's fields; the rest are proposal notes
    short_group_fields: dict[str, list[str]]
    fields: list[CatalogField]
    groups: list[CatalogGroup]


class ScopeGateView(View):
    """One scope question of Start (D-28, `feasibility.ScopeGate`)."""

    gate: Literal["modality", "pbpk_model", "site_of_action", "formulation_types", "routes"]
    label: str
    path: str
    state: Literal["supported", "limited", "not_supported", "not_set"]
    values: list[str]
    message: str
    supported: str


class RiskView(View):
    allowed: list[str] | None      # the tiers ICH M15 §2.1.5 admits for the two ratings; None until both are rated
    problems: list[str]
    admitted: dict[str, list[str]]  # "influence/consequence" -> the tiers admitted, for the picker
    criteria: dict[str, str]        # tier -> what its verdicts ask ("AUC within 1.5-fold and …, in 80 % of studies")
    target_max: dict[str, float]    # tier -> the loosest internal target |PE| % it admits (MS-01 §8)
    ruleset: str                    # the acceptance ruleset the criteria come from, with its status


class StartIssueView(View):
    """One thing Start still needs, on the brief field it belongs to (`steps.start_issues`)."""

    path: str
    message: str


class ApplicationView(View):
    """An application code with its plain name and the data items it adds (the requirement templates)."""

    option: str
    code: str
    name: str
    adds: list[str]


class RequestLineView(View):
    """One thing the project asks the client to send (`requirements.client_request`, page review 1 decision 2b)."""

    req_id: str
    what: str
    why: str
    required: bool
    product: str | None
    sheet: str


class StartBlock(View):
    """What Start still needs (`steps.start_issues`), and the parts the screen draws from."""

    problems: list[str]
    issues: list[StartIssueView]
    gates: list[ScopeGateView]
    risk: RiskView
    applications: list[ApplicationView]
    pathway_suggestions: list[str]
    pathways_not_named: list[str]   # the published OSP model's enzymes / transporters the proposal does not name
    client_request: list[RequestLineView]   # what only the client can send, from the data plan


class BriefPage(View):
    artifact: VersionView
    brief: dict[str, Any]
    issues: list[BriefIssue]
    blocking: int
    summary: BriefSummary
    catalog: BriefCatalog
    agents: AgentsStatus
    extraction_running: bool
    runs: list[RunSummary]
    start: StartBlock


class BriefImpact(View):
    """A previewed brief edit: what it would change, nothing saved."""

    impact: ImpactView


class AgentRunDetail(View):
    run: dict[str, Any]
    steps: list[dict[str, Any]]
