"""The intake's stores and the ledger's read side (contracts §4.5, §4.7, §5): hash-chained logs, the source, extract
and coverage files that open only listed names, `LedgerView`'s fold, the synthetic truth written into a ledger, and the
rules file pinned to its version."""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from modeler_intake import synthetic
from modeler_intake.anchors import AnchorError, anchor_text, canonical, parse_anchor, parse_locator, same_place, sha256_of
from modeler_intake.source_model import SourceDocument
from modeler_project.intake_fixtures import PARSER_VERSION, TRUTH_MODEL, truth_key, write_truth
from modeler_project.intake_records import (
    Assignment,
    Confirmation,
    CoverageSummary,
    FileCoverage,
    FileRecord,
    LinkConfirmation,
    MappingDecision,
    MappingEntry,
    StageTiming,
)
from modeler_project.intake_rules import RULES_SHA256, RULES_STATUS, RULES_VERSION, IntakeRules, rules
from modeler_project.intake_store import ChainedLog, IntakeStore
from modeler_project.ledger_models import (
    Entity,
    EntityRef,
    ExtractRef,
    Fact,
    MappingUse,
    Merge,
    StatusChange,
    TableExtract,
)
from modeler_project.ledger_view import LedgerReader, LedgerView, is_spread_fact
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

# The rules file's sha256 for each version: an edit without a version bump fails here (contracts §4.7)
PINNED_RULES = {"0.1": "a861d218d5d893b6051f08fe9c730bb24ced1f17e7520ce85f5e1772042b5f77"}
SRC = Path(__file__).resolve().parents[1] / "src"
A, B = "a" * 64, "b" * 64
AT = "2026-11-12T10:00:00.000Z"


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


# --- the chained log -----------------------------------------------------------------------------------------------


def _log(tmp_path: Path, n: int = 4) -> ChainedLog:
    log = ChainedLog(tmp_path / "intake" / "test.jsonl")
    for i in range(n):
        log.append("fact" if i % 2 else "status", {"i": i, "text": "µ", "nested": {"x": [1.5, None]}})
    return log


def test_a_chain_verifies_and_each_line_carries_its_hash(tmp_path):
    log = _log(tmp_path)
    assert log.verify() == []
    entries = log.entries()
    assert [e.seq for e in entries] == [1, 2, 3, 4] and [e.kind for e in log.entries("fact")] == ["fact", "fact"]
    prev = "0" * 64
    for entry in entries:
        assert entry.prev == prev
        payload = canonical({"seq": entry.seq, "at": entry.at, "kind": entry.kind, "body": entry.body})
        assert entry.hash == hashlib.sha256((prev + "\n" + payload).encode("utf-8")).hexdigest()
        prev = entry.hash
    assert log.head().seq == 4 and log.head().hash == prev
    assert ChainedLog(tmp_path / "none.jsonl").head().model_dump() == {"seq": 0, "hash": "0" * 64}
    line = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert list(line) == ["seq", "at", "kind", "body", "prev", "hash"] and line["at"].endswith("Z")
    made = log.append("fact", lambda seq: {"id": f"f-{seq}"})                    # a body made from the line's seq
    assert made.body == {"id": "f-5"} and made.seq == 5


def _rewrite(log: ChainedLog, lines: list[str]) -> None:
    log.path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def test_an_edited_removed_or_swapped_line_is_found(tmp_path):
    log = _log(tmp_path)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[1])
    edited["body"]["i"] = 99
    _rewrite(log, [lines[0], json.dumps(edited), *lines[2:]])
    assert [(p.seq, p.problem) for p in log.verify()] == [(2, "hash")]
    _rewrite(log, [lines[0], *lines[2:]])
    assert {p.problem for p in log.verify()} == {"seq", "prev"}
    _rewrite(log, [lines[0], lines[2], lines[1], lines[3]])
    assert {p.problem for p in log.verify()} >= {"seq", "prev"}
    _rewrite(log, [lines[0], "not json", *lines[2:]])
    assert (2, "hash") in [(p.seq, p.problem) for p in log.verify()]
    with pytest.raises(ValueError):
        log.entries()


