"""The review of a delivery (contracts §6.6, §8.10; plan §7.8, G6): the spot check (the draw, its strata, the ticks
once, stale and carried), every blocker, the bound record, the decisions with their audit events, the coverage they
recompute, the confirmation, and blinding (D-15) enforced in the functions the routes call.

Every number is made up (the drug is Exampleamide). The ledgers are the synthetic truth (`intake_fixtures.write_truth`)
or small hand-written ones; the coverage files are made here from D2's parse of the same files (no pipeline run)."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import Counter
from typing import Any

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import anchor_text, sha256_of
from modeler_intake.document_reading import name_key
from modeler_intake.source import parse_document
from modeler_intake.synthetic import TRUTH_PARSER_VERSION, SyntheticFile
from modeler_project import intake_review as review
from modeler_project.coverage import file_coverage, values_unassigned
from modeler_project.dataset_register import decide_dataset, propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series
from modeler_project.evidence import EvidenceState, SourceRef
from modeler_project.intake_fixtures import truth_key, write_truth
from modeler_project.intake_records import (
    Confirmation,
    FileCoverage,
    FileRecord,
    Landed,
    RegionOutcome,
    RunRecord,
    SpotCheckDraw,
    SpotTick,
)
from modeler_project.intake_rules import RULES_SHA256, RULES_STATUS, RULES_VERSION, rules
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import Ledger
from modeler_project.ledger_models import Entity, EntityRef, Fact
from modeler_project.ledger_view import LedgerView
from modeler_project.mapping_cache import MappingCache
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

from .test_ledger_support import record_table

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

AT = "2026-11-13T09:00:00.000Z"
BY = "u-reviewer"
SHA = hashlib.sha256(b"Exampleamide: a made-up delivery for the review").hexdigest()
OTHER = hashlib.sha256(b"Exampleamide: a made-up synopsis for the review").hexdigest()
_PREFIX = {"study": "st", "arm": "arm", "product": "pr", "batch": "ba", "analyte": "an"}
CARD = {"brief": None, "matrix": None, "mol_weight": None}


# --- helpers (test_intake_landing.py uses them too) ----------------------------------------------------------------------


def project(tmp_path, name: str = "p1") -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", name)


def sha_of(file: SyntheticFile) -> str:
    return hashlib.sha256(file.data).hexdigest()


def arrive(ws: Workspace, sha: str, name: str, *, delivery: str = "dl-1", data: bytes | None = None) -> FileRecord:
    """A file's `delivery` and `file` lines, as the pipeline's arrival writes them (and its bytes, when given)."""
    store = IntakeStore(ws)
    store.files.append_if(lambda entries: [] if any(e.kind == "delivery" and e.body.get("id") == delivery for e in entries)
                          else [("delivery", {"id": delivery, "by": "code", "at": AT})])
    record = FileRecord(file_id=f"fl-{sha[:12]}", sha256=sha, name=name, size_bytes=len(data or b"x"), delivery=delivery,
                        by="code", at=AT)
    store.files.append_if(lambda entries: [] if any(e.kind == "file" and e.body.get("sha256") == sha for e in entries)
                          else [("file", record.model_dump(mode="json"))])
    if data is not None:
        ws.store.put_blob(ws.tenant_id, ws.project_id, data)
    return record


def cover(ws: Workspace, file: SyntheticFile, *, unread: tuple[str, ...] = (), cite: bool = True) -> FileCoverage:
    """The file's source model (D2's parse, cached under the truth's parser version, so the truth's anchors resolve in
    it) and its coverage, as a run would store them: every table mapped with all its cells used (`unread`: region ids
    left unread), every prose region read, the context lines its tables cite (`cite`)."""
    store = IntakeStore(ws)
    doc = parse_document(file.data, file.name).model_copy(update={"parser_version": TRUTH_PARSER_VERSION})
    store.put_source(doc)
    outcomes = []
    for region in doc.regions:
        if region.id in unread or region.kind == "figure":
            continue
        cited = tuple(o.where for o in doc.outside if o.region == region.id) if cite else ()
        uses = {"value": region.numeric_cells} if region.numeric_cells else {}
        outcomes.append(RegionOutcome(region_id=region.id, state="mapped", numeric_cells=region.numeric_cells, uses=uses,
                                      cited=cited))
    record = next(FileRecord.model_validate(e.body) for e in store.files.entries("file") if e.body["sha256"] == doc.file_sha256)
    made = file_coverage(record, doc, outcomes, values_unassigned=values_unassigned(LedgerView(ws), doc.file_sha256))
    store.put_coverage(made)
    ran(ws, doc.file_sha256)
    return made


def ran(ws: Workspace, sha: str, state: str = "done", *, delivery: str = "dl-1") -> None:
    """The file's run line as the pipeline writes it when a run ends (`done` unless said otherwise); nothing when the
    file's last run line already says so."""
    store = IntakeStore(ws)
    lines = [e.body for e in store.runs.entries() if e.body.get("sha256") == sha]
    if lines and lines[-1].get("state") == state:
        return
    open_run = lines[-1]["run_id"] if lines and lines[-1].get("state") in ("queued", "running") else None
    run = RunRecord(run_id=open_run or f"run-{sha[:8]}-{len(lines)}", file_id=f"fl-{sha[:12]}", sha256=sha, delivery=delivery,
                    state=state, queued_at=AT, finished_at=AT if state in ("done", "failed") else None, by="code")  # type: ignore[arg-type]
    store.runs.append("run", run.model_dump(mode="json"))


def events(ws: Workspace, action: str | None = None) -> list[Any]:
    return [r.event for r in ws.store.audit(ws.tenant_id).records() if action is None or r.event.action == action]


def line_hash(ws: Workspace, record_id: str) -> str:
    (entry,) = [e for e in IntakeStore(ws).review.entries() if e.body.get("id") == record_id]
    return entry.hash


class Book:
    """A small ledger written line by line (as D5's tests write theirs): entities and facts of one made-up file."""

    def __init__(self, ws: Workspace, sha: str = SHA, name: str = "made-up.xlsx", sheet: str = "Data"):
        self.ws, self.sha, self.sheet = ws, sha, sheet
        self.store = IntakeStore(ws)
        self.cells = 0
        arrive(ws, sha, name)

    def anchor(self) -> str:
        self.cells += 1
        return anchor_text(self.sha, "workbook", "1.0", f"s:'{self.sheet}'!C{self.cells}")

    def entity(self, type: str, label: str, parent: str | None = None) -> str:
        source = self.anchor()
        return self.store.entities.append("entity", lambda seq: Entity(
            id=f"{_PREFIX[type]}-{seq}", type=type, label=label, key=name_key(label), parent=parent, source=source,  # type: ignore[arg-type]
            by="code", at=AT).model_dump(mode="json")).body["id"]

    def fact(self, field: str, value: Any, entity: dict[str, Any], method: str = "prose", **kw: Any) -> str:
        anchor = kw.pop("anchor", None if method in ("derived", "person") else self.anchor())
        verbatim = kw.pop("verbatim", "" if value is None else str(value))
        return self.store.facts.append("fact", lambda seq: Fact(
            id=f"f-{seq}", delivery="dl-1", entity=EntityRef(**entity), field=field, value=value, verbatim=verbatim,
            anchor=anchor, method=method, by="code", at=AT, **kw).model_dump(mode="json")).body["id"]  # type: ignore[arg-type]


def clean_study(book: Book, label: str = "EXA-401", *, points: int = 4, analyte: str = synthetic.DRUG) -> dict[str, str]:
    """A study that passes every check, with every study item found and every field the study record needs."""
    study, an = book.entity("study", label), book.entity("analyte", analyte)
    ids = {"study": study, "analyte": an}
    on = {"study": study}
    for field, value, kw in (("dose", 50.0, {"unit": "mg"}), ("n", 12, {}), ("route", "oral", {}),
                             ("formulation", "ir_tablet", {}), ("food_state", "fasted", {}),
                             ("intended_use", "model_building", {}), ("salt_or_base", "base", {}),
                             ("population", "healthy", {}), ("age_mean", 33.0, {})):
        ids[field] = book.fact(field, value, on, **kw)
    profile = {"study": study, "analyte": an, "matrix": "plasma"}
    ids["lloq"] = book.fact("lloq", 0.5, profile, unit="ng/mL")
    for i in range(points):
        ids[f"c{i}"] = book.fact("concentration", 10.0 + i, {**profile, "subject": "001"}, unit="ng/mL", time=float(i + 1),
                                 time_unit="h", statistic="individual")
    return ids


def covered(book: Book, **counts: int) -> None:
    """A coverage file for the book's file with nothing lost (or the counts given), and its run's `done` line."""
    from modeler_project.intake_records import CoverageSummary

    base = dict(state="read", regions=1, regions_mapped=1, regions_excluded=0, regions_unread=0, numeric_cells=10,
                cells_used=10, cells_excluded=0, cells_silent=0, silent_loss=0, outside_items=0)
    record = next(FileRecord.model_validate(e.body) for e in book.store.files.entries("file") if e.body["sha256"] == book.sha)
    book.store.put_coverage(FileCoverage(file=record, summary=CoverageSummary(**{**base, **counts}),  # type: ignore[arg-type]
                                         regions=(), outside=(), anchor_problems=(), computed_at=AT))
    ran(book.ws, book.sha)


def tick_all(ws: Workspace, draw: SpotCheckDraw, *, wrong: tuple[str, ...] = ()):
    ticks = [SpotTick(value_id=v, ok=v not in wrong) for v in (*draw.always, *draw.sampled)
             if v not in draw.carried and draw.strata.get(v) != "always:failed"]      # a failed tick is not ticked again
    return review.record_spot_check(ws, draw.id, ticks, by=BY)


def draw(ws: Workspace, subject: str, subject_type: str = "study", reader: LedgerView | None = None) -> SpotCheckDraw:
    return review.draw_spot_check(ws, subject_type, subject, reader=reader or Ledger(ws), by=BY, blinded=False)  # type: ignore[arg-type]


def study_of(reader: LedgerView, label: str) -> str:
    (found,) = [e for e in reader.entities("study") if e.label == label]
    return found.id


def settle(ws: Workspace, subject_type: str, subject: str, reader: Ledger) -> None:
    """A reviewer's decisions on everything a card shows that a decision settles: each cross-file link confirmed, each
    missing required item disposed, each other failed check overridden with a reason, the spot check drawn and ticked."""
    for link in (reader.pending_links(study=subject) if subject_type == "study" else ()):
        review.confirm_link(ws, link_fact=link.link_fact, study=subject, file_sha256=link.file_sha256, confirmed=True,
                            why="the same study", by=BY)
    reader.refresh()
    card = review.card(ws, subject_type, subject, reader=reader, **CARD, blinded=False)  # type: ignore[arg-type]
    for check in card.checks:
        if check.severity != "fail" or check.id in card.overridden:
            continue
        if check.code == "REQUIRED_ITEM_UNDISPOSED":
            for item in card.requirements:
                if item.status == "missing" and item.req_id in check.message:
                    review.dispose(ws, subject=subject, req_id=item.req_id, disposition="ask_client", why="asked", by=BY)
        else:
            review.override(ws, subject=subject, check_id=check.id, why="read against the source: as written", by=BY)
    if review.spot_check_state(ws, subject_type, subject, reader=reader) != "complete":  # type: ignore[arg-type]
        tick_all(ws, draw(ws, subject, subject_type, reader))


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return project(tmp_path)


@pytest.fixture
def truth(ws) -> dict[str, str]:
    """The synthetic delivery's truth in the ledger (approved mappings); truth key -> value id."""
    return write_truth(ws, synthetic.delivery())


# --- the spot check ---------------------------------------------------------------------------------------------------


def test_the_draw_is_the_same_for_the_same_state_stores_its_heads_and_differs_after_a_change(ws, truth):
    reader = Ledger(ws)
    study = study_of(reader, "230-23")
    first = draw(ws, study, reader=reader)
    store = IntakeStore(ws)
    assert first.heads == {"facts": store.facts.head().hash, "entities": store.entities.head().hash,
                           "mappings": store.mappings.head().hash, "review": reader.heads()["review"],
                           "rules": RULES_SHA256}
    assert first.rules_version == RULES_VERSION and first.subject_digest == reader.digest(study=study)
    assert first.seed == hashlib.sha256(f"{store.facts.head().hash}|{study}|{RULES_VERSION}".encode()).hexdigest()
    # asked again with nothing changed: the same draw, and no second line
    again = draw(ws, study)
    assert again == first and len(store.review.entries("spot_draw")) == 1
    # another reader of the same state computes the same draw (an auditor recomputes it from the logs)
    assert (again.always, again.sampled, again.strata) == (first.always, first.sampled, first.strata)
    # a change of the ledger: another seed, another line; a corrected value is drawn, the old one is not
    old = next(v for v in reader.values(study=study, field="concentration") if v.value is not None)
    fact = Ledger(ws).enter(supersedes=old.id, value=float(old.value) + 1.0, why="read again from the report", by=BY)
    changed = draw(ws, study)
    assert changed.id != first.id and changed.seed != first.seed and changed.subject_digest != first.subject_digest
    assert fact.id in changed.strata and old.id not in changed.strata and old.id in first.strata
    assert store.review.verify() == []


