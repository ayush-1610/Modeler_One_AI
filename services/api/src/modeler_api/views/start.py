"""Step 1 · Start answers of `brief_api` (redesign §3.1): the short brief, the scope gates, the model risk, the proposal
notes and the data checklist, from `modeler_project.start`."""

from __future__ import annotations

from typing import Any

from modeler_api.views.common import AgentsStatus, DocumentView, RunSummary, VersionView, View


class CitationView(View):
    doc_sha256: str
    page: int
    quote: str
    locator: str
    source: str


class FieldRecordView(View):
    """One brief field's record (`modeler_project.brief.FieldRecord`)."""

    value: Any
    unit: str | None
    status: str
    citations: list[CitationView]
    confidence: str | None
    note: str
    by: str | None
    at: str | None


class OptionView(View):
    value: str
    label: str
    supported: bool | None       # a scope gate's option: does the builder make it (None: not a gate)


class StartField(View):
    path: str
    label: str
    kind: str
    required: bool
    options: list[OptionView]
    unit: str | None
    help: str
    human_only: bool             # set by a person only (the ICH M15 ratings and the model risk)
    record: FieldRecordView
    warnings: list[str]          # feasibility warnings on what the field says


class StartScenario(View):
    index: int
    route: StartField
    food_state: StartField
    notes: str                   # what else the proposal says of the scenario (population, dose, product …)


class NoteGroup(View):
    """A list of things the proposal names (products, populations, data-plan statements, scenario details)."""

    id: str
    label: str
    items: list[list[StartField]]
    blank: list[StartField]      # the fields of the next item, all missing: what "Add" fills
    warnings: list[str]


class GateView(View):
    id: str
    label: str
    state: str                   # supported | not_supported | unset
    message: str


class RiskView(View):
    influence: str | None
    consequence: str | None
    allowed: list[str]
    suggested: str | None
    tier: str | None
    reasons: str
    problem: str | None


class QuestionView(View):
    id: str
    field: str
    question: str
    answer: str
    status: str
    raised_by: str


class ChecklistItemView(View):
    req_id: str
    label: str
    group: str
    criticality: str
    applies: str
    condition: str
    provider: str
    provider_source: str
    provider_statement: str
    cross_check: bool
    needed_for: list[str]
    status: str
    delivered: list[str]
    detail: str


class ChecklistView(View):
    version: int | None
    stale: bool                  # derived from an older brief (a project started before Start re-derived it)
    templates: list[str]
    items: list[ChecklistItemView]
    expected_from_client: int
    delivered_by_client: int


class ClientFileView(View):
    id: str
    file: str
    template: bool


class StartPage(View):
    project_id: str
    drug_name: str
    artifact: VersionView
    state: str                   # done | needs_you
    missing: list[str]
    identity: list[StartField]
    question: list[StartField]
    risk_fields: list[StartField]
    risk: RiskView
    gates: list[GateView]
    gate_fields: list[StartField]
    scope: list[StartField]
    scenarios: list[StartScenario]
    new_scenario: StartScenario  # the next scenario, all missing: what "Add a scenario" fills
    scenario_warnings: list[str]
    questions: list[QuestionView]
    notes: list[StartField]
    note_groups: list[NoteGroup]
    checklist: ChecklistView
    documents: list[DocumentView]
    client_files: list[ClientFileView]
    agents: AgentsStatus
    extraction_running: bool
    runs: list[RunSummary]


class ClientFileStarted(View):
    """A client file given at project start: read at once (a filled template), triaged, or refused with the reason."""

    file: str
    id: str | None
    template: bool
    problem: str | None
