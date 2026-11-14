"""T-47: the intake pipeline's run queue and stage runner (contracts §6.5, §8.9, §13; build W; plan G2, G7).

The synthetic delivery (`modeler_intake.synthetic.delivery()`: the messy workbook, the ruled PDF report, the Word
report, the delimited listing) is read end to end through every stage:
- warm cache (G7's case): every truth table's spec preloaded through `MappingCache.propose` and approved; with no model
  each file's ledger values equal its truth value by value (`value_score.score`: 100 % of the tables' truth, and the
  only rows missing from the whole truth are the prose facts, which need a model), each resolving through its anchor,
  silent loss 0. With the prose read too (a port that states the truth's sentences to code's strict check), the whole
  truth is found;
- empty cache, no model: the rules map what they map (counted), the rest is `unread` with its reason and counted in
  silent loss, never dropped.
The queue (enqueue once, take, recover, sweep), the guards (a stage that raises fails its run there, the next file
still runs; a model that fails leaves its tables unread and the run goes on), the mapping order of contract §13 (an
approved version of the cache, the table's own rule spec, a proposed spec no rule made, the table mapper, else unread
with the reason), the cache's reach (a second sheet of the same layout with its own title), a repeat and a re-parse are
tested on the same files. The LLM stages are reached through fake `LlmPorts` here; the API test runs them with the
scripted model.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import threading

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import parse_anchor, parse_locator
from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.mapping.prose_check import ProseFactError
from modeler_intake.mapping.rules import map_by_rule
from modeler_intake.mapping_spec import MappingSpec
from modeler_intake.source import parse as parse_module
from modeler_intake.source import parse_document, region_grid, resolve
from modeler_project import ArtifactKind, FileProjectStore, Workspace, intake_files, intake_pipeline
from modeler_project.brief import empty_brief
from modeler_project.client_data import ingest
from modeler_project.documents import DocumentLibrary
from modeler_project.intake_pipeline import LlmPorts, MapAnswer, MapRequest
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import REGION_GONE, Ledger
from modeler_project.ledger_models import ModelUse
from modeler_project.mapping_cache import MappingCache
from modeler_project.value_key import key_from_truth, load_key
from modeler_project.value_score import coverage_totals, from_ledger, score, timings

pytestmark = pytest.mark.req("T-47")

BRIEF = empty_brief(synthetic.DRUG, by="u1")
STAGES = list(intake_pipeline.STAGES)
FASTING, FED, METABOLITE = "s:'Fasting'!A2:G14", "s:'Fed'!A2:G14", "s:'Fasting'!A21:D27"
VESSELS, DISSOLUTION_MEAN = "s:'Dissolution'!A3:G9", "s:'Dissolution'!I3:L9"
SUMMARY, URINE, PRODUCT = "s:'Summary'!A2:C5", "s:'Urine'!A2:D6", "s:'Product'!A1:H3"


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


@pytest.fixture(scope="module")
def delivery() -> tuple[synthetic.SyntheticFile, ...]:
    return synthetic.delivery()


def _sha(file) -> str:
    return hashlib.sha256(file.data).hexdigest()


def _arrive(ws: Workspace, files, *, by: str = "u1", queue: bool = True):
    delivery = intake_files.open_delivery(ws, by=by)
    records = [intake_files.record_arrival(ws, f.data, f.name, delivery=delivery, by=by) for f in files]
    if queue:
        intake_pipeline.enqueue(ws, records, by=by)
    return records


def _drain(ws: Workspace, **kw):
    done = []
    while (run := intake_pipeline.take(ws)) is not None:
        done.append(intake_pipeline.run_file(ws, run, brief=BRIEF, **kw))
    return done


def _again(ws: Workspace, run, **kw):
    """The same run once more (a retry of a run left running): every stage again, on what the stores hold now."""
    return intake_pipeline.run_file(ws, run.model_copy(update={"state": "running"}), brief=BRIEF, **kw)


def _regions(file) -> tuple[object, dict[str, object]]:
    """The file as the pipeline parses it, and its regions by their `where`."""
    doc = parse_document(file.data, file.name)
    return doc, {r.where: r for r in doc.regions}


def _propose(ws: Workspace, file, where: str, spec: MappingSpec, *, origin: str = "person", approve: bool = True):
    """A spec stored under the layout fingerprint of this region as the pipeline parses it, approved or left proposed."""
    doc, regions = _regions(file)
    cache = MappingCache(ws)
    region = regions[where]
    entry = cache.propose(layout_fingerprint(region_grid(doc, region.id)), spec, origin=origin,  # type: ignore[arg-type]
                          origin_detail="a test", first_seen=(doc.file_sha256, region.id), by="u1")
    if approve:
        cache.approve(entry.mapping_id, entry.version, by="u1", note="the truth")
    return entry


def _preload(ws: Workspace, files, tables: tuple[str, ...] | None = None) -> None:
    """Each truth table's spec proposed for its region and approved (a person's sign-off)."""
    for file in files:
        for table in file.tables:
            if tables is None or table.id in tables:
                _propose(ws, file, table.where, table.spec)


def _spec(file, table_id: str) -> MappingSpec:
    return next(t.spec for t in file.tables if t.id == table_id)


def _outcomes(ws: Workspace, file) -> dict[str, object]:
    """The file's region outcomes from its stored coverage, by the region's `where`."""
    cover = IntakeStore(ws).coverage(_sha(file))
    assert cover is not None
    return {r.region.where: r.outcome for r in cover.regions}


def _used(ws: Workspace, file, where: str) -> tuple[str, str | None, int | None]:
    """(state, origin, mapping version) of one region's outcome."""
    outcome = _outcomes(ws, file)[where]
    return outcome.state, outcome.origin, outcome.mapping.version if outcome.mapping else None


def _tables_only(files):
    return [dataclasses.replace(f, values=tuple(v for v in f.values if v.table)) for f in files]


