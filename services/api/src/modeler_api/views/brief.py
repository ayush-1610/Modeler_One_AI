"""P0/P1 answers of `brief_api`: project start, documents, the brief page, an extraction start, an agent run."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from modeler_api.views.common import AgentsStatus, DocumentView, ImpactView, RunSummary, VersionView, View


class ExtractionStart(View):
    started: bool
    agents: bool
    problem: str | None


class ProjectStarted(View):
    project_id: str
    name: str
    documents: list[DocumentView]
    brief_version: int
    extraction: ExtractionStart | None


class Documents(View):
    documents: list[DocumentView]


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


class StartBlock(View):
    """What Start still needs (`steps.start_problems`), and the parts the screen draws from."""

    problems: list[str]
    gates: list[ScopeGateView]
    risk: RiskView
    pathway_suggestions: list[str]


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
