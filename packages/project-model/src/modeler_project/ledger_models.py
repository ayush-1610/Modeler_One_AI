"""The ledger's models (contracts §4.5): pure models, no store.

The ledger is the long-form, append-only record of every value read from a client file, with its anchor. It is kept in
two chained logs and content-addressed extract files (`intake_store`); `ledger_view` folds them into `ValueState`s.
Status is never stored on a fact: superseded, excluded, confirmed and proposed are computed by the fold. No model
confidence exists anywhere.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from modeler_intake.fields import IntervalKind, SpreadKind, Statistic, TableKind

EntityType = Literal["study", "arm", "product", "batch", "analyte"]
Method = Literal["cell", "pdf_table", "docx_table", "prose", "digitized", "derived", "person"]
Status = Literal["proposed", "confirmed", "superseded", "excluded"]
EvidenceLevel = Literal["digitized", "prose", "new_mapping", "approved_mapping", "person_confirmed"]   # ascending


class _B(BaseModel):
    # NaN and the infinities are refused where they enter: they have no JSON form, so a stored line could not hold what
    # its hash covers (anchors.canonical refuses them too)
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Entity(_B):
    id: str                                   # st-n, arm-n, pr-n, ba-n, an-n
    type: EntityType
    label: str
    key: str                                  # name_key(label)
    parent: str | None = None                 # an arm's study, a batch's product
    source: str | None = None                 # the anchor that first named it (None: a person); its file is the home file
    by: str
    at: str


class Alias(_B):
    type: EntityType
    key: str
    parent: str | None = None
    entity: str
    source: str                               # "exact" | "review:<aliases list>" | "link:<fact id>" | "person"
    by: str
    at: str


class Merge(_B):
    type: EntityType
    from_id: str
    into_id: str
    link_fact: str | None = None
    why: str
    by: str
    at: str


class EntityRef(_B):
    """Who a value is about. Any part may be None: partial facts are welcome. A value with no matrix label takes its
    study's single active matrix fact; none: MATRIX_MISSING."""

    study: str | None = None                  # entity ids
    arm: str | None = None
    product: str | None = None
    batch: str | None = None
    analyte: str | None = None
    subject: str | None = None                # labels as written (matrix read with fields.read_choice where a choice is needed)
    period: str | None = None
    sequence: str | None = None
    occasion: str | None = None
    vessel: str | None = None
    matrix: str | None = None


class MappingUse(_B):
    mapping_id: str
    version: int


class ModelUse(_B):
    provider: str
    model: str
    prompt_sha256: str
    agent_run: str


class Relation(_B):
    kind: Literal["ddi_ratio", "test_vs_reference"]
    other: EntityRef
    parameter: str


class CrossFile(_B):
    """Computed by the fold, never stored (§6.3). G3's three anchors: the stating value's, the link's (a link fact, or the
    review record of a person's assignment or merge), the receiving study entity's source."""

    stating_fact: str
    link_fact: str
    receiving_study: str


class Fact(_B):
    """A scalar value: a constant, a prose fact, a text-valued row, a relation row, a derived or a person's value."""

    id: str                                   # "f-<seq of its line>"
    delivery: str
    run_id: str | None = None
    entity: EntityRef
    field: str
    value: float | int | str | bool | None
    unit: str | None = None                   # the unit as written, never renamed
    verbatim: str = ""                        # the source text as written ("" for derived)
    conditions: dict[str, str] = Field(default_factory=dict)
    time: float | None = None
    time_unit: str | None = None
    time_actual: float | None = None
    statistic: Statistic | None = None
    spread: float | None = None
    spread_kind: SpreadKind | None = None
    n: int | None = None
    interval: tuple[float, float] | None = None
    interval_kind: IntervalKind | None = None
    interval_level: float | None = None
    censored: bool = False
    lloq: float | None = None
    lloq_unit: str | None = None
    uloq: float | None = None
    relation: Relation | None = None
    anchor: str | None = None                 # anchor text; None only for derived and person facts
    locators: dict[str, str] = Field(default_factory=dict)   # role -> anchor text of its time, unit, label, spread, n, LLOQ cells
    method: Method
    mapping: MappingUse | None = None
    model: ModelUse | None = None
    derived_from: tuple[str, ...] = ()
    compute: str | None = None                # e.g. "spread-1/sd_from_se", "compute-1/dose_to_mg"
    supersedes: str | None = None             # a fact id or a value id "<extract id>#<i>"
    reason: str = ""
    by: str                                   # "code", "agent:<run id>" or a user id
    at: str


