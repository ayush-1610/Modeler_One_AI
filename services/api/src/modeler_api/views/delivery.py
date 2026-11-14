"""The Delivery section's answers (`delivery_routes`; contracts 2026-11-12 §8.10): the page, a subject's card, a value's
source, a mapping, the spot check.

Every key is declared. A value is always a `DeliveryValue`, built in one place (`delivery_routes._Scope.rows`): for a
blinded study (D-15) its value, verbatim, spread, interval, LLOQ, ULOQ and whether it is below the LLOQ are null and
`blinded` is true. No model here reuses the name of a schema the API already publishes.
"""

from __future__ import annotations

from typing import Any, Literal

from modeler_api.views.brief import RequestLineView
from modeler_api.views.common import AgentsStatus, Number, View

SubjectKind = Literal["study", "product", "compound"]


# --- a value, as every route shows it ---------------------------------------------------------------------------------


class DeliveryValue(View):
    """One value of the ledger (a fact, or the i-th value of a table's extract) with the tuple it is read with: value,
    unit, time, labels and statistic. `blinded`: what D-15 withholds is null."""

    id: str
    field: str
    value: Number | str | bool | None
    unit: str | None
    verbatim: str | None                      # the source text as written; null for a blinded study
    time: Number | None
    time_unit: str | None
    time_actual: Number | None
    statistic: str | None
    spread: Number | None
    spread_kind: str | None
    n_at: int | None
    interval: list[Number] | None             # [low, high]
    interval_kind: str | None
    interval_level: Number | None
    censored: bool | None                     # below the LLOQ; null for a blinded study (no count of them can be made)
    lloq: Number | None
    lloq_unit: str | None
    uloq: Number | None
    conditions: dict[str, str]
    labels: dict[str, str]                    # role -> label as written: study, arm, product, batch, analyte, subject ...
    entity: dict[str, str]                    # role -> the ledger's entity id (study, arm, product, batch, analyte)
    method: str
    level: str                                # the evidence level: digitized … person_confirmed
    status: str                               # proposed | confirmed | superseded | excluded
    status_reason: str
    superseded_by: str | None
    confirmation: str | None                  # the confirmation that bound it (cf-n)
    mapping_id: str | None
    mapping_version: int | None
    derived_from: list[str]
    compute: str | None
    cross_file: bool                          # read from another file than its study's own, joined by a link
    table_kind: str | None
    file_sha256: str | None
    file: str | None                          # the file's name
    delivery: str
    anchor: str | None                        # null: a person entered it, or code derived it (no source to show)
    locators: dict[str, str]                  # role -> anchor of its time, unit, label, spread, n and LLOQ cells
    blinded: bool


# --- the page -----------------------------------------------------------------------------------------------------------


class DeliveryCoverage(View):
    """A file's coverage summary, from its coverage file (the current truth, `intake_records.CoverageSummary`)."""

    state: str                                # read | partly_read | unsupported | unreadable
    reason: str
    regions: int
    regions_mapped: int
    regions_excluded: int
    regions_unread: int
    numeric_cells: int
    cells_used: int
    cells_excluded: int
    cells_silent: int
    silent_loss: int
    outside_items: int
    outside_numeric: int
    values_unassigned: int
    needs_ocr_pages: list[int]
    anchors_unresolved: int


class DeliveryStage(View):
    stage: str
    seconds: Number
    ok: bool
    detail: str


class DeliveryRunState(View):
    """A file's latest pipeline run."""

    run_id: str
    state: Literal["queued", "running", "done", "failed"]
    attempt: int
    queued_at: str
    started_at: str | None
    finished_at: str | None
    by: str
    error: str
    stages: list[DeliveryStage]


class DeliveryRegion(View):
    """One region of a file and what was done with it. `state` is `waiting` while the file is being read again, or its
    mapping was rejected and the run that follows has not finished (its earlier values are still in the ledger)."""

    region_id: str
    kind: str                                 # table | prose | figure | table_like_text
    where: str
    caption: str | None                       # null when the file holds a blinded study's values
    table_kind: str
    state: Literal["mapped", "excluded", "unread", "waiting"]
    reason: str
    origin: str | None                        # cache | rule | llm | person
    mapping_id: str | None
    mapping_version: int | None
    mapping_status: str | None                # approved | proposed | rejected
    numeric_cells: int
    used: int
    excluded: int
    silent: int


