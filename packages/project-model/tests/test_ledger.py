"""The ledger's writes (contracts §6.3, §8.6): one extract per mapped table with a locator and a stable id per value,
idempotent re-runs, supersession by a new mapping version or a moved value, a region gone after a re-parse, facts for
text-valued and relation rows, one LLOQ fact per stated LLOQ, values with no study kept, a person's correction that
stays in its series, exclusions with a reason, verified chains and no audit event per fact. Inputs are ExtractResults
built by hand from the synthetic truth (test_ledger_support)."""

from __future__ import annotations

import hashlib
import threading

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import (
    ID_PATTERNS,
    AnchorError,
    PdfCell,
    PdfSpan,
    format_locator,
    parse_anchor,
    parse_locator,
    same_place,
)
from modeler_intake.mapping_spec import (
    ColumnMap,
    Constant,
    ExtractedConstant,
    ExtractedRow,
    ExtractResult,
    MappingSpec,
    ProseFact,
)
from modeler_intake.source_model import GridCell, RegionGrid
from modeler_intake.synthetic import truth_grid
from modeler_project.coverage import values_unassigned
from modeler_project.intake_fixtures import TRUTH_MODEL, truth_key, write_truth
from modeler_project.intake_records import Assignment, Confirmation, CoverageSummary
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import NOT_READ_AGAIN, REGION_GONE, ExtractionContext, Ledger, _box_share, cells_in_common
from modeler_project.ledger_entities import merge, resolve
from modeler_project.ledger_view import LedgerView
from modeler_project.scorecard import scorecard
from modeler_project.workspace import Workspace

from .test_ledger_support import (
    approve,
    context,
    file_record,
    grid_from_rows,
    make_ws,
    mapping_entry,
    prose_of,
    record_file,
    record_table,
    region_of,
    result_of,
    sha_of,
    sheet_context,
    truth_table,
)

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

A = "a" * 64


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return make_ws(tmp_path)


def _heads(ws: Workspace) -> tuple:
    store = IntakeStore(ws)
    return store.facts.head(), store.entities.head()


def _intake_events(ws: Workspace) -> list:
    return [r.event for r in ws.store.audit("t1").records() if r.event.resource_type == "intake"]


# --- one extract per table, one id and one locator per value -------------------------------------------------------


def test_a_recorded_extraction_gives_one_extract_whose_every_value_has_its_own_locator_and_a_stable_id(ws):
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    recorded = record_table(ledger, workbook, "fasting-individual")
    assert recorded.extract is not None and ID_PATTERNS["extract"].fullmatch(recorded.extract)
    numeric = [v for v in workbook.values if v.table == "fasting-individual" and v.field == "concentration"]
    values = [v for v in ledger.values() if v.id.startswith(f"{recorded.extract}#")]
    assert len(values) == len(numeric) == 6 * 6 + 6                   # six subjects and the mean row, six times each
    assert [v.id for v in values] == [f"{recorded.extract}#{i}" for i in range(len(values))]
    assert all(ID_PATTERNS["value"].fullmatch(v.id) for v in values)
    assert len({v.anchor for v in values}) == len(values)              # each value its own cell
    texts = {c.locator: c.text for c in truth_grid(workbook, "fasting-individual").cells.values()}
    for value, truth in zip(values, numeric, strict=True):
        assert same_place(parse_anchor(value.anchor).locator, parse_locator(truth.locator))
        assert value.verbatim == texts[truth.locator] and value.value == (None if truth.value in ("BLQ", "NS") or
                                                                          truth.value[0] in "<>" else float(truth.value.rstrip("*")))
        assert parse_anchor(value.locators["time"]).locator == parse_locator(dict(truth.locators)["time"])
        assert value.method == "cell" and value.table_kind == "pk_individual" and value.level == "approved_mapping"
    # the id is the content's: the same content in another ledger has the same id
    other = Workspace(ws.store, "t1", "p2")
    assert record_table(Ledger(other), workbook, "fasting-individual").extract == recorded.extract
    # what the table states besides its numbers: its naming constants, the dose, the food state and the LLOQ
    facts = {ledger.value(f).field: ledger.value(f) for f in recorded.facts}
    assert set(facts) == {"study_id", "analyte", "dose", "food_state", "lloq"}
    assert facts["dose"].value == 50.0 and facts["dose"].unit == "mg" and facts["food_state"].value == "fasted"
    study = ledger.entity(facts["study_id"].entity.study)
    assert study.label == "230-23" and all(v.entity.study == study.id for v in values)


def test_recording_again_adds_nothing_under_any_delivery_run_or_after_an_entity_merge(ws):
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    first = record_table(ledger, workbook, "fasting-individual")
    heads = _heads(ws)
    again = record_table(ledger, workbook, "fasting-individual")
    assert again.extract == first.extract and again.facts == first.facts and again.superseded == ()
    assert _heads(ws) == heads
    # the same bytes under a later delivery and another run: identity is content, not the arrival
    later = record_table(ledger, workbook, "fasting-individual", delivery="dl-7", run_id="run-3")
    assert later.extract == first.extract and _heads(ws)[0] == heads[0]
    # the same values after an entity merge (the study joined to another of the same label elsewhere)
    listing = synthetic.delimited()
    record_table(ledger, listing, "delimited-listing")
    study = ledger.value(first.facts[0]).entity.study
    other = next(e.id for e in ledger.entities("study") if e.label == "230-28")
    merge(ledger, type="study", from_id=study, into_id=other, link_fact=None, why="the protocol names both", by="u")
    facts_head = IntakeStore(ws).facts.head()
    after = record_table(ledger, workbook, "fasting-individual")
    assert after.extract == first.extract and IntakeStore(ws).facts.head() == facts_head
    assert {v.entity.study for v in ledger.values(file_sha256=sha_of(workbook))} == {other}


def test_a_new_mapping_version_supersedes_the_earlier_extract_and_its_facts(ws):
    """§6.3's identity is (file, region, mapping id): a new mapping version that reads every value the same writes
    nothing, whatever its version, so the subject's confirmation and draw stay current; one that reads a value
    differently supersedes the earlier extract, and each fact it reads differently supersedes that fact."""
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    first = record_table(ledger, workbook, "fasting-metabolite")
    facts = {ledger.value(f).field: ledger.value(f) for f in first.facts}
    study = facts["study_id"].entity.study
    digest, heads = ledger.digest(study=study), _heads(ws)
    same = record_table(ledger, workbook, "fasting-metabolite", version=2)
    assert (same.extract, same.facts, same.superseded) == (first.extract, first.facts, ()) and _heads(ws) == heads
    assert ledger.digest(study=study) == digest
    kept = [v for v in ledger.values() if v.id.startswith(f"{first.extract}#")]
    assert kept and {v.mapping.version for v in kept} == {1}                 # the version that read them
    # version 3 reads the means as geometric means and the LLOQ's unit as "ng/ml": a new extract and LLOQ fact
    table, grid = truth_table(workbook, "fasting-metabolite"), truth_grid(workbook, "fasting-metabolite")
    entry = mapping_entry(table.spec, version=3, first_seen=(sha_of(workbook), grid.region_id))
    approve(ws, entry)
    result = result_of(workbook, "fasting-metabolite")
    result = result.model_copy(update={
        "rows": tuple(r.model_copy(update={"statistic": "geometric_mean",
                                           "lloq_unit": "ng/ml" if r.lloq_unit else None}) for r in result.rows),
        "constants": tuple(c.model_copy(update={"unit": "ng/ml"}) if c.field == "lloq" else c for c in result.constants)})
    second = ledger.record_extraction(region=region_of(grid, table.kind, table.where), grid=grid, mapping=entry,
                                      result=result, context=context(workbook))
    assert second.extract != first.extract and first.extract in second.superseded
    assert all(v.status == "superseded" and v.superseded_by == second.extract
               for v in ledger.values(active=False) if v.id.startswith(f"{first.extract}#"))
    new = [v for v in ledger.values() if v.id.startswith(f"{second.extract}#")]
    assert new and all(v.mapping.version == 3 and v.status == "proposed" for v in new)
    (lloq,) = [ledger.value(f) for f in second.facts if ledger.value(f).field == "lloq"]
    assert (lloq.unit, ledger.value(facts["lloq"].id).status, ledger.value(facts["lloq"].id).superseded_by) == (
        "ng/ml", "superseded", lloq.id)
    for name in ("study_id", "analyte"):                                    # read the same: the same facts
        assert facts[name].id in second.facts and ledger.value(facts[name].id).status == "proposed"
    assert ledger.digest(study=study) != digest
    assert ledger.store.facts.verify() == []


def _small(caption: str = "Study 230-29, 25 mg") -> tuple[list[list], MappingSpec]:
    rows = [["Time (h)", "Conc (ng/mL)"], [0.5, 4.2], [1, 7.9], [2, 6.1]]
    spec = MappingSpec(kind="pk_summary", layout="wide_series", header_rows=1, first_data_row=2, field="concentration",
                       columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")),
                       constants=(Constant(field="study_id", cite={"near": "caption", "line": 1}, pattern=r"Study (\S+),"),))
    return rows, spec