def test_a_torn_tail_is_ignored_and_repaired_by_the_next_append(tmp_path, caplog):
    log = _log(tmp_path)
    with open(log.path, "ab") as handle:
        handle.write(b'{"seq": 5, "at": "2026-11-12T')
    assert [p.problem for p in log.verify()] == ["torn_tail"]
    assert len(log.entries()) == 4 and log.head().seq == 4
    entry = log.append("fact", {"after": "repair"})
    assert entry.seq == 5 and log.verify() == [] and len(log.entries()) == 5
    assert "torn last line" in caplog.text
    with open(log.path, "ab") as handle:                                      # a whole line, cut before its newline
        handle.write(log.path.read_bytes().splitlines()[-1].replace(b'"seq":5', b'"seq":6'))
    assert [p.problem for p in log.verify()] == ["torn_tail"]
    assert log.append("fact", {"after": "second repair"}).seq == 6 and log.verify() == []
    # a whole line (ended by its newline) that is not a log line is corruption, never a torn tail: it is reported,
    # reading raises, and nothing is appended after it (an acknowledged line is never cut)
    with open(log.path, "ab") as handle:
        handle.write(b"{broken\n")
    assert [(p.seq, p.problem) for p in log.verify()] == [(7, "hash")]
    size = log.path.stat().st_size
    with pytest.raises(ValueError):
        log.append("fact", {"after": "corruption"})
    with pytest.raises(ValueError):
        log.entries()
    assert log.path.stat().st_size == size


def test_a_non_finite_number_is_refused_before_anything_is_written(tmp_path):
    log = ChainedLog(tmp_path / "intake" / "nan.jsonl")
    log.append("fact", {"value": 1.5})
    size = log.path.stat().st_size
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            log.append("fact", {"value": bad})
    assert log.path.stat().st_size == size and log.verify() == []
    for bad in (float("nan"), float("inf")):                                  # refused where it enters, too
        with pytest.raises(ValidationError):
            Fact(id="f-1", delivery="dl-1", entity=EntityRef(), field="dose", value=bad, method="person", by="u", at=AT)
        with pytest.raises(ValidationError):
            StageTiming(stage="parse", seconds=bad, ok=True)


_WRITER = """
import sys
sys.path.insert(0, {src!r})
from pathlib import Path
from modeler_project.intake_store import ChainedLog
log = ChainedLog(Path({path!r}))
for i in range({n}):
    log.append("fact", {{"writer": {who!r}, "i": i}})
"""


def test_two_processes_appending_lose_nothing(tmp_path):
    path = tmp_path / "intake" / "shared.jsonl"
    n = 40
    procs = [subprocess.Popen([sys.executable, "-c", _WRITER.format(src=str(SRC), path=str(path), n=n, who=who)])
             for who in ("left", "right")]
    assert [p.wait(timeout=120) for p in procs] == [0, 0]
    log = ChainedLog(path)
    assert log.verify() == []
    entries = log.entries()
    assert len(entries) == 2 * n and [e.seq for e in entries] == list(range(1, 2 * n + 1))
    for who in ("left", "right"):
        assert [e.body["i"] for e in entries if e.body["writer"] == who] == list(range(n))


def test_append_if_decides_under_the_lock(tmp_path):
    log = ChainedLog(tmp_path / "intake" / "once.jsonl")
    barrier = threading.Barrier(2)

    def decide(entries):
        if any(e.kind == "entity" for e in entries):
            return []
        time.sleep(0.05)                                     # a window in which the other thread would also decide
        return [("entity", lambda seq: {"id": f"st-{seq}"})]

    def run():
        barrier.wait()
        log.append_if(decide)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [e.body for e in log.entries()] == [{"id": "st-1"}]
    assert log.append_if(lambda entries: []) == []


def test_a_store_without_a_root_is_off():
    class Memory:
        pass

    ws = Workspace(Memory(), "t1", "p1")                     # type: ignore[arg-type]
    store = IntakeStore(ws)
    assert not store.available and store.facts.entries() == [] and store.facts.verify() == []
    with pytest.raises(RuntimeError):
        store.facts.append("fact", {})
    assert LedgerView(ws).values() == [] and LedgerView(ws).head().seq == 0


# --- no path is built from input -----------------------------------------------------------------------------------


def _document(sha: str = A, version: str = "1.0+test") -> SourceDocument:
    return SourceDocument(file_sha256=sha, name="x.csv", size_bytes=3, format="csv", parser="delimited",
                          parser_version=version, state="read")


def _coverage(sha: str) -> FileCoverage:
    record = FileRecord(file_id=f"fl-{sha[:12]}", sha256=sha, name="x.csv", size_bytes=3, delivery="dl-1", by="u", at=AT)
    summary = CoverageSummary(state="read", regions=0, regions_mapped=0, regions_excluded=0, regions_unread=0,
                              numeric_cells=0, cells_used=0, cells_excluded=0, cells_silent=0, silent_loss=0, outside_items=0)
    return FileCoverage(file=record, summary=summary, regions=(), outside=(), anchor_problems=(), computed_at=AT)