class DeliveryOutside(View):
    """An item with a number outside every region that is not page furniture. `counted`: it is in the summary's
    `outside_numeric` (no mapped table cites it and no person accepted it as not data), so it blocks a confirmation."""

    where: str
    text: str | None                          # null when the file holds a blinded study's values
    region: str | None                        # the region whose context line it is
    counted: bool


class DeliveryContainer(View):
    sha256: str
    name: str
    member: str


class DeliveryFile(View):
    file_id: str
    sha256: str
    name: str
    size_bytes: int
    delivery: str
    container: DeliveryContainer | None
    repeat: bool                              # the same bytes arrived before: its regions are listed there
    legacy_sid: str | None                    # today's client file made of it (None: today's reader refused it)
    legacy_refusal: str | None
    by: str
    at: str
    state: str                                # read | partly_read | unsupported | unreadable | failed | waiting | not_read
    reason: str
    coverage: DeliveryCoverage | None
    run: DeliveryRunState | None
    regions: list[DeliveryRegion]
    outside: list[DeliveryOutside]
    blinded: bool                             # the file holds a value of a blinded study


class DeliveryArrival(View):
    """One delivery (an arrival request) with its files."""

    id: str
    by: str
    at: str
    files: list[DeliveryFile]


class DeliveryTotals(View):
    files: int
    files_by_state: dict[str, int]
    regions: int
    regions_mapped: int
    regions_excluded: int
    regions_unread: int
    silent_loss: int
    outside_numeric: int
    values_unassigned: int
    anchors_unresolved: int
    needs_ocr_pages: int
    values: int                               # active values in the ledger


class DeliverySignature(View):
    signature_id: str
    manifestation: str


class DeliveryRules(View):
    """The intake rules file a record was computed with (SME-governed: UNVERIFIED until signed)."""

    version: str
    status: str
    sha256: str


class DeliveryConfirmationState(View):
    """A subject's current confirmation as the page lists it (`intake_review.subjects`)."""

    id: str
    at: str
    by: str
    printed_name: str
    signature_id: str
    manifestation: str
    record_sha256: str
    landed: bool
    current: bool                             # the record still describes the subject's values


class DeliveryEntity(View):
    id: str
    label: str


class DeliverySubjectRow(View):
    subject_type: SubjectKind
    subject: str
    label: str
    values: int
    by_level: dict[str, int]
    by_method: dict[str, int]
    files: list[str]                          # sha256s
    deliveries: list[str]
    confirmation: DeliveryConfirmationState | None
    loaded_elsewhere: list[str]               # legacy client datasets of the same source, not rejected
    confirm_on: Literal["delivery", "client-review"]
    arms: list[DeliveryEntity]                # a study's arms (for `values:assign`)
    batches: list[DeliveryEntity]             # a product's batches
    blinded: bool


class DeliveryMappingUse(View):
    file_sha256: str
    file: str
    region_id: str
    where: str
    version: int
    state: str                                # the region's state: mapped | excluded | unread | waiting


class DeliveryMappingRow(View):
    """A mapping version that waits for a person: proposed and in use, or rejected with its file not read again yet."""

    mapping_id: str
    version: int
    status: Literal["approved", "proposed", "rejected"]
    origin: str                               # rule | llm | person
    origin_detail: str
    kind: str
    by: str
    at: str
    used_in: list[DeliveryMappingUse]
    waiting: bool                             # a file that uses it is queued or being read


class DeliveryPage(View):
    enabled: bool                             # false: the intake pipeline is off (`legacy`); everything else is empty
    running: bool                             # the intake job runs, or a run waits: poll while true
    agents: AgentsStatus
    deliveries: list[DeliveryArrival]
    totals: DeliveryTotals
    subjects: list[DeliverySubjectRow]
    unassigned: list[DeliveryValue]           # the "study not stated" values
    mappings: list[DeliveryMappingRow]
    request: list[RequestLineView]            # one line of the client request per item still to ask for
    rules: DeliveryRules


# --- a subject's card -----------------------------------------------------------------------------------------------------


class DeliveryGap(View):
    study: str
    tag: str
    value: str
    reason: str


class DeliveryCheck(View):
    id: str
    code: str
    severity: Literal["fail", "warn", "info"]
    message: str | None                       # null for a blinded subject (a message may quote a value)
    values: list[str]                         # value ids (none for a blinded subject)
    rule: str
    overridden: bool