def _small_result(grid, *, caption_value: str = "230-29") -> ExtractResult:
    caption = grid.caption[0]
    rows = []
    for r in range(2, grid.n_rows + 1):
        time, value = grid.cell(r, 1), grid.cell(r, 2)
        rows.append(ExtractedRow(field="concentration", labels={}, time=float(time.value), time_unit="h",
                                 time_locator=time.locator, value=float(value.value), verbatim=value.text,
                                 locator=value.locator, unit="ng/mL", unit_locator=grid.cell(1, 2).locator,
                                 statistic="arithmetic_mean"))
    return ExtractResult(rows=tuple(rows), cell_use=(), findings=(),
                         constants=(ExtractedConstant(field="study_id", value=caption_value, verbatim=caption.text,
                                                      locator=caption.locator),))


def test_a_reparse_whose_anchors_hold_writes_nothing_and_one_that_moves_a_value_supersedes(ws):
    ledger = Ledger(ws)
    rows, spec = _small()
    entry = mapping_entry(spec)

    def record(version: str, first_cell: str | None = None):
        grid = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), parser_version=version, first_cell=first_cell)
        return ledger.record_extraction(region=region_of(grid), grid=grid, mapping=entry, result=_small_result(grid),
                                        context=sheet_context(A, parser_version=version))

    first = record("1.0")
    heads = _heads(ws)
    held = record("1.1")                                       # a new parser version that finds every cell again
    assert held.extract == first.extract and _heads(ws) == heads
    assert {parse_anchor(v.anchor).parser_version for v in ledger.values()} == {"1.0"}   # the old anchors are kept
    moved = record("1.1", first_cell="A3")                    # the same table one row lower: every value moved
    assert moved.extract != first.extract and moved.superseded[:1] == (first.extract,)
    assert {parse_anchor(v.anchor).parser_version for v in ledger.values() if v.field == "concentration"} == {"1.1"}
    assert all(v.status == "superseded" for v in ledger.values(active=False) if v.id.startswith(f"{first.extract}#"))


def test_an_extract_whose_region_is_gone_after_a_reparse_is_retired_with_the_reason(ws):
    ledger = Ledger(ws)
    rows, spec = _small()
    entry = mapping_entry(spec)
    grid = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), region_id="rg-00000000aa")
    kept = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), region_id="rg-00000000bb", sheet="U")
    gone = ledger.record_extraction(region=region_of(grid), grid=grid, mapping=entry, result=_small_result(grid),
                                    context=sheet_context(A))
    stays = ledger.record_extraction(region=region_of(kept), grid=kept, mapping=entry, result=_small_result(kept),
                                     context=sheet_context(A))
    retired = ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"])
    assert [c.target for c in retired] == [gone.extract] and retired[0].reason == REGION_GONE
    values = {v.id: v for v in ledger.values(active=False)}
    assert all((v.status, v.status_reason) == ("excluded", REGION_GONE) for i, v in values.items() if i.startswith(gone.extract))
    assert all(v.status == "proposed" for i, v in values.items() if i.startswith(stays.extract))
    assert ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"]) == []   # once
    # a region recorded twice (the second extract superseding the first), then gone: both are retired, since retiring
    # the second brings back the first
    lower = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), region_id="rg-00000000bb", sheet="U",
                           first_cell="A3")
    moved = ledger.record_extraction(region=region_of(lower), grid=lower, mapping=entry, result=_small_result(lower),
                                     context=sheet_context(A))
    assert moved.superseded == (stays.extract,)
    retired = ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=[])
    assert [c.target for c in retired] == [moved.extract, stays.extract]
    assert ledger.values(file_sha256=A, field="concentration") == []
    assert ledger.retire_regions(file_sha256=A, parser_version="1.0", regions=[]) == []    # not after a re-parse


# --- a re-parse that gives a region another id (SEAM-5) -------------------------------------------------------------


def _renamed(ws: Workspace, ledger: Ledger):
    """A small table recorded under parser version 1.0 as region rg-00000000aa, its study confirmed by a person; and
    `record(version, region_id, ...)`, which records the same sheet again as another parse gives it."""
    rows, spec = _small()
    entry = mapping_entry(spec)

    def record(version: str, region_id: str, *, rows=rows, entry=entry, first_cell: str | None = None):
        grid = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), parser_version=version, region_id=region_id,
                              first_cell=first_cell)
        return ledger.record_extraction(region=region_of(grid), grid=grid, mapping=entry, result=_small_result(grid),
                                        context=sheet_context(A, parser_version=version))

    first = record("1.0", "rg-00000000aa")
    (study,) = ledger.entities("study")
    record_ = {"facts": [[f, "x", None] for f in first.facts], "extracts": [[first.extract, "x"]], "excluded": []}
    IntakeStore(ws).review.append("confirmation", Confirmation(
        id="cf-1", subject_type="study", subject=study.id, record_sha256="0" * 64, record=record_, signature_id="sig-1",
        manifestation="Reviewed", by="u-1", printed_name="U", at="2026-11-13T10:00:00.000Z").model_dump(mode="json"))
    ledger.refresh()
    assert {v.status for v in ledger.values(study=study.id)} == {"confirmed"}
    return first, study.id, record, spec


def _table_values(ledger: Ledger) -> list:
    return ledger.values(file_sha256=A, field="concentration")


def test_a_reparse_that_gives_a_region_another_id_writes_nothing_when_every_value_is_found_at_its_place(ws):
    """§6.3: after a re-parse, when every value of an extract is found again the extract stays and nothing is written.
    A region's id is D2's (a PDF table's hashes its box), so a new parser version may give the same table another id:
    recording it again (the same file and mapping, every value equal by place) is the same extract, whatever its
    region id, and the study's confirmation stays bound."""
    ledger = Ledger(ws)
    first, study, record, _spec = _renamed(ws, ledger)
    digest, heads = ledger.digest(study=study), _heads(ws)
    again = record("1.1", "rg-00000000bb")                    # the same cells, another region id, a new parser version
    assert (again.extract, again.facts, again.superseded) == (first.extract, first.facts, ())
    assert _heads(ws) == heads and ledger.digest(study=study) == digest
    values = _table_values(ledger)
    assert [v.id for v in values] == [f"{first.extract}#{i}" for i in range(3)]         # once, not twice
    assert {(v.status, v.confirmation) for v in values} == {("confirmed", "cf-1")}
    assert {parse_anchor(v.anchor).parser_version for v in values} == {"1.0"}             # the old anchors are kept
    # the run then retires the regions the new document no longer has (W: after its recordings, with the same Ledger):
    # the extract's region id is not one of them, but this ledger has just read its table again
    assert ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"]) == []
    assert _heads(ws) == heads
    # another Ledger (a later run, or a caller that retires before it records) says what check_anchors found again
    later = Ledger(ws)
    found = [v.id for v in later.values(file_sha256=A)]
    assert later.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"], found=found) == []
    assert record("1.1", "rg-00000000bb").extract == first.extract and _heads(ws) == heads
    assert {(v.status, v.confirmation) for v in _table_values(ledger)} == {("confirmed", "cf-1")}


def test_retire_regions_keeps_an_extract_only_when_every_value_of_it_was_found_again(ws):
    ledger = Ledger(ws)
    first, _study, _record, _spec = _renamed(ws, ledger)
    ids = [v.id for v in _table_values(ledger)]
    heads = _heads(ws)
    assert ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"], found=ids) == []
    assert ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=[], found=ids) == [] and _heads(ws) == heads
    # a value a person excluded is no longer checked (it is not active): the others found are enough
    ledger.exclude(ids[2], why="a re-assay", by="u-1")
    assert ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"], found=ids[:2]) == []
    # one value was not found (it moved, or its text differs): the region is gone, as before, with the reason
    (retired,) = ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"], found=ids[:1])
    assert (retired.target, retired.reason) == (first.extract, REGION_GONE)
    assert _table_values(ledger) == []


def test_retire_regions_called_as_before_retires_by_region_id_and_the_same_table_recorded_again_is_back(ws):
    """Without what check_anchors found, `retire_regions` judges by region id alone (the call W knows today). The
    same table recorded under its new id is then the same extract again: set proposed, no second extract, and the
    confirmation binds it as before."""
    ledger = Ledger(ws)
    first, _study, record, _spec = _renamed(ws, ledger)
    (retired,) = ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"])
    assert (retired.target, retired.reason) == (first.extract, REGION_GONE) and _table_values(ledger) == []
    back = record("1.1", "rg-00000000bb")
    assert back.extract == first.extract and back.superseded == ()
    assert len(IntakeStore(ws).facts.entries("extract")) == 1
    assert {(v.id.split("#")[0], v.status, v.confirmation) for v in _table_values(ledger)} == {
        (first.extract, "confirmed", "cf-1")}
    # read again by this ledger under 1.1, it is not retired a second time; under a later version nothing has read it
    assert ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=["rg-00000000bb"]) == []
    (later,) = ledger.retire_regions(file_sha256=A, parser_version="1.2", regions=["rg-00000000bb"])
    assert (later.target, later.reason) == (first.extract, REGION_GONE)