def _score(ws: Workspace, files) -> dict:
    return score(load_key(key_from_truth(files), "truth.xlsx"), from_ledger(ws))


_WRONG = ("found_rounded", "wrong_value", "wrong_unit", "unexpected", "unusable", "attributes_differ", "labels_differ")


def _clean(totals: dict[str, int], n: int) -> bool:
    """Every one of the key's n rows found exactly, nothing missing, nothing else read."""
    return totals["found"] == totals["scored"] == totals["key_rows"] == n and not totals["missing"] and not any(
        totals[k] for k in _WRONG)


def _place(locator: str) -> dict:
    """A locator's identity (a PDF box is carried for the viewer, never compared)."""
    found = parse_locator(locator).model_dump()
    found.pop("box", None)
    return found


def _truth_prose(file) -> LlmPorts:
    """A prose port that states the truth's prose facts as the file writes them: each sentence of the file's prose is
    offered to code's strict check as the quote, and only what the check accepts at the truth's own span is kept. Test
    scaffolding standing in for the model: the reading is code's."""
    sentences = [part if part.endswith(".") else f"{part}." for text in file.prose for part in text.split(". ")]

    def extract_prose(paragraphs, check):
        facts = []
        for truth in (v for v in file.values if not v.table):
            study = truth.study if dict(truth.locators).get("study") else None
            for paragraph, quote in itertools.product(paragraphs, sentences):
                try:
                    fact = check(truth.field, truth.value, quote, paragraph.index, study, None)
                except ProseFactError:
                    continue
                if _place(fact.locator) == _place(truth.locator):
                    facts.append(fact)
                    break
        return facts, ModelUse(provider="scripted", model="scripted", prompt_sha256="0" * 64, agent_run="ar_00000000000a")

    return LlmPorts(map_tables=lambda requests, check: [], extract_prose=extract_prose)


# --- end to end ----------------------------------------------------------------------------------------------------------


def test_warm_cache_every_value_equals_its_truth_through_its_anchor_with_no_silent_loss(ws, delivery):
    _preload(ws, delivery)
    mappings = IntakeStore(ws).mappings.head()
    _arrive(ws, delivery)
    runs = _drain(ws)
    assert [r.state for r in runs] == ["done"] * len(delivery), [r.error for r in runs]
    for run, file in zip(runs, delivery, strict=True):
        assert [s.stage for s in run.stages] == STAGES and all(s.ok and s.seconds >= 0 for s in run.stages)
        counters = run.counters
        assert (counters.mapped_by_cache, counters.mapped_by_rule, counters.mapped_by_llm, counters.unmapped) == (
            len(file.tables), 0, 0, 0)
        assert run.coverage is not None and (run.coverage.silent_loss, run.coverage.cells_silent) == (0, 0)
        assert run.agent_runs == () and counters.llm_runs == 0                 # no model, no agent run
        outcomes = _outcomes(ws, file)
        assert all(outcomes[t.where].origin == "cache" and outcomes[t.where].state == "mapped" for t in file.tables)
    assert runs[-1].ledger_head == IntakeStore(ws).facts.head().hash
    assert IntakeStore(ws).mappings.head() == mappings                          # an approved version: nothing proposed
    # value by value: the truth of every table is found exactly, and nothing else is read
    tables = _tables_only(delivery)
    scored = _score(ws, tables)
    assert _clean(scored["totals"], sum(len(f.values) for f in tables)), scored["totals"]
    assert scored["totals"]["places_unread"] == 0
    assert {r["found"]["method"] for r in scored["rows"]} == {"cell", "pdf_table", "docx_table"}
    # against the whole truth, the only rows missing are the prose facts: they need a model
    whole = _score(ws, delivery)
    prose = [v for f in delivery for v in f.values if not v.table]
    missing = [r for r in whole["rows"] if r["verdict"] == "missing"]
    assert len(prose) == 5 and sorted(r["field"] for r in missing) == sorted(v.field for v in prose)
    assert whole["totals"]["found"] == whole["totals"]["key_rows"] - 5 and not any(whole["totals"][k] for k in _WRONG)
    # each value resolves through its anchor to the text it was read from
    docs = {_sha(f): parse_document(f.data, f.name) for f in delivery}
    values = [v for v in Ledger(ws).values() if v.anchor]
    assert len(values) >= sum(len(f.values) for f in tables)
    for value in values:
        assert resolve(docs[parse_anchor(value.anchor).file_sha256], value.anchor).text == value.verbatim, value.id
    # the scorer reads the runs' lines: the time of every stage of the delivery (G7) and the coverage numbers (G2)
    (timed,) = timings(ws)["deliveries"].values()
    assert (timed["files"], timed["runs"], timed["done"], timed["failed"]) == (4, 4, 4, 0)
    assert list(timed["stages"]) == STAGES and all(s["runs"] == 4 and s["failed"] == 0 for s in timed["stages"].values())
    assert timed["arrival_to_end_seconds"] is not None
    totals = coverage_totals(ws)
    assert (totals["files"], totals["by_state"], totals["differs"]) == (4, {"read": 4}, [])
    assert totals["at_run_end"]["silent_loss"] == totals["current"]["silent_loss"] == 0


