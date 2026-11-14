"""The intake pipeline: its run queue and its stage runner (contracts §6.5; build W; plan G2, G7).

Every file that arrives (`intake_files.record_arrival`) gets one run, queued in `intake/runs.jsonl` (a hash-chained
log of `RunRecord` lines: the latest line of a run id is its state). The project's `intake` job (`API/
intake_pipeline_jobs`) takes the runs one after the other and `run_file` reads each file through every stage, with or
without a model:

    parse     the parser and its version (`source.parser_for`); the source cache, else `parse_document` and
              `put_source`. When the file has values read under another parser version: `check_anchors` against the
              new document (the problems go to the run and to the coverage)
    map       per table region: its layout fingerprint, then the first of (contract §13, the integrator's decision):
              1. the mapping cache's APPROVED versions of the layout (`MappingCache.candidates`) that have no error
                 from `validate_spec` on this region (every constant and unit re-read from it); among several, the
                 one that leaves the fewest cells with a number unaccounted, then the one that reads the most
                 constants, then the newest. A person approved the layout's reading, so it governs;
              2. the rules, recomputed on every run (`map_by_rule`: the client-data template's sheets by
                 `template_spec`, then today's no-AI reading). The spec is proposed to the cache (an equal spec is
                 its stored version: a re-run appends nothing); a version a person rejected is never executed;
              3. a PROPOSED version of the cache that no rule made (an earlier table mapper's or a person's spec),
                 chosen the same way. A proposed RULE version is never taken from the cache in place of the table's
                 own rule spec: one made for another table of the layout can validate here and read less
    map_llm   the regions left, through `LlmPorts.map_tables` (4 at a time, one agent run each, `A4-table-mapper`);
              skipped with no model: each stays `unread`, "no rule or cached mapping fits; no model is configured"
    execute   `execute` per mapped region; `coverage.outcome_from` gives its `RegionOutcome`
    prose     the prose regions through `LlmPorts.extract_prose` (one run, `A4-prose`), each fact through the strict
              check (`check_prose_fact`, a PDF span's box built from the parsed page's words); skipped with no model:
              the prose stays `unread` with that reason
    ledger    `record_extraction` per table, `record_prose`, through ONE `Ledger` for the run (it remembers what it
              has just recorded); after a re-parse, `retire_regions` with the values `check_anchors` found again: an
              extract whose table is gone is retired and listed as an anchor problem
    compute   `derive`, `link_files`
    checks    routing, requirement status and checks for the studies and products the file touched (timed for G7 and
              so a failure shows on the run; the cards recompute on read)
    coverage  `file_coverage` (with the file's unassigned values), `put_coverage`; the summary ("at run end") and the
              ledger's head into the run

Each stage is timed into a `StageTiming` and guarded: an exception ends the run `failed` at that stage, with
"<Type>: <message>", the later stages are skipped, and the run's line and its `intake.run` audit event are still
written. A problem with a file's CONTENT is never an exception: an unsupported or unreadable file ends `done` with its
state and reason, a table no mapping reads is `unread` with why, and every cell with a number of an unread table counts
as silent loss (never dropped). A model that fails is not the file's failure either: when a port raises, the tables or
the prose it was asked about stay `unread` with the error as their reason, and the deterministic stages after it still
run. Nothing here imports the agents (L4): the two LLM stages are reached through `LlmPorts`, which the API builds over
`agent_jobs`.

The queue: `enqueue` queues a file once while a run of its bytes waits or runs, and not at all when the latest run of
those bytes is done under the current parser version (the same bytes again: recorded in files.jsonl, nothing queued),
unless a person asks for the file to be read again (`again=True`: the Delivery section's re-run path);
`take` marks the first queued run `running`; `recover` puts a run left `running` (a restart) back in the queue, and
fails it after `MAX_ATTEMPTS`; `pending` says whether a run waits and `unfinished` whether one waits or was left
running; `sweep` records and queues the client files stored before the pipeline ran. Every check-then-append is one
`append_if`, so two threads never queue one file twice.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_intake.anchors import AnchorError, Box, anchor_text, parse_anchor, sha256_of
from modeler_intake.fields import FIELDS
from modeler_intake.mapping.execute import execute
from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.mapping.prose_check import ProseFactError, check_prose_fact
from modeler_intake.mapping.redact import redact
from modeler_intake.mapping.rules import map_by_rule
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import (
    ExtractResult,
    MappingError,
    MappingSpec,
    ProseCheck,
    ProseFact,
    ProseParagraph,
    RedactedTable,
)
from modeler_intake.source import check_anchors, paragraphs, parse_document, parser_for, region_grid
from modeler_intake.source.regions import page_of, span_words, union_box
from modeler_intake.source_model import AnchorProblem, Finding, Region, RegionGrid, SourceDocument
from modeler_project import intake_files
from modeler_project.brief import ProjectBrief
from modeler_project.coverage import file_coverage, outcome_from, values_unassigned
from modeler_project.intake_checks import run_checks
from modeler_project.intake_records import (
    CheckResult,
    CoverageSummary,
    FileRecord,
    MappingEntry,
    RegionDecision,
    RegionOutcome,
    RequirementDisposition,
    RunCounters,
    RunRecord,
    StageName,
    StageTiming,
)
from modeler_project.intake_store import ChainEntry, IntakeStore
from modeler_project.ledger import ExtractionContext, Ledger
from modeler_project.ledger_models import MappingUse, ModelUse
from modeler_project.mapping_cache import MappingCache
from modeler_project.requirements import RequirementMatrix
from modeler_project.study_requirements import product_requirements, requirement_status
from modeler_project.workspace import Workspace

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2                     # a run left `running` twice (two restarts) is failed, not tried a third time
STAGES: tuple[StageName, ...] = ("parse", "map", "map_llm", "execute", "prose", "ledger", "compute", "checks", "coverage")
NO_MODEL = "no rule or cached mapping fits; no model is configured"
PROSE_NO_MODEL = "prose is read by the prose extractor (A4-prose); no model is configured"
UNRULED = "an unruled table: located in the text, not read into a grid; a person reads it or marks it not data"
REJECTED_RULE = "a person rejected the rule's mapping of this layout"
REJECTED_MAPPING = "a person rejected this mapping of the layout"
_DETAIL_CHARS = 500
_SIGNATURE_BYTES = 64                # more than any signature `source.parse.file_format` looks at
# The fields the prose extractor is asked for: what a synopsis or design section states in sentences about a study, an
# arm, an analyte, a product or a batch (the dose, the subjects, the route, the fasting state, the regimen, the batch),
# with the matrix and the explicit links to another file's study. Never a table's observation: tables are mapped.
_PROSE_LEVELS = ("study", "arm", "analyte", "product", "batch")
PROSE_FIELDS: tuple[str, ...] = (
    *(name for name, d in FIELDS.items() if d.level in _PROSE_LEVELS and not name.startswith("link.") and name != "dose_unit"),
    "matrix", "link.protocol", "link.cross_reference")


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MapRequest(_B):
    """One table the table mapper is asked to map: its region and everything it is shown (redacted)."""

    region_id: str
    table: RedactedTable


class MapAnswer(_B):
    """What the table mapper gave for one region: the spec code accepted in its conversation (None: none), who made it
    (provider/model, prompt sha256, agent run) and, when there is no spec, why."""

    region_id: str
    spec: MappingSpec | None
    origin_detail: str
    agent_run: str | None
    error: str = ""


TableCheck = Callable[[str, MappingSpec], tuple[Finding, ...]]


class LlmFailure(RuntimeError):
    """What a port raises when its model gave no reading (not reachable, or cut short before any answer): the message
    says why, `agent_run` names the agent run that tried (None: none was started), so the run's line still lists it."""

    def __init__(self, message: str, agent_run: str | None = None):
        super().__init__(message)
        self.agent_run = agent_run