def test_a_region_with_another_id_whose_values_moved_or_changed_still_supersedes(ws):
    """The other half of §6.3: a table whose values moved, or are read differently, is a new extract that supersedes the
    earlier one, also when the re-parse gave its region another id; never two active extracts of one table."""
    ledger = Ledger(ws)
    first, _study, record, spec = _renamed(ws, ledger)
    kept = record("1.1", "rg-00000000bb")                      # the id changed, the cells did not: the same extract
    assert kept.extract == first.extract
    # later, under the new id: a mapping version that reads the means as geometric means
    rows, _spec = _small()
    changed = mapping_entry(spec, version=2)
    grid = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), parser_version="1.1", region_id="rg-00000000bb")
    result = _small_result(grid)
    result = result.model_copy(update={"rows": tuple(r.model_copy(update={"statistic": "geometric_mean"}) for r in result.rows)})
    second = ledger.record_extraction(region=region_of(grid), grid=grid, mapping=changed, result=result,
                                      context=sheet_context(A, parser_version="1.1"))
    assert second.extract != first.extract and second.superseded == (first.extract,)
    values = _table_values(ledger)
    assert [v.id for v in values] == [f"{second.extract}#{i}" for i in range(3)]         # one active extract
    assert {v.statistic for v in values} == {"geometric_mean"} and {v.status for v in values} == {"proposed"}
    assert all(v.status == "superseded" and v.superseded_by == second.extract
               for v in ledger.values(active=False) if v.id.startswith(f"{first.extract}#"))
    # a further re-parse: yet another id, and the table one row lower (every value moved)
    moved = record("1.2", "rg-00000000cc", entry=changed, first_cell="A3")
    assert moved.extract not in (first.extract, second.extract)
    active = {v.id.split("#")[0] for v in _table_values(ledger)}
    assert active == {moved.extract}
    # and a region that is really gone is retired with the reason: nothing of it was found, and nothing records it
    # (retiring an extract brings back the one it superseded, so each earlier reading of the table is retired in turn)
    gone = ledger.retire_regions(file_sha256=A, parser_version="1.3", regions=["rg-00000000dd"], found=[])
    assert [(c.target, c.reason) for c in gone] == [(e, REGION_GONE) for e in (moved.extract, second.extract, first.extract)]
    assert _table_values(ledger) == []


def test_a_table_under_another_region_id_is_known_by_the_regions_cells_not_only_by_those_read_as_values(ws):
    """After a re-parse gave the region another id, a mapping version that reads another column of the table (no value
    cell in common with the earlier extract) still supersedes it: the earlier values stand in cells of this region."""
    ledger = Ledger(ws)
    first, _study, _record, spec = _renamed(ws, ledger)
    rows, _spec = _small()
    grid = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), parser_version="1.1", region_id="rg-00000000bb")
    caption = grid.caption[0]
    other_column = ExtractResult(
        rows=tuple(ExtractedRow(field="concentration", labels={}, value=float(grid.cell(r, 1).value),
                                verbatim=grid.cell(r, 1).text, locator=grid.cell(r, 1).locator, unit="ng/mL",
                                unit_locator=grid.cell(1, 2).locator, statistic="arithmetic_mean") for r in (2, 3, 4)),
        cell_use=(), findings=(), constants=(ExtractedConstant(field="study_id", value="230-29", verbatim=caption.text,
                                                              locator=caption.locator),))
    second = ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec, version=2),
                                      result=other_column, context=sheet_context(A, parser_version="1.1"))
    assert second.extract != first.extract and second.superseded == (first.extract,)
    assert {v.id.split("#")[0] for v in _table_values(ledger)} == {second.extract}
    cells = {v.id.split("#")[0]: parse_anchor(v.anchor).locator.cell[0] for v in ledger.values(file_sha256=A, active=False)
             if v.field == "concentration"}
    assert cells == {first.extract: "B", second.extract: "A"}            # no value cell in common


def test_a_region_with_another_id_keeps_a_persons_exclusion_and_loses_its_extract_when_nothing_is_read_any_more(ws):
    ledger = Ledger(ws)
    first, _study, record, spec = _renamed(ws, ledger)
    # a person excluded the table: the exclusion stands when the table comes back under another region id
    ledger.exclude(first.extract, why="a draft table", by="u-1")
    heads = _heads(ws)
    again = record("1.1", "rg-00000000bb")
    assert again.extract == first.extract and _heads(ws) == heads and _table_values(ledger) == []
    # another ledger: under the new id, a mapping version that reads no numeric value any more (every row a note)
    other = Workspace(ws.store, "t1", "p2")
    ledger = Ledger(other)
    first, _study, record, spec = _renamed(other, ledger)
    assert record("1.1", "rg-00000000bb").extract == first.extract
    rows, _spec = _small()
    grid = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), parser_version="1.1", region_id="rg-00000000bb")
    nothing = _small_result(grid).model_copy(update={"rows": ()})
    emptied = ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec, version=2),
                                       result=nothing, context=sheet_context(A, parser_version="1.1"))
    assert emptied.extract is None and emptied.superseded == (first.extract,)
    gone = [v for v in ledger.values(active=False) if v.id.startswith(f"{first.extract}#")]
    assert len(gone) == 3 and all(v.status == "excluded" and v.status_reason.startswith(NOT_READ_AGAIN) for v in gone)


def test_cells_in_common_follows_the_anchor_checks_rule():
    """Across parser versions a sheet or Word cell is its place, and a PDF cell its page and box (the half-overlap by
    which `check_anchors` finds a value again), measured as D2 measures it."""
    from modeler_intake.source.pdf import overlap

    def pdf(table: int, row: int, box: tuple[float, float, float, float], page: int = 1) -> str:
        return format_locator(PdfCell(page=page, table=table, row=row, column=2, box=box))

    box = (100.0, 200.0, 140.0, 212.0)
    for other in ((100.6, 200.6, 140.6, 212.6), (120.0, 200.0, 160.0, 212.0), (121.0, 200.0, 161.0, 212.0),
                  (100.0, 212.0, 140.0, 224.0), (0.0, 0.0, 600.0, 800.0), (100.0, 200.0, 100.0, 212.0)):
        assert _box_share(box, other) == overlap(box, other)
    assert cells_in_common([pdf(1, 2, box)], [pdf(2, 2, (100.6, 200.6, 140.6, 212.6))])       # renumbered, the same box
    assert cells_in_common([pdf(1, 2, box)], [pdf(1, 2, (120.0, 200.0, 160.0, 212.0))])       # half of it
    assert not cells_in_common([pdf(1, 2, box)], [pdf(1, 2, (121.0, 200.0, 161.0, 212.0))])   # less than half
    assert not cells_in_common([pdf(1, 2, box)], [pdf(1, 2, (100.0, 400.0, 140.0, 412.0))])   # the same numbers, elsewhere
    assert not cells_in_common([pdf(1, 2, box)], [pdf(1, 2, box, page=2)])                    # another page
    assert cells_in_common(["s:'T'!B2", "s:'T'!B3"], ["s:'T'!B3"]) and not cells_in_common(["s:'T'!B2"], ["s:'U'!B2"])
    assert cells_in_common(["d:t:1/r:2/c:2"], ["d:t:1/r:2/c:2"]) and not cells_in_common(["d:t:1/r:2/c:2"], ["d:t:2/r:2/c:2"])
    assert not cells_in_common([], ["s:'T'!B3"]) and not cells_in_common(["s:'T'!B3"], [])


def test_two_pdf_tables_renumbered_by_a_reparse_are_told_apart_by_their_boxes_not_their_numbers(ws):
    """A PDF cell's place is (page, table, row, column), and a parser that finds one more table on a page numbers the
    others anew. Across parser versions a cell is the same cell when its box overlaps by half (`check_anchors`' rule):
    the first table's new reading supersedes the first table's extract, never the second table's, whose old numbers
    it now carries."""
    sha = "c" * 64

    def table(version: str, number: int, top: float, region_id: str, study: str, shift: float = 0.0) -> tuple:
        cells = {}
        texts = [["Time (h)", "Conc (ng/mL)"], ["1", "4.2"], ["2", "7.9"]]
        for r, row in enumerate(texts, start=1):
            for c, text in enumerate(row, start=1):
                box = (50.0 + 100 * (c - 1) + shift, top + 12 * (r - 1) + shift, 140.0 + 100 * (c - 1) + shift,
                       top + 12 * r + shift)
                cells[(r, c)] = GridCell(text=text, value=text, type="text" if r == 1 else "number",
                                         locator=format_locator(PdfCell(page=1, table=number, row=r, column=c, box=box)))
        caption = GridCell(text=f"Study {study}", value=f"Study {study}", type="text", locator=format_locator(
            PdfSpan(page=1, first_word=int(top), last_word=int(top) + 1, box=(50.0, top - 14, 200.0, top - 2))))
        grid = RegionGrid(file_sha256=sha, parser="pdfplumber", parser_version=version, region_id=region_id, n_rows=3,
                          n_cols=2, cells=cells, caption=(caption,))
        rows = tuple(ExtractedRow(field="concentration", labels={}, time=float(grid.cell(r, 1).text), time_unit="h",
                                  time_locator=grid.cell(r, 1).locator, value=float(grid.cell(r, 2).text),
                                  verbatim=grid.cell(r, 2).text, locator=grid.cell(r, 2).locator, unit="ng/mL",
                                  unit_locator=grid.cell(1, 2).locator, statistic="arithmetic_mean") for r in (2, 3))
        result = ExtractResult(rows=rows, cell_use=(), findings=(), constants=(ExtractedConstant(
            field="study_id", value=study, verbatim=caption.text, locator=caption.locator),))
        ctx = ExtractionContext(delivery="dl-1", run_id=None, file=file_record(sha, "report.pdf"), parser="pdfplumber",
                                parser_version=version)
        return grid, result, ctx

    ledger = Ledger(ws)
    _rows, spec = _small()
    entry = mapping_entry(spec)

    def record(*args, **kwargs):
        grid, result, ctx = table(*args, **kwargs)
        return ledger.record_extraction(region=region_of(grid, where=f"p:1/t:{args[1]}"), grid=grid, mapping=entry,
                                        result=result, context=ctx)

    upper = record("1.0", 1, 100.0, "rg-0000000a01", "230-41")
    lower = record("1.0", 2, 300.0, "rg-0000000a02", "230-42")
    # version 1.1 finds a table above them (tables 2 and 3 now), and its boxes are 0.6 pt off: other region ids
    again = record("1.1", 2, 100.0, "rg-0000000b01", "230-41", shift=0.6)
    assert again.extract != upper.extract and again.superseded == (upper.extract,)      # moved: it supersedes its own
    by_extract = {v.id.split("#")[0] for v in ledger.values(file_sha256=sha, field="concentration")}
    assert by_extract == {again.extract, lower.extract}                                  # the lower table is untouched
    below = record("1.1", 3, 300.0, "rg-0000000b02", "230-42", shift=0.6)
    assert below.superseded == (lower.extract,)
    assert {v.id.split("#")[0] for v in ledger.values(file_sha256=sha, field="concentration")} == {again.extract, below.extract}


