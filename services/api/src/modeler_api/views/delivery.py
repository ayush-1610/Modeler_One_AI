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


class DeliveryRegionDecision(View):
    """A person's "not data" decision in force on a region or an outside item (a `RegionDecision`, rd-n): who made it,
    when and why. For a file that holds a blinded study's values, the digits of `why` are masked (a person may have
    quoted what the file holds)."""

    id: str
    by: str
    at: str
    why: str


class DeliveryRegionRestore(View):
    """The latest "Restore…" that gave a region or an outside item back (a `RegionDecision` with `restores`): who, when,
    why (masked as a decision's is) and the decisions it undid. It stays the item's record when a later decision sets
    the item aside again."""

    id: str
    by: str
    at: str
    why: str
    restores: list[str]                       # the decisions it undid (rd-n)


class DeliveryRegionHead(View):
    """The first rows of a table no layout reads (never read, or its layout rejected), for a person to give it a
    layout: at most 5 rows and 30 columns, each cell as written (cut at 80 characters, "" for an empty one). For a file
    that holds a blinded study's values, only the header band (its rows above the first row of values, as a mapping's
    sample shows it) with every digit masked: no row of values. `spans` gives, for each of `rows`, each column's width
    as the file draws it: 1; n > 1 for a merged cell's first column, over n columns; 0 for a column a merged cell to its
    left covers (its text in `rows` is the merged cell's, copied as a mapping reads a merged header)."""

    n_rows: int                               # the whole table's rows and columns
    n_cols: int
    header_rows: int                          # the header band code finds (`mapping.fingerprint.header_band`)
    rows: list[list[str]]
    spans: list[list[int]]                    # one per row of `rows`, one per column: 1, n (a merged cell), 0 (covered)
    blinded: bool


class DeliveryRegion(View):
    """One region of a file and what was done with it. `state` is `waiting` while the file is being read again, or its
    mapping was rejected and the run that follows has not finished (its earlier values are still in the ledger)."""

    region_id: str
    kind: str                                 # table | prose | figure | table_like_text
    where: str
    caption: str | None                       # null when the file holds a blinded study's values
    table_kind: str
    state: Literal["mapped", "excluded", "unread", "waiting"]
    reason: str                               # a person's decision: "rd-n: why" (why masked as `decision.why` is)
    origin: str | None                        # cache | rule | llm | person
    mapping_id: str | None
    mapping_version: int | None
    mapping_status: str | None                # approved | proposed | rejected
    numeric_cells: int
    used: int
    excluded: int
    silent: int
    decision: DeliveryRegionDecision | None   # the person's "not data" decision that sets it aside; null: a rule's, or none
    restored: DeliveryRegionRestore | None    # the latest restore that gave it back; null: none
    head: DeliveryRegionHead | None           # a table no layout reads: its first rows; null for any other region
    silent_cells: list[DeliveryUnreadCell]    # a read table's numbers no part of its layout reads (the first 50), and why
    newer: DeliveryNewerLayout | None         # a read table the newest approved version of its layout does not read


class DeliveryUnreadCell(View):
    """A cell with a number in a read table that no part of its layout reads (silent: it holds up the delivery's
    signatures), and why, as code's reading of the table records it (`CellUse.rule`): "" (no column or row rule of the
    layout reads it), "unparseable" (a column reads it, but it is not a plain number), "time_unparseable" (its time is
    not a plain number), "qualifier_twice" (a second spread, n or interval for one value), "lloq_differs" (its LLOQ is
    not the table's), "time_unit_conflict" (the cell writes another time unit than its column). `text` is null for a
    file that holds a blinded study's values. Read-only: a single cell is not set aside here (plan 2026-11-14 §3 API 3,
    the owner's review)."""

    where: str
    text: str | None
    why: str


class DeliveryNewerLayout(View):
    """The newest approved version of a table's layout, newer than the version the table is read with, that does not
    read it: the pipeline reads a table only with an approved version that has no error on the table's own grid
    (`intake_pipeline._choose`), so the table stays with the older one. `findings`: that version's errors on this table
    (their digits masked for a file that holds a blinded study's values); `constants`: that version's facts read once
    for the table, which a finding's location names by number."""

    version: int
    findings: list[DeliveryMappingFinding]
    constants: list[DeliveryMappingConstant]