@dataclass(frozen=True)
class LlmPorts:
    """How L3 reaches the two LLM stages without importing L4 (the API builds it over `agent_jobs`); None: no model.
    `map_tables(requests, check)`: one answer per request, `check(region_id, spec)` judging each proposal on its own
    region's grid. `extract_prose(paragraphs, check)`: the facts the check accepted and the model that read them."""

    map_tables: Callable[[Sequence[MapRequest], TableCheck], Sequence[MapAnswer]]
    extract_prose: Callable[[Sequence[ProseParagraph], ProseCheck], tuple[Sequence[ProseFact], ModelUse | None]]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- the queue ---------------------------------------------------------------------------------------------------------


def _latest(entries: Sequence[ChainEntry]) -> dict[str, RunRecord]:
    """Each run's latest line, in the order the runs were first queued."""
    out: dict[str, RunRecord] = {}
    for entry in entries:
        if entry.kind == "run":
            record = RunRecord.model_validate(entry.body)
            out[record.run_id] = record
    return out


def runs(ws: Workspace) -> list[RunRecord]:
    """Every run in its latest state, in queue order ([] when the store has no file root)."""
    return list(_latest(IntakeStore(ws).runs.entries()).values())


def _version_of(ws: Workspace, record: FileRecord) -> str | None:
    """The parser version the file would be read with now; None when its bytes are not in the store. `parser_for`
    reads a file's name and signature only, so its first bytes are enough (nothing is parsed)."""
    path = ws.store.blob_path(ws.tenant_id, ws.project_id, record.sha256)
    if path is None:
        return None
    with open(path, "rb") as handle:
        return parser_for(handle.read(_SIGNATURE_BYTES), record.name)[1]