def test_a_pdf_reparse_that_moves_every_table_box_keeps_what_check_anchors_finds_again(ws, monkeypatch):
    """D2 and D4 together (SEAM-5). A PDF table's region id hashes its box rounded to whole points, and the parser
    version names the PDF library: an upgrade that makes every box 0.6 pt larger gives every table another region id,
    while `check_anchors` finds every value again. The ledger then keeps every extract and writes nothing."""
    import modeler_intake.source.parse as source_parse
    import modeler_intake.source.pdf as source_pdf
    from modeler_intake.mapping.execute import execute
    from modeler_intake.source import check_anchors, parse_document, region_grid

    pdf = synthetic.pdf_report(unruled_table=False)
    sha = sha_of(pdf)
    ledger = Ledger(ws)
    entries = {t.where: mapping_entry(t.spec) for t in pdf.tables}

    def run(doc) -> list:
        ctx = ExtractionContext(delivery="dl-1", run_id=None, file=file_record(sha, pdf.name, size=len(pdf.data)),
                                parser=doc.parser, parser_version=doc.parser_version)
        out = []
        for region in doc.regions:
            if region.kind == "table":
                grid = region_grid(doc, region.id)
                entry = entries[region.where]
                out.append(ledger.record_extraction(region=region, grid=grid, mapping=entry,
                                                    result=execute(entry.spec, grid), context=ctx))
        return out

    doc = parse_document(pdf.data, pdf.name)
    first = run(doc)
    assert len(first) == 3 and all(r.extract for r in first)
    heads = _heads(ws)
    original = source_pdf.pdf_table_region_id
    monkeypatch.setattr(source_pdf, "pdf_table_region_id",
                        lambda page, box, first_row, file_sha: original(page, tuple(v + 0.6 for v in box), first_row, file_sha))
    monkeypatch.setattr(source_parse, "SOURCE_VERSION", "1.1")
    new = parse_document(pdf.data, pdf.name)
    old_ids, new_ids = ({r.id for r in d.regions if r.kind == "table"} for d in (doc, new))
    assert new.parser_version != doc.parser_version and not old_ids & new_ids            # every table: another id
    items = [(v.id, v.anchor, v.verbatim) for v in ledger.values(file_sha256=sha, active=False) if v.anchor]
    problems = check_anchors(new, items)
    assert problems == [] and len(items) > 40
    again = run(new)                                                 # recorded again under the new ids: the same extracts
    assert [r.extract for r in again] == [r.extract for r in first] and _heads(ws) == heads
    regions = [r.id for r in new.regions]
    assert ledger.retire_regions(file_sha256=sha, parser_version=new.parser_version, regions=regions) == []
    found = {item[0] for item in items} - {p.id for p in problems}
    assert Ledger(ws).retire_regions(file_sha256=sha, parser_version=new.parser_version, regions=regions, found=found) == []
    assert _heads(ws) == heads
    assert {parse_anchor(v.anchor).parser_version for v in ledger.values(file_sha256=sha)} == {doc.parser_version}


# --- facts ---------------------------------------------------------------------------------------------------------


def test_a_text_valued_row_and_a_relation_row_become_facts(ws):
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    recorded = record_table(ledger, workbook, "product-batches")
    facts = [ledger.value(f) for f in recorded.facts]
    by_cell = {parse_anchor(f.anchor).locator.cell: f for f in facts}
    assert {f.field for f in facts} == {"product_role", "dosage_form", "release", "polymorph"}
    assert (by_cell["B2"].value, by_cell["F2"].value, by_cell["F2"].verbatim) == ("TEST", "IR", "immediate release")
    assert by_cell["H3"].value == "Form I" and by_cell["H3"].method == "cell" and by_cell["H3"].relation is None
    product = ledger.entity(by_cell["B2"].entity.product)
    assert product.label == f"{synthetic.DRUG} IR tablet" and ledger.entity(by_cell["B2"].entity.batch).label == "L2301"
    assert set(by_cell["B2"].locators) == {"product", "batch"}
    numbers = [v for v in ledger.values() if v.id.startswith(f"{recorded.extract}#")]
    assert {v.field for v in numbers} == {"strength_mg", "particle_size_d50_um"} and len(numbers) == 4
    # a relation row (test_ledger_relations has the full case)
    grid = grid_from_rows([["Parameter", "Ratio", "Reference arm"], ["AUC_inf", 1.08, "fasted"]], sha=A,
                          caption=("Study 230-30, fed against fasted",))
    row = ExtractedRow(field="relation.test_vs_reference.AUC_inf", labels={"arm": "fed", "other_arm": "fasted"},
                       label_locators={"other_arm": grid.cell(2, 3).locator, "parameter": grid.cell(2, 1).locator},
                       value=1.08, verbatim="1.08", locator=grid.cell(2, 2).locator)
    result = ExtractResult(rows=(row,), cell_use=(), findings=(), constants=(
        ExtractedConstant(field="study_id", value="230-30", verbatim=grid.caption[0].text, locator=grid.caption[0].locator),))
    spec = MappingSpec(kind="pk_parameters", layout="key_value", header_rows=1, first_data_row=2)
    made = ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec), result=result,
                                    context=sheet_context(A))
    assert made.extract is None
    relation = next(ledger.value(f) for f in made.facts if ledger.value(f).relation is not None)
    assert relation.relation.kind == "test_vs_reference" and relation.relation.parameter == "AUC_inf"
    assert ledger.entity(relation.relation.other.arm).label == "fasted" and relation.relation.other.study == relation.entity.study


def test_every_stated_lloq_is_one_fact_per_study_analyte_and_matrix_with_its_unit_and_anchor(ws):
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    for table in ("fasting-individual", "fasting-metabolite", "fed-individual"):
        record_table(ledger, workbook, table)
    lloqs = ledger.values(field="lloq")
    labels = sorted((ledger.entity(v.entity.study).label, ledger.entity(v.entity.analyte).label, v.entity.matrix, v.value,
                     v.unit) for v in lloqs)
    assert labels == [("230-23", synthetic.DRUG, "plasma", 0.5, "ng/mL"), ("230-23", synthetic.METABOLITE, "plasma", 0.2, "ng/mL"),
                      ("231-24", synthetic.DRUG, "plasma", 0.5, "ng/mL")]
    # the "<0.5" token states the footnote's number again: one fact, at the footnote, not at the token
    fasting = next(v for v in lloqs if v.value == 0.5 and ledger.entity(v.entity.study).label == "230-23")
    footnote = next(v.locator for v in workbook.values if v.table == "fasting-individual" and v.field == "lloq")
    assert same_place(parse_anchor(fasting.anchor).locator, parse_locator(footnote)) and fasting.verbatim == "LLOQ = 0.5 ng/mL"
    assert set(fasting.locators) == {"study", "analyte", "matrix"}
    # each value keeps its own LLOQ
    token = next(v for v in ledger.values(field="concentration") if v.verbatim == "<0.5" and v.entity.subject == "003")
    assert (token.censored, token.value, token.lloq, token.lloq_unit) == (True, None, 0.5, "ng/mL")
    assert parse_anchor(token.locators["lloq"]).locator == parse_anchor(token.anchor).locator
    # another LLOQ in the same profile (a token "<1.0"): a second fact, for the checks (ONE_LLOQ_PER_PROFILE)
    grid = grid_from_rows([["Subject", "Conc (ng/mL)"], ["009", "<1.0"]], sha=sha_of(workbook), sheet="Extra",
                          caption=(f"Study 230-23, 50 mg, fasted: {synthetic.DRUG} plasma",),
                          parser="workbook", parser_version=synthetic.TRUTH_PARSER_VERSION)
    cell = grid.cell(2, 2)
    result = ExtractResult(rows=(ExtractedRow(
        field="concentration", labels={"subject": "009", "matrix": "plasma"},
        label_locators={"subject": grid.cell(2, 1).locator, "matrix": grid.caption[0].locator}, value=None, censored=True,
        lloq=1.0, lloq_unit="ng/mL", lloq_locator=cell.locator, verbatim="<1.0", locator=cell.locator, unit="ng/mL"),),
        constants=(ExtractedConstant(field="study_id", value="230-23", verbatim=grid.caption[0].text, locator=grid.caption[0].locator),
                   ExtractedConstant(field="analyte", value=synthetic.DRUG, verbatim=grid.caption[0].text,
                                     locator=grid.caption[0].locator)),
        cell_use=(), findings=())
    ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(synthetic.INDIVIDUAL_SPEC), result=result,
                             context=context(workbook))
    again = [v for v in ledger.values(field="lloq") if ledger.entity(v.entity.study).label == "230-23"
             and v.entity.analyte == fasting.entity.analyte]
    assert sorted(v.value for v in again) == [0.5, 1.0]