class DeliveryOutside(View):
    """An item with a number outside every region that is not page furniture. `counted`: it is in the summary's
    `outside_numeric` (no mapped table cites it and no person accepted it as not data), so it blocks a confirmation.
    Not counted with no `decision`: a table that is read cites it (a fact read once for the table)."""

    where: str
    text: str | None                          # null when the file holds a blinded study's values
    region: str | None                        # the region whose context line it is
    counted: bool
    decision: DeliveryRegionDecision | None   # the person's decision in force that it is not data; null: none
    restored: DeliveryRegionRestore | None    # the latest restore that gave it back to the count; null: none


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
    links: list[DeliveryFileLink]             # the links in force on its values (none on a repeat: listed on the first)
    blinded: bool                             # the file holds a value of a blinded study


class DeliveryFileLink(View):
    """A person's link in force on this file's values (`link_carry.file_links`): what it covers here (`targets`: an
    extract id for a whole table, else value ids; fact ids), how many values, where it sent them (entity ids, followed
    through merges, with their labels), who linked them, when and why (the digits masked in a blinded file). Linking the
    targets again replaces it whole."""

    assignment: str                           # as-n
    targets: list[str]
    values: int
    study: str | None
    arm: str | None
    product: str | None
    batch: str | None
    analyte: str | None
    labels: dict[str, str]
    by: str
    at: str
    why: str


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
    landed_datasets: list[str]                # the datasets its landing loaded (one count on the page: the card, the status line)
    current: bool                             # the record still describes the subject: its values, and no restore since
                                              # undid a "not data" decision it binds (`confirmation_current`)


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
    loaded_elsewhere: list[str]               # legacy client datasets of the same source a person accepted (in the model)
    proposed_elsewhere: list[str]             # legacy client datasets of the same source still proposed (not confirmed)
    legacy_groups: list[str]                  # the client-review groups (`/client-review` ids) of the same source: holding
                                              # those datasets, or read from files a person linked to this subject
    confirm_on: Literal["delivery", "client-review"]
    arms: list[DeliveryEntity]                # a study's arms (for `values:assign`)
    batches: list[DeliveryEntity]             # a product's batches
    blinded: bool
    blinded_why: str | None                   # why it is blinded, in words ("the project's blinding list names it (study X)")


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


class DeliveryRelink(View):
    """A person's link a re-read of its table did not carry over (`link_carry.waiting`): the values of `targets` (extract
    or fact ids on the "study not stated" list now) were read from the table that `assignment` linked, in part (`whole`
    false: which part it would cover now cannot be told), or whole before links were carried over. Where it sent them
    (entity ids, followed through merges), who linked them, when and why (the digits masked when the study is blinded)."""

    targets: list[str]
    assignment: str                           # as-n
    study: str | None
    arm: str | None
    product: str | None
    batch: str | None
    analyte: str | None
    labels: dict[str, str]                    # role -> the label of each of those (a study with no value left is named)
    whole: bool
    by: str
    at: str
    why: str


class DeliveryPage(View):
    enabled: bool                             # false: the intake pipeline is off (`legacy`); everything else is empty
    running: bool                             # the intake job runs, or a run waits: poll while true
    agents: AgentsStatus
    deliveries: list[DeliveryArrival]
    totals: DeliveryTotals
    subjects: list[DeliverySubjectRow]
    unassigned: list[DeliveryValue]           # the "study not stated" values
    relink: list[DeliveryRelink]              # links to an earlier reading of their tables a re-read did not carry over
    analytes: list[DeliveryEntity]            # the ledger's analytes: `values:assign` takes one by its id (`analyte`)
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
    # what deciding it does to a spot check drawn (said before the decision; final review round 4): accepted as is, its
    # values are always checked, and `outside_draw` of them the draw does not hold, so it is drawn again (0: none, no
    # draw, or it is stale already); its analyte stated, the `computed` values worked out from its values (an SD from
    # an SE) are computed again, so it is drawn again (0: none)
    outside_draw: int
    computed: int


