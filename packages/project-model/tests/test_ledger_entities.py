"""Entity resolution (contracts §6.3, §8.6): the same name written three ways is one entity; an alias a person
confirmed in today's review record is reused (and kept in the ledger); two similar but different names stay two; an
arm resolves inside its study and a batch inside its product; matrix, sequence and occasion are labels; a merge keeps
both ids resolvable; two threads resolving one label create one entity. Never by similarity."""

from __future__ import annotations

import threading

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import anchor_text
from modeler_intake.document_reading import name_key
from modeler_intake.mapping_spec import ExtractedConstant, ExtractedRow, ExtractResult, MappingSpec
from modeler_project.client_data import update_review
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import Ledger
from modeler_project.ledger_entities import home_file, merge, resolve
from modeler_project.ledger_view import LedgerView
from modeler_project.workspace import Workspace

from .test_ledger_support import grid_from_rows, make_ws, mapping_entry, record_table, region_of, sheet_context

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")

A, B = "a" * 64, "b" * 64


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return make_ws(tmp_path)


def _at(sha: str, cell: str = "A1", sheet: str = "T") -> str:
    return anchor_text(sha, "workbook", "1.0", f"s:'{sheet}'!{cell}")


def _resolve(ledger: Ledger, type: str, label: str, sha: str = A, cell: str = "A1", parent: str | None = None):
    return resolve(ledger, type=type, label=label, parent=parent, source=_at(sha, cell), file_sha256=sha, by="code",
                   delivery="dl-1")


def _entities(ws: Workspace) -> list:
    return IntakeStore(ws).entities.entries("entity")


def test_the_same_name_written_three_ways_is_one_entity(ws):
    ledger = Ledger(ws)
    found = [_resolve(ledger, "study", label, cell=f"A{i}") for i, label in enumerate(("230-23", "230 23", "230_23"), 1)]
    assert len({entity.id for entity, _link in found}) == 1 and all(link is None for _e, link in found)
    (line,) = _entities(ws)
    assert line.body["label"] == "230-23" and line.body["key"] == name_key("230-23") == "23023"
    assert home_file(ledger.entity(found[0][0].id)) == A                       # its source is the first label's cell
    # in a table: a study column that writes it three ways gives every row one study
    grid = grid_from_rows([["Study", "Dose (mg)"], ["230-23", 50], ["230 23", 50]], sha=B)
    rows = tuple(ExtractedRow(field="dose", labels={"study": grid.cell(r, 1).text},
                              label_locators={"study": grid.cell(r, 1).locator}, value=50.0, verbatim="50",
                              locator=grid.cell(r, 2).locator, unit="mg", unit_locator=grid.cell(1, 2).locator)
                 for r in (2, 3))
    result = ExtractResult(rows=rows, constants=(), cell_use=(), findings=())
    spec = MappingSpec(kind="study_design", layout="long", header_rows=1, first_data_row=2)
    recorded = ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec), result=result,
                                        context=sheet_context(B))
    studies = {v.entity.study for v in ledger.values() if v.id.startswith(f"{recorded.extract}#")}
    assert studies == {found[0][0].id}                       # B's label names A's study: one study, joined by a link
    assert len(_entities(ws)) == 1


def test_an_alias_a_person_confirmed_in_todays_review_record_is_reused(ws):
    ledger = Ledger(ws)
    study, _ = _resolve(ledger, "study", "230-23")
    product, _ = _resolve(ledger, "product", f"{synthetic.DRUG} IR tablet", cell="B1")
    batch, _ = _resolve(ledger, "batch", "L2301", cell="C1", parent=product.id)

    def aliases(record: dict) -> tuple[dict, str]:
        return {**record, "aliases": {"EXA/230-23 (EU)": "230-23"},
                "product_aliases": {"Exampleamide 50 mg film-coated tablet": f"{synthetic.DRUG} IR tablet"},
                "batch_aliases": {f"{product.key}|L-2301/A": "L2301"}}, "linked by a person on Inputs"

    update_review(ws, aliases, by="u-1")
    assert _resolve(ledger, "study", "EXA/230-23 (EU)", cell="A9")[0].id == study.id
    assert _resolve(ledger, "product", "Exampleamide 50 mg film-coated tablet", cell="B9")[0].id == product.id
    assert _resolve(ledger, "batch", "L-2301/A", cell="C9", parent=product.id)[0].id == batch.id
    assert len(_entities(ws)) == 3
    written = {(a.body["type"], a.body["entity"], a.body["source"]) for a in IntakeStore(ws).entities.entries("alias")}
    assert written == {("study", study.id, "review:aliases"), ("product", product.id, "review:product_aliases"),
                       ("batch", batch.id, "review:batch_aliases")}
    # the ledger keeps the alias it used: it holds after the review record changes
    update_review(ws, lambda record: ({**record, "aliases": {}}, "reopened"), by="u-1")
    assert _resolve(ledger, "study", "EXA/230-23 (EU)", cell="A10")[0].id == study.id
    # a batch alias holds within its product only
    other, _ = _resolve(ledger, "product", "Comparamide tablet", cell="D1")
    assert _resolve(ledger, "batch", "L-2301/A", cell="D2", parent=other.id)[0].id != batch.id
    # another file's label through the alias: that file's study, joined by a link fact at its label
    joined, link = _resolve(ledger, "study", "EXA/230-23 (EU)", sha=B)
    assert joined.id == study.id and link is not None and link.anchor == _at(B) and link.field == "link.study_id"