def enqueue(ws: Workspace, files: Sequence[FileRecord], *, by: str, again: bool = False) -> list[RunRecord]:
    """Queue one run per file, decided under the runs log's lock: never a second run of the same bytes while one waits
    or runs, and none when the latest run of those bytes is done under the current parser version (a repeat is
    recorded in files.jsonl and queues nothing). `again` (a person asks for the file to be read again: Delivery's
    "run", or a mapping approved, rejected or edited): a file whose latest run is done is queued too, as a new run
    with its own id, so what the mapping cache and the rules give now is read; a file whose run waits or runs still
    queues nothing. The runs queued now."""
    store = IntakeStore(ws)
    queued: list[RunRecord] = []
    versions: dict[str, str | None] = {}

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        latest: dict[str, RunRecord] = {}
        for run in _latest(entries).values():
            latest[run.sha256] = run                       # the last run queued for those bytes
        rows: list[tuple[str, Any]] = []
        planned: set[str] = set()
        for record in files:
            last = latest.get(record.sha256)
            if record.sha256 in planned or (last is not None and last.state in ("queued", "running")):
                continue
            if last is not None and last.state == "done" and not again:
                if record.sha256 not in versions:
                    versions[record.sha256] = _version_of(ws, record)
                if versions[record.sha256] == last.parser_version:
                    continue
            planned.add(record.sha256)

            def body(seq: int, record: FileRecord = record) -> dict[str, Any]:
                run = RunRecord(run_id=f"run-{seq}", file_id=record.file_id, sha256=record.sha256, delivery=record.delivery,
                                state="queued", queued_at=_now(), by=by)
                queued.append(run)
                return run.model_dump(mode="json")
            rows.append(("run", body))
        return rows

    store.runs.append_if(decide)
    return queued


def take(ws: Workspace) -> RunRecord | None:
    """The first queued run, marked `running` (its attempt counted); None when none waits."""
    taken: list[RunRecord] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        run = next((r for r in _latest(entries).values() if r.state == "queued"), None)
        if run is None:
            return []
        running = run.model_copy(update={"state": "running", "attempt": run.attempt + 1, "started_at": _now(),
                                         "finished_at": None})
        taken.append(running)
        return [("run", running.model_dump(mode="json"))]

    IntakeStore(ws).runs.append_if(decide)
    return taken[0] if taken else None


def recover(ws: Workspace) -> int:
    """Runs left `running` (the job stopped with them: a restart): queued again, or failed once they were started
    `MAX_ATTEMPTS` times (with their `intake.run` event). Called by the job before it takes a run, under its lease, so
    nothing else is running them. How many runs it changed."""
    store = IntakeStore(ws)
    failed: list[RunRecord] = []

    def decide(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        rows: list[tuple[str, Any]] = []
        for run in _latest(entries).values():
            if run.state != "running":
                continue
            if run.attempt >= MAX_ATTEMPTS:
                done = run.model_copy(update={"state": "failed", "finished_at": _now(),
                                              "error": f"stopped while running {run.attempt} times (a restart?): not tried again"})
                failed.append(done)
            else:
                done = run.model_copy(update={"state": "queued", "started_at": None})
            rows.append(("run", done.model_dump(mode="json")))
        return rows

    written = store.runs.append_if(decide) if store.available else []
    for entry in written:
        if entry.body.get("state") == "failed":
            run = RunRecord.model_validate(entry.body)
            _audit(store, run, entry.hash)
    return len(written)


def pending(ws: Workspace) -> bool:
    """Whether a run waits in the queue."""
    return any(r.state == "queued" for r in runs(ws))


def unfinished(ws: Workspace) -> bool:
    """Whether the job has work: a run waits, or one was left `running` (by this job while it runs; else by a job
    that stopped, for `recover`)."""
    return any(r.state in ("queued", "running") for r in runs(ws))


def sweep(ws: Workspace, *, by: str = "code") -> int:
    """The client files stored before the pipeline ran (`client_data.submissions` whose bytes no run has read): each
    recorded under one delivery (when files.jsonl does not name it yet) and queued. How many runs it queued."""
    from modeler_project.client_data import submissions  # only here: nothing else of the pipeline needs today's reader

    store = IntakeStore(ws)
    if not store.available:
        return 0
    seen = {str(e.body.get("sha256")) for e in store.runs.entries("run")}
    todo: dict[str, str] = {}
    for sub in submissions(ws):
        sha, name = str(sub.get("sha256", "")), str(sub.get("file", ""))
        if sha and sha not in seen and sha not in todo:
            todo[sha] = name
    if not todo:
        return 0
    known = {r.sha256: r for r in intake_files.files(ws)}
    records = [known[sha] for sha in todo if sha in known]
    missing = [(sha, name) for sha, name in todo.items() if sha not in known]
    if missing:
        records += intake_files.record_stored(ws, missing, by=by)
    return len(enqueue(ws, records, by=by))


# --- one run -----------------------------------------------------------------------------------------------------------


class _Stopped(Exception):
    """A stage failed: the run ends `failed` there."""


def _detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:_DETAIL_CHARS]