def test_strata_and_always_as_the_rules_say(ws, truth):
    workbook, pdf = synthetic.delivery()[:2]
    reader = Ledger(ws)
    study = study_of(reader, "230-23")
    store = IntakeStore(ws)
    analyte = next(v.entity.analyte for v in reader.values(study=study, field="concentration"))
    profile = {"study": study, "analyte": analyte, "matrix": "plasma"}
    # a digitized value, and a dose in g with its derived dose in mg
    book = Book(ws, sha=sha_of(workbook), name=workbook.name, sheet="Fasting")
    digitized = book.fact("concentration", 3.3, profile, method="digitized", unit="ng/mL", time=36.0, time_unit="h",
                          statistic="arithmetic_mean", anchor=anchor_text(sha_of(workbook), "workbook", TRUTH_PARSER_VERSION, "d:f:1"))
    grams = book.fact("meal_fat_g", 0.05, {"study": study}, unit="g", anchor=anchor_text(sha_of(workbook), "workbook",
                                                                                         TRUTH_PARSER_VERSION, "s:'Fasting'!Z1"))
    derived = book.fact("meal_fat_g", 50.0, {"study": study}, method="derived", unit="mg", derived_from=(grams,),
                        compute="compute-1/dose_to_mg")
    reader.refresh()
    found = draw(ws, study, reader=reader)
    values = {v.id: v for v in reader.values(study=study)}
    spot = rules().spot_check
    why = found.strata
    # never sampled: the fields the rules name, digitized and derived values, cross-file scalar facts and link facts
    for value in values.values():
        if value.field in spot.always_verify_fields and value.value is not None:
            assert why[value.id] == "always:field", value.field
    assert {values[v].field for v in found.always if why[v] == "always:field"} == {"dose", "lloq", "n"}
    assert why[digitized] == "always:digitized" and why[derived] == "always:derived"
    assert grams in found.sampled and values[derived].derived_from == (grams,)      # shown with its input
    links = [v for v in values.values() if v.field.startswith("link.")]
    assert links and all(why[v.id] == "always:link" for v in links)
    crossed = [v for v in values.values() if v.cross_file is not None and not v.id.startswith("tx-")]
    assert {v.field for v in crossed} >= {"food_state", "n"} and all(v.file_sha256 == sha_of(pdf) for v in crossed)
    assert all(why[v.id].startswith("always:") for v in crossed)
    assert set(found.always).isdisjoint(found.sampled) and len(set(found.always)) == len(found.always)
    # BLQ values are candidates, and their marker form is a stratum ("BLQ" beside "<x")
    censored = [v for v in values.values() if v.censored and v.field == "concentration"]
    assert {v.verbatim for v in censored} >= {"BLQ", "<0.5"} and all(v.id in found.sampled for v in censored)
    forms = {why[v.id].split("|")[2] for v in censored}
    assert forms == {"blq_form=BLQ", "blq_form=<x"}
    # the strata: table kind, the field's unit class, the BLQ form, cross-file
    assert why[next(v.id for v in values.values() if v.table_kind == "pk_individual" and v.value is not None)] == \
        "table_kind=pk_individual|unit_class=concentration|blq_form=|cross_file=no"
    assert {s.split("|")[0] for s in why.values() if not s.startswith("always:")} >= {
        "table_kind=pk_individual", "table_kind=pk_summary", "table_kind=pk_parameters", "table_kind=excretion",
        "table_kind=fact"}
    assert {s.split("|")[1] for s in why.values() if "|" in s} >= {"unit_class=concentration", "unit_class=other", "unit_class=mass"}
    # a text value that is none of these is not a candidate (a tick compares a number with its source)
    assert all(v.id not in why for v in values.values() if v.field == "analyte")
    assert store.review.entries("spot_draw")[-1].body["id"] == found.id


def test_a_study_with_fewer_values_than_the_size_is_checked_whole_and_a_larger_one_by_strata(ws):
    book = Book(ws)
    small = clean_study(book, "EXA-401", points=6)
    reader = Ledger(ws)
    found = draw(ws, small["study"], reader=reader)
    candidates = [v.id for v in reader.values(study=small["study"]) if isinstance(v.value, int | float) or v.censored]
    assert sorted((*found.always, *found.sampled)) == sorted(candidates) and len(candidates) < rules().spot_check.size
    # a larger study: 150 quantified values, 4 written BLQ and one "<0.5"
    big = clean_study(book, "EXA-402", points=0)
    profile = {"study": big["study"], "analyte": big["analyte"], "matrix": "plasma"}
    for i in range(150):
        book.fact("concentration", 1.0 + i, {**profile, "subject": f"{i // 10:03d}"}, unit="ng/mL", time=float(i % 10 + 1),
                  time_unit="h", statistic="individual")
    for i in range(4):
        book.fact("concentration", None, {**profile, "subject": f"9{i:02d}"}, unit="ng/mL", time=0.0, time_unit="h",
                  statistic="individual", censored=True, lloq=0.5, lloq_unit="ng/mL", verbatim="BLQ")
    book.fact("concentration", None, {**profile, "subject": "999"}, unit="ng/mL", time=0.0, time_unit="h",
              statistic="individual", censored=True, lloq=0.5, lloq_unit="ng/mL", verbatim="<0.5")
    reader.refresh()
    found = draw(ws, big["study"], reader=reader)
    spot = rules().spot_check
    per_stratum = Counter(found.strata[v] for v in found.sampled)
    assert len(found.sampled) == spot.size == 100
    # min_per_stratum (2) from each stratum, or all of a smaller one: 2 + 2 + 1 + 1; then the remaining 94 in proportion
    # to what is left (148 quantified, 2 BLQ): 92.75 and 1.25, the spare one to the largest remainder
    assert per_stratum == {"table_kind=fact|unit_class=concentration|blq_form=|cross_file=no": 95,
                           "table_kind=fact|unit_class=concentration|blq_form=BLQ|cross_file=no": 3,
                           "table_kind=fact|unit_class=concentration|blq_form=<x|cross_file=no": 1,
                           "table_kind=fact|unit_class=other|blq_form=|cross_file=no": 1}       # the mean age
    assert {found.strata[v] for v in found.always} == {"always:field"}
    # inside a stratum the order is sha256(seed + value id): nothing random
    quantified = sorted((v for v, s in found.strata.items() if s.endswith("blq_form=|cross_file=no")),
                        key=lambda v: hashlib.sha256((found.seed + v).encode()).hexdigest())
    quantified = [v for v in quantified if "concentration" in found.strata[v]]
    assert [v for v in found.sampled if found.strata[v] == "table_kind=fact|unit_class=concentration|blq_form=|cross_file=no"] \
        == quantified[:95]


def test_ticks_are_accepted_once_two_threads_one_record(ws):
    ids = clean_study(Book(ws))
    found = draw(ws, ids["study"])
    ticks = [SpotTick(value_id=v, ok=True) for v in (*found.always, *found.sampled)]
    answers: list[Any] = []

    def submit() -> None:
        try:
            answers.append(review.record_spot_check(ws, found.id, ticks, by=BY))
        except (review.ReviewError, RuntimeError, OSError) as exc:   # collected, asserted below
            answers.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    store = IntakeStore(ws)
    assert len(store.review.entries("spot_check")) == 1 and answers[0] == answers[1]
    record = answers[0]
    assert record.draw_id == found.id and len(record.ticks) == len(ticks)
    (event,) = events(ws, "intake.spot_check")
    assert event.after == {"spot_check": record.id, "draw": found.id, "ok": len(ticks), "not_ok": 0,
                           "row_hash": line_hash(ws, record.id)}
    assert event.resource_type == "intake" and event.resource_id == f"{ws.project_id}/{record.id}"
    # other ticks for the same draw are refused; so are a partial set, a value twice and a value not in the draw
    with pytest.raises(review.ReviewError) as refused:
        review.record_spot_check(ws, found.id, [t.model_copy(update={"ok": False}) for t in ticks], by=BY)
    assert refused.value.code == "CONFLICT"
    again = draw(ws, clean_study(Book(ws, sha=OTHER, name="other.xlsx"), "EXA-402")["study"])
    wanted = [SpotTick(value_id=v, ok=True) for v in (*again.always, *again.sampled)]
    for bad in (wanted[:-1], [*wanted, wanted[0]], [*wanted[:-1], SpotTick(value_id="f-999999", ok=True)]):
        with pytest.raises(review.ReviewError) as refused:
            review.record_spot_check(ws, again.id, bad, by=BY)
        assert refused.value.code == "INVALID"
    for bad_id in ("sd-999", "../sd-1", "sc-1"):
        with pytest.raises(review.ReviewError):
            review.record_spot_check(ws, bad_id, wanted, by=BY)
    assert len(store.review.entries("spot_check")) == 1 and len(events(ws, "intake.spot_check")) == 1
    assert store.review.verify() == []


def test_a_failed_tick_blocks(ws):
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    assert review.spot_check_state(ws, "study", ids["study"], reader=reader) == "none"
    found = draw(ws, ids["study"], reader=reader)
    assert review.spot_check_state(ws, "study", ids["study"], reader=reader) == "drawn"
    tick_all(ws, found, wrong=(ids["c1"],))
    assert review.spot_check_state(ws, "study", ids["study"], reader=reader) == "failed"
    (blocker,) = review.blockers(ws, "study", ids["study"], reader=reader, **CARD, blinded=False)
    assert blocker.code == "SPOT_CHECK" and "does not match its source" in blocker.detail
    assert events(ws, "intake.spot_check")[0].after["not_ok"] == 1


def test_a_correction_makes_the_draw_stale_and_the_next_draw_carries_the_unchanged_ticks(ws):
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    first = draw(ws, ids["study"], reader=reader)
    record = tick_all(ws, first)
    assert review.spot_check_state(ws, "study", ids["study"], reader=reader) == "complete"
    assert review.blockers(ws, "study", ids["study"], reader=reader, **CARD, blinded=False) == ()
    fact = reader.enter(supersedes=ids["c2"], value=12.5, why="the report says 12.5", by=BY)
    assert review.spot_check_state(ws, "study", ids["study"], reader=reader) == "stale"
    (blocker,) = review.blockers(ws, "study", ids["study"], reader=reader, **CARD, blinded=False)
    assert blocker.code == "SPOT_CHECK" and "draw again" in blocker.detail
    # the next draw carries every unchanged tick: only the corrected value is ticked again
    stale = review.draw_spot_check(ws, "study", ids["study"], reader=reader, by=BY, blinded=False)
    drawn = {*stale.always, *stale.sampled}
    assert fact.id in drawn and ids["c2"] not in drawn
    assert stale.carried == {v: record.id for v in sorted(drawn - {fact.id})}
    assert review.spot_check_state(ws, "study", ids["study"], reader=reader) == "drawn"
    with pytest.raises(review.ReviewError):                       # a carried value is not ticked again
        review.record_spot_check(ws, stale.id, [SpotTick(value_id=v, ok=True) for v in drawn], by=BY)
    second = review.record_spot_check(ws, stale.id, [SpotTick(value_id=fact.id, ok=True)], by=BY)
    assert [t.value_id for t in second.ticks] == [fact.id]
    assert review.spot_check_state(ws, "study", ids["study"], reader=reader) == "complete"
    # the ticks of a stale draw, and of a draw that is no longer the subject's latest, are refused
    other = clean_study(Book(ws, sha=OTHER, name="other.xlsx"), "EXA-402")
    reader.refresh()
    early = draw(ws, other["study"], reader=reader)
    reader.enter(supersedes=other["c1"], value=99.0, why="a correction", by=BY)
    with pytest.raises(review.ReviewError) as refused:
        tick_all(ws, early)
    assert refused.value.code == "STALE"
    later = draw(ws, other["study"], reader=reader)
    with pytest.raises(review.ReviewError) as refused:
        tick_all(ws, early)
    assert refused.value.code == "STALE" and later.id in str(refused.value)
    # a value ticked wrong is never carried
    tick_all(ws, later, wrong=(other["c0"],))
    reader.enter(supersedes=other["c2"], value=98.0, why="another correction", by=BY)
    last = draw(ws, other["study"], reader=reader)
    assert other["c0"] in last.strata and other["c0"] not in last.carried and other["c3"] in last.carried


def _confirm(ws: Workspace, subject: str, reader: LedgerView, subject_type: str = "study") -> Confirmation:
    record, sha = review.bound_record(ws, subject_type, subject, reader=reader, **CARD)  # type: ignore[arg-type]
    return review.record_confirmation(ws, subject_type=subject_type, subject=subject, record=record, record_sha256=sha,  # type: ignore[arg-type]
                                      signature_id="sig-0001", manifestation="Reviewed by A. Reviewer", by=BY,
                                      printed_name="A. Reviewer", blinded=False)


@pytest.mark.req("T-47", "T-05", "F-404", "F-403", "T-06")
def test_recording_the_confirmation_does_not_make_its_own_draw_stale(ws):
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    tick_all(ws, draw(ws, ids["study"], reader=reader))
    record, sha = review.bound_record(ws, "study", ids["study"], reader=reader, **CARD)
    confirmation = _confirm(ws, ids["study"], reader)
    assert confirmation.id.startswith("cf-") and confirmation.record == record and confirmation.record_sha256 == sha
    assert confirmation.signature_id == "sig-0001" and confirmation.supersedes is None
    reader.refresh()
    assert {v.status for v in reader.values(study=ids["study"])} == {"confirmed"}
    assert {v.confirmation for v in reader.values(study=ids["study"])} == {confirmation.id}
    assert review.spot_check_state(ws, "study", ids["study"], reader=reader) == "complete"
    assert review.blockers(ws, "study", ids["study"], reader=reader, **CARD, blinded=False) == ()
    (event,) = events(ws, "intake.confirm")
    assert event.after == {"confirmation": confirmation.id, "record_sha256": sha, "signature_id": "sig-0001",
                           "row_hash": line_hash(ws, confirmation.id)}
    # a double submit of the same record gives the one line back
    assert _confirm(ws, ids["study"], reader) == confirmation
    assert len(IntakeStore(ws).review.entries("confirmation")) == 1 and len(events(ws, "intake.confirm")) == 1
    # the landing has not run: the confirmation waits for it, and is found by its record hash
    assert review.landing_incomplete(ws, "study", ids["study"], sha) == confirmation
    assert review.landing_incomplete(ws, "study", ids["study"], "0" * 64) is None
    IntakeStore(ws).review.append("landed", Landed(confirmation=confirmation.id, datasets=(), evidence=(),
                                                   dissolution_records=0, rejected_legacy=(), pending=(), at=AT).model_dump())
    assert review.landing_incomplete(ws, "study", ids["study"], sha) is None
    assert review.current_confirmation(ws, "study", ids["study"], reader=reader) == confirmation