def test_a_value_with_no_study_is_kept_and_nothing_is_guessed_from_the_file_name(ws):
    listing = synthetic.delimited()
    ledger = Ledger(ws)
    recorded = record_table(ledger, listing, "delimited-listing", drop=("study_id",))
    values = [v for v in ledger.values() if v.id.startswith(f"{recorded.extract}#")]
    assert len(values) == 8 and all(v.entity.study is None for v in values)
    assert {v.id for v in ledger.values(unassigned=True)} >= {v.id for v in values}
    assert ledger.entities("study") == []                       # "concentrations" (the file's stem) names nothing
    assert all(v.entity.analyte is not None and v.entity.matrix == "plasma" for v in values)


def test_a_table_that_names_a_batch_and_no_product_gives_unassigned_values_and_the_blocker(ws):
    """A dissolution table whose mapping reads the batch from the caption and not the product (D3's rule does so): the
    batch is an entity with no parent, and its values belong to no study, product or the compound. They are on the
    "study not stated" list, the file's coverage counts them, and the scorecard blocks on them (UNASSIGNED_VALUES)
    until a person gives them their product."""
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    recorded = record_table(ledger, workbook, "dissolution-vessels", drop=("product",))
    values = [v for v in ledger.values() if v.id.startswith(f"{recorded.extract}#")]
    (batch,) = ledger.entities("batch")
    assert len(values) == 36 and ledger.entities("product") == [] and (batch.label, batch.parent) == ("L2301", None)
    assert all((v.entity.study, v.entity.product, v.entity.batch) == (None, None, batch.id) for v in values)
    named = [ledger.value(f) for f in recorded.facts]             # the batch's naming fact stands with them
    assert [v.field for v in named] == ["batch"]
    waiting = {v.id for v in (*values, *named)}
    assert {v.id for v in ledger.values(unassigned=True)} == waiting
    assert values_unassigned(ledger, sha_of(workbook)) == len(waiting) == 37
    summary = CoverageSummary(state="read", regions=1, regions_mapped=1, regions_excluded=0, regions_unread=0,
                              numeric_cells=36, cells_used=36, cells_excluded=0, cells_silent=0, silent_loss=0,
                              outside_items=0, values_unassigned=values_unassigned(ledger, sha_of(workbook)))
    card = scorecard(ledger, subject_type="compound", subject="compound", coverage=[summary], requirements=(), gaps=(),
                     checks=())
    assert [b.code for b in card.blockers] == ["UNASSIGNED_VALUES"]
    # a person assigns them their product: they leave the list for the product's card, and the blocker is gone
    product = resolve(ledger, type="product", label=f"{synthetic.DRUG} IR tablet", source=None, file_sha256=None, by="u-1")[0]
    IntakeStore(ws).review.append("assignment", Assignment(
        id="as-1", targets=(recorded.extract, *recorded.facts), product=product.id, batch=batch.id, why="the CoA names it",
        by="u-1", at="2026-11-13T10:00:00.000Z").model_dump(mode="json"))
    ledger.refresh()
    assert ledger.values(unassigned=True) == [] and values_unassigned(ledger, sha_of(workbook)) == 0
    assert {v.id for v in ledger.values(product=product.id)} == waiting


# --- a person's entry and an exclusion -----------------------------------------------------------------------------


def test_enter_supersedes_a_value_keeps_it_readable_and_keeps_the_point_in_its_series(ws):
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    recorded = record_table(ledger, workbook, "dissolution-summary")
    point = next(v for v in ledger.values() if v.id.startswith(recorded.extract) and v.time == 30)
    assert _intake_events(ws) == []
    fact = ledger.enter(value=71.5, why="the report's corrected table", by="u-1", supersedes=point.id)
    assert ID_PATTERNS["line"].fullmatch(fact.id) and fact.method == "person" and fact.anchor is None
    assert (fact.field, fact.time, fact.time_unit, fact.statistic, fact.unit, fact.conditions) == (
        point.field, point.time, point.time_unit, point.statistic, point.unit, point.conditions)
    assert fact.entity == point.entity and fact.supersedes == point.id and fact.reason == "the report's corrected table"
    old = ledger.value(point.id)
    assert old is not None and old.value == point.value                    # readable, as it was
    assert (old.status, old.superseded_by) == ("superseded", fact.id)
    new = ledger.value(fact.id)
    assert (new.status, new.level, new.value) == ("proposed", "person_confirmed", 71.5)
    series = sorted(v.time for v in ledger.values(field="percent_dissolved") if v.conditions == point.conditions
                    and v.statistic == "arithmetic_mean")
    assert series == [5, 10, 15, 30, 45, 60]                            # the corrected point is still in its series
    (event,) = _intake_events(ws)
    entry = IntakeStore(ws).facts.entries()[-1]
    assert (event.action, event.after, event.reason, event.actor) == (
        "intake.entry", {"fact": fact.id, "row_hash": entry.hash}, "the report's corrected table", "u-1")
    with pytest.raises(ValueError):
        ledger.enter(value=1.0, why=" ", by="u-1", supersedes=fact.id)
    with pytest.raises(ValueError):
        ledger.enter(value=1.0, why="again", by="u-1", supersedes=point.id)      # superseded already
    with pytest.raises(ValueError):
        ledger.enter(field="not_a_field", value=1.0, why="x", by="u-1")
    with pytest.raises(KeyError):
        ledger.enter(value=1.0, why="x", by="u-1", supersedes="f-999")
    with pytest.raises(AnchorError):
        ledger.enter(value=1.0, why="x", by="u-1", supersedes="../f-1")
    loose = ledger.enter(field="dose", value=20.0, unit="mg", why="stated by phone", by="u-1")
    assert ledger.value(loose.id).entity.study is None and ledger.value(loose.id).delivery == ""


def test_exclude_needs_a_reason_and_names_an_existing_target(ws):
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    recorded = record_table(ledger, workbook, "urine-excretion")
    target = f"{recorded.extract}#1"
    with pytest.raises(ValueError):
        ledger.exclude(target, why="", by="u")
    with pytest.raises(KeyError):
        ledger.exclude(f"{recorded.extract}#99", why="none", by="u")
    with pytest.raises(AnchorError):
        ledger.exclude("tx-../../x", why="none", by="u")
    change = ledger.exclude(target, why="a re-assay", by="u")
    assert (change.target, change.status, change.reason) == (target, "excluded", "a re-assay")
    assert (ledger.value(target).status, ledger.value(target).status_reason) == ("excluded", "a re-assay")
    heads = _heads(ws)
    assert ledger.exclude(target, why="a re-assay", by="u") == change and _heads(ws) == heads     # once
    whole = ledger.exclude(recorded.extract, why="the urine sheet is a draft", by="u")
    assert whole.target == recorded.extract
    assert all(v.status == "excluded" for v in ledger.values(active=False) if v.id.startswith(recorded.extract))
    fact = recorded.facts[0]
    ledger.exclude(fact, why="named twice", by="u")
    assert ledger.value(fact).status == "excluded"
    assert _intake_events(ws) == []                             # the decision that excludes is audited by its owner


# --- chains, audit, concurrency ------------------------------------------------------------------------------------


def test_the_chains_verify_no_audit_event_is_written_per_fact_and_a_tampered_line_is_found(ws):
    ledger = Ledger(ws)
    for file in synthetic.delivery():
        record_file(ledger, file)
    ledger.derive()
    ledger.link_files()
    store = IntakeStore(ws)
    assert store.facts.verify() == [] and store.entities.verify() == []
    assert len(ledger.values()) > 200 and _intake_events(ws) == []        # no event per fact, extract or entity
    ledger.enter(field="n", value=24, why="the protocol", by="u", entity=ledger.values(field="n")[0].entity)
    assert [e.action for e in _intake_events(ws)] == ["intake.entry"]
    lines = store.facts.path.read_text(encoding="utf-8").splitlines()
    store.facts.path.write_text("\n".join([lines[0].replace('"code"', '"someone"', 1), *lines[1:]]) + "\n", encoding="utf-8")
    assert [p.problem for p in store.facts.verify()] == ["hash"]


def test_two_threads_recording_one_table_write_it_once(ws):
    workbook = synthetic.messy_workbook()
    barrier = threading.Barrier(2)
    out: list = []

    def run() -> None:
        barrier.wait()
        out.append(record_table(Ledger(ws), workbook, "fed-individual", approved=False))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(out) == 2 and out[0].extract == out[1].extract and set(out[0].facts) == set(out[1].facts)
    store = IntakeStore(ws)
    assert len(store.facts.entries("extract")) == 1 and len(store.entities.entries("entity")) == 2   # the study, the drug
    assert len(store.facts.entries("fact")) == len(out[0].facts)