def _audit(store: IntakeStore, run: RunRecord, row_hash: str) -> None:
    store.audit(actor="code", action="intake.run", resource_id=run.run_id,
                after={"run": run.run_id, "file_sha256": run.sha256, "state": run.state, "row_hash": row_hash,
                       "ledger_head": run.ledger_head, "values": run.counters.values,
                       "silent_loss": run.coverage.silent_loss if run.coverage is not None else None})


def _products(brief: ProjectBrief | None) -> list[dict[str, str]]:
    """The brief's products as today's reading names them (`sheet_intake.products_of`)."""
    if brief is None:
        return []
    return [{"name": str(brief.value(f"products[{i}].name") or ""), "role": str(brief.value(f"products[{i}].role") or "")}
            for i, _item in enumerate(brief.groups.get("products", ()))]


def _unaccounted(region: Region, result: ExtractResult) -> int:
    """The cells with a number a reading of this table leaves unaccounted, as the coverage counts them
    (`coverage._region_coverage`: a cell the reading does not account for at all is unaccounted too)."""
    outcome = outcome_from(region, result, state="mapped")
    put = sum(n for use, n in outcome.uses.items() if use != "unaccounted")
    return max(outcome.unaccounted_count, outcome.numeric_cells - put)


def _constants_read(spec: MappingSpec) -> int:
    """The constants a spec with no error on a region reads there: every one it cites (`validate_spec` refuses a
    constant its cite does not state), the table's LLOQ included."""
    return len(spec.constants) + (1 if spec.lloq is not None else 0)