def test_the_store_opens_only_listed_names(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    other = Workspace(FileProjectStore(tmp_path), "t1", "p2")
    store, foreign = IntakeStore(ws), IntakeStore(other)
    doc = _document()
    assert store.put_source(doc) == hashlib.sha256(canonical(doc).encode()).hexdigest()
    assert store.source(A, "delimited", "1.0+test") == doc and store.source_versions(A) == [("delimited", "1.0+test")]
    foreign.put_source(_document(B))
    foreign.put_coverage(_coverage(B))
    foreign.files.append("file", _coverage(B).file.model_dump(mode="json"))
    escape = "../../p2/intake"
    for sha in ("..", "/", f"{escape}/source/{B}", B.upper(), B):
        assert store.source(sha, "delimited", "1.0+test") is None
        assert store.coverage(sha) is None
        assert store.source_versions(sha) == []
    for parser, version in (("../delimited", "1.0+test"), ("delimited", "../../p2"), ("delimited", "/etc"),
                            ("delimited", "1.0+other")):
        assert store.source(A, parser, version) is None
    for extract_id in ("..", "/", f"{escape}/ledger/extracts/x", "tx-../../p2/ledger", "tx-0123456789abcdef"):
        with pytest.raises(KeyError):
            store.extract(extract_id)
    for bad in (_document(".."), _document(A, "../x"), _document("/" + A[1:])):
        with pytest.raises(AnchorError):
            store.put_source(bad)
    with pytest.raises(AnchorError):
        store.put_coverage(_coverage("../x"))
    # a file at the right path is still not opened unless a log line names it
    store.put_coverage(_coverage(A))
    assert store.coverage(A) is None
    store.files.append("file", _coverage(A).file.model_dump(mode="json"))
    assert store.coverage(A) == _coverage(A)
    extract = _extract(A, ("st-1",), (1.0, 2.0))
    extract_id, content = store.put_extract(extract)
    assert extract_id == "tx-" + content[:16] and content == hashlib.sha256(canonical(extract).encode()).hexdigest()
    with pytest.raises(KeyError):
        store.extract(extract_id)                            # written, but no `extract` line names it yet
    assert store.put_extract(extract) == (extract_id, content)                 # write-once: the same answer
    path = store.base / "ledger" / "extracts" / f"{extract_id}.json.gz"
    assert gzip.decompress(path.read_bytes()).decode() == canonical(extract)


def test_a_mapping_entry_line_reads_back_whichever_way_it_was_dumped(tmp_path):
    entry = MappingEntry(mapping_id="mp-000000000001", version=1, fingerprint="f" * 64, spec=synthetic.INDIVIDUAL_SPEC,
                         origin="rule", origin_detail="rules-1", first_seen=(A, "rg-0000000001"), by="code", at=AT)
    log = ChainedLog(tmp_path / "intake" / "mappings.jsonl")
    for body in (entry.model_dump(mode="json"), entry.model_dump(mode="json", by_alias=True)):
        line = log.append("entry", body)
        assert MappingEntry.model_validate(line.body) == entry
    assert log.verify() == []


def test_the_audit_helper_writes_one_intake_event(ws):
    IntakeStore(ws).audit(actor="code", action="intake.run", resource_id="run-1", after={"run": "run-1"})
    (record,) = ws.store.audit("t1").records()
    assert (record.event.action, record.event.resource_type, record.event.resource_id) == ("intake.run", "intake", "p1/run-1")
    assert record.event.after == {"run": "run-1"}


# --- the fold ------------------------------------------------------------------------------------------------------


def _extract(sha: str, studies: tuple[str, ...], values: tuple[float, ...], *, mapping: str = "mp-000000000001",
             sheet: str = "T", start: int = 2) -> TableExtract:
    n = len(values)
    nothing = (None,) * n
    return TableExtract(
        file_sha256=sha, parser="workbook", parser_version="1.0", region_id="rg-0000000001",
        mapping=MappingUse(mapping_id=mapping, version=1), kind="pk_summary", decimal="point",
        entities=tuple(EntityRef(study=s, analyte="an-1", matrix="plasma") for s in studies),
        entity_locators=tuple({"study": f"s:'{sheet}'!A1"} for _ in studies), fields=("concentration",), units=("ng/mL",),
        conditions=(), condition_locators=(), n=n, entity_ix=(0,) * n, field_ix=(0,) * n, unit_ix=(0,) * n,
        condition_ix=nothing, time=tuple(float(i) for i in range(n)), time_unit=("h",) * n, time_actual=nothing,
        value=values, verbatim=tuple(str(v) for v in values), censored=(False,) * n, lloq=nothing, lloq_unit=nothing,
        uloq=nothing, statistic=("arithmetic_mean",) * n, spread=nothing, spread_kind=nothing, n_at=nothing,
        interval_low=nothing, interval_high=nothing, interval_kind=nothing, interval_level=nothing,
        locator=tuple(f"s:'{sheet}'!B{start + i}" for i in range(n)),
        time_locator=tuple(f"s:'{sheet}'!A{start + i}" for i in range(n)), time_actual_locator=nothing,
        unit_locator=(f"s:'{sheet}'!B1",) * n, spread_locator=nothing, n_locator=nothing, lloq_locator=nothing,
        interval_locator=nothing)


class _Book:
    """A small ledger written line by line, as the ledger's writes would."""

    def __init__(self, ws: Workspace):
        self.store = IntakeStore(ws)

    def entity(self, id: str, label: str, sha: str | None) -> None:
        source = anchor_text(sha, "workbook", "1.0", "s:'T'!A1") if sha else None
        self.store.entities.append("entity", Entity(id=id, type="study", label=label, key=label.upper(), source=source,
                                                     by="code", at=AT).model_dump(mode="json"))

    def fact(self, field: str, value, *, study: str | None, sha: str | None = A, cell: str = "C1", method: str = "cell",
             supersedes: str | None = None, mapping: str | None = None, derived_from: tuple[str, ...] = ()) -> str:
        def body(seq: int) -> dict:
            return Fact(id=f"f-{seq}", delivery="dl-1", entity=EntityRef(study=study), field=field, value=value, unit="mg",
                        anchor=anchor_text(sha, "workbook", "1.0", f"s:'T'!{cell}") if sha else None, method=method,
                        mapping=MappingUse(mapping_id=mapping, version=1) if mapping else None, supersedes=supersedes,
                        derived_from=derived_from, by="code", at=AT).model_dump(mode="json")
        return self.store.facts.append("fact", body).body["id"]

    def extract(self, extract: TableExtract, *, supersedes: tuple[str, ...] = ()) -> str:
        extract_id, content = self.store.put_extract(extract)
        ref = ExtractRef(id=extract_id, content_sha256=content, file_sha256=extract.file_sha256, region_id=extract.region_id,
                         mapping=extract.mapping, kind=extract.kind, n=extract.n,
                         studies=tuple(sorted({e.study for e in extract.entities if e.study})), products=(), delivery="dl-1",
                         run_id=None, supersedes=supersedes, by="code", at=AT)
        self.store.facts.append("extract", ref.model_dump(mode="json"))
        return extract_id

    def status(self, target: str, status: str, reason: str) -> None:
        self.store.facts.append("status", StatusChange(target=target, status=status, reason=reason, by="u", at=AT).model_dump())

    def approve(self, mapping: str) -> None:
        self.store.mappings.append("decision", MappingDecision(mapping_id=mapping, version=1, status="approved", by="u",
                                                               at=AT).model_dump())

    def review(self, kind: str, record) -> None:
        self.store.review.append(kind, record.model_dump(mode="json"))


def test_the_ledger_view_folds_supersession_exclusion_assignment_links_and_levels(ws):
    book = _Book(ws)
    book.entity("st-1", "230-23", A)                         # home file A
    book.entity("st-2", "231-24", A)
    book.entity("st-3", "230-23 copy", B)                    # merged into st-1 below
    book.approve("mp-000000000001")
    dose = book.fact("dose", 50.0, study="st-1", mapping="mp-000000000001")
    corrected = book.fact("dose", 55.0, study="st-1", sha=None, method="person", supersedes=dose)
    first = book.extract(_extract(A, ("st-1",), (1.0, 2.0)))
    second = book.extract(_extract(A, ("st-1",), (1.5, 2.5, 3.5)), supersedes=(first,))
    point = book.fact("concentration", 1.6, study="st-1", sha=None, method="person", supersedes=f"{second}#0")
    book.status(f"{second}#1", "excluded", "a re-assay")
    loose = book.fact("food_state", "fasted", study=None, cell="D1")
    unapproved = book.fact("n", 24, study="st-2", mapping="mp-000000000002", cell="E1")
    prose = book.fact("n", 12, study="st-2", method="prose", cell="F1")
    derived = book.fact("dose", 0.5, study="st-2", sha=None, method="derived", derived_from=(unapproved, prose))
    link = book.fact("link.study_id", "230-23", study="st-1", sha=B, cell="A1")
    crossed = book.fact("dose", 50.0, study="st-1", sha=B, cell="B2")
    other = book.extract(_extract(B, ("st-3",), (9.0,), mapping="mp-000000000002", sheet="U"))
    view: LedgerReader = LedgerView(ws)
    digest = view.digest(study="st-1")
    v = view.value
    assert (v(dose).status, v(dose).superseded_by, v(corrected).status) == ("superseded", corrected, "proposed")
    assert [v(f"{first}#{i}").status for i in range(2)] == ["superseded", "superseded"]
    assert v(f"{second}#0").superseded_by == point and v(f"{second}#2").status == "proposed"
    assert (v(f"{second}#1").status, v(f"{second}#1").status_reason) == ("excluded", "a re-assay")
    assert v(loose).entity.study is None and [x.id for x in view.values(unassigned=True)] == [loose]
    # levels: approved and new mappings, prose, a person's entry, a derived value at its lowest input
    assert v(f"{second}#2").level == "approved_mapping" and v(unapproved).level == "new_mapping"
    assert v(prose).level == "prose" and v(corrected).level == "person_confirmed" and v(derived).level == "prose"
    assert v(f"{second}#2").anchor == anchor_text(A, "workbook", "1.0", "s:'T'!B4")
    assert v(f"{second}#2").locators == {"time": anchor_text(A, "workbook", "1.0", "s:'T'!A4"),
                                        "unit": anchor_text(A, "workbook", "1.0", "s:'T'!B1"),
                                        "study": anchor_text(A, "workbook", "1.0", "s:'T'!A1")}
    assert (v(f"{second}#2").method, v(f"{second}#2").table_kind, v(f"{second}#2").file_sha256) == ("cell", "pk_summary", A)
    # cross-file: file B on study st-1 (home A) through the link fact; file A's values are home
    assert v(crossed).cross_file.model_dump() == {"stating_fact": crossed, "link_fact": link, "receiving_study": "st-1"}
    assert v(f"{second}#2").cross_file is None and v(f"{other}#0").entity.study == "st-3"
    active = {x.id for x in view.values(study="st-1")}
    assert {corrected, f"{second}#2", point, crossed, link} <= active and dose not in active and f"{second}#1" not in active
    assert view.heads().keys() == {"facts", "entities", "mappings", "review"}
    assert view.head() == IntakeStore(ws).facts.head()

    # later: a merge, an assignment, a refused link, a confirmation
    book.store.entities.append("merge", Merge(type="study", from_id="st-3", into_id="st-1", link_fact=None, why="one study",
                                              by="u", at=AT).model_dump())
    book.review("assignment", Assignment(id="as-1", targets=(loose,), study="st-2", why="stated on the cover", by="u", at=AT))
    book.review("link", LinkConfirmation(id="lk-2", link_fact=link, study="st-1", file_sha256=B, confirmed=False,
                                         why="another protocol", by="u", at=AT))
    record = {"facts": [[corrected, "55.0", "mg"]], "extracts": [[second, "x"]], "excluded": [f"{second}#2"]}
    book.review("confirmation", Confirmation(id="cf-3", subject_type="study", subject="st-1", record_sha256="0" * 64,
                                             record=record, signature_id="sig-1", manifestation="Reviewed", by="u",
                                             printed_name="U", at=AT))
    view = LedgerView(ws)
    assert view.entity("st-3").id == "st-1" and "st-3" not in {e.id for e in view.entities("study")}
    assert v(loose).entity.study is None                                         # the first view is a snapshot
    assert view.value(loose).entity.study == "st-2" and view.values(unassigned=True) == []
    assert view.value(f"{other}#0").entity.study == "st-1"                        # followed through the merge
    assert view.value(f"{other}#0").cross_file.link_fact == link                  # B's link to st-1
    assert (view.value(crossed).status, view.value(crossed).status_reason) == ("excluded", "another protocol")
    assert view.value(f"{other}#0").status == "excluded"                          # the refused link excludes it too
    assert (view.value(corrected).status, view.value(corrected).confirmation) == ("confirmed", "cf-3")
    assert view.value(f"{second}#2").status == "proposed"                         # left out of the binding
    assert view.value(f"{second}#1").status == "excluded" and view.value(f"{second}#0").status == "superseded"
    assert view.digest(study="st-1") != digest                                    # the refusal changed the active set

    # recording a confirmation changes no digest; an exclusion does
    before = LedgerView(ws).digest(study="st-2")
    book.review("confirmation", Confirmation(id="cf-4", subject_type="study", subject="st-2", record_sha256="1" * 64,
                                             record={"facts": [[prose, "12", None]]}, signature_id="sig-2",
                                             manifestation="Reviewed", by="u", printed_name="U", at=AT))
    assert LedgerView(ws).digest(study="st-2") == before and LedgerView(ws).value(prose).level == "person_confirmed"
    book.status(prose, "excluded", "a duplicate")
    assert LedgerView(ws).digest(study="st-2") != before
    with pytest.raises(NotImplementedError):
        LedgerView(ws).conflicts()
    with pytest.raises(NotImplementedError):
        LedgerView(ws).pending_links()


def _confirm(book: _Book, id: str, subject_type: str, subject: str, facts: tuple[str, ...], *,
             excluded: tuple[str, ...] = (), supersedes: str | None = None) -> None:
    record = {"facts": [[f, "x", None] for f in facts], "excluded": list(excluded)}
    book.review("confirmation", Confirmation(id=id, subject_type=subject_type, subject=subject, record_sha256=sha256_of(record),
                                             record=record, signature_id=f"sig-{id}", manifestation="Reviewed", by="u",
                                             printed_name="U", at=AT, supersedes=supersedes))


def test_subjects_unassigned_values_and_the_current_confirmation(ws):
    book = _Book(ws)
    book.entity("st-1", "230-23", A)
    book.entity("st-2", "231-24", A)

    def fact(field: str, value, entity: EntityRef, cell: str) -> str:
        return book.store.facts.append("fact", lambda seq: Fact(
            id=f"f-{seq}", delivery="dl-1", entity=entity, field=field, value=value, method="cell", by="code", at=AT,
            anchor=anchor_text(A, "workbook", "1.0", f"s:'T'!{cell}")).model_dump(mode="json")).body["id"]

    dissolved = fact("percent_dissolved", 85.0, EntityRef(product="pr-1"), "A1")
    strength = fact("strength_mg", 50, EntityRef(product="pr-1", batch="ba-1"), "A2")
    logp = fact("phys.logp", 2.1, EntityRef(), "A3")
    loose = fact("concentration", 12.0, EntityRef(analyte="an-1", matrix="plasma"), "A4")
    dose = book.fact("dose", 50.0, study="st-1", cell="B1")
    view = LedgerView(ws)
    # a product's and the compound's values have a subject; only the concentration names none
    assert [v.id for v in view.values(unassigned=True)] == [loose]
    assert [v.id for v in view.values(compound=True)] == [logp]
    assert [v.id for v in view.values(product="pr-1")] == [dissolved, strength]
    compound = view.digest(compound=True)
    assert compound == sha256_of([[logp, 2.1, None, view.value(logp).anchor]]) != view.digest()
    book.fact("n", 24, study="st-2", cell="B2")                       # another subject's fact: the compound's digest stays
    assert LedgerView(ws).digest(compound=True) == compound and LedgerView(ws).digest() != view.digest()

    # each subject's current confirmation binds the values it lists that still belong to it
    _confirm(book, "cf-1", "study", "st-1", (dose, logp))             # logp is not st-1's: not bound by it
    _confirm(book, "cf-2", "compound", "compound", (logp,))
    _confirm(book, "cf-3", "product", "pr-1", (dissolved,))
    view = LedgerView(ws)
    assert [(view.value(i).status, view.value(i).confirmation) for i in (dose, logp, dissolved, strength)] == [
        ("confirmed", "cf-1"), ("confirmed", "cf-2"), ("confirmed", "cf-3"), ("proposed", None)]
    # a later confirmation that supersedes cf-2 and leaves logp out; a value moved to another study by an assignment
    _confirm(book, "cf-4", "compound", "compound", (), excluded=(logp,), supersedes="cf-2")
    book.review("assignment", Assignment(id="as-5", targets=(dose,), study="st-2", why="the cover names 231-24", by="u",
                                         at=AT))
    view = LedgerView(ws)
    assert (view.value(logp).status, view.value(logp).confirmation, view.value(logp).level) == ("proposed", None, "new_mapping")
    moved = view.value(dose)
    assert (moved.entity.study, moved.status, moved.confirmation, moved.level) == ("st-2", "proposed", None, "new_mapping")
    # a later confirmation of the same subject replaces the earlier one, named in `supersedes` or not
    _confirm(book, "cf-5", "product", "pr-1", (strength,))
    view = LedgerView(ws)
    assert (view.value(dissolved).status, view.value(strength).confirmation) == ("proposed", "cf-5")


def test_an_assignment_names_a_study_a_product_or_both(ws):
    # §13 integrator decision: a product- or batch-level value of no subject can be given its product and batch
    with pytest.raises(ValidationError):
        Assignment(id="as-1", targets=("f-1",), why="w", by="u", at=AT)                   # no subject
    with pytest.raises(ValidationError):
        Assignment(id="as-1", targets=("f-1",), arm="a-1", product="pr-1", why="w", by="u", at=AT)   # an arm, no study
    with pytest.raises(ValidationError):
        Assignment(id="as-1", targets=("f-1",), study="st-1", batch="bt-1", why="w", by="u", at=AT)  # a batch, no product
    book = _Book(ws)
    book.entity("st-1", "230-23", A)
    loose, dissolved, both = (book.fact(field, 1.0, study=None, cell=cell)
                              for field, cell in (("dose", "C1"), ("percent_dissolved", "C2"), ("dose", "C3")))
    assert {v.id for v in LedgerView(ws).values(unassigned=True)} == {loose, dissolved, both}
    book.review("assignment", Assignment(id="as-1", targets=(dissolved,), product="pr-1", batch="bt-1", why="the CoA",
                                         by="u", at=AT))
    book.review("assignment", Assignment(id="as-2", targets=(both,), study="st-1", arm="ar-1", product="pr-1",
                                         why="the cover", by="u", at=AT))
    view = LedgerView(ws)
    product_only, assigned_both = view.value(dissolved), view.value(both)
    assert (product_only.entity.study, product_only.entity.arm, product_only.entity.product,
            product_only.entity.batch) == (None, None, "pr-1", "bt-1")
    assert (assigned_both.entity.study, assigned_both.entity.arm, assigned_both.entity.product,
            assigned_both.entity.batch) == ("st-1", "ar-1", "pr-1", None)
    assert {v.id for v in view.values(unassigned=True)} == {loose}
    assert {v.id for v in view.values(product="pr-1")} == {dissolved, both}
    assert {v.id for v in view.values(study="st-1")} == {both}
    # the latest assignment of a value replaces the earlier one whole: a study with no arm and no product
    book.review("assignment", Assignment(id="as-3", targets=(both,), study="st-1", why="no arm", by="u", at=AT))
    assert LedgerView(ws).value(both).entity.model_dump(include={"study", "arm", "product"}) == {
        "study": "st-1", "arm": None, "product": None}


def test_the_snapshot_is_one_state_and_refresh_reads_again(ws, monkeypatch):
    book = _Book(ws)
    book.entity("st-1", "230-23", A)
    first = book.fact("dose", 50.0, study="st-1")
    view = LedgerView(ws)
    other = ChainedLog(IntakeStore(ws).facts.path)                     # another writer, another handle
    read_entities = view.store.entities.entries

    def racing(kind=None):                                              # a fact appended while the fold reads
        other.append("fact", Fact(id="f-2", delivery="dl-1", entity=EntityRef(study="st-1"), field="n", value=24,
                                  method="person", by="u", at=AT).model_dump(mode="json"))
        return read_entities(kind)

    monkeypatch.setattr(view.store.entities, "entries", racing)
    assert [v.id for v in view.values()] == [first]
    assert view.head().seq == 1 and view.heads()["facts"] == view.head().hash
    monkeypatch.undo()
    assert [v.id for v in view.values()] == [first]                      # a snapshot until refreshed
    view.refresh()
    assert [v.id for v in view.values()] == [first, "f-2"] and view.heads()["facts"] == IntakeStore(ws).facts.head().hash


def test_a_spread_fact_qualifies_a_value_and_is_not_one(ws):
    book = _Book(ws)
    book.entity("st-1", "230-23", A)
    mean = book.fact("concentration", 12.0, study="st-1")
    store = book.store
    spread = store.facts.append("fact", lambda seq: Fact(
        id=f"f-{seq}", delivery="dl-1", entity=EntityRef(study="st-1"), field="concentration", value=None, spread=2.4,
        spread_kind="SD", method="derived", derived_from=(mean,), compute="spread-1/sd_from_se", by="code",
        at=AT).model_dump(mode="json")).body["id"]
    blq = store.facts.append("fact", lambda seq: Fact(
        id=f"f-{seq}", delivery="dl-1", entity=EntityRef(study="st-1"), field="concentration", value=None, censored=True,
        lloq=0.5, lloq_unit="ng/mL", method="cell", anchor=anchor_text(A, "workbook", "1.0", "s:'T'!D1"), by="code",
        at=AT).model_dump(mode="json")).body["id"]
    view = LedgerView(ws)
    assert [is_spread_fact(view.value(i)) for i in (mean, spread, blq)] == [False, True, False]


# --- the synthetic truth in a ledger -------------------------------------------------------------------------------


def _number(text: str) -> float | None:
    text = text.rstrip("*").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def test_write_truth_round_trips_through_the_ledger_view(ws):
    files = synthetic.delivery()
    ids = write_truth(ws, files)
    store = IntakeStore(ws)
    assert all(log.verify() == [] for log in (store.files, store.mappings, store.facts, store.entities))
    view = LedgerView(ws)
    expected = sum(len(f.values) for f in files)
    assert len(ids) == expected
    for file in files:
        sha = hashlib.sha256(file.data).hexdigest()
        assert ws.store.blob_path("t1", "p1", sha) is not None and store.coverage(sha) is None
        for truth in file.values:
            value = view.value(ids[truth_key(file, truth)])
            anchor = parse_anchor(value.anchor)
            assert (anchor.file_sha256, anchor.parser_version) == (sha, PARSER_VERSION)
            assert same_place(anchor.locator, parse_locator(truth.locator))
            assert value.field == truth.field and value.status == "proposed" and (value.unit or "") == truth.unit
            assert value.level == ("prose" if truth.table == "" else "approved_mapping")
            study = view.entity(value.entity.study) if value.entity.study else None
            assert (study.label if study else "") == truth.study
            assert (value.entity.subject or "") == truth.subject and (value.entity.vessel or "") == truth.vessel
            if value.id.startswith("tx-"):
                assert value.verbatim in (truth.value, f"{truth.value} ({truth.spread})")
                assert value.time == _number(truth.time) and (value.time_unit or "") == truth.time_unit
                assert value.value == (None if truth.value.startswith(("<", ">")) else _number(truth.value))
                assert value.censored == (truth.value in ("BLQ",) or truth.value.startswith("<"))
                assert value.statistic == (truth.statistic or None) and value.spread == _number(truth.spread)
                assert value.conditions == dict(truth.conditions)
            for role, locator in truth.locators:                  # every cell it is read with, its own row's labels too
                assert role in value.locators, (role, truth)
                assert same_place(parse_anchor(value.locators[role]).locator, parse_locator(locator)), (role, truth)
            if value.censored:                                      # a BLQ's LLOQ is the one its LLOQ cell states
                cited = dict(truth.locators).get("lloq")
                lloq = [t for t in file.values if t.field == "lloq" and t.locator == cited]
                expected = (_number(truth.value[1:]), truth.unit) if truth.value.startswith("<") else \
                    (_number(lloq[0].value), lloq[0].unit) if lloq else (None, "")
                assert (value.lloq, value.lloq_unit or "") == expected, truth
            if truth.table == "":
                assert value.mapping is None and value.method == "prose"
    blq = [v for v in view.values() if v.censored and "lloq" in v.locators]
    assert blq and all(v.lloq is not None and v.lloq_unit for v in blq)
    # products and the compound are subjects of their own: a delivery with dissolution and product tables has no value
    # of no subject; a concentration with no study would be one (test_subjects_...)
    assert view.values(unassigned=True) == [] and view.values(product=view.entities("product")[0].id)
    # entities are resolved inside their file first (§6.3): the drug is an analyte of each file that names it, while
    # a study named in another file is that file's study, linked
    assert len([e for e in view.entities("analyte") if e.label == synthetic.DRUG]) == len(files)
    synopsis = [view.value(ids[truth_key(files[1], t)]) for t in files[1].values if t.table == ""]
    assert synopsis and all(v.cross_file is not None and v.cross_file.link_fact.startswith("f-") for v in synopsis)
    link = view.value(synopsis[0].cross_file.link_fact)
    assert (link.field, link.method, link.level) == ("link.study_id", "prose", "prose")
    prose = [store.facts.entries()[int(v.id[2:]) - 1].body for v in synopsis]
    assert all(b["model"] == TRUTH_MODEL.model_dump() and b["by"] == f"agent:{TRUTH_MODEL.agent_run}" for b in prose)
    head = store.facts.head()
    assert write_truth(ws, files) == ids and store.facts.head() == head                 # the same truth twice: nothing new
    assert write_truth(ws, files, delivery="dl-2") == ids and store.facts.head() == head  # the same bytes again: repeats
    again = [e.body for e in store.files.entries("file") if e.body["delivery"] == "dl-2"]
    assert len(again) == len(files) and all(b["repeat"] for b in again)
    unapproved = Workspace(ws.store, "t1", "p-new")
    write_truth(unapproved, files[:1], approved=False)
    assert {v.level for v in LedgerView(unapproved).values()} == {"new_mapping"}


# --- the rules file ------------------------------------------------------------------------------------------------


def test_the_rules_file_loads_unverified_and_is_pinned_to_its_version():
    loaded = rules()
    assert RULES_STATUS == loaded.status == "UNVERIFIED" and RULES_VERSION == loaded.version
    assert PINNED_RULES[RULES_VERSION] == RULES_SHA256, "intake_rules.yaml changed: bump its version and pin the new sha256"
    assert loaded.landing.geometric_sd_sent_as == "GeometricStdDev" and loaded.spot_check.size == 100
    assert loaded.routing.by_tag[3].in_ == ("fed",) and loaded.routing.item_fields["REQ-obs.bioanalytical"].per == (
        "analyte", "matrix")
    codes = [c for level in ("fail", "warn", "info") for c in loaded.checks.severity[level]]
    assert len(codes) == len(set(codes))
    data = loaded.model_dump(mode="json", by_alias=True)
    assert IntakeRules.model_validate(data) == loaded
    with pytest.raises(ValidationError):
        IntakeRules.model_validate({**data, "landing": {**data["landing"], "geometric_sd_sent_as": "GeometricCV"}})
    routing = {**data["routing"], "item_fields": {**data["routing"]["item_fields"], "REQ-not.scoped": {"all": ["lloq"]}}}
    with pytest.raises(ValidationError):
        IntakeRules.model_validate({**data, "routing": routing})