# --- the shared truth convention -----------------------------------------------------------------------------------


def _labels(view: LedgerView, value) -> dict:
    out = {p: (view.entity(getattr(value.entity, p)).label if getattr(value.entity, p) else None)
           for p in ("study", "arm", "product", "batch", "analyte")}
    out.update({p: getattr(value.entity, p) for p in ("subject", "period", "sequence", "occasion", "vessel", "matrix")})
    return out


_COMPARED = ("value", "unit", "verbatim", "statistic", "spread", "spread_kind", "n_at", "time", "time_unit", "time_actual",
             "censored", "lloq", "lloq_unit", "uloq", "conditions", "method", "level", "locators", "status", "interval",
             "table_kind")


def _against_the_truth(ws: Workspace, files: tuple, project: str) -> tuple[Ledger, LedgerView, list]:
    """Record the files through the ledger and write their truth with `write_truth` into another project: every truth
    value must be in the ledger, read the same. Returns the ledger, the truth's view and what the ledger holds besides."""
    ledger = Ledger(ws)
    for file in files:
        record_file(ledger, file)
    truth_ws = Workspace(ws.store, "t1", project)
    ids = write_truth(truth_ws, files)
    truth = LedgerView(truth_ws)
    by_place = {(v.field, v.anchor): v for v in ledger.values()}
    assert len(by_place) == len(ledger.values())
    for file in files:
        for item in file.values:
            expected = truth.value(ids[truth_key(file, item)])
            got = by_place[(expected.field, expected.anchor)]
            assert {k: getattr(got, k) for k in _COMPARED} == {k: getattr(expected, k) for k in _COMPARED}, item
            assert _labels(ledger, got) == _labels(truth, expected), item
            assert (got.cross_file is None) == (expected.cross_file is None), item
    assert sorted((e.type, e.label) for e in ledger.entities()) == sorted((e.type, e.label) for e in truth.entities())
    known = {(v.field, v.anchor) for v in truth.values()}
    return ledger, truth, [v for v in ledger.values() if (v.field, v.anchor) not in known]


def test_the_writes_follow_the_shared_truth_convention(ws):
    """D0, D5, W and D6 test against `intake_fixtures.write_truth`; the ledger's own writes, from what the executor
    gives for the same delivery, must be the same values: the same anchors, fields, numbers, units, labels, locators,
    qualifiers, levels and cross-file links."""
    files = synthetic.delivery()
    ledger, truth, extra = _against_the_truth(ws, files, "truth")
    assert extra == [] and len(ledger.values()) == len(truth.values())
    links = sorted((v.anchor, v.value, v.method) for v in ledger.values() if v.field.startswith("link."))
    assert links == sorted((v.anchor, v.value, v.method) for v in truth.values() if v.field.startswith("link."))
    assert len(links) == 1 and parse_anchor(links[0][0]).file_sha256 == hashlib.sha256(files[1].data).hexdigest()
    # a locator outside the region and its context is a bug in the caller, never written
    workbook = files[0]
    grid = truth_grid(workbook, "summary-parameters")
    bad = result_of(workbook, "summary-parameters").model_copy(update={"constants": (ExtractedConstant(
        field="study_id", value="230-23", verbatim="x", locator="s:'Summary'!Z99"),)})
    with pytest.raises(ValueError):
        ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(workbook.tables[0].spec),
                                 result=bad, context=context(workbook))
    with pytest.raises(ValueError):                              # a grid of another file than the context's
        ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(workbook.tables[0].spec),
                                 result=result_of(workbook, "summary-parameters"), context=context(files[3]))


def test_a_filled_template_follows_the_convention_and_its_token_lloq_is_a_fact(ws):
    """The template's record tables (Studies, Product), its long tables with actual times and BLQ flags, its
    dissolution conditions and urine intervals: the same values as the truth. The "<0.5" written in the individual
    listing states an LLOQ, written once as an `lloq` fact (contracts §6.3): by the ledger and by the truth alike."""
    template = synthetic.template_workbook()
    ledger, truth, extra = _against_the_truth(ws, (template,), "truth-template")
    assert extra == [] and len(ledger.values()) == len(truth.values())
    (token,) = [v for v in ledger.values(field="lloq") if v.verbatim == "<0.5"]
    assert (token.field, token.value, token.unit, token.verbatim) == ("lloq", 0.5, "ng/ml", "<0.5")   # the unit as written
    assert parse_anchor(token.anchor).locator.sheet == "PK_Individual"
    assert ledger.entity(token.entity.study).label == "EXA-101"
    (stated,) = [v for v in truth.values(field="lloq") if v.anchor == token.anchor]
    assert {k: getattr(stated, k) for k in _COMPARED} == {k: getattr(token, k) for k in _COMPARED}
    assert _labels(truth, stated) == _labels(ledger, token)


def _held(view: LedgerView) -> dict:
    """What a ledger holds, by (field, anchor): each value as a reviewer would compare it."""
    out = {}
    for value in view.values():
        key = (value.field, value.anchor)
        assert key not in out, key
        out[key] = {**{k: getattr(value, k) for k in _COMPARED}, "entity": _labels(view, value),
                    "cross_file": value.cross_file is not None}
    return out


def test_the_truth_ledger_holds_what_the_executor_and_the_ledger_write_the_lloq_facts_included(ws):
    """D0, D5, W and D6 build their tests on `write_truth`; the pipeline's ledger is what D3's executor reads from a
    table and `record_extraction` writes. Over every truth table of the delivery and the filled template the two hold
    the same values, both ways: the same field at the same anchor with the same value, unit, text, entity, locators
    and qualifiers. That includes §6.3's `lloq` facts, which the truth writes by its own rule: one per stated LLOQ per
    (study, analyte, matrix), a "<0.5" token's too, with its column's unit and the unit cell among its locators."""
    from modeler_intake.mapping.execute import execute

    files = (*synthetic.delivery(), synthetic.template_workbook())
    ledger = Ledger(ws)
    for file in files:
        for table in file.tables:
            if table.spec.kind == "not_data":
                continue
            grid = truth_grid(file, table.id)
            entry = mapping_entry(table.spec, first_seen=(sha_of(file), grid.region_id))
            approve(ws, entry)
            ledger.record_extraction(region=region_of(grid, table.kind, table.where), grid=grid, mapping=entry,
                                     result=execute(entry.spec, grid), context=context(file))
        if prose_of(file):
            ledger.record_prose(facts=prose_of(file), model=TRUTH_MODEL, context=context(file))
    truth_ws = Workspace(ws.store, "t1", "truth-all")
    ids = write_truth(truth_ws, files)
    truth = LedgerView(truth_ws)
    written, expected = _held(ledger), _held(truth)
    assert sorted(written, key=str) == sorted(expected, key=str)          # the same values, neither holds one more
    for key in expected:
        assert written[key] == expected[key], key
    assert len(ledger.values()) == len(truth.values()) == len(expected)
    # every stated LLOQ once per (study, analyte, matrix): the lines the delivery's tables state, and the template's
    # token, which no line states (so the truth holds one value more than its TruthValues)
    lloqs = {key: value for key, value in expected.items() if key[0] == "lloq" and value["table_kind"] is None}
    assert sorted((v["entity"]["study"], v["entity"]["analyte"], v["entity"]["matrix"], v["value"], v["unit"], v["verbatim"])
                  for v in lloqs.values()) == sorted([
        ("230-23", synthetic.DRUG, "plasma", 0.5, "ng/mL", "LLOQ = 0.5 ng/mL"),
        ("230-23", synthetic.METABOLITE, "plasma", 0.2, "ng/mL", "LLOQ = 0.2 ng/mL"),
        ("231-24", synthetic.DRUG, "plasma", 0.5, "ng/mL", "LLOQ = 0.5 ng/mL"),
        ("230-25", synthetic.DRUG, "plasma", 0.5, "ng/mL", lloqs[next(k for k in lloqs if "p:3" in k[1])]["verbatim"]),
        ("EXA-101", None, None, 0.5, "ng/ml", "<0.5")], key=str)
    (token,) = [key for key, value in lloqs.items() if value["verbatim"] == "<0.5"]
    assert set(expected[token]["locators"]) == {"study", "unit"} and parse_anchor(token[1]).locator.sheet == "PK_Individual"
    # besides its TruthValues the truth writes that fact and the synopsis PDF's link to the workbook's study
    assert len(ids) == sum(len(f.values) for f in files)
    beside = [v for v in truth.values() if v.id not in set(ids.values())]
    assert sorted((v.field, v.verbatim) for v in beside) == [("link.study_id", "230-23"), ("lloq", "<0.5")]


# --- identity across tables and mapping versions --------------------------------------------------------------------

LINE = "Study 230-60, 50 mg"