# --- blockers ---------------------------------------------------------------------------------------------------------


def _codes(found) -> list[str]:
    return [b.code for b in found]


def _legacy_dataset(ws: Workspace, *, sha: str, study_id: str, locator: str, values: tuple[float, ...] = (1.0, 2.0),
                    accept: bool = False, name: str = "legacy.xlsx") -> ObservedDataset:
    """A client dataset as today's readers propose one (for the overlap with a Delivery subject)."""
    study = {"study_id": study_id, "n": 12, "route": "oral", "dose_mg": 50.0, "formulation": "ir_tablet",
             "n_timepoints": len(values), "statistic": "mean"}
    made = propose_dataset(ws, ObservedDataset(
        id="ds-" + hashlib.sha256(f"{study_id}|{locator}".encode()).hexdigest()[:10], kind="profile", study=study,
        series=(Series(times=tuple(float(i + 1) for i in range(len(values))), values=values, n=12),), origin=Origin.CLIENT,
        extraction="CELL", provider="CLIENT", source=SourceRef(doc_sha256=sha, locator=locator, title=name)), actor="code")
    if accept:
        made = decide_dataset(ws, made.id, state=EvidenceState.ACCEPTED, reason="confirmed on the client-review card", by=BY)
    return made


def test_every_blocker_and_what_clears_it(ws, truth):
    files = synthetic.delivery()
    workbook, pdf = files[:2]
    for file in files:
        cover(ws, file)
    reader = Ledger(ws)
    study = study_of(reader, "230-23")
    ask = {"reader": reader, **CARD}
    found = review.blockers(ws, "study", study, **ask, blinded=False)
    # as the delivery arrives: a note with a number outside every table, no route (a schema gap), failed checks, the
    # synopsis joined across files, no spot check
    assert _codes(found) == ["OUTSIDE_NUMBERS", "SCHEMA_GAP", "CHECK_FAILED", "LINK_UNCONFIRMED", "SPOT_CHECK"]
    assert found == (*review.card(ws, "study", study, **ask, blinded=False).blockers, found[-1])
    # silent loss: a table of another study in the same delivery is unread (judged per delivery)
    fed = next(r.region.id for r in cover(ws, workbook).regions if r.region.where.startswith("s:'Fed'"))
    lost = cover(ws, workbook, unread=(fed,))
    assert lost.summary.silent_loss > 0
    # a value that names no study, in a file of the same delivery
    stray = Book(ws, sha=sha_of(workbook), name=workbook.name, sheet="Notes").fact("age_mean", 33.0, {})
    reader.refresh()
    assert [v.id for v in review.unassigned(ws, reader=reader)] == [stray]
    assert cover(ws, workbook, unread=(fed,)).summary.values_unassigned == 1
    # a dataset of the same sheet and study accepted on the legacy card; a file still being read; a blinded study
    legacy = _legacy_dataset(ws, sha=sha_of(workbook), study_id="230-23", locator="Fasting!A2:G14", accept=True)
    run = RunRecord(run_id="run-1", file_id=f"fl-{sha_of(pdf)[:12]}", sha256=sha_of(pdf), delivery="dl-1", state="queued",
                    queued_at=AT, by="code")
    IntakeStore(ws).runs.append("run", run.model_dump(mode="json"))
    found = review.blockers(ws, "study", study, **ask, blinded=True)
    assert _codes(found) == ["SILENT_LOSS", "OUTSIDE_NUMBERS", "UNASSIGNED_VALUES", "SCHEMA_GAP", "CHECK_FAILED",
                             "LINK_UNCONFIRMED", "SILENT_LOSS", "SPOT_CHECK", "LOADED_ON_CLIENT_REVIEW", "BLINDED"]
    by_code = {b.code: b for b in found}
    assert by_code["LOADED_ON_CLIENT_REVIEW"].ids == (legacy.id,) and "still being read" in found[6].detail
    assert found[6].ids == (f"fl-{sha_of(pdf)[:12]}",)
    # no detail names a value, an LLOQ or a count of values below the LLOQ (a blinded study's card shows them)
    assert not any("BLQ" in b.detail or "0.5" in b.detail for b in found)

    # each is cleared by its own decision
    IntakeStore(ws).runs.append("run", run.model_copy(update={"state": "done", "finished_at": AT}).model_dump(mode="json"))
    cover(ws, workbook)                                                           # the table is read after all
    review.exclude_regions(ws, file_sha256=sha_of(workbook), regions=["s:'Summary'!A10"], scope="outside",
                           why="a working note, not data", by=BY)
    review.assign(ws, targets=[stray], study=study, why="the note belongs to study 230-23", by=BY)
    decide_dataset(ws, legacy.id, state=EvidenceState.REJECTED, reason="confirmed on Delivery instead", by=BY)
    reader.refresh()
    assert _codes(review.blockers(ws, "study", study, **ask, blinded=False)) == [
        "SCHEMA_GAP", "CHECK_FAILED", "LINK_UNCONFIRMED", "SPOT_CHECK"]
    for field, value in (("route", "oral"), ("formulation", "ir_tablet"), ("intended_use", "model_building")):
        reader.enter(entity=EntityRef(study=study), field=field, value=value, why="from the protocol", by=BY)
    link = next(p for p in reader.pending_links(study=study))
    review.confirm_link(ws, link_fact=link.link_fact, study=study, file_sha256=link.file_sha256, confirmed=True,
                        why="the synopsis is this study's", by=BY)
    reader.refresh()
    card = review.card(ws, "study", study, **ask, blinded=False)
    failed = [c for c in card.checks if c.severity == "fail"]
    assert {c.code for c in failed} == {"ABOVE_RANGE", "REQUIRED_ITEM_UNDISPOSED"}
    for check in failed:
        if check.code == "REQUIRED_ITEM_UNDISPOSED":
            item = next(r for r in card.requirements if r.status == "missing")
            review.dispose(ws, subject=study, req_id=item.req_id, disposition="ask_client", why="asked on 13 Nov", by=BY)
        else:
            review.override(ws, subject=study, check_id=check.id, why="read against the report: as written", by=BY)
    found = review.blockers(ws, "study", study, **ask, blinded=False)
    assert _codes(found) == ["SPOT_CHECK"] and found[0].detail == "the spot check has not been drawn"
    drawn = draw(ws, study, reader=reader)
    # every value of an overridden check is verified, never sampled
    above = next(c for c in failed if c.code == "ABOVE_RANGE")
    assert all(drawn.strata[v] == "always:override" for v in above.values)
    tick_all(ws, drawn)
    assert review.blockers(ws, "study", study, **ask, blinded=False) == ()
    assert _codes(review.blockers(ws, "study", study, **ask, blinded=True)) == ["BLINDED"]
    assert IntakeStore(ws).review.verify() == []


def test_a_subject_that_is_not_the_projects_is_refused(ws, truth):
    reader = Ledger(ws)
    for subject_type, subject in (("study", "st-999"), ("product", study_of(reader, "230-23")), ("compound", "st-1"),
                                  ("study", "../st-1"), ("batch", "ba-1")):
        with pytest.raises(review.ReviewError) as refused:
            review.blockers(ws, subject_type, subject, reader=reader, **CARD, blinded=False)  # type: ignore[arg-type]
        assert refused.value.code in ("UNKNOWN", "INVALID")
        with pytest.raises(review.ReviewError):
            review.draw_spot_check(ws, subject_type, subject, reader=reader, by=BY, blinded=False)  # type: ignore[arg-type]
    assert IntakeStore(ws).review.entries() == []


# --- the bound record -------------------------------------------------------------------------------------------------


def _sha(ws: Workspace, subject: str, reader: LedgerView | None = None) -> str:
    return review.bound_record(ws, "study", subject, reader=reader or Ledger(ws), **CARD)[1]


def test_the_bound_record_is_the_contracts_and_changes_with_everything_it_binds(ws, monkeypatch):
    book = Book(ws)
    study = book.entity("study", "EXA-401")
    analyte = book.entity("analyte", synthetic.DRUG)
    on, profile = {"study": study}, {"study": study, "analyte": analyte, "matrix": "plasma"}
    ids = {name: book.fact(name, value, on, **kw) for name, value, kw in (
        ("dose", 50.0, {"unit": "mg"}), ("n", 12, {}), ("route", "oral", {}), ("formulation", "ir_tablet", {}),
        ("food_state", "fasted", {}), ("intended_use", "model_building", {}), ("salt_or_base", "base", {}))}
    ids["lloq"] = book.fact("lloq", 0.5, profile, unit="ng/mL")
    for i in range(3):
        ids[f"c{i}"] = book.fact("concentration", 10.0 + i, {**profile, "subject": "001"}, unit="ng/mL", time=float(i + 1),
                                 time_unit="h", statistic="individual")
    book.fact("concentration", None, {**profile, "subject": "001"}, unit="ng/mL", time=9.0, time_unit="h",
              statistic="individual", uloq=1000.0, verbatim=">1000")                 # above the range: a failed check
    covered(book)
    reader = Ledger(ws)
    record, sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
    assert sha == sha256_of(record) and json.loads(json.dumps(record)) == record
    assert list(record) == ["schema", "project", "subject_type", "subject", "label", "subject_digest", "facts", "extracts",
                            "excluded", "assignments", "mappings", "overrides", "dispositions", "choices", "links",
                            "regions", "spot_check", "coverage", "requirements", "checks", "held", "rules"]
    assert (record["schema"], record["project"], record["subject_type"], record["subject"], record["label"]) == (
        "confirmation/1", "p1", "study", study, "EXA-401")
    assert record["subject_digest"] == reader.digest(study=study)
    assert [ids["dose"], "50.0", "mg"] in record["facts"] and [ids["n"], "12", None] in record["facts"]
    assert len(record["facts"]) == len(reader.values(study=study)) and record["extracts"] == [] == record["excluded"]
    assert record["coverage"] == {"files": 1, "silent_loss": 0, "regions_unread": 0, "outside_numeric": 0,
                                  "values_unassigned": 0}
    assert record["rules"] == {"version": RULES_VERSION, "status": RULES_STATUS, "sha256": RULES_SHA256}
    assert record["rules"]["status"] == "UNVERIFIED" and record["spot_check"] is None
    assert ["REQ-sys.demographics", "missing"] in record["requirements"]
    missing = next(c for c in record["checks"] if c[0] == "REQUIRED_ITEM_UNDISPOSED")
    assert missing[2] == "fail"
    # what the landing writes nowhere is listed with its reason: here the salt form, which a study record does not hold
    assert record["held"] == ["EXA-401: study facts with no place in the study record (salt_or_base): kept in the ledger"]
    seen = {sha}

    def changed(what: str) -> dict[str, Any]:
        reader.refresh()
        now, now_sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
        assert now_sha not in seen, what
        seen.add(now_sha)
        return now

    # another study's fact (the same file, the same delivery) changes nothing
    other = book.entity("study", "EXA-402")
    book.fact("dose", 10.0, {"study": other}, unit="mg")
    reader.refresh()
    assert _sha(ws, study, reader) == sha
    # a value
    fact = reader.enter(supersedes=ids["c1"], value=11.5, why="the report says 11.5", by=BY)
    now = changed("a value")
    assert [fact.id, "11.5", "ng/mL"] in now["facts"] and not any(row[0] == ids["c1"] for row in now["facts"])
    # an override, a disposition
    check = next(c for c in review.card(ws, "study", study, reader=reader, **CARD, blinded=False).checks
                 if c.code == "ABOVE_RANGE")
    assert [check.code, check.id, "fail"] in record["checks"]
    made = review.override(ws, subject=study, check_id=check.id, why="read against the source", by=BY)
    now = changed("an override")
    assert now["overrides"] == [f"{made.id}:{line_hash(ws, made.id)}"] and [check.code, check.id, "overridden"] in now["checks"]
    disposed = review.dispose(ws, subject=study, req_id="REQ-sys.demographics", disposition="not_needed",
                              why="adults of the label population", by=BY)
    now = changed("a disposition")
    assert now["dispositions"] == [f"{disposed.id}:{line_hash(ws, disposed.id)}"]
    assert ["REQ-sys.demographics", "not_needed"] in now["requirements"]         # and with it a requirement's status
    assert not any(c[0] == "REQUIRED_ITEM_UNDISPOSED" for c in now["checks"])    # the item is disposed: its check is gone
    # a requirement status alone: the demographics arrive
    book.fact("population", "healthy", on)
    book.fact("age_mean", 33.0, on)
    assert ["REQ-sys.demographics", "found"] in changed("a requirement status")["requirements"]
    # an assignment
    arm = book.entity("arm", "Fasted", parent=study)
    reader.refresh()
    assigned = review.assign(ws, targets=[ids["dose"]], study=study, arm=arm, why="the dose is the fasted arm's", by=BY)
    assert changed("an assignment")["assignments"] == [f"{assigned.id}:{line_hash(ws, assigned.id)}"]
    # the spot check: its draw, then its record
    drawn = draw(ws, study, reader=reader)
    assert changed("the draw")["spot_check"] == f"{drawn.id}:{line_hash(ws, drawn.id)}"
    ticked = tick_all(ws, drawn)
    assert changed("the spot check")["spot_check"] == f"{ticked.id}:{line_hash(ws, ticked.id)}"
    # the coverage
    covered(book, silent_loss=3, cells_silent=3, cells_used=7)
    assert changed("the coverage")["coverage"]["silent_loss"] == 3
    # the rules file
    monkeypatch.setattr(review, "RULES_SHA256", "f" * 64)
    assert changed("the rules file")["rules"]["sha256"] == "f" * 64