class DeliveryConflict(View):
    id: str
    field: str
    time: Number | None
    time_unit: str | None                     # the time's unit as the first value writes it
    kind: Literal["value", "unit"]
    labels: dict[str, str]                    # the subject, period, arm ... the values are read with
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


class DeliveryIndividual(View):
    """A study's simulated individual (D-29) as the landing would set it from the study's active values: one source
    for the card, Populations and individuals, and what loads (`intake_landing.study_individual`)."""

    demographics: dict[str, Any] | None       # the study record's `demographics`; null until a person chose it
    needs: list[str]                          # the fields a person still gives (individual_population, individual_sex, age_mean)
    why: str                                  # why a stated value cannot make it ("" when none)
    stated: list[str]                         # the demographic fields with an active value
    kept: list[str]                           # of them, those the individual does not carry (the share of women, ...)


class DeliverySpotState(View):
    state: Literal["none", "drawn", "failed", "complete", "stale"]
    draw_id: str | None
    drawn: int                                # values in the draw
    always: int                               # of them, the values always checked (not sampled): drawn again in any
                                              # new draw while they stand, their ticks with them
    wanted: int                               # values that still need a tick
    recorded_by: str | None                   # who recorded the draw's ticks, and when (null: not recorded)
    recorded_at: str | None


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
    current: bool                             # as `DeliveryConfirmationState.current`
    rules: DeliveryRules | None
    coverage: dict[str, int]                  # the record's coverage counts
    held: list[str] | None                    # what the landing held back; null for a blinded subject
    landed: DeliveryLanded | None             # null: the landing did not complete (confirm again: no new signature)


class DeliveryDecision(View):
    """A person's decision the subject's signature binds (plan 2026-11-14 §2.2.4), read from the intake's logs: who
    made it, when and why, and what it is about. `scope` "subject": about the subject, or the clean-up of the files its
    values were read from; "delivery": the clean-up of the delivery's other files, which the signature binds too
    (contracts §11.10). For a blinded subject, or a decision about a file that holds a blinded study's values, the
    digits of `why` are masked (as a region decision's are) and an entry gives no `value` (D-15)."""

    id: str                                   # ov-n, dp-n, f-n, ch-n, lk-n, as-n, rd-n; a layout's "<mapping>/<version>/<n>"
    kind: Literal["override", "disposition", "entry", "choice", "link", "assign", "not_data", "restore", "layout"]
    scope: Literal["subject", "delivery"]
    by: str
    at: str
    why: str
    files: list[str]                          # the names of the files it is about; a layout's: every file it reads now
    check_id: str | None               # override: the check accepted as is
    req_id: str | None                 # disposition: the required item
    disposition: str | None
    value_id: str | None               # entry: the value entered (or the correction); choice: the value kept
    field: str | None                  # entry, choice
    value: float | int | str | bool | None   # entry: the value entered; null for a blinded subject
    unit: str | None
    time: float | None
    time_unit: str | None
    supersedes: str | None             # entry: the value it corrected
    confirmed: bool | None             # link: the file's values are the study's (or not)
    linked_to: dict[str, str]  # assign: role (study, arm, product, batch, analyte) -> label
    values: int | None                 # assign: the values it linked
    current: int | None                # assign of the subject: those of them that are still the subject's
    places: list[str]          # not_data, restore: where in the file (a region, a note)
    region_scope: str | None           # not_data, restore: regions | unread_prose | figures | outside
    restores: list[str]        # restore: the decisions it undid (rd-n)
    mapping_id: str | None             # layout
    version: int | None
    status: str | None                 # layout: approved | rejected
    table_kind: str | None


