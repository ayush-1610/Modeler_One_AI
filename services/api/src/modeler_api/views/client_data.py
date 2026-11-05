"""P3 answers of `client_api`: the client data page, a sheet with its reading form, a mapping preview or reading."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from modeler_api.views.common import (
    AgentsStatus,
    DataPlanStatus,
    FileTagView,
    Number,
    StoredContent,
    TagProposalView,
    VersionView,
    View,
)


class ReconciledRow(View):
    """One client item of the data plan and what arrived for it (`client_data.Reconciled`)."""

    req_id: str
    label: str
    criticality: str
    applies: str
    status: str
    delivered: list[str]
    detail: str
    cross_check: bool
    literature_accepted: list[str]
    kind: str
    target: str
    product: str | None


class Reconciliation(View):
    rows: list[ReconciledRow]
    unpromised: list[str]
    blocking: list[str]


class Dissolution(View):
    profiles: list[StoredContent]
    comparisons: list[dict[str, Any]]      # test vs reference pairs with their f2
    problems: list[str]


class ClientDataPage(View):
    template: str
    data_plan: DataPlanStatus
    files: list[StoredContent]
    reconciliation: Reconciliation
    dissolution: Dissolution
    register_: VersionView | None = Field(alias="register")  # "register" would shadow the class method
    agents: AgentsStatus
    running: bool                         # an agent job on the project's client files: sorting or reading
    reading: bool                         # the reading agent is reading sheets


class ReadFile(View):
    id: str
    file: str
    template: bool
    sha256: str = ""                              # the stored file, to change its tag (`documents/{sha256}:tag`)
    tag: FileTagView | None = None                # what the person said it is (plan 2026-11-03 §3.1)
    tag_proposal: TagProposalView | None = None   # another tag code read from its content, to use or keep
    needs_ocr: bool = False


class ClientUpload(ClientDataPage):
    """The files just stored (a filled template is read at once), and the page."""

    read: list[ReadFile]


class TriageStart(View):
    status: str


class Product(View):
    name: str
    role: str


class ReadBefore(View):
    recipe_id: str | None
    datasets: list[str]


class SheetView(View):
    """One sheet as text, the reading form's first filling and what was found."""

    sheet: str
    rows: list[list[str]]
    max_row: int
    max_column: int
    category: str
    form: dict[str, Any]                  # modeler_intake.sheet_form.SheetForm, as the page edits it
    notes: list[str]
    products: list[Product]
    read_before: list[ReadBefore]
    proposed_by: str                      # "code" (the first filling), or the reading agent's run ("agent:<run id>")
    run_id: str | None = None             # the agent run that proposed the form, when the agent did


class MapIssue(View):
    code: str
    location: str
    message: str


class SampleRow(View):
    series: str
    time: Number
    value: Number | None
    blq: bool | None = None               # concentration rows only
    cell: str


class Sample(View):
    """What the recipe read, in a person's terms (values withheld for an external study before the MAP is signed)."""

    series: list[str]
    times: list[Number]
    time_unit: str | None = None          # absent when nothing was read
    unit: str | None = None
    rows: list[SampleRow]
    below_lloq: int
    values_hidden: bool


class MapPreview(View):
    ready: bool
    issues: list[MapIssue]
    questions: list[str]
    concentrations: int
    dissolution: int
    studies: list[str]
    recipe: dict[str, Any] | None
    sample: Sample


class MapReading(MapPreview, ClientDataPage):
    """A confirmed reading: the preview's fields, the datasets it proposed and the page, merged into one object
    (today's shape; the owner chose to keep it, 2026-10-08). Where both name a key the page's wins: `dissolution` is
    the page's profiles and comparisons, not the preview's record count."""

    datasets: list[str]
    dissolution: Dissolution  # type: ignore[assignment]


class ReleaseProposal(ClientDataPage):
    """A profile's fit proposed as release-model evidence: the evidence ids, and the page."""

    evidence: list[str]


# --- confirm inline (plan 2026-11-03 §3.3): `modeler_project.client_review` ---------------------------------------


class ReviewOption(View):
    id: str
    label: str
    value: Any
    source: dict[str, Any] | None       # where the value comes from (doc_sha256, page, locator, title, quote)
    datasets: list[str]


class ReviewIssue(View):
    """A conflict, an explainable difference or a question on a group: open until a person confirms a selection."""

    id: str
    kind: Literal["conflict", "difference", "question", "link"]   # link: are two names of a study the same study
    text: str
    options: list[ReviewOption]
    answer: bool                        # the question asks for a value rather than an option
    selected: str | None
    answered: float | None
    selected_by: str | None
    selected_at: str | None


class ReviewItem(View):
    id: str
    kind: Literal["dataset", "value", "profile"]
    label: str
    value: str
    state: str
    source: dict[str, Any]
    note: str = ""
    target: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    duplicate_of: str | None = None     # the same profile as another file's (within the rule's tolerance): loads once


class ReviewFact(View):
    field: str
    label: str
    value: str
    source: dict[str, Any]
    stored: Any = None                  # the value as the study record keeps it
    fills: list[str] = Field(default_factory=list)   # datasets lacking it that a document's fact fills on confirm (I4)


class ReviewGroup(View):
    """A study, a product or a file's compound values, to confirm or confirmed."""

    id: str
    kind: Literal["study", "product", "compound"]
    tab: str
    title: str
    items: list[ReviewItem]
    facts: list[ReviewFact]
    issues: list[ReviewIssue]
    notes: list[str] = Field(default_factory=list)   # what code linked or found the same across files (I3)
    state: Literal["to_confirm", "confirmed"]
    open: int
    confirmed_by: str | None
    confirmed_at: str | None


class ClientReviewPage(View):
    groups: list[ReviewGroup]
    to_confirm: int