class DeliveryConflict(View):
    id: str
    field: str
    time: Number | None
    kind: Literal["value", "unit"]
    labels: dict[str, str]
    values: list[str]                         # the value ids that disagree


class DeliveryLink(View):
    id: str
    link_fact: str | None
    study: str | None
    study_label: str | None
    file_sha256: str
    file: str
    values: int
    candidates: list[DeliveryEntity]
    state: Literal["unconfirmed", "ambiguous", "refused"]


class DeliveryRequirement(View):
    req_id: str
    template: str
    label: str
    scope: str
    criticality: str
    applies: str
    status: str
    values: list[str]
    disposition: str | None


class DeliveryBlocker(View):
    code: str
    detail: str
    ids: list[str]


class DeliveryTable(View):
    """The subject's values of one table (an extract), or its scalar facts of one file (`kind` facts)."""

    id: str                                   # the extract's id, or "facts:<file id>" / "facts:entered"
    kind: Literal["table", "facts"]
    file_sha256: str | None
    file: str | None
    region_id: str | None
    table_kind: str | None
    mapping_id: str | None
    mapping_version: int | None
    mapping_status: str | None                # approved | proposed | rejected
    waiting: bool                             # its file is being read again (a rejected mapping's values are still shown)
    values: list[DeliveryValue]


class DeliverySpotState(View):
    state: Literal["none", "drawn", "failed", "complete", "stale"]
    draw_id: str | None
    drawn: int                                # values in the draw
    wanted: int                               # values that still need a tick


class DeliveryLanded(View):
    datasets: list[str]
    evidence: list[str]
    dissolution_records: int
    rejected_legacy: list[str]
    pending: list[str] | None                 # what was not landed or landed PROPOSED; null for a blinded subject
    at: str


class DeliveryConfirmation(View):
    """The subject's current confirmation with its signature manifestation and what its record says."""

    id: str
    at: str
    by: str
    printed_name: str
    signature_id: str
    manifestation: str
    record_sha256: str
    supersedes: str | None
    current: bool
    rules: DeliveryRules | None
    coverage: dict[str, int]                  # the record's coverage counts
    held: list[str] | None                    # what the landing held back; null for a blinded subject
    landed: DeliveryLanded | None             # null: the landing did not complete (confirm again: no new signature)


class DeliverySubject(View):
    subject_type: SubjectKind
    subject: str
    label: str
    blinded: bool
    confirm_on: Literal["delivery", "client-review"]
    loaded_elsewhere: list[str]
    values: int
    by_level: dict[str, int]
    by_method: dict[str, int]
    silent_loss: int
    coverage: list[DeliveryCoverage]          # the files of the subject's deliveries
    # exceptions first
    blockers: list[DeliveryBlocker]
    gaps: list[DeliveryGap]
    checks: list[DeliveryCheck]               # failed and not overridden first
    conflicts: list[DeliveryConflict]
    links: list[DeliveryLink]
    requirements: list[DeliveryRequirement]   # missing first
    mappings: list[DeliveryMappingRow]        # the mapping versions its values were read with that no person approved
    tables: list[DeliveryTable]
    held: list[str] | None                    # what the landing would hold back; null for a blinded subject
    landing_problem: str | None               # why the landing cannot be planned (a study record field no value gives)
    spot_check: DeliverySpotState
    confirmation: DeliveryConfirmation | None
    rules: DeliveryRules
    signature: DeliverySignature | None = None    # set by `:confirm` when it signed


# --- the spot check ---------------------------------------------------------------------------------------------------------


class DeliverySpotDraw(View):
    id: str
    by: str
    at: str
    seed: str
    subject_digest: str
    rules_version: str
    heads: dict[str, str]
    always: list[str]
    sampled: list[str]
    carried: dict[str, str]


class DeliverySpotTick(View):
    value_id: str
    ok: bool
    note: str


class DeliverySpotRecord(View):
    id: str
    by: str
    at: str
    ticks: list[DeliverySpotTick]


class DeliverySpotValue(View):
    """One value of the draw with the tuple it is ticked for (`value`) and its source reference (`value.id` for
    `/delivery/source?value=`, `value.anchor`, `value.locators`)."""

    value: DeliveryValue
    reason: str | None                        # its stratum, or "always:<why>"; null for a blinded study
    wanted: bool                              # the submit must carry a tick for it
    carried_by: str | None                    # the earlier spot check whose ok tick carries over
    ok: bool | None                           # its tick in this draw's record
    note: str
    inputs: list[DeliveryValue]               # a derived value's inputs