def test_warm_cache_with_the_prose_read_the_whole_truth_is_found(ws, delivery):
    _preload(ws, delivery)
    records = _arrive(ws, delivery)
    for file in delivery:                     # each file with the port that states its own prose
        run = intake_pipeline.take(ws)
        assert run is not None and run.sha256 == _sha(file)
        done = intake_pipeline.run_file(ws, run, brief=BRIEF, llm=_truth_prose(file))
        assert done.state == "done" and done.coverage is not None and done.coverage.silent_loss == 0
        assert (done.counters.llm_runs, done.agent_runs) == ((1, ("ar_00000000000a",)) if file.prose else (0, ()))
    assert len(records) == 4 and not intake_pipeline.pending(ws)
    scored = _score(ws, delivery)
    assert _clean(scored["totals"], sum(len(f.values) for f in delivery)), scored["totals"]
    assert {r["found"]["method"] for r in scored["rows"]} == {"cell", "pdf_table", "docx_table", "prose"}
    # a prose fact's anchor is the span of the value itself, its verbatim the quote that holds it
    docs = {_sha(f): parse_document(f.data, f.name) for f in delivery}
    prose = [v for v in Ledger(ws).values() if v.method == "prose" and not v.field.startswith("link.")]
    assert len(prose) == 5
    for value in prose:
        text = resolve(docs[parse_anchor(value.anchor).file_sha256], value.anchor).text
        assert text in value.verbatim and len(text) < len(value.verbatim)
    for file in (delivery[1], delivery[2]):
        region = next(o for o in _outcomes(ws, file).values() if o.reason.startswith("read by the prose extractor"))
        assert (region.state, region.origin) == ("mapped", "llm")


def test_empty_cache_the_rules_map_what_they_map_and_the_rest_is_unread_and_counted(ws, delivery):
    _arrive(ws, delivery)
    runs = {r.sha256: r for r in _drain(ws)}
    assert all(r.state == "done" for r in runs.values())
    counted = {f.name: runs[_sha(f)].counters for f in delivery}
    by_rule = {name: (c.mapped_by_cache, c.mapped_by_rule, c.unmapped, c.values) for name, c in counted.items()}
    assert by_rule == {"messy-delivery.xlsx": (0, 4, 4, 114), "study-report.pdf": (0, 3, 0, 30),
                       "design-report.docx": (0, 1, 0, 6), "concentrations.csv": (0, 1, 0, 8)}, by_rule
    messy = delivery[0]
    outcomes = _outcomes(ws, messy)
    assert {w for w, o in outcomes.items() if o.origin == "rule"} == {FASTING, METABOLITE, FED, VESSELS}
    unread = {where for where, o in outcomes.items() if o.state == "unread"}
    assert unread == {DISSOLUTION_MEAN, SUMMARY, URINE, PRODUCT}
    assert all(outcomes[w].reason == intake_pipeline.NO_MODEL and outcomes[w].mapping is None for w in unread)
    # never dropped: every cell with a number of an unread table is silent loss, with what the rules left unaccounted
    run = runs[_sha(messy)]
    assert run.coverage is not None
    unread_cells = sum(outcomes[w].numeric_cells for w in unread)
    left_by_rules = sum(o.unaccounted_count for o in outcomes.values() if o.state == "mapped")
    assert (unread_cells, left_by_rules) == (50, 53)
    assert run.coverage.cells_silent == left_by_rules and run.coverage.silent_loss == left_by_rules + unread_cells == 103
    assert (run.coverage.regions_mapped, run.coverage.regions_unread) == (4, 4)
    # a batch with no product is no subject: the dissolution values the rules read wait as "study not stated"
    assert run.coverage.values_unassigned == 37 and run.coverage.outside_numeric == 1
    # two sheets of one layout, two PDF tables of one layout: one rule spec and one version each, read by rule both times
    assert outcomes[FASTING].mapping == outcomes[FED].mapping
    pdf = _outcomes(ws, delivery[1])
    assert [pdf[w].origin for w in ("p:2/t:1", "p:4/t:1", "p:5/t:1")] == ["rule", "rule", "rule"]
    assert pdf["p:4/t:1"].mapping == pdf["p:5/t:1"].mapping
    assert len(MappingCache(ws).entries()) == 7 and {e.origin for e in MappingCache(ws).entries()} == {"rule"}
    # the files the rules read whole have no silent loss; the prose waits for a model: listed unread, not counted
    assert [runs[_sha(f)].coverage.silent_loss for f in delivery[1:]] == [0, 0, 0]
    prose = [o for o in pdf.values() if o.reason == intake_pipeline.PROSE_NO_MODEL]
    assert len(prose) == 1 and prose[0].state == "unread"
    # what the rules found is right as far as it goes: no wrong value, the rest of the truth missing (counted)
    totals = _score(ws, _tables_only(delivery))["totals"]
    assert (totals["found"], totals["wrong_value"], totals["wrong_unit"]) == (151, 0, 0) and totals["missing"] == 81


def test_a_filled_client_template_is_read_whole_by_its_rule_and_its_own_readme_text_is_no_outside_number(ws):
    template = synthetic.template_workbook()
    _arrive(ws, [template])
    (run,) = _drain(ws)
    counters = run.counters
    assert run.state == "done" and (counters.mapped_by_rule, counters.mapped_by_cache, counters.unmapped) == (9, 0, 0)
    outcomes = _outcomes(ws, template)
    readme = next(o for where, o in outcomes.items() if where.startswith("s:'README'!"))
    assert (readme.state, readme.origin) == ("excluded", "rule") and readme.reason.startswith("not data: ")
    assert all(o.state == "mapped" and o.origin == "rule" for o in outcomes.values() if o is not readme)
    assert {e.origin_detail for e in MappingCache(ws).entries()} == {"template/rules-1"}
    # every cell with a number is read or set aside by a stated rule; the template's own instructions are furniture
    cover = IntakeStore(ws).coverage(_sha(template))
    assert (run.coverage.silent_loss, run.coverage.outside_numeric, run.coverage.values_unassigned) == (0, 0, 0)
    assert cover.outside and all(item.furniture for item in cover.outside) and any(item.numeric for item in cover.outside)
    scored = _score(ws, [template])
    assert _clean(scored["totals"], len(template.values)), scored["totals"]


# --- the guards and the stage times ----------------------------------------------------------------------------------


