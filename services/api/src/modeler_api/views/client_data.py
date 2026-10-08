"""P3 answers of `client_api`: the client data page, a sheet with its reading form, a mapping preview or reading."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from modeler_api.views.common import AgentsStatus, DataPlanStatus, Number, StoredContent, VersionView, View


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
    running: bool


class ReadFile(View):
    id: str
    file: str
    template: bool


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
