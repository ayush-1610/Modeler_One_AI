"""P0/P1 answers of `brief_api`: project start, documents, the brief page, an extraction start, an agent run."""

from __future__ import annotations

from typing import Any

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
    fields: list[CatalogField]
    groups: list[CatalogGroup]


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


class BriefImpact(View):
    """A previewed brief edit: what it would change, nothing saved."""

    impact: ImpactView


class AgentRunDetail(View):
    run: dict[str, Any]
    steps: list[dict[str, Any]]