def test_every_stage_has_a_time_and_a_parser_that_raises_fails_that_run_at_parse(ws, delivery, monkeypatch):
    listing, word = delivery[3], delivery[2]
    real = intake_pipeline.parse_document

    def parse(data, filename, **kw):
        if filename == listing.name:
            raise RuntimeError("the parser broke")
        return real(data, filename, **kw)

    monkeypatch.setattr(intake_pipeline, "parse_document", parse)
    _arrive(ws, [listing, word])
    tick = itertools.count(0.0, 0.25)
    failed, done = _drain(ws, clock=lambda: next(tick))
    assert failed.state == "failed" and failed.error == "parse: RuntimeError: the parser broke"
    assert [(s.stage, s.ok, s.seconds, s.detail) for s in failed.stages] == [
        ("parse", False, 0.25, "RuntimeError: the parser broke")]
    assert failed.coverage is None and failed.finished_at is not None
    # the next file still runs, and each of its stages has its time
    assert done.state == "done" and [(s.stage, s.seconds) for s in done.stages] == [(s, 0.25) for s in STAGES]
    events = [r.event for r in ws.store.audit("t1").records() if r.event.action == "intake.run"]
    assert [(e.resource_id, e.after["state"]) for e in events] == [("p1/run-1", "failed"), ("p1/run-2", "done")]
    # one event per run, each with the hash of the run's last line
    lines = {e.body["run_id"]: e.hash for e in IntakeStore(ws).runs.entries("run")}
    assert [e.after["row_hash"] for e in events] == [lines["run-1"], lines["run-2"]]
    assert IntakeStore(ws).runs.verify() == []