def test_the_bound_record_binds_extracts_by_content_and_a_mapping_by_its_decision(ws):
    csv = synthetic.delivery()[3]
    keys = write_truth(ws, [csv], approved=False)
    reader = Ledger(ws)
    study = study_of(reader, "230-28")
    record, sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
    store = IntakeStore(ws)
    (line,) = store.facts.entries("extract")
    assert record["extracts"] == [[line.body["id"], line.body["content_sha256"]]] and record["excluded"] == []
    ((mapping_id, version, status),) = record["mappings"]
    assert status == "proposed" and (mapping_id, version) == (line.body["mapping"]["mapping_id"], 1)
    # the mapping is approved: the record changes
    MappingCache(ws).approve(mapping_id, version, by=BY, note="read against the file")
    reader.refresh()
    now, now_sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
    assert now["mappings"] == [[mapping_id, version, "approved"]] and now_sha != sha
    # a value of the extract a person excluded is left out of what the record binds, by its id
    value_id = next(v for k, v in keys.items() if "|concentration|" in k)
    reader.exclude(value_id, why="a transcription error in the listing", by=BY)
    after, after_sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
    assert after["excluded"] == [value_id] and after["extracts"] == now["extracts"] and after_sha != now_sha
    assert after["subject_digest"] != now["subject_digest"]


@pytest.mark.req("T-47", "T-05", "F-404", "F-403", "T-06")
def test_a_confirmation_is_refused_when_its_record_is_not_the_subjects_as_it_is_now(ws):
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    record, sha = review.bound_record(ws, "study", ids["study"], reader=reader, **CARD)
    signed = dict(signature_id="sig-0001", manifestation="Reviewed by A. Reviewer", by=BY, printed_name="A. Reviewer",
                  blinded=False)
    for bad_record, bad_sha, code in (({**record, "label": "another"}, sha, "INVALID"),            # not the hash signed
                                      (record, "0" * 64, "INVALID"), (record, "../x", "INVALID")):
        with pytest.raises(review.ReviewError) as refused:
            review.record_confirmation(ws, subject_type="study", subject=ids["study"], record=bad_record,
                                       record_sha256=bad_sha, **signed)
        assert refused.value.code == code
    other_book = Book(ws, sha=OTHER, name="other.xlsx")
    other = clean_study(other_book, "EXA-402")
    covered(other_book)
    reader.refresh()
    with pytest.raises(review.ReviewError):                       # another subject's record
        review.record_confirmation(ws, subject_type="study", subject=other["study"], record=record, record_sha256=sha, **signed)
    with pytest.raises(review.ReviewError):                       # no signature id
        review.record_confirmation(ws, subject_type="study", subject=ids["study"], record=record, record_sha256=sha,
                                   **{**signed, "signature_id": " "})
    reader.enter(supersedes=ids["c0"], value=9.0, why="a correction after the record was computed", by=BY)
    with pytest.raises(review.ReviewError) as refused:            # the values changed since
        review.record_confirmation(ws, subject_type="study", subject=ids["study"], record=record, record_sha256=sha, **signed)
    assert refused.value.code == "STALE"
    assert IntakeStore(ws).review.entries("confirmation") == [] and events(ws, "intake.confirm") == []
    # a record that itself shows a refusal is never recorded: here no spot check was done (the route checks every
    # refusal before it signs; this is the net under it)
    record, sha = review.bound_record(ws, "study", ids["study"], reader=reader, **CARD)
    with pytest.raises(review.ReviewError) as refused:
        review.record_confirmation(ws, subject_type="study", subject=ids["study"], record=record, record_sha256=sha, **signed)
    assert refused.value.code == "CONFLICT" and "no spot check" in str(refused.value)
    covered(book, silent_loss=2, cells_silent=2, cells_used=8)
    settle(ws, "study", ids["study"], reader)
    with pytest.raises(review.ConfirmationRefused) as blocked:
        review.prepare_confirmation(ws, None, "study", ids["study"], reader=reader, **CARD, blinded=False)
    assert [b.code for b in blocked.value.blockers] == ["SILENT_LOSS"] and blocked.value.code == "CONFLICT"
    record, sha = review.bound_record(ws, "study", ids["study"], reader=reader, **CARD)
    with pytest.raises(review.ReviewError, match="silent_loss"):
        review.record_confirmation(ws, subject_type="study", subject=ids["study"], record=record, record_sha256=sha, **signed)
    assert IntakeStore(ws).review.entries("confirmation") == [] and events(ws, "intake.confirm") == []
    covered(book)
    with pytest.raises(review.ConfirmationRefused) as blocked:                 # a blinded study is refused before signing
        review.prepare_confirmation(ws, None, "study", ids["study"], reader=reader, **CARD, blinded=True)
    assert [b.code for b in blocked.value.blockers] == ["BLINDED"]
    # every refusal checked in one call: the record to sign, its hash and the landing plan; nothing written
    record, sha, plan = review.prepare_confirmation(ws, None, "study", ids["study"], reader=reader, **CARD, blinded=False)
    assert sha == sha256_of(record) and len(plan.datasets) == 1 and IntakeStore(ws).review.entries("confirmation") == []
    # a correction supersedes: the next confirmation names the one before, and binds the corrected value
    first = review.record_confirmation(ws, subject_type="study", subject=ids["study"], record=record, record_sha256=sha, **signed)
    fact = reader.enter(supersedes=ids["c1"], value=19.0, why="another correction", by=BY)
    assert reader.value(fact.id).status == "proposed" and reader.value(ids["c2"]).status == "confirmed"
    settle(ws, "study", ids["study"], reader)
    record, sha = review.bound_record(ws, "study", ids["study"], reader=reader, **CARD)
    second = review.record_confirmation(ws, subject_type="study", subject=ids["study"], record=record, record_sha256=sha,
                                        **{**signed, "signature_id": "sig-0002"})
    reader.refresh()
    assert second.supersedes == first.id and reader.value(fact.id).confirmation == second.id
    assert review.current_confirmation(ws, "study", ids["study"], reader=reader) == second
    (row,) = [r for r in review.subjects(ws, reader=reader) if r["subject"] == ids["study"]]
    assert row["confirmation"]["id"] == second.id and row["confirmation"]["current"] and not row["confirmation"]["landed"]


# --- decisions: the coverage they recompute, their audit events ----------------------------------------------------------


def _stored(ws: Workspace, sha: str) -> FileCoverage:
    found = IntakeStore(ws).coverage(sha)
    assert found is not None
    return found


def test_exclude_regions_and_assign_store_the_recomputed_coverage(ws):
    pdf = synthetic.pdf_report(unruled_table=False)
    sha = sha_of(pdf)
    arrive(ws, sha, pdf.name, data=pdf.data)
    ledger = Ledger(ws)
    record_table(ledger, pdf, "report-table6")                                        # Study 230-26, Cohort 1
    untold = record_table(ledger, pdf, "report-table5", drop=("study_id",))            # a table that names no study
    study = study_of(ledger, "230-26")
    listed = review.unassigned(ws, reader=ledger)
    table5 = [v for v in listed if v.id.startswith(f"{untold.extract}#")]
    assert table5 and len(listed) > len(table5)                                        # its values, and its caption's facts
    before = cover(ws, pdf)
    assert before.summary.values_unassigned == len(listed) and before.summary.outside_numeric == 0
    region5 = next(r.region.id for r in before.regions if r.region.where == "p:2/t:1")
    prose = next(r.region.id for r in before.regions if r.region.kind == "prose")

    # assigning the table's values: the stored coverage counts what is left
    made = review.assign(ws, targets=[untold.extract], study=study, why="Table 5 is study 230-26's listing", by=BY)
    assert made.targets == (untold.extract,) and (made.study, made.arm, made.product) == (study, None, None)
    after = _stored(ws, sha)
    assert after.summary.values_unassigned == len(listed) - len(table5) > 0
    assert after.computed_at != before.computed_at and after.summary.regions_mapped == before.summary.regions_mapped
    ledger.refresh()
    assert all(v.entity.study == study for v in ledger.values() if v.id.startswith(f"{untold.extract}#"))

    # a prose decision cannot exclude a table; an unknown region, another file and a bad id are refused; nothing is written
    lines = len(IntakeStore(ws).review.entries("region"))
    for kwargs, code in ((dict(regions=[region5], scope="unread_prose"), "INVALID"),
                         (dict(regions=[region5], scope="figures"), "INVALID"),
                         (dict(regions=["rg-0000000000"], scope="regions"), "UNKNOWN"),
                         (dict(regions=["../rg-1"], scope="regions"), "INVALID"),
                         (dict(regions=[], scope="regions"), "INVALID"),
                         (dict(regions=[region5], scope="everything"), "INVALID"),
                         (dict(regions=["s:'Nowhere'!A1"], scope="outside"), "UNKNOWN"),
                         (dict(regions=["not a locator"], scope="outside"), "INVALID")):
        with pytest.raises(review.ReviewError) as refused:
            review.exclude_regions(ws, file_sha256=sha, why="not data", by=BY, **kwargs)  # type: ignore[arg-type]
        assert refused.value.code == code, kwargs
    for bad_file in ("f" * 64, "../" + sha[3:], sha[:-1]):
        with pytest.raises(review.ReviewError):
            review.exclude_regions(ws, file_sha256=bad_file, regions=[region5], scope="regions", why="not data", by=BY)
    with pytest.raises(review.ReviewError):
        review.exclude_regions(ws, file_sha256=sha, regions=[region5], scope="regions", why=" ", by=BY)
    assert len(IntakeStore(ws).review.entries("region")) == lines and _stored(ws, sha) == after

    # excluding the table: its region is excluded with the reason, and what the ledger read from it is set aside
    decision = review.exclude_regions(ws, file_sha256=sha, regions=[region5], scope="regions",
                                      why="a duplicate of the listing sent as CSV", by=BY)
    assert decision.parser_version == TRUTH_PARSER_VERSION and decision.scope == "regions"
    final = _stored(ws, sha)
    excluded = next(r for r in final.regions if r.region.id == region5)
    assert excluded.outcome.state == "excluded" and excluded.outcome.reason == f"{decision.id}: {decision.why}"
    assert final.decisions == (decision.id,) and final.summary.regions_excluded == before.summary.regions_excluded + 1
    assert final.summary.silent_loss == 0 and final.summary.values_unassigned == 0
    ledger.refresh()
    assert review.unassigned(ws, reader=ledger) == []
    gone = [v for v in ledger.values(active=False) if v.id.startswith(f"{untold.extract}#")]
    assert gone and all(v.status == "excluded" and v.status_reason.startswith(decision.id) for v in gone)
    kept = ledger.values(study=study)
    assert kept and all(not v.id.startswith(f"{untold.extract}#") for v in kept)      # Table 6 is untouched
    # a later decision recomputes from ALL decisions: the first one still holds
    second = review.exclude_regions(ws, file_sha256=sha, regions=[prose], scope="unread_prose", why="a cover page", by=BY)
    assert set(_stored(ws, sha).decisions) == {decision.id, second.id}
    assert next(r for r in _stored(ws, sha).regions if r.region.id == region5).outcome.state == "excluded"


def test_one_audit_event_per_decision_with_the_lines_hash(ws, truth):
    workbook, pdf = synthetic.delivery()[:2]
    for file in (workbook, pdf):
        cover(ws, file)
    ledger = Ledger(ws)
    study = study_of(ledger, "230-23")
    facts_before = len(IntakeStore(ws).facts.entries())
    before = len(events(ws))

    def only(action: str, record_id: str, why: str | None, **after: Any) -> None:
        (event,) = events(ws, action)
        assert event.after == {**after, "row_hash": line_hash(ws, record_id)} and event.reason == why
        assert (event.actor, event.resource_type, event.resource_id) == (BY, "intake", f"{ws.project_id}/{record_id}")

    check = next(c for c in review.card(ws, "study", study, reader=ledger, **CARD, blinded=False).checks
                 if c.code == "ABOVE_RANGE")
    made = review.override(ws, subject=study, check_id=check.id, why="as written in the listing", by=BY)
    only("intake.override", made.id, made.why, override=made.id, check_id=check.id)
    disposed = review.dispose(ws, subject=study, req_id="REQ-sys.demographics", disposition="ask_client", why="asked", by=BY)
    only("intake.disposition", disposed.id, "asked", disposition=disposed.id, req_id="REQ-sys.demographics")
    # a conflict: the synopsis says 24 subjects, a person's note says 12
    (stated,) = [v for v in ledger.values(study=study, field="n")]
    other = Book(ws, sha=sha_of(workbook), name=workbook.name, sheet="Notes").fact("n", 12, {"study": study})
    ledger.refresh()
    (conflict,) = [c for c in ledger.conflicts(study=study) if c.field == "n"]
    chosen = review.choose(ws, conflict_id=conflict.id, keep=stated.id, why="the synopsis is the signed report", by=BY)
    only("intake.choice", chosen.id, chosen.why, id=chosen.id)
    ledger.refresh()
    assert ledger.value(other).status == "excluded" and chosen.id in ledger.value(other).status_reason
    assert [c for c in ledger.conflicts(study=study) if c.field == "n"] == []
    link = ledger.pending_links(study=study)[0]
    confirmed = review.confirm_link(ws, link_fact=link.link_fact, study=study, file_sha256=link.file_sha256, confirmed=True,
                                    why="", by=BY)
    only("intake.link", confirmed.id, None, id=confirmed.id)
    assert review.confirm_link(ws, link_fact=link.link_fact, study=study, file_sha256=link.file_sha256, confirmed=True,
                               why="", by=BY) == confirmed                       # the same decision again: nothing new
    ledger.refresh()
    assert ledger.pending_links(study=study) == []
    stray = Book(ws, sha=sha_of(workbook), name=workbook.name, sheet="Notes2").fact("age_mean", 33.0, {})
    assigned = review.assign(ws, targets=[stray], study=study, why="the note is this study's", by=BY)
    only("intake.assign", assigned.id, assigned.why, id=assigned.id)
    region = review.exclude_regions(ws, file_sha256=sha_of(workbook), regions=["s:'Summary'!A10"], scope="outside",
                                    why="a working note", by=BY)
    only("intake.region", region.id, region.why, id=region.id)
    assert _stored(ws, sha_of(workbook)).summary.outside_numeric == 0
    # six decisions, six events: none per fact (the exclusions a choice makes are the choice's)
    assert len(events(ws)) == before + 6
    assert len(IntakeStore(ws).facts.entries()) > facts_before + 1
    kinds = Counter(e.kind for e in IntakeStore(ws).review.entries())
    assert kinds == {"override": 1, "disposition": 1, "choice": 1, "link": 1, "assignment": 1, "region": 1}
    assert {e.body["by"] for e in IntakeStore(ws).review.entries()} == {BY}
    assert all(e.body["at"] and ("why" in e.body) for e in IntakeStore(ws).review.entries())
    # the chain: a changed line is found
    store = IntakeStore(ws)
    assert store.review.verify() == []
    text = store.review.path.read_text(encoding="utf-8")
    store.review.path.write_text(text.replace("as written in the listing", "as written in the listing!"), encoding="utf-8")
    assert [p.problem for p in store.review.verify()] == ["hash"]