def test_two_similar_but_different_names_stay_two(ws):
    ledger = Ledger(ws)
    assert _resolve(ledger, "study", "230-23")[0].id != _resolve(ledger, "study", "230-24", cell="A2")[0].id
    assert _resolve(ledger, "analyte", synthetic.DRUG)[0].id != _resolve(ledger, "analyte", synthetic.METABOLITE, cell="A2")[0].id
    first = _resolve(ledger, "product", f"{synthetic.DRUG} IR tablet")[0]
    assert first.id != _resolve(ledger, "product", f"{synthetic.DRUG} IR tablets", cell="A2")[0].id
    assert len(_entities(ws)) == 6
    with pytest.raises(ValueError):
        _resolve(ledger, "study", " - ")                         # a label with no letter or digit names nothing


def test_two_codes_whose_digits_are_grouped_differently_stay_two(ws):
    """`name_key` drops every separator, so "EXA-1-2" and "EXA-12" share a key; their digits say two studies. Resolution
    keeps runs of digits apart ("230-23" is not "23023"), in a file, across files and in a merge's arms; letters beside
    digits need no mark ("EXA-101" is "EXA101")."""
    ledger = Ledger(ws)
    one, two = _resolve(ledger, "study", "EXA-1-2")[0], _resolve(ledger, "study", "EXA-12", cell="A2")[0]
    assert one.key == two.key and one.id != two.id
    assert _resolve(ledger, "study", "230-23", cell="A3")[0].id != _resolve(ledger, "study", "23023", cell="A4")[0].id
    assert _resolve(ledger, "study", "EXA-101", cell="A5")[0].id == _resolve(ledger, "study", "EXA101", cell="A6")[0].id
    assert _resolve(ledger, "study", "EXA 1/2", cell="A7")[0].id == one.id
    # another file's "EXA-12" joins the "EXA-12" of this one, never "EXA-1-2"
    joined, link = _resolve(ledger, "study", "EXA-12", sha=B)
    assert joined.id == two.id and link is not None
    # arms of the same name join on a study merge; "Cohort 1-2" and "Cohort 12" do not
    kept = _resolve(ledger, "arm", "Cohort 12", cell="B1", parent=two.id)[0]
    moved = _resolve(ledger, "arm", "Cohort 1-2", cell="B2", parent=one.id)[0]
    merge(ledger, type="study", from_id=one.id, into_id=two.id, link_fact=None, why="one study", by="u")
    assert ledger.entity(moved.id).id == moved.id != kept.id


def test_an_arm_resolves_inside_its_study_and_a_batch_inside_its_product(ws):
    ledger = Ledger(ws)
    first, second = _resolve(ledger, "study", "230-26")[0], _resolve(ledger, "study", "231-24", cell="A2")[0]
    arm = _resolve(ledger, "arm", "Cohort 1", cell="B1", parent=first.id)[0]
    assert _resolve(ledger, "arm", "COHORT-1", cell="B2", parent=first.id)[0].id == arm.id
    assert _resolve(ledger, "arm", "Cohort 1", cell="B3", parent=second.id)[0].id != arm.id
    assert ledger.entity(arm.id).parent == first.id
    # another file that names the same study (joined by its label) and the same arm: the study's arm
    joined, link = _resolve(ledger, "study", "230-26", sha=B)
    assert joined.id == first.id and link is not None
    assert _resolve(ledger, "arm", "Cohort 1", sha=B, cell="B1", parent=joined.id)[0].id == arm.id
    # an arm no study names: resolved inside its file only
    loose = _resolve(ledger, "arm", "Cohort 1", cell="C1")[0]
    assert loose.parent is None and loose.id != arm.id
    assert _resolve(ledger, "arm", "Cohort 1", sha=B, cell="C1")[0].id != loose.id
    # batches inside their products
    one, two = _resolve(ledger, "product", "Test tablet", cell="D1")[0], _resolve(ledger, "product", "Reference tablet",
                                                                                  cell="D2")[0]
    assert _resolve(ledger, "batch", "L1", cell="E1", parent=one.id)[0].id != _resolve(ledger, "batch", "L1", cell="E2",
                                                                                      parent=two.id)[0].id


