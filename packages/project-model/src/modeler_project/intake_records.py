"""The intake's operational records (contracts §4.6): pure models.

Files and deliveries, pipeline runs, the mapping cache, coverage, checks, requirement status, the scorecard and the
review's records. Each is a line of an append-only, hash-chained log (`intake_store`) or a file beside it. The review
records carry who, when and why; none has a signature of its own: the confirmation binds them (§6.6).
(RequirementDisposition, not Disposition: the plan routes already publish a schema named Disposition.)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modeler_intake.mapping_spec import MappingSpec
from modeler_intake.source_model import AnchorProblem, ContainerRef, DocState, OutsideItem, Region
from modeler_project.ledger_models import Conflict, MappingUse, PendingLink


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)      # no NaN: it has no JSON form


# --- files and runs ------------------------------------------------------------------------------------------------


class FileRecord(_B):
    file_id: str                              # "fl-" + sha256[:12]
    sha256: str
    name: str
    size_bytes: int
    delivery: str                             # "dl-<seq>", one per arrival request
    container: ContainerRef | None = None
    repeat: bool = False                      # the same bytes arrived before
    # what today's ingest did with it: None on the `file` line, filled from the file's later `legacy` line by intake_files.files()
    legacy_sid: str | None = None
    legacy_refusal: str | None = None
    by: str
    at: str


StageName = Literal["parse", "map", "map_llm", "execute", "prose", "ledger", "compute", "checks", "coverage"]


class StageTiming(_B):
    stage: StageName
    seconds: float
    ok: bool
    detail: str = ""


class RunCounters(_B):
    regions: int = 0
    tables: int = 0
    mapped_by_cache: int = 0
    mapped_by_rule: int = 0
    mapped_by_llm: int = 0
    unmapped: int = 0
    values: int = 0
    facts: int = 0
    outside_items: int = 0
    needs_ocr_pages: int = 0
    anchors_checked: int = 0
    anchors_unresolved: int = 0
    llm_runs: int = 0


class CoverageSummary(_B):
    """Here a "numeric cell" is a cell with a number (has_number, §4.2), not only a bare number."""

    state: DocState
    reason: str = ""
    regions: int
    regions_mapped: int
    regions_excluded: int
    regions_unread: int
    numeric_cells: int                        # cells with a number, of mapped tables
    cells_used: int
    cells_excluded: int
    cells_silent: int
    silent_loss: int                          # cells_silent + the cells with a number of unread table and table_like_text regions
    outside_items: int
    outside_numeric: int = 0                  # outside items with a number, not furniture, not cited by a constant, not accepted
    values_unassigned: int = 0                # active values of this file with no study, not assigned or excluded
    needs_ocr_pages: tuple[int, ...] = ()
    anchors_unresolved: int = 0


class RunRecord(_B):
    """One line per state change of a run; the latest line of a run_id is its state."""

    run_id: str
    file_id: str
    sha256: str
    delivery: str
    state: Literal["queued", "running", "done", "failed"]
    attempt: int = 0
    queued_at: str
    started_at: str | None = None
    finished_at: str | None = None
    by: str
    parser: str | None = None
    parser_version: str | None = None
    source_sha256: str | None = None
    stages: tuple[StageTiming, ...] = ()
    counters: RunCounters = RunCounters()
    coverage: CoverageSummary | None = None
    ledger_head: str | None = None
    agent_runs: tuple[str, ...] = ()
    error: str = ""


# --- the mapping cache ---------------------------------------------------------------------------------------------


class MappingEntry(_B):
    mapping_id: str                           # "mp-" + fingerprint[:12]
    version: int
    fingerprint: str
    spec: MappingSpec
    origin: Literal["rule", "llm", "person"]
    origin_detail: str                        # rule name and version | provider/model + prompt sha256 + agent run | user id
    first_seen: tuple[str, str]               # (file sha256, region id)
    by: str
    at: str


class MappingDecision(_B):
    mapping_id: str
    version: int
    status: Literal["approved", "rejected"]
    why: str = ""
    by: str
    at: str


# --- coverage ------------------------------------------------------------------------------------------------------


class RegionOutcome(_B):
    """Stored compactly (the full cell_use stays in memory): what D5 counts, with no grid."""

    region_id: str
    state: Literal["mapped", "excluded", "unread"]
    reason: str = ""
    mapping: MappingUse | None = None
    origin: Literal["cache", "rule", "llm", "person"] | None = None
    numeric_cells: int = 0                    # cells with a number in the region (merged copies not counted)
    uses: dict[str, int] = Field(default_factory=dict)        # CellUse.use -> cells with a number put to that use
    unaccounted: tuple[str, ...] = ()         # locators (at most 200)
    unaccounted_count: int = 0                # and the true count
    cited: tuple[str, ...] = ()               # context-line locators its constants read
    decimal: Literal["point", "comma"] | None = None


class RegionCoverage(_B):
    region: Region
    outcome: RegionOutcome
    numeric_cells: int
    used: int
    excluded: int
    silent: tuple[str, ...]                   # locators of unaccounted numeric cells (at most 200)
    silent_count: int


class FileCoverage(_B):
    """coverage/<sha>.json is the CURRENT truth (recomputed by exclude_regions and assign); a run line's summary is a
    snapshot "at run end"."""

    file: FileRecord
    summary: CoverageSummary
    regions: tuple[RegionCoverage, ...]
    outside: tuple[OutsideItem, ...]
    anchor_problems: tuple[AnchorProblem, ...]
    decisions: tuple[str, ...] = ()           # the RegionDecision ids applied
    computed_at: str


# --- checks, requirements, the scorecard ---------------------------------------------------------------------------


class CheckResult(_B):
    id: str                                   # "ck-" + sha256(code + subject + sorted(values) + detail key)[:12]
    code: str
    severity: Literal["fail", "warn", "info"]
    subject_type: Literal["study", "product", "compound", "file"]
    subject: str
    message: str
    values: tuple[str, ...] = ()
    rule: str = ""                            # the key of intake_rules.yaml it applied


class SchemaGap(_B):
    study: str
    tag: str
    value: str
    reason: str


class RequirementStatus(_B):
    req_id: str
    template: str
    label: str
    scope: Literal["study", "product", "project"]
    subject: str | None
    criticality: str
    applies: Literal["yes", "no", "undetermined"]
    status: Literal["found", "conflicting", "missing", "ask_client", "literature", "not_needed", "not_applicable"]
    values: tuple[str, ...] = ()
    disposition: str | None = None


class Routing(_B):
    study: str
    tags: dict[str, str]
    templates: tuple[str, ...]
    gaps: tuple[SchemaGap, ...]


class StudyRequirements(_B):
    routing: Routing
    items: tuple[RequirementStatus, ...]


class Blocker(_B):
    code: Literal["SILENT_LOSS", "OUTSIDE_NUMBERS", "UNASSIGNED_VALUES", "SCHEMA_GAP", "CHECK_FAILED", "LINK_UNCONFIRMED",
                  "SPOT_CHECK", "LOADED_ON_CLIENT_REVIEW", "BLINDED"]
    detail: str
    ids: tuple[str, ...] = ()


class Scorecard(_B):
    subject_type: Literal["study", "product", "compound"]
    subject: str
    label: str
    coverage: tuple[CoverageSummary, ...]
    silent_loss: int
    requirements: tuple[RequirementStatus, ...]
    gaps: tuple[SchemaGap, ...]
    checks: tuple[CheckResult, ...]
    overridden: tuple[str, ...]               # check ids cleared by an override or a disposition
    conflicts: tuple[Conflict, ...]
    links: tuple[PendingLink, ...]
    values: int
    by_level: dict[str, int]
    by_method: dict[str, int]
    blockers: tuple[Blocker, ...]             # D5: all but SPOT_CHECK, LOADED_ON_CLIENT_REVIEW and BLINDED, which D6 adds


# --- review.jsonl: who, when, why on every line ---------------------------------------------------------------------


class Override(_B):                          # ov-n
    id: str
    subject: str
    check_id: str
    why: str = Field(min_length=1)
    by: str
    at: str


class RequirementDisposition(_B):            # dp-n; review.jsonl kind `disposition`
    id: str
    subject: str
    req_id: str
    disposition: Literal["ask_client", "literature", "not_needed"]
    why: str = Field(min_length=1)
    by: str
    at: str


class Choice(_B):                            # ch-n
    id: str
    conflict_id: str
    keep: str
    why: str = Field(min_length=1)
    by: str
    at: str


class LinkConfirmation(_B):                  # lk-n; per (study, file); an ambiguous link: `study` is the one chosen
    id: str
    link_fact: str | None
    study: str
    file_sha256: str
    confirmed: bool
    why: str = ""
    by: str
    at: str


class Assignment(_B):                        # as-n; values with no study (fact, extract or value ids)
    """A person gives values their subject: a study (and its arm), a product (and its batch), or both. A study
    assignment sets the study and the arm, as before (an arm left out clears it); a product assignment sets the product
    and the batch. At least one of study or product; an arm needs its study, a batch its product (§13)."""

    id: str
    targets: tuple[str, ...]
    study: str | None = None
    arm: str | None = None
    product: str | None = None
    batch: str | None = None
    why: str = Field(min_length=1)
    by: str
    at: str

    @model_validator(mode="after")
    def _names_a_subject(self) -> Assignment:
        if self.study is None and self.product is None:
            raise ValueError("an assignment names a study or a product")
        if self.arm is not None and self.study is None:
            raise ValueError("an arm is assigned with its study")
        if self.batch is not None and self.product is None:
            raise ValueError("a batch is assigned with its product")
        return self

    def entity_update(self) -> dict[str, str | None]:
        """The entity parts this assignment sets: study and arm, product and batch, each pair only when named."""
        update: dict[str, str | None] = {}
        if self.study is not None:
            update.update(study=self.study, arm=self.arm)
        if self.product is not None:
            update.update(product=self.product, batch=self.batch)
        return update


class RegionDecision(_B):                    # rd-n
    id: str
    file_sha256: str
    parser_version: str
    regions: tuple[str, ...]
    scope: Literal["regions", "unread_prose", "figures", "outside"] = "regions"   # outside: `regions` lists the outside
    why: str = Field(min_length=1)                                                # items' locators accepted as not data
    by: str
    at: str


class SpotCheckDraw(_B):                     # sd-n
    id: str
    subject_type: str
    subject: str
    seed: str
    subject_digest: str
    rules_version: str
    heads: dict[str, str]                    # facts, entities, mappings, review: each log's head hash, and the rules file's sha256
    always: tuple[str, ...]
    sampled: tuple[str, ...]
    strata: dict[str, str]                   # value id -> stratum (or "always:<reason>")
    carried: dict[str, str] = Field(default_factory=dict)   # value id -> the earlier spot check that ticked it
    by: str
    at: str


class SpotTick(_B):                          # one tick covers value, unit, time, labels and statistic
    value_id: str
    ok: bool
    note: str = ""


class SpotCheckRecord(_B):                   # sc-n
    id: str
    draw_id: str
    ticks: tuple[SpotTick, ...]
    by: str
    at: str


class Confirmation(_B):                      # cf-n
    id: str
    subject_type: Literal["study", "product", "compound"]
    subject: str
    record_sha256: str
    record: dict[str, Any]                   # the canonical record the hash and the signature bind (§6.6)
    signature_id: str
    manifestation: str
    by: str
    printed_name: str
    at: str
    supersedes: str | None = None


class Landed(_B):
    confirmation: str
    datasets: tuple[str, ...]
    evidence: tuple[str, ...]
    dissolution_records: int
    rejected_legacy: tuple[str, ...]
    pending: tuple[str, ...]                 # "<what>: <reason>" for each thing not landed or landed PROPOSED
    at: str