class _Runner:
    """One file's run through the stages (see the module docstring); `go` raises `_Stopped` at a failed stage."""

    def __init__(self, ws: Workspace, run: RunRecord, *, llm: LlmPorts | None, brief: ProjectBrief | None,
                 matrix: RequirementMatrix | None, clock: Callable[[], float]):
        self.ws, self.run, self.llm, self.brief, self.matrix, self.clock = ws, run, llm, brief, matrix, clock
        self.store = IntakeStore(ws)
        self.drug = brief.drug_name if brief is not None else ""
        self.stages: list[StageTiming] = []
        self.counters = RunCounters()
        self.error = ""
        self.file: FileRecord | None = None
        self.doc: SourceDocument | None = None
        self.parser: str | None = None
        self.version: str | None = None
        self.source_sha256: str | None = None
        self.coverage: CoverageSummary | None = None
        self.agent_runs: list[str] = []
        self.anchor_problems: list[AnchorProblem] = []
        self.reparsed = False
        self.found_again: set[str] = set()                 # the values of an earlier parser version found at their place
        self.ledger: Ledger | None = None
        self.regions: dict[str, Region] = {}
        self.grids: dict[str, RegionGrid] = {}
        self.fingerprints: dict[str, str] = {}
        self.mapped: dict[str, tuple[MappingEntry, Literal["cache", "rule", "llm"]]] = {}
        self.unread: dict[str, str] = {}
        self.left: list[str] = []
        self.results: dict[str, ExtractResult] = {}
        self.tried: dict[tuple[str, str, int], ExtractResult] = {}     # (region, mapping, version): read while choosing
        self.outcomes: dict[str, RegionOutcome] = {}
        self.prose_facts: Sequence[ProseFact] = ()
        self.prose_model: ModelUse | None = None

    def count(self, **changes: int) -> None:
        self.counters = self.counters.model_copy(update={k: getattr(self.counters, k) + v for k, v in changes.items()})

    def stage(self, name: StageName, work: Callable[[], str]) -> None:
        start = self.clock()
        try:
            detail = work()
        except Exception as exc:
            seconds = max(0.0, self.clock() - start)
            self.stages.append(StageTiming(stage=name, seconds=seconds, ok=False, detail=_detail(exc)))
            self.error = f"{name}: {_detail(exc)}"
            log.warning("intake run %s (%s) failed at %s", self.run.run_id, self.run.sha256[:12], name, exc_info=True)
            raise _Stopped from exc
        self.stages.append(StageTiming(stage=name, seconds=max(0.0, self.clock() - start), ok=True,
                                       detail=(detail or "")[:_DETAIL_CHARS]))

    def go(self) -> None:
        for name in STAGES:
            self.stage(name, getattr(self, f"_{name}"))

    # --- parse -------------------------------------------------------------------------------------------------------

    def _file_record(self) -> FileRecord:
        record = intake_files.file_record(self.ws, self.run.sha256, delivery=self.run.delivery)
        if record is None:
            raise LookupError(f"files.jsonl names no file {self.run.sha256[:12]}")
        return record

    def _parse(self) -> str:
        file = self.file = self._file_record()
        path = self.ws.store.blob_path(self.ws.tenant_id, self.ws.project_id, file.sha256)
        if path is None:
            raise FileNotFoundError(f"the bytes of {file.name} are not in the project store")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != file.sha256:
            raise ValueError(f"the stored bytes of {file.name} do not match its sha256")
        self.parser, self.version = parser_for(data, file.name)
        doc = self.store.source(file.sha256, self.parser, self.version)
        cached = doc is not None
        if doc is None:
            doc = parse_document(data, file.name, container=file.container)
            self.source_sha256 = self.store.put_source(doc)
        else:
            self.source_sha256 = sha256_of(doc)
        if (doc.parser, doc.parser_version) != (self.parser, self.version):
            raise ValueError(f"the source model is of {doc.parser}/{doc.parser_version}, not {self.parser}/{self.version}")
        self.doc = doc
        self.regions = {r.id: r for r in doc.regions}
        self.count(regions=len(doc.regions), tables=sum(1 for r in doc.regions if r.kind == "table"),
                   outside_items=len(doc.outside), needs_ocr_pages=sum(1 for p in doc.pages if p.needs_ocr))
        self.ledger = Ledger(self.ws)
        checked = self._check_anchors(doc)
        how = "from the source cache" if cached else "parsed"
        return f"{doc.state}: {len(doc.regions)} regions, {how}" + (f"; {checked} anchors of an earlier version checked"
                                                                    if self.reparsed else "")

    def _check_anchors(self, doc: SourceDocument) -> int:
        """The file's active values read under another parser version, looked for again in the new document: each with
        the anchor and the verbatim the ledger stores, as they are (a table's value: its cell and the cell's text; a
        prose fact: the value's own span and the quote that holds it, found when the quote lies over the span). The
        values found again are kept for `retire_regions`."""
        assert self.ledger is not None
        items: list[tuple[str, str, str]] = []
        for value in self.ledger.values(file_sha256=doc.file_sha256):
            if not value.anchor:
                continue
            try:
                anchor = parse_anchor(value.anchor)
            except AnchorError:                       # not an anchor: `check_anchors` lists it as not found
                items.append((value.id, value.anchor, value.verbatim or ""))
                continue
            if (anchor.parser, anchor.parser_version) != (doc.parser, doc.parser_version):
                items.append((value.id, value.anchor, value.verbatim or ""))
        if not items:
            return 0
        self.reparsed = True
        self.anchor_problems = check_anchors(doc, items)
        self.found_again = {value_id for value_id, _anchor, _text in items} - {p.id for p in self.anchor_problems}
        self.count(anchors_checked=len(items), anchors_unresolved=len(self.anchor_problems))
        return len(items)

    # --- map ---------------------------------------------------------------------------------------------------------

    def _choose(self, region: Region, versions: Sequence[MappingEntry]) -> MappingEntry | None:
        """Among these versions of the region's layout, the one to read it with: only one that has no error on this
        region's own grid (`validate_spec`); among several, the one that leaves the fewest cells with a number
        unaccounted, then the one that reads the most constants, then the newest. None when none reads here."""
        grid = self.grids[region.id]
        passing = [e for e in versions if not any(f.severity == "error" for f in validate_spec(e.spec, grid))]
        if len(passing) < 2:
            return passing[0] if passing else None
        ranked: list[tuple[tuple[int, int, int], MappingEntry]] = []
        for entry in passing:
            try:
                result = execute(entry.spec, grid)
            except MappingError:
                continue
            self.tried[(region.id, entry.mapping_id, entry.version)] = result
            ranked.append(((_unaccounted(region, result), -_constants_read(entry.spec), -entry.version), entry))
        return min(ranked, key=lambda item: item[0])[1] if ranked else None

    def _map(self) -> str:
        assert self.doc is not None and self.file is not None
        doc, file = self.doc, self.file
        cache = MappingCache(self.ws)
        products = _products(self.brief)
        for region in doc.regions:
            if region.kind == "table_like_text":
                self.unread[region.id] = UNRULED
                self.count(unmapped=1)
            if region.kind != "table":
                continue
            grid = self.grids[region.id] = region_grid(doc, region.id)
            fingerprint = self.fingerprints[region.id] = layout_fingerprint(grid)
            versions = cache.candidates(fingerprint)           # approved, then proposed; never a rejected one
            # 1. a version a person approved that reads this region
            approved = self._choose(region, [e for e, status in versions if status == "approved"])
            if approved is not None:
                self.mapped[region.id] = (approved, "cache")
                self.count(mapped_by_cache=1)
                continue
            # 2. the table's own rule spec, made anew (never a proposed rule version of another table of the layout)
            rule = map_by_rule(grid, region, filename=file.name, drug=self.drug, products=products, document_role=doc.role)
            if rule is not None:
                entry = cache.propose(fingerprint, rule.spec, origin="rule", origin_detail=rule.rule,
                                      first_seen=(file.sha256, region.id), by="code")
                if cache.status(entry.mapping_id, entry.version) != "rejected":
                    self.mapped[region.id] = (entry, "rule")
                    self.count(mapped_by_rule=1)
                    continue
                self.unread[region.id] = REJECTED_RULE
            # 3. an earlier table mapper's or a person's spec that waits for approval
            earlier = self._choose(region, [e for e, status in versions if status == "proposed" and e.origin != "rule"])
            if earlier is not None:
                self.unread.pop(region.id, None)
                self.mapped[region.id] = (earlier, "cache")
                self.count(mapped_by_cache=1)
                continue
            self.left.append(region.id)                        # 4. the table mapper, 5. else unread with the reason
        return (f"{self.counters.mapped_by_cache} by cache, {self.counters.mapped_by_rule} by rule, "
                f"{len(self.left)} left for the table mapper")

    def _map_llm(self) -> str:
        assert self.doc is not None and self.file is not None
        if not self.left:
            return "no table left"
        if self.llm is None:
            for region_id in self.left:
                reason = self.unread.get(region_id)
                self.unread[region_id] = f"{reason}; no model is configured" if reason else NO_MODEL
            self.count(unmapped=len(self.left))
            return f"skipped: no model is configured ({len(self.left)} tables unread)"
        doc, file = self.doc, self.file
        requests = [MapRequest(region_id=rid, table=redact(self.grids[rid], self.regions[rid], file_name=file.name,
                                                          document_role=doc.role)) for rid in self.left]

        def check(region_id: str, spec: MappingSpec) -> tuple[Finding, ...]:
            grid = self.grids.get(region_id)
            if grid is None:
                return (Finding(code="UNKNOWN_REGION", location=region_id, message="not a table of this request"),)
            return validate_spec(spec, grid)

        try:
            answers = {a.region_id: a for a in self.llm.map_tables(requests, check)}
        except Exception as exc:      # the model's failure is not the file's: its tables stay unread, the run goes on
            log.warning("intake run %s: the table mapper failed", self.run.run_id, exc_info=True)
            for region_id in self.left:
                self.unread[region_id] = f"the table mapper failed ({_detail(exc)})"
            self.count(unmapped=len(self.left))
            return f"the table mapper failed ({_detail(exc)}): {len(self.left)} tables unread"
        cache = MappingCache(self.ws)
        mapped = 0
        for region_id in self.left:
            answer = answers.get(region_id)
            if answer is not None and answer.agent_run:
                self.agent_runs.append(answer.agent_run)
            if answer is None:
                self.unread[region_id] = "the table mapper gave no answer for this table"
            elif answer.spec is None:
                self.unread[region_id] = f"the table mapper gave no mapping ({answer.error or 'no proposal was accepted'})"
            elif errors := [f.code for f in validate_spec(answer.spec, self.grids[region_id]) if f.severity == "error"]:
                self.unread[region_id] = f"the table mapper's mapping does not read this table ({', '.join(errors)})"
            else:
                entry = cache.propose(self.fingerprints[region_id], answer.spec, origin="llm",
                                      origin_detail=answer.origin_detail, first_seen=(file.sha256, region_id),
                                      by=f"agent:{answer.agent_run}" if answer.agent_run else "code")
                if cache.status(entry.mapping_id, entry.version) == "rejected":
                    self.unread[region_id] = REJECTED_MAPPING
                else:
                    self.unread.pop(region_id, None)
                    self.mapped[region_id] = (entry, "llm")
                    mapped += 1
        self.count(mapped_by_llm=mapped, unmapped=len(self.left) - mapped,
                   llm_runs=len({a.agent_run for a in answers.values() if a.agent_run}))
        return f"{mapped} of {len(self.left)} tables mapped by the table mapper"

    # --- execute and prose -------------------------------------------------------------------------------------------

    def _execute(self) -> str:
        values = 0
        for region_id, (entry, origin) in self.mapped.items():
            region = self.regions[region_id]
            use = MappingUse(mapping_id=entry.mapping_id, version=entry.version)
            result = self.tried.pop((region_id, entry.mapping_id, entry.version), None)
            if entry.spec.kind == "not_data":
                # recorded too (it reads nothing): what an earlier version of the mapping read here is then set aside
                self.results[region_id] = result if result is not None else execute(entry.spec, self.grids[region_id])
                self.outcomes[region_id] = outcome_from(region, None, state="excluded", mapping=use, origin=origin,
                                                        reason=f"not data: {entry.spec.not_data_reason}")
                continue
            try:
                if result is None:
                    result = execute(entry.spec, self.grids[region_id])
            except MappingError as exc:       # `validate_spec` passed, so this is not expected: counted, never dropped
                self.outcomes[region_id] = outcome_from(region, None, state="unread",
                                                        reason=f"the mapping does not read this table ({exc})")
                self.count(**{f"mapped_by_{origin}": -1, "unmapped": 1})
                continue
            self.results[region_id] = result
            self.outcomes[region_id] = outcome_from(region, result, state="mapped", mapping=use, origin=origin)
            values += len(result.rows)
        for region_id, reason in self.unread.items():
            if region_id not in self.outcomes:
                self.outcomes[region_id] = outcome_from(self.regions[region_id], None, state="unread", reason=reason)
        return f"{len(self.outcomes) - len(self.unread)} tables executed, {values} rows read"

    def _pdf_box(self, page: int, first: int, last: int) -> Box:
        assert self.doc is not None
        return union_box(w.box for w in span_words(page_of(self.doc, page), first, last))

    def _prose(self) -> str:
        assert self.doc is not None
        regions = [r for r in self.doc.regions if r.kind == "prose"]
        if not regions:
            return "no prose"
        if self.llm is None:
            for region in regions:
                self.outcomes[region.id] = outcome_from(region, None, state="unread", reason=PROSE_NO_MODEL)
            return f"skipped: no model is configured ({len(regions)} prose regions unread)"
        shown: list[ProseParagraph] = []
        for region in regions:
            for paragraph in paragraphs(self.doc, region.id):     # numbered across the file: the model's handle on each
                shown.append(paragraph.model_copy(update={"index": len(shown) + 1}))
        by_index = {p.index: p for p in shown}

        def check(field: str, value: Any, quote: str, paragraph: int, study: str | None, arm: str | None) -> ProseFact:
            found = by_index.get(paragraph)
            if found is None:
                raise ProseFactError(f"paragraph {paragraph} is not one of the paragraphs shown")
            return check_prose_fact(field, value, quote, found, study=study, arm=arm, pdf_box=self._pdf_box)

        facts: Sequence[ProseFact] = ()
        model: ModelUse | None = None
        why = "the prose extractor did not read this prose"
        if not shown:
            why = "the prose holds no paragraph to read"
        else:
            try:
                facts, model = self.llm.extract_prose(shown, check)
            except Exception as exc:      # the model's failure is not the file's: the prose stays unread, the run goes on
                log.warning("intake run %s: the prose extractor failed", self.run.run_id, exc_info=True)
                why = f"the prose extractor failed ({_detail(exc)})"
                if isinstance(exc, LlmFailure) and exc.agent_run:
                    self.agent_runs.append(exc.agent_run)
                    self.count(llm_runs=1)
        if model is not None:
            self.agent_runs.append(model.agent_run)
            self.count(llm_runs=1)
            self.prose_facts, self.prose_model = tuple(facts), model
        for region in regions:
            if model is None:
                self.outcomes[region.id] = outcome_from(region, None, state="unread", reason=why)
            else:
                self.outcomes[region.id] = outcome_from(region, None, state="mapped", origin="llm",
                                                        reason=f"read by the prose extractor (run {model.agent_run})")
        return f"{len(self.prose_facts)} facts from {len(shown)} paragraphs" if model is not None else why

    # --- ledger, compute, checks, coverage ---------------------------------------------------------------------------

    def _context(self) -> ExtractionContext:
        assert self.doc is not None and self.file is not None and self.parser and self.version
        return ExtractionContext(delivery=self.run.delivery, run_id=self.run.run_id, file=self.file, parser=self.parser,
                                 parser_version=self.version, document_role=self.doc.role, drug=self.drug)

    def _ledger(self) -> str:
        assert self.ledger is not None and self.doc is not None and self.file is not None
        context = self._context()
        values = facts = 0
        for region_id, result in self.results.items():
            entry, _origin = self.mapped[region_id]
            recorded = self.ledger.record_extraction(region=self.regions[region_id], grid=self.grids[region_id],
                                                     mapping=entry, result=result, context=context)
            if recorded.extract is not None:
                values += self.store.extract(recorded.extract).n
            facts += len(recorded.facts)
        if self.prose_facts and self.prose_model is not None:
            facts += len(self.ledger.record_prose(facts=self.prose_facts, model=self.prose_model, context=context).facts)
        retired = 0
        if self.reparsed:
            assert self.version is not None
            listed = {p.id.split("#", 1)[0] for p in self.anchor_problems}
            # the same Ledger that has just recorded (it keeps what it read again), with the values found at their place
            for change in self.ledger.retire_regions(file_sha256=self.file.sha256, parser_version=self.version,
                                                     regions=[r.id for r in self.doc.regions], found=self.found_again):
                retired += 1
                if change.target in listed:
                    continue
                gone = self.store.extract(change.target)
                where = anchor_text(gone.file_sha256, gone.parser, gone.parser_version, gone.locator[0]) if gone.n else ""
                self.anchor_problems.append(AnchorProblem(id=change.target, anchor=where, problem="not_found"))
            self.count(anchors_unresolved=len(self.anchor_problems) - self.counters.anchors_unresolved)
        self.count(values=values, facts=facts)
        return f"{values} table values, {facts} facts" + (f"; {retired} extracts retired" if retired else "")

    def _compute(self) -> str:
        assert self.ledger is not None
        context = self._context()
        derived = self.ledger.derive(context=context)
        merged = self.ledger.link_files(context=context)
        return f"{len(derived)} derived, {len(merged)} merged"

    def _checks(self) -> str:
        assert self.ledger is not None and self.file is not None
        reader = self.ledger
        reader.refresh()
        values = reader.values(file_sha256=self.file.sha256)
        studies = sorted({v.entity.study for v in values if v.entity.study})
        products = sorted({v.entity.product for v in values if v.entity.product})
        compound = bool(reader.values(file_sha256=self.file.sha256, compound=True))
        dispositions = [RequirementDisposition.model_validate(e.body) for e in self.store.review.entries("disposition")]
        parents = (self.drug,) if self.drug else ()
        results: list[CheckResult] = []
        for study in studies:
            items = requirement_status(reader, study, brief=self.brief, matrix=self.matrix, dispositions=dispositions).items
            results += run_checks(reader, subject_type="study", subject=study, requirements=items, parent_names=parents)
        for product in products:
            items = product_requirements(reader, product, brief=self.brief, matrix=self.matrix, dispositions=dispositions)
            results += run_checks(reader, subject_type="product", subject=product, requirements=items, parent_names=parents)
        if compound:
            results += run_checks(reader, subject_type="compound", subject="compound", parent_names=parents)
        failing = sum(1 for r in results if r.severity == "fail")
        return (f"{len(studies)} studies, {len(products)} products{', the compound' if compound else ''}: "
                f"{len(results)} results, {failing} failing")

    def _coverage(self) -> str:
        assert self.ledger is not None and self.doc is not None and self.file is not None
        decisions = [RegionDecision.model_validate(e.body) for e in self.store.review.entries("region")]
        self.ledger.refresh()
        unassigned = values_unassigned(self.ledger, self.file.sha256)
        covered = file_coverage(self.file, self.doc, list(self.outcomes.values()), decisions, self.anchor_problems,
                                values_unassigned=unassigned)
        self.store.put_coverage(covered)
        self.coverage = covered.summary
        s = covered.summary
        return (f"{s.regions_mapped} mapped, {s.regions_excluded} excluded, {s.regions_unread} unread; silent loss "
                f"{s.silent_loss}, outside numbers {s.outside_numeric}, unassigned values {s.values_unassigned}")

    # --- the run's line -----------------------------------------------------------------------------------------------

    def finish(self) -> RunRecord:
        """The run's last line (done, or failed with the stage and why) and its `intake.run` audit event."""
        try:
            head: str | None = self.store.facts.head().hash
        except Exception:      # a broken ledger log does not stop the run's own line
            log.exception("intake run %s: the ledger's head could not be read", self.run.run_id)
            head = None
        final = self.run.model_copy(update={
            "state": "failed" if self.error else "done", "finished_at": _now(), "parser": self.parser,
            "parser_version": self.version, "source_sha256": self.source_sha256, "stages": tuple(self.stages),
            "counters": self.counters, "coverage": self.coverage, "ledger_head": head,
            "agent_runs": tuple(dict.fromkeys(self.agent_runs)), "error": self.error})
        try:
            entry = self.store.runs.append("run", final.model_dump(mode="json"))
        except Exception:      # the run stays `running`: `recover` queues it again, or fails it after MAX_ATTEMPTS
            log.exception("intake run %s: its last line could not be written", self.run.run_id)
            return final
        try:
            _audit(self.store, final, entry.hash)
        except Exception:
            log.exception("intake run %s: its audit event could not be written", self.run.run_id)
        return final


def run_file(ws: Workspace, run: RunRecord, *, llm: LlmPorts | None = None, brief: ProjectBrief | None = None,
             matrix: RequirementMatrix | None = None, clock: Callable[[], float] = time.monotonic) -> RunRecord:
    """Read one file through every stage (the module docstring) and write the run's last line and its audit event; the
    run as it ended. Never raises: a stage that fails ends the run `failed` at that stage."""
    runner = _Runner(ws, run, llm=llm, brief=brief, matrix=matrix, clock=clock)
    try:
        runner.go()
    except _Stopped:
        pass
    except Exception as exc:      # outside every stage: a bug in the runner itself
        log.exception("intake run %s failed", run.run_id)
        runner.error = runner.error or f"run: {_detail(exc)}"
    return runner.finish()