def test_a_decision_that_names_nothing_of_the_project_is_refused_and_writes_nothing(ws, truth):
    ledger = Ledger(ws)
    study = study_of(ledger, "230-23")
    pdf = synthetic.delivery()[1]
    product = ledger.entities("product")[0].id
    batch = ledger.entities("batch")[0].id
    value = ledger.values(study=study, field="concentration")[0].id
    refusals = [
        lambda: review.override(ws, subject=study, check_id="ck-1", why="x", by=BY),
        lambda: review.override(ws, subject=study, check_id="ck-0123456789ab", why="  ", by=BY),
        lambda: review.override(ws, subject="st-999", check_id="ck-0123456789ab", why="x", by=BY),
        lambda: review.override(ws, subject="../../etc", check_id="ck-0123456789ab", why="x", by=BY),
        lambda: review.dispose(ws, subject=study, req_id="REQ-sys.demographics", disposition="forget", why="x", by=BY),
        lambda: review.dispose(ws, subject=study, req_id="../REQ", disposition="not_needed", why="x", by=BY),
        lambda: review.dispose(ws, subject=study, req_id="REQ-sys.demographics", disposition="not_needed", why="", by=BY),
        lambda: review.choose(ws, conflict_id="cx-0123456789", keep=value, why="x", by=BY),
        lambda: review.choose(ws, conflict_id="cx-1", keep=value, why="x", by=BY),
        lambda: review.confirm_link(ws, link_fact=None, study=study, file_sha256="e" * 64, confirmed=True, why="", by=BY),
        lambda: review.confirm_link(ws, link_fact=None, study="st-999", file_sha256=sha_of(pdf), confirmed=True, why="", by=BY),
        lambda: review.confirm_link(ws, link_fact=None, study=study, file_sha256=sha_of(pdf), confirmed=False, why="", by=BY),
        lambda: review.confirm_link(ws, link_fact="tx-1", study=study, file_sha256=sha_of(pdf), confirmed=True, why="", by=BY),
        lambda: review.assign(ws, targets=[value], why="x", by=BY),
        lambda: review.assign(ws, targets=[], study=study, why="x", by=BY),
        lambda: review.assign(ws, targets=["f-999999"], study=study, why="x", by=BY),
        lambda: review.assign(ws, targets=[value], study=product, why="x", by=BY),
        lambda: review.assign(ws, targets=[value], study=study, batch=batch, why="x", by=BY),
        lambda: review.assign(ws, targets=[value], study=study, arm="arm-999", why="x", by=BY),
        lambda: review.assign(ws, targets=["../f-1"], study=study, why="x", by=BY),
        lambda: review.assign(ws, targets=[value], study=study, why="", by=BY),
    ]
    for refusal in refusals:
        with pytest.raises(review.ReviewError):
            refusal()
    assert IntakeStore(ws).review.entries() == [] and events(ws) == []
    # a product assignment (§13): the product and its batch, the study left as it was
    made = review.assign(ws, targets=[value], product=product, batch=batch, why="the test product's listing", by=BY)
    ledger.refresh()
    assert (made.study, made.product, made.batch) == (None, product, batch)
    assert (ledger.value(value).entity.study, ledger.value(value).entity.product) == (study, product)
    # a refused link excludes the values joined through it, and says why
    link = ledger.pending_links(study=study)[0]
    refused = review.confirm_link(ws, link_fact=link.link_fact, study=study, file_sha256=link.file_sha256, confirmed=False,
                                  why="the synopsis is another protocol's", by=BY)
    ledger.refresh()
    joined = [v for v in ledger.values(file_sha256=sha_of(pdf), active=False) if v.entity.study == study and v.cross_file]
    assert joined and all(v.status == "excluded" and v.status_reason == refused.why for v in joined)


def test_a_value_with_a_batch_alone_is_still_study_not_stated(ws):
    """Written for the fixed `ledger_view.is_unassigned` (no study, no product, not a compound field: a batch alone
    does not assign a value). It fails on a line where a batch alone still counts as a subject."""
    book = Book(ws)
    product = book.entity("product", "Exampleamide IR tablet")
    batch = book.entity("batch", "L2301", parent=product)
    fact = book.fact("percent_dissolved", 85.0, {"batch": batch}, unit="%", time=30.0, time_unit="min")
    assert [v.id for v in review.unassigned(ws, reader=Ledger(ws))] == [fact]


# --- the page's lists -------------------------------------------------------------------------------------------------


def test_the_subjects_are_the_studies_the_products_and_the_compound_with_their_counts(ws, truth):
    workbook = synthetic.delivery()[0]
    reader = Ledger(ws)
    rows = review.subjects(ws, reader=reader)
    studies = {r["label"]: r for r in rows if r["subject_type"] == "study"}
    assert set(studies) == {e.label for e in reader.entities("study")} >= {"230-23", "231-24"}
    assert {r["label"] for r in rows if r["subject_type"] == "product"} == {e.label for e in reader.entities("product")}
    assert not any(r["subject_type"] == "compound" for r in rows)                       # the delivery states no compound value
    row = studies["230-23"]
    values = reader.values(study=row["subject"])
    assert row["values"] == len(values) and sum(row["by_level"].values()) == len(values) == sum(row["by_method"].values())
    assert row["by_level"].keys() == {v.level for v in values} and row["deliveries"] == ["dl-1"]
    assert row["files"] == sorted({v.file_sha256 for v in values if v.file_sha256}) and len(row["files"]) == 2
    assert row["confirmation"] is None and row["loaded_elsewhere"] == [] and row["confirm_on"] == "delivery"
    assert "blockers" not in row                                 # the polled page never recomputes every card
    # a legacy dataset of the same sheet and study is listed; a rejected one is not; another study's table is not
    same = _legacy_dataset(ws, sha=sha_of(workbook), study_id="230-23", locator="Fasting!A2:G14")
    _legacy_dataset(ws, sha=sha_of(workbook), study_id="999-99", locator="Fasting!A40:G52")
    rows = {r["label"]: r for r in review.subjects(ws, reader=reader)}
    assert rows["230-23"]["loaded_elsewhere"] == [same.id] and rows["231-24"]["loaded_elsewhere"] == []
    decide_dataset(ws, same.id, state=EvidenceState.REJECTED, reason="read again", by=BY)
    assert {r["label"]: r for r in review.subjects(ws, reader=reader)}["230-23"]["loaded_elsewhere"] == []
    # the compound is a subject once a compound-level value arrives, with its own card
    fact = Book(ws, sha=sha_of(workbook), name=workbook.name, sheet="Physchem").fact("phys.logp", 2.1, {})
    reader.refresh()
    (compound,) = [r for r in review.subjects(ws, reader=reader) if r["subject_type"] == "compound"]
    assert (compound["subject"], compound["label"], compound["values"]) == ("compound", "compound", 1)
    assert review.unassigned(ws, reader=reader) == []            # a compound value is not "study not stated"
    card = review.card(ws, "compound", "compound", reader=reader, **CARD, blinded=False)
    assert card.values == 1 and card.requirements == () and card.gaps == ()
    assert fact in review.draw_spot_check(ws, "compound", "compound", reader=reader, by=BY, blinded=False).sampled
    # a project with no file root has no Delivery: the lists read as empty
    class Memory:
        pass

    off = Workspace(Memory(), "t1", "p1")  # type: ignore[arg-type]
    assert review.subjects(off, reader=LedgerView(off)) == [] and review.unassigned(off, reader=LedgerView(off)) == []


# --- blinding (D-15) --------------------------------------------------------------------------------------------------

ON = {"blinding": {"on": True, "reason": "external validation is judged blind", "by": "u-lead", "at": AT}}
BLIND = pytest.mark.req("T-47", "T-05", "F-404", "F-402")


def _external_study(ws: Workspace) -> tuple[Book, dict[str, str]]:
    book = Book(ws)
    ids = clean_study(book)
    ids["intended_use"] = Ledger(ws).enter(supersedes=ids["intended_use"], value="external_validation",
                                          why="the study judges the model", by=BY).id
    profile = {"study": ids["study"], "analyte": ids["analyte"], "matrix": "plasma"}
    ids["blq"] = book.fact("concentration", None, {**profile, "subject": "001"}, unit="ng/mL", time=0.0, time_unit="h",
                           statistic="individual", censored=True, lloq=0.5, lloq_unit="ng/mL", verbatim="<0.5")
    ids["mean"] = book.fact("concentration", 20.0, profile, unit="ng/mL", time=1.0, time_unit="h",
                            statistic="arithmetic_mean", spread=2.5, spread_kind="SD", interval=(15.0, 25.0),
                            interval_kind="range")
    covered(book)
    return book, ids


@BLIND
def test_which_studies_are_blinded(ws):
    _book, ids = _external_study(ws)
    other_book = Book(ws, sha=OTHER, name="other.xlsx")
    other = clean_study(other_book, "EXA-402")                                       # for model building
    covered(other_book)
    assert review.blinded_subjects(ws, ON, None) == {ids["study"]}
    assert review.blinded_subjects(ws, None, "high") == {ids["study"]}               # on by default for high model risk
    assert review.blinded_subjects(ws, None, "low") == set() == review.blinded_subjects(ws, None, None)
    assert review.blinded_subjects(ws, {"blinding": {"on": False, "reason": "open"}}, "high") == set()
    # a study whose landed dataset the plan judges externally is blinded too, whatever its intended use says
    reader = Ledger(ws)
    tick_all(ws, draw(ws, other["study"], reader=reader))
    confirmation = _confirm(ws, other["study"], reader)
    landed = _legacy_dataset(ws, sha=OTHER, study_id="EXA-402", locator="Delivery confirmation " + confirmation.id)
    IntakeStore(ws).review.append("landed", Landed(confirmation=confirmation.id, datasets=(landed.id,), evidence=(),
                                                   dissolution_records=0, rejected_legacy=(), pending=(), at=AT).model_dump())
    assert review.blinded_subjects(ws, ON, None) == {ids["study"]}
    from modeler_project.artifacts import ArtifactKind
    from modeler_project.dataset_register import dataset

    external = dataset(ws, landed.id).model_copy(update={"purpose": "external_validation"})
    ws.commit(ArtifactKind.DATASET, landed.id, external.to_content(), actor=BY, reason="entered for external validation")
    assert review.blinded_subjects(ws, ON, None) == {ids["study"], other["study"]}
    assert review.blinded_subjects(ws, None, "low") == set()
    hidden = review.blinded_subjects(ws, ON, None)
    assert review.is_blinded(reader, "study", ids["study"], hidden) and not review.is_blinded(reader, "study", ids["study"], set())