class DeliverySubject(View):
    subject_type: SubjectKind
    subject: str
    label: str
    blinded: bool
    blinded_why: str | None                   # as `DeliverySubjectRow`: why, in words, so a wrong match is seen
    confirm_on: Literal["delivery", "client-review"]
    loaded_elsewhere: list[str]               # as `DeliverySubjectRow`: accepted (in the model)
    proposed_elsewhere: list[str]             # proposed (read with the sheet form, not confirmed yet)
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
    individual: DeliveryIndividual | None     # a study's simulated individual; null for a product, the compound or blinded
    spot_check: DeliverySpotState
    confirmation: DeliveryConfirmation | None
    rules: DeliveryRules
    decisions: list[DeliveryDecision]         # what its signature binds, newest first
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
    """The table a mapping is shown on: its context lines, its header rows as the layout counts them (`header_rows`,
    the layout's own: their cells as written, as each column's header is), and its first 5 and last 3 body rows with
    every digit masked (`mapping.redact.redact_cell`): `body_rows` numbers them, so the rows left out are those of
    `header_rows + 1 .. n_rows` not listed. For a file with a blinded study's values the body is withheld and the
    digits of the header and the context lines are masked."""

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


class DeliveryTableMove(View):
    """What approving the version shown (one waiting for approval) changes for a table of its layout: the pipeline's
    own rule (`intake_pipeline.choose_version`: of the approved versions that read a table, the one leaving the fewest
    numbers unread, then reading the most facts once, then the newest) would read it with that version instead of the
    one it is read with now (`from_version`). What changes: the numbers its reading leaves unread, before and after,
    and the facts read once for the whole table (by field) that it no longer reads or newly reads."""

    from_version: int
    unread_before: int
    unread_after: int
    facts_lost: list[str]
    facts_gained: list[str]


class DeliveryMappingTable(View):
    """A table of the mapping's layout that one of its versions reads now (one row per table of `used_in`), and how the
    version shown reads it: `reads` false when that version has an error on the table (`findings`: its errors and
    notes there, their digits masked for a file that holds a blinded study's values), null when the table's source
    model is not cached. `newer`: the table stays with an older version because the newest approved one does not read
    it (as on the page's region). `moves`: the version shown waits for approval, and approving it moves the table to
    it (final review round 3: said before the approval, never found after it); null otherwise."""

    file_sha256: str
    file: str
    region_id: str
    where: str
    version: int                              # the version the table is read with now
    state: str
    reads: bool | None
    findings: list[DeliveryMappingFinding]
    newer: DeliveryNewerLayout | None
    moves: DeliveryTableMove | None


class DeliveryMappingVersion(View):
    version: int
    status: Literal["approved", "proposed", "rejected"]
    origin: str
    origin_detail: str
    by: str
    at: str
    decisions: list[DeliveryMappingDecision]


class DeliveryMappingField(View):
    """A field of the ledger's vocabulary (`modeler_intake.fields`): what a value, a constant or a label is of."""

    name: str
    value: Literal["number", "integer", "choice", "name", "text"]
    level: str                                # study | arm | product | batch | analyte | observation | compound | condition | label
    unit_class: str                           # mass | concentration | time | percentage | ratio | other | none
    choices: list[str]                        # a choice field's choices


class DeliveryMappingVocabulary(View):
    """The words a mapping spec (`mapping/2`) is written with, read from `modeler_intake.mapping_spec` and
    `modeler_intake.fields`: a form that edits a layout offers these and never makes one up."""

    kinds: list[str]                          # what a table is (MappingSpec.kind)
    layouts: list[str]
    roles: list[str]                          # a column's role
    row_roles: list[str]                      # a row rule's role
    cell_forms: list[str]
    statistics: list[str]
    spread_kinds: list[str]
    time_references: list[str]
    cite_near: list[str]                      # where a context line is cited: caption, above, below
    fields: list[DeliveryMappingField]        # a CPF id of the parameter registry is a field too (not listed)
    conditions: list[str]                     # a condition column's or series' name
    labels: list[str]                         # the labels a column may write (subject, period ...)


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
    tables: list[DeliveryMappingTable]        # each table a version of it reads now, and how the version shown reads it
    waiting: bool                             # a file that uses it is queued or being read
    queued: list[str]                         # sha256s of the files queued again by this request
    vocabulary: DeliveryMappingVocabulary     # the words a spec may use, for a form that edits it