def _between(ledger: Ledger, *, a_version: int = 1, a_dose: float | None = 50.0, b_dose: float | None = 50.0,
             a_rows: bool = True) -> tuple:
    """Two tables of one sheet with a line between them that both cite (A's line below, B's line above): each reads
    the study and, when given, a dose from it."""
    from dataclasses import replace

    upper = grid_from_rows([["Time (h)", "Conc (ng/mL)"], [1, 4.2]], sha=A, region_id="rg-00000000a1", below=((LINE,),))
    lower = replace(grid_from_rows([["Subject", "Conc (ng/mL)"], ["001", 3.9]], sha=A, region_id="rg-00000000b1",
                                   first_cell="A4"), above=upper.below)
    line = upper.below[0][0]
    out = []
    for grid, spec, dose, version, rows in (
            (upper, MappingSpec(kind="pk_summary", layout="long", header_rows=1, first_data_row=2), a_dose, a_version, a_rows),
            (lower, MappingSpec(kind="pk_individual", layout="long", header_rows=1, first_data_row=2), b_dose, 1, True)):
        constants = [ExtractedConstant(field="study_id", value="230-60", verbatim=LINE, locator=line.locator)]
        if dose is not None:
            constants.append(ExtractedConstant(field="dose", value=dose, unit="mg", verbatim=LINE, locator=line.locator))
        value, label = grid.cell(2, 2), grid.cell(2, 1)
        by_subject = spec.kind == "pk_individual"
        row = ExtractedRow(field="concentration", labels={"subject": label.text} if by_subject else {},
                           label_locators={"subject": label.locator} if by_subject else {}, time=1.0, time_unit="h",
                           value=float(value.value), verbatim=value.text, locator=value.locator, unit="ng/mL",
                           unit_locator=grid.cell(1, 2).locator, statistic="individual" if by_subject else "arithmetic_mean")
        result = ExtractResult(rows=(row,) if rows else (), constants=tuple(constants), cell_use=(), findings=())
        out.append(ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec, version=version),
                                            result=result, context=sheet_context(A)))
    return tuple(out)


def test_two_tables_that_cite_one_line_read_it_once_and_a_rerun_adds_nothing(ws):
    ledger = Ledger(ws)
    upper, lower = _between(ledger)
    (study,) = ledger.values(field="study_id")
    (dose,) = ledger.values(field="dose")
    assert {study.id, dose.id} <= set(upper.facts) and {study.id, dose.id} <= set(lower.facts)   # the lower one's too
    assert dose.mapping == ledger.value(upper.extract + "#0").mapping
    heads = _heads(ws)
    for _ in range(2):
        assert _between(ledger) == (upper, lower)
    assert _heads(ws) == heads
    # the lower table's mapping reads another dose from the line: its own fact, beside the upper one's, a conflict
    _between(ledger, b_dose=60.0)
    doses = sorted((v.value, v.mapping.mapping_id) for v in ledger.values(field="dose"))
    assert [d for d, _m in doses] == [50.0, 60.0] and doses[0][1] != doses[1][1]
    (conflict,) = ledger.conflicts()
    assert conflict.field == "dose" and conflict.kind == "value"
    heads = _heads(ws)
    _between(ledger, b_dose=60.0)
    assert _heads(ws) == heads


def test_a_mapping_version_that_no_longer_reads_a_value_sets_the_earlier_reading_aside(ws):
    ledger = Ledger(ws)
    first, _lower = _between(ledger, b_dose=None)
    (dose,) = ledger.values(field="dose")
    assert dose.id in first.facts
    # version 2 of the upper table's mapping no longer reads the dose (the line states the lower table's): set aside
    second, _lower = _between(ledger, a_version=2, a_dose=None, b_dose=None)
    old = ledger.value(dose.id)
    assert old.status == "excluded" and old.status_reason.startswith(NOT_READ_AGAIN) and "v2" in old.status_reason
    assert dose.id in second.superseded and ledger.values(field="dose") == []
    assert old.value == 50.0                                                  # still readable
    # version 3 reads no value at all: the extract of version 2 is set aside too
    third, _lower = _between(ledger, a_version=3, a_dose=None, b_dose=None, a_rows=False)
    assert third.extract is None and second.extract in third.superseded
    assert ledger.value(f"{second.extract}#0").status == "excluded"
    assert [v.value for v in ledger.values(field="concentration")] == [3.9]   # the lower table's only
    # back to version 1: its reading is the active one again, the same ids, and a re-run adds nothing
    again, _lower = _between(ledger, b_dose=None)
    assert again.extract == first.extract and ledger.value(dose.id).status == "proposed"
    assert sorted(v.value for v in ledger.values(field="concentration")) == [3.9, 4.2]
    heads = _heads(ws)
    _between(ledger, b_dose=None)
    assert _heads(ws) == heads
    # a person's exclusion is never undone by a recording
    ledger.exclude(dose.id, why="the line is the protocol's planned dose", by="u-1")
    _between(ledger, b_dose=None)
    assert ledger.value(dose.id).status == "excluded" and _heads(ws)[0].seq == heads[0].seq + 1
    assert ledger.store.facts.verify() == []


def test_a_region_gone_after_a_reparse_is_active_again_when_a_later_parse_finds_it(ws):
    ledger = Ledger(ws)
    rows, spec = _small()
    entry = mapping_entry(spec)

    def record(version: str):
        grid = grid_from_rows(rows, sha=A, caption=("Study 230-29, 25 mg",), parser_version=version)
        return ledger.record_extraction(region=region_of(grid), grid=grid, mapping=entry, result=_small_result(grid),
                                        context=sheet_context(A, parser_version=version))

    first = record("1.0")
    (retired,) = ledger.retire_regions(file_sha256=A, parser_version="1.1", regions=[])
    assert retired.target == first.extract and ledger.values(field="concentration") == []
    back = record("1.2")                                     # a later parser finds the region again, the same cells
    assert back.extract == first.extract and back.superseded == ()
    values = ledger.values(field="concentration")
    assert len(values) == 3 and all(v.status == "proposed" for v in values)
    heads = _heads(ws)
    assert record("1.2").extract == first.extract and _heads(ws) == heads
    assert ledger.retire_regions(file_sha256=A, parser_version="1.3", regions=["rg-0000000001"]) == []   # it is there


def test_a_prose_fact_with_no_study_label_takes_the_files_study_only_when_it_names_exactly_one(ws):
    pdf = synthetic.pdf_report(unruled_table=False)
    ledger = Ledger(ws)
    record_table(ledger, pdf, "report-table6")                # the file names one study: 230-26
    (study,) = ledger.entities("study")
    sentence = pdf.prose[3]
    span = "p:1/w:29-29@151.00,132.00,161.00,142.00"

    def state(value: float, delivery: str) -> object:
        made = ledger.record_prose(facts=[ProseFact(field="n", value=value, quote=sentence, locator=span)],
                                   model=TRUTH_MODEL, context=context(pdf, delivery=delivery))
        (found,) = [ledger.value(f) for f in made.facts]
        return found

    taken = state(24.0, "dl-1")
    assert taken.entity.study == study.id and taken.cross_file is None and taken.method == "prose"
    record_table(ledger, pdf, "report-table5")                # now 230-25 as well: two studies, none is taken
    span = "p:1/w:30-30@162.00,132.00,170.00,142.00"
    loose = state(24.0, "dl-2")
    assert loose.entity.study is None and loose.id in {v.id for v in ledger.values(unassigned=True)}