@BLIND
def test_a_blinded_studys_values_are_withheld_its_spot_check_cannot_be_drawn_and_its_confirmation_is_refused(ws):
    book, ids = _external_study(ws)
    reader = Ledger(ws)
    hidden = review.blinded_subjects(ws, ON, None)
    blinded = review.is_blinded(reader, "study", ids["study"], hidden)
    assert blinded
    # the card: no check names a value (which values are below the LLOQ says something of them); nothing else changes
    open_card = review.card(ws, "study", ids["study"], reader=reader, **CARD, blinded=False)
    card = review.card(ws, "study", ids["study"], reader=reader, **CARD, blinded=blinded)
    assert any(c.code == "BLQ_PRESENT" and c.values for c in open_card.checks)
    assert all(c.values == () for c in card.checks) and [c.id for c in card.checks] == [c.id for c in open_card.checks]
    assert card.model_copy(update={"checks": open_card.checks}) == open_card
    text = card.model_dump_json()
    assert "0.5" not in text and "20.0" not in text and "<0.5" not in text
    # the spot check cannot be drawn; the confirmation is refused with BLINDED
    with pytest.raises(review.ReviewError) as refused:
        review.draw_spot_check(ws, "study", ids["study"], reader=reader, by=BY, blinded=blinded)
    assert refused.value.code == "BLINDED" and IntakeStore(ws).review.entries("spot_draw") == []
    found = review.blockers(ws, "study", ids["study"], reader=reader, **CARD, blinded=blinded)
    assert [b.code for b in found] == ["SPOT_CHECK", "BLINDED"]
    assert not any(ch.isdigit() for b in found for ch in b.detail.replace("D-15", ""))
    # `blinded` cannot be forgotten: the functions that show or act on a subject's values need it
    for call in (lambda: review.card(ws, "study", ids["study"], reader=reader, **CARD),
                 lambda: review.draw_spot_check(ws, "study", ids["study"], reader=reader, by=BY),
                 lambda: review.blockers(ws, "study", ids["study"], reader=reader, **CARD),
                 lambda: review.shown(reader.values(study=ids["study"])),
                 lambda: review.latest_spot_check(ws, "study", ids["study"], reader=reader),
                 lambda: review.prepare_confirmation(ws, None, "study", ids["study"], reader=reader, **CARD),
                 lambda: review.source_view(ws, reader=reader, value=ids["mean"])):
        with pytest.raises(TypeError):
            call()  # type: ignore[call-arg]
    # every value a route lists goes through `shown`: value, verbatim, spread, interval, LLOQ and the BLQ mark are gone
    listed = {v.id: (v, flag) for v, flag in review.shown(reader.values(study=ids["study"]), hidden)}
    for value_id in (ids["blq"], ids["mean"], ids["c0"], ids["dose"]):
        value, flag = listed[value_id]
        assert flag and (value.value, value.verbatim, value.spread, value.interval, value.lloq, value.uloq) == (
            None, "", None, None, None, None) and not value.censored
        original = reader.value(value_id)
        assert (value.field, value.unit, value.time, value.entity, value.anchor) == (
            original.field, original.unit, original.time, original.entity, original.anchor)
    assert not any(v.censored for v, _flag in listed.values())                      # no count of BLQ values can be made
    shown_open = review.shown(reader.values(study=ids["study"]), set())
    assert all(not flag for _v, flag in shown_open) and [v for v, _f in shown_open] == reader.values(study=ids["study"])
    # a study blinded after its spot check was drawn: the draw is shown without its strata (they say which values
    # are below the LLOQ), the record without its notes
    assert review.latest_spot_check(ws, "study", ids["study"], reader=reader, blinded=blinded) == (None, None)
    other = clean_study(Book(ws, sha=OTHER, name="other.xlsx"), "EXA-402")
    reader.refresh()
    drawn = draw(ws, other["study"], reader=reader)
    review.record_spot_check(ws, drawn.id, [SpotTick(value_id=v, ok=v != other["c0"], note="reads 10.5 in the source")
                                            for v in (*drawn.always, *drawn.sampled)], by=BY)
    open_draw, open_record = review.latest_spot_check(ws, "study", other["study"], reader=reader, blinded=False)
    assert open_draw == drawn and open_record.ticks[0].note
    late_draw, late_record = review.latest_spot_check(ws, "study", other["study"], reader=reader, blinded=True)
    assert late_draw.strata == {} and (late_draw.id, late_draw.sampled) == (drawn.id, drawn.sampled)
    assert {t.note for t in late_record.ticks} == {""} and [t.ok for t in late_record.ticks] == [t.ok for t in open_record.ticks]
    # a product's card is blinded when one of its values is the blinded study's
    product = book.entity("product", "Exampleamide IR tablet")
    book.fact("strength_mg", 50.0, {"study": ids["study"], "product": product})
    reader.refresh()
    assert review.is_blinded(reader, "product", product, hidden) and not review.is_blinded(reader, "product", product, set())
    ((value, flag),) = review.shown(reader.values(product=product), hidden)
    assert flag and value.value is None


@BLIND
def test_the_source_of_a_value_is_shown_with_its_cells_and_blank_for_a_blinded_study(ws, truth):
    files = synthetic.delivery()
    workbook, pdf = files[:2]
    for file in files[:2]:
        cover(ws, file)
    reader = Ledger(ws)
    study = study_of(reader, "230-23")
    truth_value = next(v for v in workbook.values if v.table == "fasting-individual" and v.field == "concentration"
                       and v.subject and v.value == "12.1")
    value_id = truth[truth_key(workbook, truth_value)]
    view, file, shown_id = review.source_view(ws, reader=reader, hidden=set(), value=value_id)
    assert (file.sha256, file.name, shown_id) == (sha_of(workbook), workbook.name, value_id)
    assert view.kind == "grid" and view.region_id is not None
    by_role = {c.role: c for c in view.cells if c.highlighted}
    assert by_role["value"].text == "12.1" and by_role["value"].locator == truth_value.locator
    assert {"value", "time", "subject"} <= set(by_role) and by_role["subject"].text == truth_value.subject
    numbers = [c for c in view.cells if c.numeric]
    assert len(numbers) > 10
    # the same by its anchor
    by_anchor, _file, no_id = review.source_view(ws, reader=reader, hidden=set(), anchor=reader.value(value_id).anchor)
    assert no_id is None and [c.text for c in by_anchor.cells] == [c.text for c in view.cells]
    # a blinded study: every cell with a number of its region, and every cell a value is anchored at (a BLQ mark), is
    # blank; the headers and labels stay
    blind, _file, _id = review.source_view(ws, reader=reader, hidden={study}, value=value_id)
    anchored = {review._locator(v.anchor) for v in reader.values(file_sha256=sha_of(workbook), active=False) if v.anchor}
    assert all(c.text == "" for c in blind.cells if c.numeric or c.locator in anchored) and len(blind.cells) == len(view.cells)
    assert [c.text for c in blind.cells if not c.numeric and c.locator not in anchored] == [
        c.text for c in view.cells if not c.numeric and c.locator not in anchored]
    assert {"BLQ", "Subject"} <= {c.text for c in view.cells} and "BLQ" not in {c.text for c in blind.cells}
    assert "Subject" in {c.text for c in blind.cells} and not any(ch.isdigit() for ch in blind.title)
    assert next(c for c in blind.cells if c.role == "value").highlighted
    # a sentence of the synopsis: the span, and its digits masked for a blinded study
    dose = next(v for v in reader.values(study=study, field="dose") if v.file_sha256 == sha_of(pdf))
    text, _file, _id = review.source_view(ws, reader=reader, hidden=set(), value=dose.id)
    assert text.kind == "text" and "50 mg" in text.text and text.span is not None and text.page == 1
    masked, _file, _id = review.source_view(ws, reader=reader, hidden={study}, value=dose.id)
    assert not any(ch.isdigit() for ch in masked.text) and len(masked.text) == len(text.text)
    # another study's table in the same file is shown as it is
    other = next(v for v in reader.values(study=study_of(reader, "231-24"), field="concentration") if v.value is not None)
    open_view, _file, _id = review.source_view(ws, reader=reader, hidden={study}, value=other.id)
    assert any(c.text for c in open_view.cells if c.numeric)
    # no path is built from input: an anchor resolves only for a file of this project, in a source model it cached
    foreign = project(ws.store.root, "p2")
    template = synthetic.template_workbook()                    # a file this project never received
    write_truth(foreign, [template])
    cover(foreign, template)
    foreign_value = Ledger(foreign).values(field="concentration")[0]
    assert review.source_view(foreign, reader=Ledger(foreign), hidden=set(), value=foreign_value.id)[1].name == template.name
    for kwargs, code in ((dict(anchor=foreign_value.anchor), "UNKNOWN"), (dict(value=foreign_value.id), "UNKNOWN"),
                         (dict(anchor="../../etc/passwd"), "INVALID"), (dict(anchor="/" + "a" * 64), "INVALID"),
                         (dict(value="../f-1"), "INVALID"), (dict(value="tx-zz#1"), "INVALID"), (dict(), "INVALID"),
                         (dict(value=value_id, anchor=reader.value(value_id).anchor), "INVALID"),
                         (dict(anchor=reader.value(value_id).anchor.replace(TRUTH_PARSER_VERSION, "9.9")), "CONFLICT"),
                         (dict(anchor=reader.value(value_id).anchor.rsplit("!", 1)[0] + "!ZZ999"), "UNKNOWN")):
        with pytest.raises(review.ReviewError) as refused:
            review.source_view(ws, reader=reader, hidden=set(), **kwargs)  # type: ignore[arg-type]
        assert refused.value.code == code, kwargs
    # a person's entry has no source to show
    entered = reader.enter(entity=EntityRef(study=study), field="route", value="oral", why="from the protocol", by=BY)
    with pytest.raises(review.ReviewError) as refused:
        review.source_view(ws, reader=reader, hidden=set(), value=entered.id)
    assert refused.value.code == "UNKNOWN"


# --- regressions of the D6-PM review (2026-11-14) -------------------------------------------------------------------------


def test_a_file_of_the_delivery_that_was_not_read_blocks(ws):
    """G2: every file of the subject's deliveries has a finished run and a coverage file, or the confirmation refuses.
    A run that failed, a file with no run and a file with no coverage file were never counted: silent loss."""
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    study = ids["study"]
    settle(ws, "study", study, reader)
    ask = {"reader": reader, **CARD, "blinded": False}
    assert review.blockers(ws, "study", study, **ask) == ()
    other = hashlib.sha256(b"Exampleamide: the report of the same delivery, never read").hexdigest()
    arrive(ws, other, "study-report.pdf")
    for state, why in ((None, "no run"), ("failed", "its run failed"), ("done", "no coverage file")):
        if state is not None:
            ran(ws, other, state)
        (blocker,) = review.blockers(ws, "study", study, **ask)
        assert blocker.code == "SILENT_LOSS" and blocker.ids == (f"fl-{other[:12]}",)
        assert f"study-report.pdf ({why})" in blocker.detail and "not counted" in blocker.detail
        with pytest.raises(review.ConfirmationRefused):
            review.prepare_confirmation(ws, None, "study", study, **ask)
    # a file still being read is said to be so, as before
    ran(ws, other, "running")
    (blocker,) = review.blockers(ws, "study", study, **ask)
    assert blocker.code == "SILENT_LOSS" and "still being read" in blocker.detail
    # read, with its coverage file: nothing blocks
    covered(Book(ws, sha=other, name="study-report.pdf"))
    assert review.blockers(ws, "study", study, **ask) == ()
    # a ZIP is read through its members: the archive itself needs no run; a member that was not read blocks
    from modeler_intake.source_model import ContainerRef

    archive = hashlib.sha256(b"Exampleamide: a made-up archive").hexdigest()
    member = hashlib.sha256(b"Exampleamide: a made-up member of the archive").hexdigest()
    arrive(ws, archive, "delivery.zip")
    in_zip = FileRecord(file_id=f"fl-{member[:12]}", sha256=member, name="listing.csv", size_bytes=1, delivery="dl-1",
                        container=ContainerRef(sha256=archive, name="delivery.zip", member="listing.csv"), by="code", at=AT)
    IntakeStore(ws).files.append("file", in_zip.model_dump(mode="json"))
    (blocker,) = review.blockers(ws, "study", study, **ask)
    assert blocker.ids == (f"fl-{member[:12]}",) and "listing.csv (no run)" in blocker.detail and "delivery.zip" not in blocker.detail
    covered(Book(ws, sha=member, name="listing.csv"))
    assert review.blockers(ws, "study", study, **ask) == ()
    # the study's own file: its run failed after all (a re-run)
    ran(ws, book.sha, "failed")
    (blocker,) = review.blockers(ws, "study", study, **ask)
    assert blocker.ids == (f"fl-{book.sha[:12]}",) and "made-up.xlsx (its run failed)" in blocker.detail


def test_an_override_made_after_the_draw_makes_the_draw_stale(ws):
    """Decision 6: every value of an overridden check is verified, never sampled. An override made after the draw names
    values the draw did not hold: the draw is stale, and the next one verifies them all and carries the other ticks."""
    book = Book(ws)
    ids = clean_study(book, "EXA-402", points=0)
    study = ids["study"]
    profile = {"study": study, "analyte": ids["analyte"], "matrix": "plasma"}
    for i in range(150):
        book.fact("concentration", 1.0 + i, {**profile, "subject": f"{i // 10:03d}"}, unit="ng/mL", time=float(i % 10 + 1),
                  time_unit="h", statistic="individual")
    for i in range(40):                                    # read from a table by a mapping nobody approved: a failed check
        book.fact("concentration", 5.0 + i, {**profile, "subject": f"8{i:02d}"}, unit="ng/mL", time=1.0, time_unit="h",
                  statistic="individual", method="cell")
    covered(book)
    reader = Ledger(ws)
    first = draw(ws, study, reader=reader)
    tick_all(ws, first)
    assert review.spot_check_state(ws, "study", study, reader=reader) == "complete"
    card = review.card(ws, "study", study, reader=reader, **CARD, blinded=False)
    (check,) = [c for c in card.checks if c.code == "MAPPING_NOT_APPROVED"]
    drawn = {*first.always, *first.sampled}
    outside = set(check.values) - drawn
    assert len(check.values) == 40 and outside and outside != set(check.values)
    review.override(ws, subject=study, check_id=check.id, why="read against the source: as written", by=BY)
    reader.refresh()
    assert review.spot_check_state(ws, "study", study, reader=reader) == "stale"
    (blocker,) = [b for b in review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False) if b.code == "SPOT_CHECK"]
    assert "overrides" in blocker.detail and "draw again" in blocker.detail
    second = draw(ws, study, reader=reader)
    assert second.id != first.id and set(check.values) <= set(second.always)
    assert all(second.strata[v] == "always:override" for v in check.values)
    again = {*second.always, *second.sampled}
    assert set(second.carried) == again & drawn                 # the unchanged ticks carry over
    assert outside <= again - set(second.carried)              # the overridden values not seen before are ticked now
    tick_all(ws, second)
    assert review.spot_check_state(ws, "study", study, reader=reader) == "complete"
    # an override whose values the draw holds already leaves it as it is (a small study is drawn whole)
    small_book = Book(ws, sha=OTHER, name="other.xlsx")
    small = clean_study(small_book, "EXA-403", points=3)
    negative = small_book.fact("concentration", -2.0, {"study": small["study"], "analyte": small["analyte"], "matrix": "plasma",
                                                      "subject": "001"}, unit="ng/mL", time=9.0, time_unit="h",
                               statistic="individual")
    covered(small_book)
    reader.refresh()
    whole = draw(ws, small["study"], reader=reader)
    tick_all(ws, whole)
    (check,) = [c for c in review.card(ws, "study", small["study"], reader=reader, **CARD, blinded=False).checks
                if c.code == "NEGATIVE_VALUE"]
    assert check.values == (negative,) and negative in whole.sampled
    review.override(ws, subject=small["study"], check_id=check.id, why="as the report writes it", by=BY)
    reader.refresh()
    assert review.spot_check_state(ws, "study", small["study"], reader=reader) == "complete"