class TableExtract(_B):
    """The numeric values of one table under one mapping, column-wise; one file per extract. NO delivery and no run:
    identity is content. Every column below has length n (None where a value has none). Text-valued rows (route,
    apparatus, sex) and relation rows are written as Facts, never into an extract.

    `entities` and `entity_locators` are parallel and hold one entry per distinct (entity, label cells) pair, not per
    entity: the same EntityRef appears again when another row names it in other cells (a long table writes the subject
    on every row), so each value's `entity_ix` gives the cells of its own row. Likewise `conditions` and
    `condition_locators` hold one entry per distinct (conditions, cells) pair."""

    # read by its alias or its name: a body dumped without by_alias reads back too (canonical() writes the alias)
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, validate_by_name=True)

    schema_id: Literal["extract/1"] = Field(default="extract/1", alias="schema")
    file_sha256: str
    parser: str
    parser_version: str
    region_id: str
    mapping: MappingUse
    kind: TableKind
    decimal: Literal["point", "comma"]
    entities: tuple[EntityRef, ...]
    entity_locators: tuple[dict[str, str], ...]     # role -> the cell that named it here
    fields: tuple[str, ...]
    units: tuple[str, ...]
    conditions: tuple[dict[str, str], ...]
    condition_locators: tuple[dict[str, str], ...]
    n: int                                          # values
    entity_ix: tuple[int, ...]
    field_ix: tuple[int, ...]
    unit_ix: tuple[int | None, ...]
    condition_ix: tuple[int | None, ...]
    time: tuple[float | None, ...]
    time_unit: tuple[str | None, ...]
    time_actual: tuple[float | None, ...]
    value: tuple[float | None, ...]
    verbatim: tuple[str, ...]
    censored: tuple[bool, ...]
    lloq: tuple[float | None, ...]
    lloq_unit: tuple[str | None, ...]
    uloq: tuple[float | None, ...]
    statistic: tuple[str | None, ...]
    spread: tuple[float | None, ...]
    spread_kind: tuple[str | None, ...]
    n_at: tuple[int | None, ...]
    interval_low: tuple[float | None, ...]
    interval_high: tuple[float | None, ...]
    interval_kind: tuple[str | None, ...]
    interval_level: tuple[float | None, ...]
    locator: tuple[str, ...]                        # the value cell of each value: its own anchor
    time_locator: tuple[str | None, ...]
    time_actual_locator: tuple[str | None, ...]
    unit_locator: tuple[str | None, ...]
    spread_locator: tuple[str | None, ...]
    n_locator: tuple[str | None, ...]
    lloq_locator: tuple[str | None, ...]
    interval_locator: tuple[tuple[str, str] | None, ...]


class ExtractRef(_B):
    """The extract's line in the ledger."""

    id: str                                   # "tx-" + content_sha256[:16]
    content_sha256: str
    file_sha256: str
    region_id: str
    mapping: MappingUse
    kind: TableKind
    n: int
    studies: tuple[str, ...]
    products: tuple[str, ...]
    delivery: str
    run_id: str | None
    supersedes: tuple[str, ...] = ()
    by: str
    at: str


class StatusChange(_B):
    target: str                               # a fact id, an extract id, or a value id "<extract id>#<index, 0-based>"
    status: Literal["excluded", "proposed"]
    reason: str
    by: str
    at: str


class ValueState(_B):
    """One value as every reader sees it, whether a fact or the i-th value of an extract."""

    id: str
    entity: EntityRef
    field: str
    value: float | int | str | bool | None
    unit: str | None
    verbatim: str
    file_sha256: str | None = None            # the file it was read from (None: derived, person)
    time: float | None = None
    time_unit: str | None = None
    time_actual: float | None = None
    statistic: str | None = None
    spread: float | None = None
    spread_kind: str | None = None
    n_at: int | None = None
    interval: tuple[float, float] | None = None
    interval_kind: str | None = None
    interval_level: float | None = None
    censored: bool = False
    lloq: float | None = None
    lloq_unit: str | None = None
    uloq: float | None = None
    conditions: dict[str, str] = Field(default_factory=dict)
    relation: Relation | None = None
    anchor: str | None
    locators: dict[str, str] = Field(default_factory=dict)   # role -> anchor text (time, unit, labels ...)
    method: Method
    mapping: MappingUse | None = None
    derived_from: tuple[str, ...] = ()
    compute: str | None = None
    cross_file: CrossFile | None = None
    status: Status
    status_reason: str = ""
    superseded_by: str | None = None
    confirmation: str | None = None
    level: EvidenceLevel
    table_kind: TableKind | None = None
    delivery: str


class Conflict(_B):
    id: str                                   # "cx-" + sha256(key)[:10]
    entity: EntityRef
    field: str
    time: float | None
    values: tuple[str, ...]                   # the value ids that disagree; all are kept
    kind: Literal["value", "unit"]


class PendingLink(_B):
    """ambiguous: two or more studies match, nothing was joined; unconfirmed: joined, waits for a reviewer."""

    id: str
    link_fact: str | None
    study: str | None
    file_sha256: str
    values: int
    candidates: tuple[str, ...]
    state: Literal["unconfirmed", "ambiguous", "refused"]


class ChainHead(_B):
    seq: int
    hash: str