def test_two_people_correcting_one_value_at_once_give_one_correction(ws):
    workbook = synthetic.messy_workbook()
    ledger = Ledger(ws)
    recorded = record_table(ledger, workbook, "dissolution-summary")
    target = f"{recorded.extract}#3"
    barrier = threading.Barrier(2)
    made: list = []
    refused: list = []

    def run(value: float) -> None:
        barrier.wait()
        try:
            made.append(Ledger(ws).enter(value=value, why="the corrected table", by="u-1", supersedes=target))
        except ValueError as exc:
            refused.append(exc)

    threads = [threading.Thread(target=run, args=(v,)) for v in (70.0, 71.0)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(made) == 1 and len(refused) == 1
    assert ledger.value(target).superseded_by == made[0].id and len(_intake_events(ws)) == 1


def test_two_tables_of_one_layout_never_set_each_others_note_aside(ws):
    """Two stacked tables of one layout (one mapping) each read a dose from the note below them; the upper note is also
    a line above the lower table. Neither recording sets the other's reading aside, so a re-run adds nothing; a version
    of the mapping that reads no note sets both aside."""
    from dataclasses import replace

    ledger = Ledger(ws)
    spec = MappingSpec(kind="pk_individual", layout="long", header_rows=1, first_data_row=2)

    def record(version: int = 1, dose: bool = True) -> list:
        upper = grid_from_rows([["Subject", "Conc (ng/mL)"], ["001", 4.2]], sha=A, region_id="rg-00000000c1",
                               below=(("Cohort 1: 10 mg",),))
        lower = replace(grid_from_rows([["Subject", "Conc (ng/mL)"], ["002", 3.9]], sha=A, region_id="rg-00000000c2",
                                       first_cell="A4", below=(("Cohort 2: 30 mg",),)), above=upper.below)
        out = []
        for grid, amount in ((upper, 10.0), (lower, 30.0)):
            note = grid.below[0][0]
            value, subject = grid.cell(2, 2), grid.cell(2, 1)
            row = ExtractedRow(field="concentration", labels={"subject": subject.text},
                               label_locators={"subject": subject.locator}, time=1.0, time_unit="h",
                               value=float(value.value), verbatim=value.text, locator=value.locator, unit="ng/mL",
                               statistic="individual")
            constants = (ExtractedConstant(field="dose", value=amount, unit="mg", verbatim=note.text, locator=note.locator),)
            result = ExtractResult(rows=(row,), constants=constants if dose else (), cell_use=(), findings=())
            out.append(ledger.record_extraction(region=region_of(grid), grid=grid,
                                                mapping=mapping_entry(spec, version=version), result=result,
                                                context=sheet_context(A)))
        return out

    first = record()
    assert sorted(v.value for v in ledger.values(field="dose")) == [10.0, 30.0]
    heads = _heads(ws)
    assert record() == first and _heads(ws) == heads
    second = record(version=2, dose=False)
    assert ledger.values(field="dose") == [] and all(s.superseded for s in second)
    heads = _heads(ws)
    record(version=2, dose=False)
    assert _heads(ws) == heads


# --- what a recording guards ------------------------------------------------------------------------------------------


def test_a_prose_label_without_its_own_span_or_a_number_its_quote_does_not_write_is_refused(ws):
    """The strict prose check returns a label's span and the number it parsed; the ledger checks both again before it
    writes: a study label anchored at the value's span would join files on the number's anchor. Nothing is written."""
    pdf = synthetic.pdf_report(unruled_table=False)
    ledger = Ledger(ws)
    record_table(ledger, synthetic.messy_workbook(), "fasting-individual")      # 230-23 in another file
    heads = _heads(ws)
    (dose,) = [f for f in prose_of(pdf) if f.field == "dose"]
    assert dose.study_label and dose.study_locator
    for bad in (dose.model_copy(update={"study_locator": None}), dose.model_copy(update={"arm_label": "Cohort 1"}),
                dose.model_copy(update={"value": 999.0})):
        with pytest.raises(ValueError):
            ledger.record_prose(facts=[bad], model=TRUTH_MODEL, context=context(pdf))
    assert _heads(ws) == heads and ledger.values(file_sha256=sha_of(pdf)) == []
    made = ledger.record_prose(facts=[dose], model=TRUTH_MODEL, context=context(pdf))
    assert {ledger.value(f).field for f in made.facts} == {"dose", "link.study_id"}


def test_an_lloq_stated_as_text_and_a_relation_row_stated_as_text_are_kept(ws):
    """Nothing a table states is dropped: an LLOQ constant whose value is text is an `lloq` fact as written (for the
    checks), and a relation row that states text instead of a ratio keeps the text."""
    ledger = Ledger(ws)
    grid = grid_from_rows([["Parameter", "Ratio", "Reference arm"], ["AUC_inf", "NE", "fasted"]], sha=A,
                          caption=("Study EXA-101; LLOQ 0.5 ng/mL",))
    caption = grid.caption[0]
    row = ExtractedRow(field="relation.test_vs_reference.AUC_inf", labels={"arm": "fed", "other_arm": "fasted"},
                       label_locators={"other_arm": grid.cell(2, 3).locator, "parameter": grid.cell(2, 1).locator},
                       text_value="NE", verbatim="NE", locator=grid.cell(2, 2).locator)
    result = ExtractResult(rows=(row,), cell_use=(), findings=(), constants=(
        ExtractedConstant(field="study_id", value="EXA-101", verbatim=caption.text, locator=caption.locator),
        ExtractedConstant(field="lloq", value="0.5 ng/mL", verbatim=caption.text, locator=caption.locator)))
    spec = MappingSpec(kind="pk_parameters", layout="key_value", header_rows=1, first_data_row=2)
    made = ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec), result=result,
                                    context=sheet_context(A))
    facts = {ledger.value(f).field: ledger.value(f) for f in made.facts}
    assert (facts["lloq"].value, facts["lloq"].verbatim) == ("0.5 ng/mL", caption.text)
    relation = facts["relation.test_vs_reference.AUC_inf"]
    assert relation.value == "NE" and relation.relation is not None and relation.relation.parameter == "AUC_inf"


def test_an_lloq_facts_unit_is_the_one_its_own_text_states(ws):
    """A line "LLOQ = 0.5" that states no unit gives an `lloq` fact with no unit (the value column's unit is not its
    own), and a token "<0.5" that repeats it is that fact. A token alone takes its column's unit, the unit cell among
    its locators."""
    ledger = Ledger(ws)
    grid = grid_from_rows([["Subject", "Conc (ng/mL)"], ["001", "BLQ"], ["002", "<0.5"]], sha=A,
                          caption=("Study 230-61: Exampleamide plasma",), below=(("LLOQ = 0.5",),))
    caption, line, header = grid.caption[0], grid.below[0][0], grid.cell(1, 2)

    def row(r: int, lloq_at: str) -> ExtractedRow:
        return ExtractedRow(field="concentration", labels={"subject": grid.cell(r, 1).text, "matrix": "plasma"},
                            label_locators={"subject": grid.cell(r, 1).locator, "matrix": caption.locator}, time=1.0,
                            time_unit="h", value=None, censored=True, lloq=0.5, lloq_locator=lloq_at,
                            verbatim=grid.cell(r, 2).text, locator=grid.cell(r, 2).locator, unit="ng/mL",
                            unit_locator=header.locator, statistic="individual")

    constants = (ExtractedConstant(field="study_id", value="230-61", verbatim=caption.text, locator=caption.locator),
                 ExtractedConstant(field="analyte", value=synthetic.DRUG, verbatim=caption.text, locator=caption.locator))
    spec = MappingSpec(kind="pk_individual", layout="long", header_rows=1, first_data_row=2)
    result = ExtractResult(rows=(row(2, line.locator), row(3, grid.cell(3, 2).locator)), constants=constants,
                           cell_use=(), findings=())
    ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec), result=result,
                             context=sheet_context(A))
    (stated,) = ledger.values(field="lloq")
    assert (stated.value, stated.unit, stated.verbatim) == (0.5, None, "LLOQ = 0.5") and "unit" not in stated.locators
    # a table whose only LLOQ is a token
    other = grid_from_rows([["Subject", "Conc (ng/mL)"], ["003", "<0.2"]], sha=A, sheet="U", region_id="rg-0000000002",
                           caption=("Study 230-62: Exampleamide plasma",))
    cap, cell = other.caption[0], other.cell(2, 2)
    token = ExtractedRow(field="concentration", labels={"subject": "003", "matrix": "plasma"},
                         label_locators={"subject": other.cell(2, 1).locator, "matrix": cap.locator}, time=1.0,
                         time_unit="h", value=None, censored=True, lloq=0.2, lloq_locator=cell.locator, verbatim="<0.2",
                         locator=cell.locator, unit="ng/mL", unit_locator=other.cell(1, 2).locator, statistic="individual")
    ledger.record_extraction(region=region_of(other), grid=other, mapping=mapping_entry(spec), context=sheet_context(A),
                             result=ExtractResult(rows=(token,), cell_use=(), findings=(), constants=(
                                 ExtractedConstant(field="study_id", value="230-62", verbatim=cap.text, locator=cap.locator),
                                 ExtractedConstant(field="analyte", value=synthetic.DRUG, verbatim=cap.text,
                                                   locator=cap.locator))))
    (alone,) = [v for v in ledger.values(field="lloq") if v.value == 0.2]
    assert alone.unit == "ng/mL" and parse_anchor(alone.locators["unit"]).locator == parse_locator(other.cell(1, 2).locator)


def test_one_line_a_mapping_reads_for_two_arms_is_two_readings_and_a_rerun_adds_nothing(ws):
    """Two stacked tables of one layout (one mapping) both read the dose from the line between them, one for arm A and
    one for arm B: two facts side by side, neither superseding the other, and recording both again writes nothing."""
    from dataclasses import replace

    ledger = Ledger(ws)
    spec = MappingSpec(kind="pk_summary", layout="long", header_rows=1, first_data_row=2)
    entry = mapping_entry(spec)
    upper = grid_from_rows([["Arm", "Conc (ng/mL)"], ["A", 4.2]], sha=A, region_id="rg-00000000d1",
                           below=(("Study 230-63, dose 50 mg",),))
    lower = replace(grid_from_rows([["Arm", "Conc (ng/mL)"], ["B", 3.9]], sha=A, region_id="rg-00000000d2",
                                   first_cell="A4"), above=upper.below)
    line = upper.below[0][0]

    def record() -> None:
        for grid in (upper, lower):
            arm, value = grid.cell(2, 1), grid.cell(2, 2)
            row = ExtractedRow(field="concentration", labels={"arm": arm.text}, label_locators={"arm": arm.locator},
                               time=1.0, time_unit="h", value=float(value.value), verbatim=value.text,
                               locator=value.locator, unit="ng/mL", statistic="arithmetic_mean")
            constants = (ExtractedConstant(field="study_id", value="230-63", verbatim=line.text, locator=line.locator),
                         ExtractedConstant(field="dose", value=50.0, unit="mg", verbatim=line.text, locator=line.locator))
            ledger.record_extraction(region=region_of(grid), grid=grid, mapping=entry, context=sheet_context(A),
                                     result=ExtractResult(rows=(row,), constants=constants, cell_use=(), findings=()))

    record()
    doses = ledger.values(field="dose")
    assert sorted(ledger.entity(v.entity.arm).label for v in doses) == ["A", "B"]
    heads = _heads(ws)
    for _ in range(2):
        record()
    assert _heads(ws) == heads and ledger.values(field="dose") == doses