@pytest.mark.req("T-47", "T-05", "F-404", "F-403", "T-06")
def test_record_confirmation_refuses_on_its_own_what_the_workspace_and_the_ledger_show(ws):
    """The route checks every refusal before it signs (`prepare_confirmation`). `record_confirmation` does not rely on
    it: a spot check that is not complete, a file not read, a dataset accepted on the legacy card and a blinded study
    are refused there too, and nothing is recorded."""
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    study = ids["study"]

    def refused(blinded: bool = False) -> list[str]:
        reader.refresh()
        record, sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
        with pytest.raises(review.ConfirmationRefused) as found:
            review.record_confirmation(ws, subject_type="study", subject=study, record=record, record_sha256=sha,
                                       signature_id="sig-0001", manifestation="Reviewed by A. Reviewer", by=BY,
                                       printed_name="A. Reviewer", blinded=blinded)
        assert found.value.code == "CONFLICT"
        assert IntakeStore(ws).review.entries("confirmation") == [] and events(ws, "intake.confirm") == []
        return [b.code for b in found.value.blockers]

    settle(ws, "study", study, reader)                                # everything a card shows is settled, and then:
    assert review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False) == ()
    fact = reader.enter(supersedes=ids["c0"], value=9.5, why="the report says 9.5", by=BY)
    reader.refresh()
    first = draw(ws, study, reader=reader)
    assert refused() == ["SPOT_CHECK"]                                # drawn, not ticked
    tick_all(ws, first, wrong=(fact.id,))
    assert refused() == ["SPOT_CHECK"]                                # a failed tick
    reader.enter(supersedes=fact.id, value=9.6, why="read again", by=BY)
    reader.refresh()
    assert review.spot_check_state(ws, "study", study, reader=reader) == "stale" and refused() == ["SPOT_CHECK"]
    tick_all(ws, draw(ws, study, reader=reader))
    assert review.spot_check_state(ws, "study", study, reader=reader) == "complete"
    assert refused(blinded=True) == ["BLINDED"]                       # a blinded study (`is_blinded` gives it)
    other = hashlib.sha256(b"Exampleamide: the report of the same delivery, never read").hexdigest()
    arrive(ws, other, "study-report.pdf")
    assert refused() == ["SILENT_LOSS"]                               # a file of the delivery was not read
    covered(Book(ws, sha=other, name="study-report.pdf"))
    legacy = _legacy_dataset(ws, sha=SHA, study_id="EXA-401", locator="Data!A1:B5", accept=True)
    assert refused() == ["LOADED_ON_CLIENT_REVIEW"]                   # the same source accepted on the legacy card
    decide_dataset(ws, legacy.id, state=EvidenceState.REJECTED, reason="confirmed on Delivery instead", by=BY)
    confirmation = _confirm(ws, study, reader)                        # nothing refuses: recorded
    assert confirmation.record["spot_check"] and len(events(ws, "intake.confirm")) == 1


BLINDED = pytest.mark.req("T-47", "T-05", "F-404", "F-402")


@BLINDED
def test_a_blinded_source_view_shows_no_mark_of_a_value_and_no_digit_of_its_title(ws, truth):
    """D-15 withholds values, LLOQs and the count of values below the LLOQ. The grid beside a blinded study's value
    blanks every cell a value of the file is anchored at ("BLQ" and missing-sample marks, which have no digit, with
    them) as well as every cell with a number, and its title shows no digit; the labels that are no value stay."""
    files = synthetic.delivery()
    for file in files:
        cover(ws, file)
    reader = Ledger(ws)
    hidden = {e.id for e in reader.entities("study")}
    marks = {"BLQ", "NS", "<0.5", ">1000"}
    seen = set()
    for value in reader.values(field="concentration"):
        view, file, _id = review.source_view(ws, reader=reader, hidden=hidden, value=value.id)
        if (file.sha256, view.region_id) in seen:
            continue
        seen.add((file.sha256, view.region_id))
        shown, _file, _id = review.source_view(ws, reader=reader, hidden=set(), value=value.id)
        anchored = {review._locator(v.anchor) for v in reader.values(file_sha256=file.sha256, active=False) if v.anchor}
        assert any(c.text in marks for c in shown.cells) or file.name != files[0].name       # the open view shows them
        assert not any(c.text.strip().upper() in marks for c in view.cells), (file.name, view.title)
        assert all(c.text == "" for c in view.cells if c.numeric or c.locator in anchored)
        assert not any(ch.isdigit() for ch in view.title) and len(view.title) == len(shown.title)
        kept = [c for c in view.cells if not c.numeric and c.locator not in anchored]
        assert [c.text for c in kept] == [c.text for c in shown.cells if not c.numeric and c.locator not in anchored]
        assert any(c.text for c in kept)                                 # headers and labels that are no value stay
        assert len(view.cells) == len(shown.cells) and [c.role for c in view.cells] == [c.role for c in shown.cells]
    assert len(seen) >= 6


@pytest.mark.req("T-47", "T-05", "F-404", "F-403", "T-06")
def test_a_subject_with_no_active_value_cannot_be_confirmed(ws):
    """There is nothing to sign for a subject with no active value: the empty compound, or a study whose values were
    all excluded. `prepare_confirmation` and `record_confirmation` both refuse, and nothing is recorded."""
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    for value in reader.values(study=ids["study"]):
        reader.exclude(value.id, why="not this project's", by=BY)
    reader.refresh()
    assert reader.values(study=ids["study"]) == [] and reader.values(compound=True) == []
    for subject_type, subject in (("compound", "compound"), ("study", ids["study"])):
        found = draw(ws, subject, subject_type, reader)
        assert (found.always, found.sampled) == ((), ())
        with pytest.raises(review.ReviewError, match="no active value") as refused:
            review.prepare_confirmation(ws, None, subject_type, subject, reader=reader, **CARD, blinded=False)  # type: ignore[arg-type]
        assert refused.value.code == "CONFLICT" and not isinstance(refused.value, review.ConfirmationRefused)
        record, sha = review.bound_record(ws, subject_type, subject, reader=reader, **CARD)  # type: ignore[arg-type]
        with pytest.raises(review.ReviewError, match="no active value") as refused:
            review.record_confirmation(ws, subject_type=subject_type, subject=subject, record=record, record_sha256=sha,  # type: ignore[arg-type]
                                       signature_id="sig-0001", manifestation="Reviewed by A. Reviewer", by=BY,
                                       printed_name="A. Reviewer", blinded=False)
        assert refused.value.code == "CONFLICT"
    assert IntakeStore(ws).review.entries("confirmation") == [] and events(ws, "intake.confirm") == []


@pytest.mark.req("T-47", "T-05", "F-404", "F-403", "T-06")
def test_a_confirmation_is_refused_when_an_intake_log_does_not_verify(ws):
    """A signature binds the lines of the intake logs by their hashes. A log whose chain does not verify (a line was
    edited: here a tick's note written over) refuses `prepare_confirmation` and `record_confirmation`, naming the
    log; nothing is signed over a broken chain."""
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    study = ids["study"]
    settle(ws, "study", study, reader)
    record, sha, _plan = review.prepare_confirmation(ws, None, "study", study, reader=reader, **CARD, blinded=False)
    store = IntakeStore(ws)
    whole = store.review.path.read_text(encoding="utf-8")
    lines = whole.splitlines()
    edited = []
    for line in lines:
        row = json.loads(line)
        if row["kind"] == "spot_check":
            row["body"]["ticks"][0]["note"] = "written over"
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        edited.append(line)
    store.review.path.write_text("\n".join(edited) + "\n", encoding="utf-8")
    assert [p.problem for p in store.review.verify()] == ["hash"]
    reader = Ledger(ws)
    with pytest.raises(review.ReviewError, match="the intake log review does not verify") as refused:
        review.prepare_confirmation(ws, None, "study", study, reader=reader, **CARD, blinded=False)
    assert refused.value.code == "CONFLICT"
    with pytest.raises(review.ReviewError, match="the intake log review does not verify"):
        review.record_confirmation(ws, subject_type="study", subject=study, record=record, record_sha256=sha,
                                   signature_id="sig-0001", manifestation="Reviewed by A. Reviewer", by=BY,
                                   printed_name="A. Reviewer", blinded=False)
    assert store.review.entries("confirmation") == [] and events(ws, "intake.confirm") == []
    # the log as it was: the same record is recorded
    store.review.path.write_text(whole, encoding="utf-8")
    assert store.review.verify() == []
    confirmation = review.record_confirmation(ws, subject_type="study", subject=study, record=record, record_sha256=sha,
                                              signature_id="sig-0001", manifestation="Reviewed by A. Reviewer", by=BY,
                                              printed_name="A. Reviewer", blinded=False)
    assert confirmation.record_sha256 == sha


def test_a_failed_tick_is_never_cleared_by_drawing_again(ws):
    """A value a reviewer ticked as not matching its source stays failed in every later draw (`always:failed`, no new
    tick accepted for it) until the value itself is corrected, superseded or excluded."""
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    study = ids["study"]
    first = draw(ws, study, reader=reader)
    failing = tick_all(ws, first, wrong=(ids["c0"],))
    assert review.spot_check_state(ws, "study", study, reader=reader) == "failed"
    # drawn again with the ledger as it was: the failed value is in the draw as failed, the others are carried
    second = draw(ws, study, reader=reader)
    assert second.id != first.id and second.strata[ids["c0"]] == "always:failed" and ids["c0"] in second.always
    assert ids["c0"] not in second.carried and set(second.carried) == {*second.always, *second.sampled} - {ids["c0"]}
    assert set(second.carried.values()) == {failing.id}
    assert review.spot_check_state(ws, "study", study, reader=reader) == "failed"
    with pytest.raises(review.ReviewError) as refused:            # it cannot be ticked again, ok or not
        review.record_spot_check(ws, second.id, [SpotTick(value_id=ids["c0"], ok=True)], by=BY)
    assert refused.value.code == "INVALID"
    tick_all(ws, second)                                          # nothing is left to tick: the state stays failed
    assert review.spot_check_state(ws, "study", study, reader=reader) == "failed"
    (blocker,) = review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False)
    assert blocker.code == "SPOT_CHECK" and "does not match its source" in blocker.detail
    # another change of the ledger does not clear it either (another seed, another sample)
    reader.enter(supersedes=ids["c1"], value=11.5, why="the report says 11.5", by=BY)
    third = draw(ws, study, reader=reader)
    assert third.strata[ids["c0"]] == "always:failed"
    tick_all(ws, third)
    assert review.spot_check_state(ws, "study", study, reader=reader) == "failed"
    # the value entered again with a reason (an audited correction, also for a tick made by mistake) is a new value
    fact = reader.enter(supersedes=ids["c0"], value=10.0, why="read again against the report: 10.0 is right", by=BY)
    last = draw(ws, study, reader=reader)
    assert ids["c0"] not in last.strata and fact.id in last.strata and "always:failed" not in last.strata.values()
    tick_all(ws, last)
    assert review.spot_check_state(ws, "study", study, reader=reader) == "complete"
    assert review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False) == ()


# --- a study or a product a person names when assigning ------------------------------------------------------------------


def _untold_profile(book: Book, *, points: int = 4) -> dict[str, str]:
    """A table that names no study (its title is not read as a study id): its analyte, its LLOQ, its concentrations,
    and the dose its caption states. Every value is "study not stated"."""
    analyte = book.entity("analyte", synthetic.DRUG)
    profile = {"analyte": analyte, "matrix": "plasma"}
    ids = {"analyte": analyte, "dose": book.fact("dose", 25.0, {}, unit="mg"),
           "lloq": book.fact("lloq", 0.5, profile, unit="ng/mL")}
    for i in range(points):
        ids[f"c{i}"] = book.fact("concentration", 10.0 + i, {**profile, "subject": "001"}, unit="ng/mL", time=float(i + 1),
                                 time_unit="h", statistic="individual")
    return ids


def _entity_lines(ws: Workspace) -> list[Any]:
    return IntakeStore(ws).entities.entries("entity")