class DeliverySpotCheck(View):
    subject_type: SubjectKind
    subject: str
    label: str
    blinded: bool
    state: Literal["none", "drawn", "failed", "complete", "stale"]
    draw: DeliverySpotDraw | None
    record: DeliverySpotRecord | None
    values: list[DeliverySpotValue]
    wanted: list[str]                         # the value ids the one submit must tick


# --- a value's source ---------------------------------------------------------------------------------------------------


class DeliverySourceCell(View):
    row: int
    column: int
    text: str
    numeric: bool
    locator: str
    highlighted: bool
    role: str | None


class DeliverySource(View):
    """A `SourceView` (§4.2) plus the file and the value. `blinded`: the region holds a value of a blinded study, so
    its cells with a number and the cells a value is anchored at are blank, every digit of the text and the title is
    masked, and the page is not given (it must not be drawn)."""

    kind: Literal["grid", "text"]
    title: str
    region_id: str | None
    n_rows: int
    n_cols: int
    cells: list[DeliverySourceCell]
    text: str
    span: list[int] | None
    page: int | None
    page_size: list[Number] | None
    box: list[Number] | None
    file: str
    sha256: str
    value_id: str | None
    blinded: bool


# --- a mapping ------------------------------------------------------------------------------------------------------------


class DeliveryMappingColumn(View):
    column: int
    header: str | None                        # the header text of the sample table's column
    role: str
    field: str | None
    unit: str | None
    statistic: str | None
    spread_kind: str | None
    of: int | None
    cell_form: str
    condition: str | None
    series_role: str | None
    reason: str


class DeliveryMappingKey(View):
    pattern: str
    field: str
    statistic: str | None
    spread_kind: str | None


class DeliveryMappingTokens(View):
    below_lloq: list[str]
    missing: list[str]


class DeliveryMappingRule(View):
    column: int
    pattern: str
    role: str
    spread_kind: str | None
    reason: str


class DeliveryMappingConstant(View):
    field: str
    cite: dict[str, Any]                      # a cell (row, column) or a context line (near, line)
    pattern: str | None


class DeliveryMappingContext(View):
    near: str
    line: int
    text: str


class DeliveryMappingSample(View):
    """The table as the table mapper is shown it (`mapping.redact`): no digit of its body. For a file with a blinded
    study's values the body and the context lines are withheld."""

    file_sha256: str
    file: str
    region_id: str
    where: str
    n_rows: int
    n_cols: int
    header_rows: int
    context: list[DeliveryMappingContext]
    header: list[list[str]]
    body_rows: list[int]
    body: list[list[str]]
    blinded: bool


class DeliveryMappingFinding(View):
    code: str
    location: str
    message: str
    severity: str


class DeliveryMappingDecision(View):
    status: Literal["approved", "rejected"]
    why: str
    by: str
    at: str


class DeliveryMappingVersion(View):
    version: int
    status: Literal["approved", "proposed", "rejected"]
    origin: str
    origin_detail: str
    by: str
    at: str
    decisions: list[DeliveryMappingDecision]


class DeliveryMapping(View):
    mapping_id: str
    version: int                              # the version shown
    status: Literal["approved", "proposed", "rejected"]
    origin: str
    origin_detail: str
    fingerprint: str
    by: str
    at: str
    kind: str
    layout: str
    header_rows: int
    first_data_row: int
    last_data_row: int | None
    field: str | None
    time_row: int | None
    time_unit: str | None
    value_unit: str | None
    statistic: str | None
    time_reference: str | None
    not_data_reason: str
    questions: list[str]
    columns: list[DeliveryMappingColumn]
    keys: list[DeliveryMappingKey]
    tokens: DeliveryMappingTokens
    rules: list[DeliveryMappingRule]
    constants: list[DeliveryMappingConstant]
    spec: dict[str, Any]                      # the stored spec (mapping/2), for `:edit`
    sample: DeliveryMappingSample | None      # null: the source model of its table is not cached
    findings: list[DeliveryMappingFinding]    # the spec checked on the sample table (`validate_spec`)
    versions: list[DeliveryMappingVersion]
    used_in: list[DeliveryMappingUse]
    waiting: bool                             # a file that uses it is queued or being read
    queued: list[str]                         # sha256s of the files queued again by this request