def test_a_stage_that_raises_later_fails_the_run_there_with_its_line_and_event(ws, delivery, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("the ledger refused")

    monkeypatch.setattr(Ledger, "record_extraction", broken)
    _arrive(ws, [delivery[3]])
    (run,) = _drain(ws)
    assert run.state == "failed" and run.error == "ledger: ValueError: the ledger refused"
    assert [s.stage for s in run.stages] == STAGES[:STAGES.index("ledger") + 1] and not run.stages[-1].ok
    assert run.coverage is None and run.counters.mapped_by_rule == 1          # what the earlier stages counted is kept
    assert intake_pipeline.runs(ws)[0] == run and not intake_pipeline.pending(ws)


def test_an_unsupported_or_unreadable_file_ends_done_with_its_state_and_reason(ws, delivery):
    files = [dataclasses.replace(delivery[3], name="trial.xpt"),
             dataclasses.replace(delivery[3], name="broken.pdf", data=b"%PDF-1.4 not really a PDF")]
    _arrive(ws, files)
    runs = _drain(ws)
    assert [r.state for r in runs] == ["done", "done"] and all([s.stage for s in r.stages] == STAGES for r in runs)
    unsupported, unreadable = (r.coverage for r in runs)
    assert unsupported is not None and (unsupported.state, unsupported.reason) == ("unsupported", "no parser for .xpt")
    assert unreadable is not None and unreadable.state == "unreadable" and unreadable.reason
    assert runs[0].parser == "none" and runs[0].counters.regions == 0 and runs[0].counters.values == 0
    assert IntakeStore(ws).coverage(runs[1].sha256) is not None


def test_a_second_run_of_a_file_and_the_same_bytes_in_a_later_delivery_add_nothing(ws, delivery):
    messy = delivery[0]
    _arrive(ws, [messy])
    (first,) = _drain(ws)
    store = IntakeStore(ws)
    heads = store.facts.head(), store.entities.head(), store.mappings.head()
    again = _again(ws, first)
    assert again.state == "done" and again.counters == first.counters and again.coverage == first.coverage
    assert (store.facts.head(), store.entities.head(), store.mappings.head()) == heads
    # the same bytes again, later: recorded as a repeat, and no run is queued
    later = intake_files.open_delivery(ws, by="u2")
    repeat = intake_files.record_arrival(ws, messy.data, messy.name, delivery=later, by="u2")
    assert repeat.repeat and intake_pipeline.enqueue(ws, [repeat], by="u2") == []
    assert not intake_pipeline.pending(ws) and len(intake_pipeline.runs(ws)) == 1
    assert (store.facts.head(), store.entities.head(), store.mappings.head()) == heads


def _reparsed(monkeypatch, version: str, change=None) -> None:
    """The parser as a later version of itself; `change`: what that version reads differently in a document."""
    real = parse_document
    monkeypatch.setattr(parse_module, "SOURCE_VERSION", version)
    monkeypatch.setattr(intake_pipeline, "parse_document",
                        lambda data, name, **kw: (change or (lambda doc: doc))(real(data, name, **kw)))


def test_a_bumped_parser_version_reparses_checks_the_anchors_and_reports_the_counts(ws, delivery, monkeypatch):
    messy = delivery[0]
    (record,) = _arrive(ws, [messy])
    (first,) = _drain(ws)
    store = IntakeStore(ws)
    anchored = [v for v in Ledger(ws).values(file_sha256=record.sha256) if v.anchor]
    assert len(anchored) > first.counters.values                # the table values, and the facts of their captions
    facts, mappings = store.facts.head(), store.mappings.head()

    # a new parser version that reads every cell as before: re-parsed, every anchor checked and found, nothing written
    _reparsed(monkeypatch, "1.1")
    assert [r.run_id for r in intake_pipeline.enqueue(ws, [record], by="code")] == ["run-4"]
    (second,) = _drain(ws)
    assert second.state == "done" and second.parser_version.startswith("1.1+") and first.parser_version.startswith("1.0+")
    assert (second.counters.anchors_checked, second.counters.anchors_unresolved) == (len(anchored), 0)
    assert second.coverage is not None and second.coverage.anchors_unresolved == 0
    assert store.coverage(record.sha256).anchor_problems == ()
    assert sorted(store.source_versions(record.sha256)) == sorted([(first.parser, first.parser_version),
                                                                    (second.parser, second.parser_version)])
    assert (store.facts.head(), store.mappings.head()) == (facts, mappings)     # every extract kept, with its old anchors
    assert f"{len(anchored)} anchors of an earlier version checked" in {s.stage: s.detail for s in second.stages}["parse"]
    assert second.counters.values == first.counters.values and second.coverage.silent_loss == first.coverage.silent_loss

    # a version that reads one cell differently: that value is listed with the text now found, and its table is read anew
    moved = next(v for v in anchored if "#" in v.id and v.verbatim == "12.1" and "'Fasting'" in v.anchor)
    cell = parse_anchor(moved.anchor).locator

    def differently(doc):
        sheets = tuple(s.model_copy(update={"cells": tuple(
            c.model_copy(update={"text": "12.7", "value": 12.7}) if s.name == cell.sheet and f"{_letters(c.column)}{c.row}"
            == cell.cell else c for c in s.cells)}) for s in doc.sheets)
        return doc.model_copy(update={"sheets": sheets})

    _reparsed(monkeypatch, "1.2", differently)
    intake_pipeline.enqueue(ws, [record], by="code")
    (third,) = _drain(ws)
    assert third.state == "done" and (third.counters.anchors_checked, third.counters.anchors_unresolved) == (len(anchored), 1)
    problems = store.coverage(record.sha256).anchor_problems
    assert [(p.id, p.problem, p.found) for p in problems] == [(moved.id, "text_differs", "12.7")]
    assert third.coverage is not None and third.coverage.anchors_unresolved == 1
    ledger = Ledger(ws)
    assert ledger.value(moved.id).status == "superseded"
    there = _place(moved.anchor.split("#", 1)[1])
    now = [v for v in ledger.values(file_sha256=record.sha256) if "#" in v.id and _place(v.anchor.split("#", 1)[1]) == there]
    assert [(v.value, v.verbatim) for v in now] == [(12.7, "12.7")] and "@workbook/1.2+" in now[0].anchor
    assert third.counters.values == first.counters.values                      # one table read anew, none lost


def _letters(column: int) -> str:
    letters = ""
    while column:
        column, r = divmod(column - 1, 26)
        letters = chr(65 + r) + letters
    return letters


def test_a_table_gone_after_a_reparse_is_retired_and_listed(ws, delivery, monkeypatch):
    messy = delivery[0]
    (record,) = _arrive(ws, [messy])
    (first,) = _drain(ws)
    fed = [v for v in Ledger(ws).values(file_sha256=record.sha256) if v.anchor and "'Fed'" in v.anchor]
    extracts = {v.id.split("#", 1)[0] for v in fed if "#" in v.id}
    assert len(extracts) == 1 and len(fed) > 30

    def without_fed(doc):
        return doc.model_copy(update={"sheets": tuple(s for s in doc.sheets if s.name != "Fed"),
                                      "regions": tuple(r for r in doc.regions if "'Fed'" not in r.where),
                                      "outside": tuple(o for o in doc.outside if "'Fed'" not in o.where)})

    _reparsed(monkeypatch, "1.1", without_fed)
    intake_pipeline.enqueue(ws, [record], by="code")
    (second,) = _drain(ws)
    assert second.state == "done" and second.counters.regions == first.counters.regions - 1
    problems = IntakeStore(ws).coverage(record.sha256).anchor_problems
    assert {p.id for p in problems} == {v.id for v in fed} and {p.problem for p in problems} == {"not_found"}
    assert second.counters.anchors_unresolved == second.coverage.anchors_unresolved == len(fed)
    ledger = Ledger(ws)
    gone = [ledger.value(v.id) for v in fed if "#" in v.id]
    assert {(v.status, v.status_reason) for v in gone} == {("excluded", REGION_GONE)}
    assert "1 extracts retired" in {s.stage: s.detail for s in second.stages}["ledger"]
    # the tables still there keep their extracts (found again at their place), under their old anchors
    kept = [v for v in ledger.values(file_sha256=record.sha256) if "#" in v.id]
    assert len(kept) == first.counters.values - len(gone) and all("@workbook/1.0+" in v.anchor for v in kept)


# --- mapping ---------------------------------------------------------------------------------------------------------


def test_the_mapping_order_is_an_approved_version_then_the_rule_then_a_proposed_spec_then_unread(ws, delivery):
    messy = delivery[0]
    _propose(ws, messy, SUMMARY, _spec(messy, "summary-parameters"))                       # approved: no rule maps it
    _propose(ws, messy, FED, _spec(messy, "fed-individual"))                               # approved: a rule maps it too
    waiting = _propose(ws, messy, URINE, _spec(messy, "urine-excretion"), origin="llm", approve=False)
    _arrive(ws, [messy])
    (run,) = _drain(ws)
    outcomes = _outcomes(ws, messy)
    # 1. a version a person approved governs, also where a rule would map the table (Fasting and Fed: one layout)
    assert (outcomes[SUMMARY].state, outcomes[SUMMARY].origin) == ("mapped", "cache")
    assert [outcomes[w].origin for w in (FASTING, FED)] == ["cache", "cache"]
    assert outcomes[FED].unaccounted_count == 0
    # 2. else the table's own rule spec, proposed and executed at once
    assert (outcomes[METABOLITE].state, outcomes[METABOLITE].origin) == ("mapped", "rule")
    cache = MappingCache(ws)
    rule = cache.get(outcomes[METABOLITE].mapping.mapping_id, outcomes[METABOLITE].mapping.version)
    assert rule.origin == "rule" and rule.origin_detail == "sheet_form/rules-1" and rule.by == "code"
    assert cache.status(rule.mapping_id, rule.version) == "proposed"
    # 3. else a spec no rule made that waits for approval (an earlier table mapper's)
    assert (outcomes[URINE].state, outcomes[URINE].origin) == ("mapped", "cache")
    assert outcomes[URINE].mapping.version == waiting.version and cache.status(waiting.mapping_id, waiting.version) == "proposed"
    # 5. else unread with the reason (4, the table mapper, needs a model)
    for where in (PRODUCT, DISSOLUTION_MEAN):
        assert (outcomes[where].state, outcomes[where].origin, outcomes[where].reason) == ("unread", None, intake_pipeline.NO_MODEL)
    counters = run.counters
    assert (counters.mapped_by_cache, counters.mapped_by_rule, counters.mapped_by_llm, counters.unmapped) == (4, 2, 0, 2)
    assert run.agent_runs == () and counters.llm_runs == 0                    # a cache or rule mapping makes no agent run
    # the rules are recomputed on every run, and an equal spec is its stored version: a re-run appends nothing
    head = IntakeStore(ws).mappings.head()
    assert _again(ws, run).counters == counters and IntakeStore(ws).mappings.head() == head


def test_among_approved_versions_the_one_that_reads_most_governs(ws, delivery):
    messy = delivery[0]
    doc, regions = _regions(messy)
    truth = _spec(messy, "fasting-individual")
    fewer = truth.model_copy(update={"constants": truth.constants[1:]})           # reads all the cells, one constant less
    rule = map_by_rule(region_grid(doc, regions[FASTING].id), regions[FASTING], filename=messy.name, drug=synthetic.DRUG)
    v1 = _propose(ws, messy, FASTING, fewer)
    v2 = _propose(ws, messy, FASTING, truth)
    v3 = _propose(ws, messy, FASTING, rule.spec, origin="rule")                   # the newest: leaves the summary rows
    v4 = _propose(ws, messy, FASTING, fewer.model_copy(update={"questions": ("is the dose stated elsewhere?",)}))
    assert [v.version for v in (v1, v2, v3, v4)] == [1, 2, 3, 4]
    _arrive(ws, [messy])
    (run,) = _drain(ws)
    cache = MappingCache(ws)
    # the fewest cells with a number left unaccounted, then the most constants: the truth's spec, neither first nor newest
    assert _used(ws, messy, FASTING) == ("mapped", "cache", 2) and _used(ws, messy, FED) == ("mapped", "cache", 2)
    cache.reject(v2.mapping_id, 2, by="u1", why="a test")
    _again(ws, run)
    assert _used(ws, messy, FASTING) == ("mapped", "cache", 4)                    # as much read by two: the newest
    cache.reject(v4.mapping_id, 4, by="u1", why="a test")
    _again(ws, run)
    assert _used(ws, messy, FASTING) == ("mapped", "cache", 1)
    cache.reject(v1.mapping_id, 1, by="u1", why="a test")
    last = _again(ws, run)
    assert _used(ws, messy, FASTING) == ("mapped", "cache", 3)                    # the approved rule version: still approved
    assert _outcomes(ws, messy)[FASTING].unaccounted_count == 21 and last.coverage.silent_loss > 0
    assert len(cache.entries()) - 4 == 2                                         # the two other tables the rules map


def test_a_proposed_rule_version_is_never_taken_in_place_of_the_tables_own_rule_spec(ws, delivery):
    messy = delivery[0]
    _arrive(ws, [messy])
    (run,) = _drain(ws)
    cache = MappingCache(ws)
    own = _outcomes(ws, messy)[FASTING].mapping
    spec = cache.get(own.mapping_id, own.version).spec
    # a rule version made for a shorter table of the layout validates here and reads less: it is the newest proposed one
    shorter = _propose(ws, messy, FASTING, spec.model_copy(update={"last_data_row": 6}), origin="rule", approve=False)
    assert cache.lookup(shorter.fingerprint)[0].version == shorter.version == own.version + 1
    again = _again(ws, run)
    assert _used(ws, messy, FASTING) == ("mapped", "rule", own.version) and _used(ws, messy, FED) == ("mapped", "rule", own.version)
    assert again.counters == run.counters and len(cache.entries()) == 4          # the rules' three and the shorter one


def test_a_rejected_version_is_never_executed(ws, delivery):
    messy = delivery[0]
    _arrive(ws, [messy])
    (run,) = _drain(ws)
    cache = MappingCache(ws)
    rule = _outcomes(ws, messy)[FASTING].mapping
    cache.reject(rule.mapping_id, rule.version, by="u1", why="the rule leaves the mean rows out")
    head = IntakeStore(ws).mappings.head()
    again = _again(ws, run)
    for where in (FASTING, FED):                                                 # the rules make the same spec again
        outcome = _outcomes(ws, messy)[where]
        assert (outcome.state, outcome.mapping) == ("unread", None)
        assert outcome.reason == f"{intake_pipeline.REJECTED_RULE}; no model is configured"
    assert (again.counters.mapped_by_rule, again.counters.unmapped) == (2, 6) and IntakeStore(ws).mappings.head() == head
    assert again.coverage.silent_loss > run.coverage.silent_loss                  # their cells are counted, never dropped
    # a spec of the table mapper that waits for approval is then the one read with (no rule stands before it)
    waiting = _propose(ws, messy, FASTING, _spec(messy, "fasting-individual"), origin="llm", approve=False)
    _again(ws, run)
    assert _used(ws, messy, FASTING) == ("mapped", "cache", waiting.version)
    # and once it is rejected too, the table is unread again: a rejected version is in no one's way and no one's hands
    cache.reject(waiting.mapping_id, waiting.version, by="u1", why="a test")
    _again(ws, run)
    assert _used(ws, messy, FASTING) == ("unread", None, None)


def test_a_table_a_person_approved_as_not_data_is_excluded_and_what_was_read_from_it_is_set_aside(ws, delivery):
    messy = delivery[0]
    _propose(ws, messy, URINE, _spec(messy, "urine-excretion"), origin="llm", approve=False)
    (record,) = _arrive(ws, [messy])
    (run,) = _drain(ws)
    read = [v for v in Ledger(ws).values(file_sha256=record.sha256) if v.anchor and "'Urine'" in v.anchor and "#" in v.id]
    assert len(read) == 4
    not_data = MappingSpec(kind="not_data", layout="long", header_rows=0, first_data_row=1,
                           not_data_reason="a worked example, not a measurement")
    _propose(ws, messy, URINE, not_data)
    again = _again(ws, run)
    urine = _outcomes(ws, messy)[URINE]
    assert (urine.state, urine.origin) == ("excluded", "cache") and urine.reason == "not data: a worked example, not a measurement"
    assert again.coverage.regions_excluded == 1 and again.coverage.silent_loss == run.coverage.silent_loss
    ledger = Ledger(ws)
    assert not [v for v in ledger.values(file_sha256=record.sha256) if v.anchor and "'Urine'" in v.anchor and "#" in v.id]
    assert {ledger.value(v.id).status for v in read} == {"excluded"}


def test_a_second_sheet_of_the_same_layout_and_another_title_is_mapped_by_the_cache_with_its_own_study_and_dose(ws, delivery):
    messy = delivery[0]
    _preload(ws, [messy], tables=("fasting-individual",))
    _arrive(ws, [messy])
    _drain(ws)
    outcomes = _outcomes(ws, messy)
    fasting, fed = outcomes[FASTING], outcomes[FED]
    assert (fasting.origin, fed.origin) == ("cache", "cache") and fasting.mapping == fed.mapping
    assert len([e for e in MappingCache(ws).entries() if e.mapping_id == fed.mapping.mapping_id]) == 1
    ledger = Ledger(ws)
    studies = {e.label: e.id for e in ledger.entities("study")}
    doses = {label: [(v.value, v.unit) for v in ledger.values(study=sid, field="dose")] for label, sid in studies.items()}
    assert doses["230-23"] == [(50.0, "mg")] and doses["231-24"] == [(100.0, "mg")]
    food = {label: [v.value for v in ledger.values(study=sid, field="food_state")] for label, sid in studies.items()}
    assert food["230-23"] == ["fasted"] and food["231-24"] == ["fed"]
    fed_values = [v for v in ledger.values(study=studies["231-24"], field="concentration") if "#" in v.id]
    assert fed_values and all("'Fed'" in v.anchor for v in fed_values)
    truth = [v for v in messy.values if v.table == "fed-individual" and v.field == "concentration"]
    assert len(fed_values) == len(truth)


# --- the LLM stages, through the ports ---------------------------------------------------------------------------------


def test_the_table_mapper_maps_what_is_left_and_never_sees_a_body_digit(ws, delivery):
    messy = delivery[0]
    _doc, regions = _regions(messy)
    urine_id = regions[URINE].id
    urine_spec = _spec(messy, "urine-excretion")
    asked: list[MapRequest] = []

    def map_tables(requests, check):
        asked.extend(requests)
        answers = []
        for request in requests:
            spec = urine_spec if request.region_id == urine_id else None
            assert spec is None or not any(f.severity == "error" for f in check(request.region_id, spec))
            answers.append(MapAnswer(region_id=request.region_id, spec=spec,
                                     origin_detail="scripted/scripted prompt x run ar_1" if spec else "",
                                     agent_run="ar_1" if spec else "ar_2", error="" if spec else "no proposal was accepted"))
        return answers

    llm = LlmPorts(map_tables=map_tables, extract_prose=lambda paragraphs, check: ((), None))
    _arrive(ws, [messy])
    (run,) = _drain(ws, llm=llm)
    assert {r.region_id for r in asked} == {regions[w].id for w in (DISSOLUTION_MEAN, SUMMARY, URINE, PRODUCT)}
    assert (run.counters.mapped_by_llm, run.counters.unmapped, run.counters.llm_runs) == (1, 3, 2)
    assert sorted(run.agent_runs) == ["ar_1", "ar_2"]
    # the mapper is shown no digit of any body cell
    for request in asked:
        assert request.table.body and not any(ch.isdigit() for row in request.table.body for cell in row for ch in cell)
    urine = _outcomes(ws, messy)[URINE]
    assert (urine.state, urine.origin) == ("mapped", "llm")
    entry = MappingCache(ws).get(urine.mapping.mapping_id, urine.mapping.version)
    assert entry.origin == "llm" and entry.by == "agent:ar_1" and "ar_1" in entry.origin_detail
    assert MappingCache(ws).status(entry.mapping_id, entry.version) == "proposed"
    left = [o for o in _outcomes(ws, messy).values() if o.state == "unread"]
    assert len(left) == 3 and all(o.reason == "the table mapper gave no mapping (no proposal was accepted)" for o in left)
    # the next run reads the table with the spec that waits in the cache: the mapper is not asked for it again
    asked.clear()
    again = _again(ws, run, llm=llm)
    assert urine_id not in {r.region_id for r in asked} and len(asked) == 3
    assert (_outcomes(ws, messy)[URINE].origin, again.counters.mapped_by_llm) == ("cache", 0)


def test_a_model_that_fails_leaves_its_tables_and_prose_unread_and_the_run_goes_on(ws, delivery):
    def down(*args):
        raise ConnectionError("the model is not reachable")

    llm = LlmPorts(map_tables=down, extract_prose=down)
    _arrive(ws, [delivery[0], delivery[1]])
    messy, pdf = _drain(ws, llm=llm)
    assert (messy.state, pdf.state) == ("done", "done") and all(s.ok for s in (*messy.stages, *pdf.stages))
    assert (messy.counters.mapped_by_rule, messy.counters.unmapped, messy.counters.values) == (4, 4, 114)
    unread = [o for o in _outcomes(ws, delivery[0]).values() if o.state == "unread"]
    assert {o.reason for o in unread} == {"the table mapper failed (ConnectionError: the model is not reachable)"}
    assert messy.coverage.silent_loss == 103 and messy.agent_runs == ()
    prose = next(o for w, o in _outcomes(ws, delivery[1]).items() if w.startswith("p:1/w:"))
    assert (prose.state, prose.reason) == ("unread", "the prose extractor failed (ConnectionError: the model is not reachable)")
    assert pdf.counters.values == 30 and pdf.coverage.silent_loss == 0


def test_the_prose_extractor_s_facts_are_code_s_reading_of_the_paragraph(ws, delivery):
    pdf = delivery[1]
    seen: list = []
    refused: list[str] = []

    def extract_prose(paragraphs, check):
        seen.extend(paragraphs)
        synopsis = next(p for p in paragraphs if "50 mg" in p.text)
        try:                                          # a number the sentence does not state is refused by code
            check("dose", 500, "Exampleamide was given as a single oral dose of 50 mg.", synopsis.index, "230-23", None)
        except ProseFactError as exc:
            refused.append(str(exc))
        fact = check("dose", 50, "Exampleamide was given as a single oral dose of 50 mg.", synopsis.index, "230-23", None)
        return [fact], ModelUse(provider="scripted", model="scripted", prompt_sha256="0" * 64, agent_run="ar_000000000001")

    llm = LlmPorts(map_tables=lambda requests, check: [], extract_prose=extract_prose)
    _arrive(ws, [pdf])
    (run,) = _drain(ws, llm=llm)
    assert run.state == "done" and run.agent_runs == ("ar_000000000001",) and run.counters.llm_runs == 1
    assert len(refused) == 1
    assert [p.index for p in seen] == list(range(1, len(seen) + 1))           # one numbering across the file
    truth = next(v for v in pdf.values if v.field == "dose" and not v.table)
    prose = [v for v in Ledger(ws).values(field="dose") if v.method == "prose"]
    assert len(prose) == 1 and (prose[0].value, prose[0].unit) == (50.0, "mg")
    assert prose[0].verbatim == "Exampleamide was given as a single oral dose of 50 mg."
    # anchored at the value's own words, with the box of those words on the parsed page (never an invented one)
    assert _place(prose[0].anchor.split("#", 1)[1]) == _place(truth.locator)
    doc = parse_document(pdf.data, pdf.name)
    found = resolve(doc, prose[0].anchor)
    assert found.text == "50" and found.box == parse_anchor(prose[0].anchor).locator.box
    region = next(o for w, o in _outcomes(ws, pdf).items() if w.startswith("p:1/w:"))
    assert (region.state, region.origin) == ("mapped", "llm")


# --- the queue -------------------------------------------------------------------------------------------------------


def test_enqueue_from_two_threads_queues_once(ws, delivery):
    records = _arrive(ws, delivery[:1], queue=False)
    queued: list = []
    threads = [threading.Thread(target=lambda: queued.extend(intake_pipeline.enqueue(ws, records, by="u1")))
               for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(queued) == 1 and [r.state for r in intake_pipeline.runs(ws)] == ["queued"]
    assert intake_pipeline.pending(ws)
    # and not again while it runs
    run = intake_pipeline.take(ws)
    assert run is not None and intake_pipeline.enqueue(ws, records, by="u1") == [] and not intake_pipeline.pending(ws)


def test_take_recover_and_a_run_stopped_twice(ws, delivery):
    _arrive(ws, delivery[3:])
    run = intake_pipeline.take(ws)
    assert run is not None and (run.state, run.attempt) == ("running", 1) and intake_pipeline.take(ws) is None
    assert intake_pipeline.unfinished(ws) and not intake_pipeline.pending(ws)       # left running: nothing waits
    assert intake_pipeline.recover(ws) == 1                  # a restart: queued again
    again = intake_pipeline.take(ws)
    assert (again.run_id, again.attempt) == (run.run_id, 2)
    assert intake_pipeline.recover(ws) == 1                  # stopped twice: failed, with its event
    (last,) = intake_pipeline.runs(ws)
    assert last.state == "failed" and "not tried again" in last.error and not intake_pipeline.unfinished(ws)
    events = [r.event for r in ws.store.audit("t1").records() if r.event.action == "intake.run"]
    assert [(e.resource_id, e.after["state"]) for e in events] == [(f"p1/{run.run_id}", "failed")]
    assert events[0].after["row_hash"] == IntakeStore(ws).runs.head().hash
    # a failed run does not stand in the way: the same file is queued again when it arrives again
    assert len(_arrive(ws, delivery[3:])) == 1 and intake_pipeline.pending(ws)


def test_sweep_records_and_queues_the_stored_files_once(ws, delivery):
    library = DocumentLibrary(ws)
    assert ws.commit(ArtifactKind.BRIEF, "main", BRIEF.to_content(), actor="u1", reason="start") is not None
    word, pdf = delivery[2], delivery[1]
    for file in (word, pdf):                              # stored by today's reader before the pipeline ran
        ingest(ws, library, file.data, file.name, by="u1", brief=BRIEF)
    # one of them was recorded (an arrival whose run was never queued), the other never was
    first = intake_files.open_delivery(ws, by="u1")
    recorded = intake_files.record_arrival(ws, word.data, word.name, delivery=first, by="u1")
    assert intake_pipeline.sweep(ws) == 2
    assert intake_pipeline.sweep(ws) == 0
    files = intake_files.files(ws)
    assert len(files) == 2 and files[0] == recorded and (files[1].name, files[1].by) == (pdf.name, "code")
    assert len(intake_files.deliveries(ws)) == 2
    assert sorted(r.sha256 for r in intake_pipeline.runs(ws)) == sorted(f.sha256 for f in files)
    assert [r.state for r in _drain(ws)] == ["done", "done"]
    assert intake_pipeline.sweep(ws) == 0 and len(intake_pipeline.runs(ws)) == 2