def test_resolution_is_inside_the_file_first_and_never_joins_on_a_drug_or_product_name(ws):
    ledger = Ledger(ws)
    here = _resolve(ledger, "analyte", synthetic.DRUG)[0]
    there = _resolve(ledger, "analyte", synthetic.DRUG, sha=B)[0]
    assert here.id != there.id                                          # the drug of each file: never joined by name
    assert _resolve(ledger, "product", "Test tablet")[0].id != _resolve(ledger, "product", "Test tablet", sha=B)[0].id
    assert _resolve(ledger, "analyte", synthetic.DRUG, cell="A7")[0].id == here.id     # inside the file: one


def test_matrix_sequence_period_and_occasion_are_labels_as_written(ws):
    ledger = Ledger(ws)
    grid = grid_from_rows([["Subject", "Sequence", "Period", "Visit", "Conc (ng/mL)"],
                           ["001", "AB", "2", "Day 14", 12.5]], sha=A, caption=("Study 230-31: Exampleamide in Plasma",))
    cells = {name: grid.cell(2, c).locator for c, name in enumerate(("subject", "sequence", "period", "occasion"), 1)}
    row = ExtractedRow(field="concentration", labels={"subject": "001", "sequence": "AB", "period": "2", "occasion": "Day 14",
                                                      "matrix": "Plasma"},
                       label_locators={**cells, "matrix": grid.caption[0].locator}, time=1.0, time_unit="h", value=12.5,
                       verbatim="12.5", locator=grid.cell(2, 5).locator, unit="ng/mL", statistic="individual")
    result = ExtractResult(rows=(row,), cell_use=(), findings=(), constants=(
        ExtractedConstant(field="study_id", value="230-31", verbatim=grid.caption[0].text, locator=grid.caption[0].locator),))
    spec = MappingSpec(kind="pk_individual", layout="long", header_rows=1, first_data_row=2)
    recorded = ledger.record_extraction(region=region_of(grid), grid=grid, mapping=mapping_entry(spec), result=result,
                                        context=sheet_context(A))
    (value,) = [v for v in ledger.values() if v.id.startswith(f"{recorded.extract}#")]
    assert (value.entity.subject, value.entity.sequence, value.entity.period, value.entity.occasion, value.entity.matrix) == (
        "001", "AB", "2", "Day 14", "Plasma")
    assert {line.body["type"] for line in _entities(ws)} == {"study"}           # labels are never entities
    assert set(value.locators) >= {"subject", "sequence", "period", "occasion", "matrix", "study"}


def test_a_merge_keeps_both_ids_resolvable(ws):
    ledger = Ledger(ws)
    workbook = synthetic.messy_workbook()
    record_table(ledger, workbook, "fasting-individual")
    record_table(ledger, synthetic.delimited(), "delimited-listing")
    source = next(e for e in ledger.entities("study") if e.label == "230-23")
    target = next(e for e in ledger.entities("study") if e.label == "230-28")
    with pytest.raises(ValueError):
        merge(ledger, type="study", from_id=source.id, into_id=target.id, link_fact=None, why=" ", by="u")
    with pytest.raises(ValueError):
        merge(ledger, type="analyte", from_id=source.id, into_id=target.id, link_fact=None, why="x", by="u")
    with pytest.raises(KeyError):
        merge(ledger, type="study", from_id="st-999", into_id=target.id, link_fact=None, why="x", by="u")
    made = merge(ledger, type="study", from_id=source.id, into_id=target.id, link_fact=None, why="one study", by="u")
    view = LedgerView(ws)
    assert view.entity(source.id).id == target.id and view.entity(target.id).id == target.id
    assert source.id not in {e.id for e in view.entities("study")}
    assert view.values(study=source.id) == view.values(study=target.id) and len(view.values(study=target.id)) > 40
    heads = IntakeStore(ws).entities.head()
    assert merge(ledger, type="study", from_id=source.id, into_id=target.id, link_fact=None, why="again", by="u") == made
    assert IntakeStore(ws).entities.head() == heads                        # the same merge again: the line written
    with pytest.raises(ValueError):
        merge(ledger, type="study", from_id=target.id, into_id=source.id, link_fact=None, why="a cycle", by="u")
    third = _resolve(ledger, "study", "231-24", cell="Z1")[0]
    with pytest.raises(ValueError):
        merge(ledger, type="study", from_id=source.id, into_id=third.id, link_fact=None, why="elsewhere", by="u")
    # a label of the merged study, resolved again in its file, is the study it was merged into
    assert _resolve(ledger, "study", "230-23", sha=source.source.split("@")[0], cell="A1")[0].id == target.id


def test_two_threads_resolving_the_same_label_create_one_entity(ws):
    barrier = threading.Barrier(4)
    found: list[str] = []

    def run(cell: str) -> None:
        barrier.wait()
        found.append(_resolve(Ledger(ws), "study", "230-23", cell=cell)[0].id)

    threads = [threading.Thread(target=run, args=(f"A{i}",)) for i in range(1, 5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(found) == 4 and len(set(found)) == 1 and len(_entities(ws)) == 1
    assert IntakeStore(ws).entities.verify() == []