def test_a_person_names_a_new_study_when_assigning_and_its_values_are_the_studys_own(ws):
    book = Book(ws)
    ids = _untold_profile(book)
    file_study = book.entity("study", "EXA-401")                           # a study another table of the file names
    covered(book, values_unassigned=6)
    targets = [ids["dose"], ids["lloq"], *(ids[f"c{i}"] for i in range(4))]
    assert [v.id for v in review.unassigned(ws, reader=Ledger(ws))] == targets
    lines, entities = len(IntakeStore(ws).review.entries()), len(_entity_lines(ws))

    # refused, and nothing is written: both an id and a new name; a name with no key; one too long or on two lines; a
    # name a study already has, however it is spelt (never a duplicate: the answer names the one that exists)
    def named(label: Any, **more: Any) -> Any:
        return review.assign(ws, targets=targets, new_study=label, why="the title says ABC-1", by=BY, **more)

    for refusal, code in ((lambda: named("ABC-1", study=file_study), "INVALID"), (lambda: named("  "), "INVALID"),
                          (lambda: named("-- / --"), "INVALID"), (lambda: named("A" * 81), "INVALID"),
                          (lambda: named("ABC-1\nDROP"), "INVALID"), (lambda: named(7), "INVALID"),
                          (lambda: named("EXA-401"), "CONFLICT"), (lambda: named("exa 401"), "CONFLICT"),
                          (lambda: named("ABC-1", arm="arm-999"), "UNKNOWN"),
                          (lambda: review.assign(ws, targets=targets, new_study="ABC-1", why=" ", by=BY), "INVALID"),
                          (lambda: review.assign(ws, targets=["f-999999"], new_study="ABC-1", why="x", by=BY), "UNKNOWN")):
        with pytest.raises(review.ReviewError) as refused:
            refusal()
        assert refused.value.code == code, str(refused.value)
    with pytest.raises(review.ReviewError, match=rf"a study named 'EXA-401' exists already \({file_study}\)"):
        named("Exa401")
    assert len(IntakeStore(ws).review.entries()) == lines and len(_entity_lines(ws)) == entities
    assert events(ws, "intake.entity") == [] and events(ws, "intake.assign") == []

    # named: the ledger's write side creates the study (a person's statement: no source), and the values are assigned
    made = named(" ABC-1 ")
    reader = Ledger(ws)
    (study,) = [e for e in reader.entities("study") if e.label == "ABC-1"]
    assert (made.study, made.arm, made.product, made.targets) == (study.id, None, None, tuple(targets))
    assert (study.type, study.source, study.by, study.parent, study.key) == ("study", None, BY, None, name_key("ABC-1"))
    assert study.id.startswith("st-") and study.id == f"st-{_entity_lines(ws)[-1].seq}"
    (created,) = events(ws, "intake.entity")
    assert created.after == {"entity": study.id, "type": "study", "label": "ABC-1", "row_hash": _entity_lines(ws)[-1].hash}
    assert (created.actor, created.reason, created.resource_id) == (BY, "the title says ABC-1", f"p1/{study.id}")
    (assigned,) = events(ws, "intake.assign")
    assert assigned.after == {"id": made.id, "row_hash": line_hash(ws, made.id)}
    assert IntakeStore(ws).entities.verify() == []
    # its values are the study's own: a study a person named has no home file, so nothing is a cross-file value and
    # no link waits for a confirmation. The assignment is the person's decision
    values = reader.values(study=study.id)
    assert [v.id for v in values] == targets and all(v.cross_file is None and v.status == "proposed" for v in values)
    assert reader.pending_links(study=study.id) == [] and review.unassigned(ws, reader=reader) == []
    assert _stored(ws, book.sha).summary.values_unassigned == 0                 # the stored coverage follows
    # it is a subject like any other: its row, its card and checks, its spot check
    row = next(r for r in review.subjects(ws, reader=reader) if r["subject"] == study.id)
    assert (row["label"], row["values"], row["files"], row["confirm_on"]) == ("ABC-1", 6, [book.sha], "delivery")
    card = review.card(ws, "study", study.id, reader=reader, **CARD, blinded=False)
    assert card.label == "ABC-1" and card.values == 6 and card.links == () and card.checks
    assert {b.code for b in card.blockers} <= {"SCHEMA_GAP", "CHECK_FAILED"}     # what any study with these facts has
    drawn = draw(ws, study.id, reader=reader)
    assert set(drawn.always) | set(drawn.sampled) == set(targets)
    # the same name again, by anyone: refused, naming the study to assign to
    for who in (BY, "u-other"):
        with pytest.raises(review.ReviewError, match=rf"a study named 'ABC-1' exists already \({study.id}\)") as again:
            review.assign(ws, targets=[ids["c0"]], new_study="abc 1", why="x", by=who)
        assert again.value.code == "CONFLICT"
    assert len(_entity_lines(ws)) == entities + 1 and len(events(ws, "intake.entity")) == 1


def test_naming_an_entity_is_idempotent_for_the_same_person_under_two_threads_and_never_a_duplicate(ws):
    book = Book(ws)
    file_study = book.entity("study", "EXA-401")
    made: list[Any] = []
    threads = [threading.Thread(target=lambda: made.append(Ledger(ws).name_entity("study", "ABC-1", by=BY, why="the title")))
               for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(made) == 8 and len({e.id for e in made}) == 1                # one entity, whoever wrote it first
    assert [e.body["label"] for e in _entity_lines(ws)] == ["EXA-401", "ABC-1"]
    (event,) = events(ws, "intake.entity")                                   # one line, one event with its hash
    assert event.after["row_hash"] == _entity_lines(ws)[-1].hash and event.after["entity"] == made[0].id
    ledger = Ledger(ws)
    assert ledger.name_entity("study", "abc-1", by=BY, why="again").id == made[0].id     # the same key: the same study
    assert len(_entity_lines(ws)) == 2 and len(events(ws, "intake.entity")) == 1
    # another person, a file's study, a ledger alias: never a duplicate, and the message names the one that exists
    with pytest.raises(ValueError, match=rf"a study named 'ABC-1' exists already \({made[0].id}\)"):
        ledger.name_entity("study", "ABC 1", by="u-other", why="x")
    with pytest.raises(ValueError, match=rf"a study named 'EXA-401' exists already \({file_study}\)"):
        ledger.name_entity("study", "exa401", by=BY, why="x")
    IntakeStore(ws).entities.append("alias", {"type": "study", "key": name_key("Protocol 77"), "parent": None,
                                               "entity": file_study, "source": "person", "by": BY, "at": AT})
    with pytest.raises(ValueError, match="'EXA-401' exists already"):
        ledger.name_entity("study", "Protocol 77", by=BY, why="x")
    # the same label is free for another type; only a study and a product are named; a name needs a key and a reason
    product = ledger.name_entity("product", "ABC-1", by=BY, why="the client's name for the capsule")
    assert product.id.startswith("pr-") and (product.type, product.source) == ("product", None)
    for refusal in (lambda: ledger.name_entity("arm", "Cohort 1", by=BY, why="x"),
                    lambda: ledger.name_entity("analyte", "M1", by=BY, why="x"),
                    lambda: ledger.name_entity("study", " ", by=BY, why="x"),
                    lambda: ledger.name_entity("study", "!!", by=BY, why="x"),
                    lambda: ledger.name_entity("study", "B" * 81, by=BY, why="x"),
                    lambda: ledger.name_entity("study", "ABC-2", by=BY, why=" ")):
        with pytest.raises(ValueError):
            refusal()
    assert len(_entity_lines(ws)) == 3 and len(events(ws, "intake.entity")) == 2
    # a study merged into another is that study: its old name names the one it became
    merged = ledger.name_entity("study", "ABC-9", by=BY, why="x")
    from modeler_project.ledger_entities import merge

    merge(ledger, type="study", from_id=merged.id, into_id=file_study, link_fact=None, why="the same protocol", by=BY)
    with pytest.raises(ValueError, match=rf"exists already \({file_study}\)"):
        Ledger(ws).name_entity("study", "ABC-9", by=BY, why="x")


def test_a_product_is_named_for_a_dissolution_table_that_states_only_its_batch(ws):
    book = Book(ws)
    batch = book.entity("batch", "L9001")                                    # a batch no product owns: the table names only it
    other_product = book.entity("product", "Comparamide tablet")
    owned = book.entity("batch", "R7745", parent=other_product)
    points = [book.fact("percent_dissolved", value, {"batch": batch}, unit="%", time=time, time_unit="min",
                        conditions={"apparatus": "paddle", "rpm": "50", "medium": "pH 6.8 buffer"})
              for time, value in ((10.0, 41.0), (20.0, 73.0), (30.0, 92.0))]
    covered(book, values_unassigned=3)
    assert [v.id for v in review.unassigned(ws, reader=Ledger(ws))] == points       # a batch alone is no subject
    # refused: a batch of another product, a product that exists (by key), both an id and a new name
    for refusal, code in (
            (lambda: review.assign(ws, targets=points, new_product="Exampleamide capsule", batch=owned, why="x", by=BY), "INVALID"),
            (lambda: review.assign(ws, targets=points, new_product="comparamide TABLET", why="x", by=BY), "CONFLICT"),
            (lambda: review.assign(ws, targets=points, product=other_product, new_product="Exampleamide capsule", why="x", by=BY),
             "INVALID"),
            (lambda: review.assign(ws, targets=points, batch=batch, why="x", by=BY), "INVALID")):
        with pytest.raises(review.ReviewError) as refused:
            refusal()
        assert refused.value.code == code, str(refused.value)
    assert events(ws, "intake.entity") == [] and IntakeStore(ws).review.entries() == []
    # named, with the batch the table states: the values are the new product's, and keep their batch
    made = review.assign(ws, targets=points, new_product="Exampleamide capsule", batch=batch,
                         why="the client's e-mail names the product of batch L9001", by=BY)
    reader = Ledger(ws)
    (product,) = [e for e in reader.entities("product") if e.label == "Exampleamide capsule"]
    assert (made.product, made.batch, made.study) == (product.id, batch, None) and product.source is None
    values = reader.values(product=product.id)
    assert [v.id for v in values] == points and all(v.entity.batch == batch and v.entity.study is None for v in values)
    assert review.unassigned(ws, reader=reader) == [] and _stored(ws, book.sha).summary.values_unassigned == 0
    (created,) = events(ws, "intake.entity")
    assert (created.after["type"], created.after["label"], created.after["row_hash"]) == (
        "product", "Exampleamide capsule", _entity_lines(ws)[-1].hash)
    assert len(events(ws, "intake.assign")) == 1
    row = next(r for r in review.subjects(ws, reader=reader) if r["subject"] == product.id)
    assert (row["subject_type"], row["label"], row["values"]) == ("product", "Exampleamide capsule", 3)
    card = review.card(ws, "product", product.id, reader=reader, **CARD, blinded=False)
    assert card.values == 3 and card.label == "Exampleamide capsule"
    assert set(draw(ws, product.id, "product", reader).sampled) | set(draw(ws, product.id, "product", reader).always) == set(points)
    # a later assignment to that product may name the same batch again; one that leaves the batch out clears it, as an
    # Assignment does (§13)
    review.assign(ws, targets=points[:1], product=product.id, batch=batch, why="the same batch", by=BY)
    review.assign(ws, targets=points[1:2], product=product.id, why="its batch is not known after all", by=BY)
    reader.refresh()
    assert [v.entity.batch for v in reader.values(product=product.id)] == [batch, None, batch]


@BLIND
def test_a_study_a_person_named_is_blinded_like_any_other(ws):
    book = Book(ws)
    ids = _untold_profile(book)
    covered(book, values_unassigned=6)
    targets = [ids["dose"], ids["lloq"], *(ids[f"c{i}"] for i in range(4))]
    made = review.assign(ws, targets=targets, new_study="ABC-1", why="the title says ABC-1", by=BY)
    ledger = Ledger(ws)
    assert review.blinded_subjects(ws, ON, None) == set()                    # no external purpose yet: nothing is withheld
    ledger.enter(entity=EntityRef(study=made.study), field="intended_use", value="external_validation",
                 why="the plan judges the model on it", by=BY)
    hidden = review.blinded_subjects(ws, ON, None)
    assert hidden == {made.study} and review.is_blinded(ledger, "study", made.study, hidden)
    shown = review.shown(ledger.values(study=made.study), hidden)
    assert len(shown) == 7 and all(blinded and v.value is None and v.verbatim == "" and v.lloq is None for v, blinded in shown)
    with pytest.raises(review.ReviewError) as refused:
        review.draw_spot_check(ws, "study", made.study, reader=ledger, by=BY, blinded=True)
    assert refused.value.code == "BLINDED"
    assert "BLINDED" in [b.code for b in review.blockers(ws, "study", made.study, reader=ledger, **CARD, blinded=True)]
    # and naming a study tells nothing of a blinded one: with blinding off the same study is open
    assert review.blinded_subjects(ws, None, "low") == set()


def test_blockers_take_the_card_already_computed_and_refuse_another_subjects(ws):
    book = Book(ws)
    ids = clean_study(book)
    other_book = Book(ws, sha=OTHER, name="other.xlsx")
    other = clean_study(other_book, "EXA-402")
    covered(book)
    covered(other_book)
    reader = Ledger(ws)
    card = review.card(ws, "study", ids["study"], reader=reader, **CARD, blinded=False)
    alone = review.blockers(ws, "study", ids["study"], reader=reader, **CARD, blinded=False)
    assert review.blockers(ws, "study", ids["study"], reader=reader, **CARD, blinded=False, card=card) == alone
    assert [b.code for b in alone] == ["SPOT_CHECK"]
    # a blinded subject's card (its checks name no value) serves as well: the blockers are the same, with BLINDED
    hidden_card = review.card(ws, "study", ids["study"], reader=reader, **CARD, blinded=True)
    assert [b.code for b in review.blockers(ws, "study", ids["study"], reader=reader, **CARD, blinded=True,
                                            card=hidden_card)] == ["SPOT_CHECK", "BLINDED"]
    with pytest.raises(review.ReviewError) as refused:                       # never another subject's card
        review.blockers(ws, "study", other["study"], reader=reader, **CARD, blinded=False, card=card)
    assert refused.value.code == "INVALID"
    # the bound record takes it too, and is the same record: a confirmation computes the card once
    assert review.bound_record(ws, "study", ids["study"], reader=reader, **CARD, card=card) == \
        review.bound_record(ws, "study", ids["study"], reader=reader, **CARD)
    with pytest.raises(review.ReviewError):
        review.bound_record(ws, "study", other["study"], reader=reader, **CARD, card=card)
    calls: list[str] = []
    real = review._card
    review._card = lambda *a, **k: calls.append(a[2]) or real(*a, **k)       # type: ignore[assignment]
    try:
        tick_all(ws, draw(ws, ids["study"], reader=reader))
        review.prepare_confirmation(ws, None, "study", ids["study"], reader=reader, **CARD, blinded=False)
    finally:
        review._card = real
    assert calls == [ids["study"]]
