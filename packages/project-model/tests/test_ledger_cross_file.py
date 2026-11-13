"""Cross-file facts, the owner's five conditions (plan §7.6, contracts §6.3, §8.6), one test each:
(1) an explicit anchored link joins, nothing else: an upload tag or the same drug name joins nothing; the same study
    label in a workbook and a synopsis PDF gives a `link.study_id` fact at the PDF's label; an explicit `link.protocol`
    fact merges the file's study into the one it names;
(2) the match is unique: two candidates give an ambiguous pending link and nothing joined;
(3) the joined values carry `cross_file` and its three anchors (the value's, the link's, the receiving study's);
(4) they wait for a reviewer: unconfirmed until a `LinkConfirmation` of (study, file), then inherited by every later
    value through the same link; a refused link excludes them;
(5) `cross_file` is on every view of the value (here: the fold, a fresh LedgerView). Never a join on an upload tag or a
    drug name."""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import PdfSpan, format_locator, parse_anchor, parse_locator, same_place
from modeler_intake.mapping_spec import ProseFact
from modeler_project.client_data import update_review
from modeler_project.documents import DocumentLibrary
from modeler_project.intake_fixtures import TRUTH_MODEL
from modeler_project.intake_records import Assignment, LinkConfirmation
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import ExtractionContext, Ledger
from modeler_project.ledger_compute import DOSE_TO_MG, ORPHANED, SD_FROM_SE, UNCONFIRMED
from modeler_project.ledger_entities import resolve
from modeler_project.ledger_models import Entity, Merge
from modeler_project.ledger_view import LedgerView
from modeler_project.workspace import Workspace

from .test_ledger_support import AT, context, file_record, make_ws, prose_of, record_rows, record_table, sha_of

pytestmark = pytest.mark.req("T-47", "T-05", "F-404")


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return make_ws(tmp_path)


@pytest.fixture
def files() -> tuple[synthetic.SyntheticFile, synthetic.SyntheticFile]:
    return synthetic.messy_workbook(), synthetic.pdf_report(unruled_table=False)


def _study(ledger: Ledger, label: str, sha: str | None = None) -> Entity:
    (found,) = [e for e in ledger.entities("study") if e.label == label and (sha is None or e.source.startswith(sha))]
    return found


def _synopsis(ledger: Ledger, pdf: synthetic.SyntheticFile, **kwargs) -> list:
    recorded = ledger.record_prose(facts=prose_of(pdf), model=TRUTH_MODEL, context=context(pdf, **kwargs))
    return [ledger.value(f) for f in recorded.facts]


def _confirm(ledger: Ledger, id: str, *, study: str, file: str, confirmed: bool, link_fact: str | None = None,
             why: str = "") -> None:
    """The review's `link` line, as D6's confirm_link writes it (and audits it); the ledger then reads again."""
    ledger.store.review.append("link", LinkConfirmation(id=id, link_fact=link_fact, study=study, file_sha256=file,
                                                        confirmed=confirmed, why=why, by="u-1", at=AT).model_dump())
    ledger.refresh()


def test_an_upload_tag_or_the_same_drug_name_joins_nothing(ws, files):
    workbook, pdf = files
    ledger = Ledger(ws)
    record_table(ledger, workbook, "fasting-individual")
    library = DocumentLibrary(ws)
    library.add(pdf.data, pdf.name, role="client_file", by="u-1")
    library.tag(sha_of(pdf), "clinical", by="u-1", study="230-23")            # the person's tag says study 230-23
    untold = record_table(ledger, pdf, "report-table5", drop=("study_id",))    # a table that names no study
    values = [v for v in ledger.values() if v.id.startswith(f"{untold.extract}#")]
    assert values and all(v.entity.study is None and v.cross_file is None for v in values)
    record_table(ledger, pdf, "report-table6")                                  # Study 230-26, the same drug
    drugs = [e for e in ledger.entities("analyte") if e.label == synthetic.DRUG]
    assert len(drugs) == 2 and {e.source.split("@")[0] for e in drugs} == {sha_of(workbook), sha_of(pdf)}
    assert {e.label for e in ledger.entities("study")} == {"230-23", "230-26"}
    assert ledger.values(field="link.study_id") == [] and all(v.cross_file is None for v in ledger.values())
    assert ledger.link_files() == [] and ledger.pending_links() == []


def test_the_same_study_label_in_a_workbook_and_a_synopsis_links_the_pdf_values_with_three_anchors(ws, files):
    workbook, pdf = files
    ledger = Ledger(ws)
    record_table(ledger, workbook, "fasting-individual")
    study = _study(ledger, "230-23")
    synopsis = _synopsis(ledger, pdf)
    (link,) = [v for v in synopsis if v.field == "link.study_id"]
    label = dict(pdf.values[0].locators)["study"]                     # the synopsis's "230-23", a word span on page 1
    assert parse_anchor(link.anchor).file_sha256 == sha_of(pdf) and same_place(parse_anchor(link.anchor).locator,
                                                                               parse_locator(label))
    assert (link.value, link.method, link.entity.study, link.status) == ("230-23", "prose", study.id, "proposed")
    stated = [v for v in synopsis if v.field != "link.study_id"]
    assert {v.field for v in stated} == {"dose", "n", "food_state"}
    for value in [*stated, link]:
        assert value.entity.study == study.id
        assert value.cross_file.model_dump() == {"stating_fact": value.id, "link_fact": link.id, "receiving_study": study.id}
        # the three anchors: the stating value's (the PDF), the link's (the PDF's label), the study's source (the workbook)
        anchors = (value.anchor, ledger.value(value.cross_file.link_fact).anchor, ledger.entity(study.id).source)
        assert [parse_anchor(a).file_sha256 for a in anchors] == [sha_of(pdf), sha_of(pdf), sha_of(workbook)]
    assert all(v.cross_file is None for v in ledger.values(file_sha256=sha_of(workbook)))
    (pending,) = ledger.pending_links()
    assert (pending.state, pending.study, pending.file_sha256, pending.link_fact, pending.values) == (
        "unconfirmed", study.id, sha_of(pdf), link.id, 4)
    assert ledger.pending_links(study=study.id) == [pending]
    # every view says so: a fresh read side too
    assert all(LedgerView(ws).value(v.id).cross_file == v.cross_file for v in synopsis)
    assert len(IntakeStore(ws).entities.entries("entity")) == 2            # the study and the drug: no study for the PDF


def test_two_candidate_studies_give_an_ambiguous_pending_link_and_nothing_joined(ws, files):
    workbook, pdf = files
    ledger = Ledger(ws)
    record_table(ledger, workbook, "fasting-individual")
    first = _study(ledger, "230-23")
    # another file's 230-23 that was never joined to the workbook's (as a person who split them would leave it)
    elsewhere = "c" * 64
    store = IntakeStore(ws)
    store.entities.append("entity", lambda seq: Entity(
        id=f"st-{seq}", type="study", label="230-23", key="23023", source=f"{elsewhere}@workbook/1.0#s:'Cover'!A1",
        by="u-1", at=AT).model_dump(mode="json"))
    second = next(e for e in Ledger(ws).entities("study") if e.id != first.id)
    synopsis = _synopsis(ledger, pdf)
    assert not any(v.field == "link.study_id" for v in synopsis)            # nothing joined
    local = ledger.entity(synopsis[0].entity.study)
    assert local.id not in (first.id, second.id) and local.source.startswith(sha_of(pdf))
    assert all(v.entity.study == local.id and v.cross_file is None for v in synopsis)
    (pending,) = ledger.pending_links(study=local.id)
    assert (pending.state, pending.study, pending.link_fact, pending.file_sha256, pending.values) == (
        "ambiguous", local.id, None, sha_of(pdf), 3)
    assert set(pending.candidates) == {first.id, second.id}
    assert ledger.pending_links(study=first.id) == []                     # the first study of a label waits on nothing
    assert ledger.link_files() == []
    # the reviewer chooses the workbook's study: the PDF's study is merged into it, and the choice is the confirmation
    _confirm(ledger, "lk-1", study=first.id, file=sha_of(pdf), confirmed=True, why="the synopsis is the workbook's study")
    (made,) = ledger.link_files()
    assert (made.from_id, made.into_id, made.link_fact, made.by) == (local.id, first.id, None, "u-1")
    assert all(ledger.value(v.id).entity.study == first.id and ledger.value(v.id).cross_file is not None for v in synopsis)
    assert not [p for p in ledger.pending_links() if p.file_sha256 == sha_of(pdf)]
    assert ledger.link_files() == []


def test_an_explicit_link_that_names_two_studies_joins_nothing(ws):
    ledger = Ledger(ws)
    one, two, three = "1" * 64, "2" * 64, "3" * 64
    record_rows(ledger, sha=one, sheet="Cover", region="rg-0000000001", caption="Study EXA-101",
                constants=(("study_id", "EXA-101", None),))
    record_rows(ledger, sha=two, sheet="Cover", region="rg-0000000002", caption="Study 231-24 (reference EXA-101)",
                constants=(("study_id", "231-24", None), ("reference", "EXA-101", None)))
    record_rows(ledger, sha=three, sheet="Cover", region="rg-0000000003", caption="Study LOC-7, protocol EXA-101",
                constants=(("study_id", "LOC-7", None), ("link.protocol", "EXA-101", None)))
    link = ledger.values(field="link.protocol")[0]
    local = _study(ledger, "LOC-7")
    assert ledger.link_files() == []
    (pending,) = ledger.pending_links(study=local.id)
    assert (pending.state, pending.link_fact, pending.file_sha256) == ("ambiguous", link.id, three)
    assert set(pending.candidates) == {_study(ledger, "EXA-101").id, _study(ledger, "231-24").id}


def test_an_explicit_link_protocol_merges_the_files_study_into_the_one_it_names(ws, files):
    workbook, _pdf = files
    ledger = Ledger(ws)
    record_table(ledger, workbook, "fasting-individual")
    target = _study(ledger, "230-23")
    other = "d" * 64
    recorded = record_rows(ledger, sha=other, sheet="PK", region="rg-0000000004",
                           caption="Study LOC-7 (protocol 230-23): Exampleamide plasma",
                           rows=({"time": 1, "value": 11.0}, {"time": 2, "value": 8.0}),
                           constants=(("study_id", "LOC-7", None), ("link.protocol", "230-23", None),
                                      ("analyte", synthetic.DRUG, None)))
    local = _study(ledger, "LOC-7")
    (link,) = ledger.values(field="link.protocol")
    assert link.entity.study == local.id and link.cross_file is None
    (made,) = ledger.link_files()
    assert isinstance(made, Merge) and (made.from_id, made.into_id, made.link_fact, made.by) == (
        local.id, target.id, link.id, "code")
    assert ledger.link_files() == []                                         # idempotent
    values = [ledger.value(f"{recorded.extract}#{i}") for i in range(2)]
    assert all(v.entity.study == target.id and v.cross_file.link_fact == link.id for v in values)
    assert ledger.entity(local.id).id == target.id                          # both ids resolve
    (pending,) = ledger.pending_links()
    assert (pending.state, pending.study, pending.file_sha256, pending.link_fact) == ("unconfirmed", target.id, other, link.id)


def test_values_wait_for_a_link_confirmation_and_later_values_through_the_link_inherit_it(ws, files):
    workbook, pdf = files
    ledger = Ledger(ws)
    record_table(ledger, workbook, "fasting-individual")
    study = _study(ledger, "230-23")
    synopsis = _synopsis(ledger, pdf)
    link = next(v.id for v in synopsis if v.field == "link.study_id")
    assert [p.state for p in ledger.pending_links()] == ["unconfirmed"]
    _confirm(ledger, "lk-1", study=study.id, file=sha_of(pdf), confirmed=True, link_fact=link, why="the same protocol")
    assert ledger.pending_links() == []
    # a later delivery of the same file: another sentence read with the same study label, through the same link
    sentence = synthetic.pdf_report(unruled_table=False).prose[1]
    span = format_locator(PdfSpan(page=1, first_word=12, last_word=12, box=(380.0, 100.0, 420.0, 110.0)))
    later = ledger.record_prose(facts=[ProseFact(
        field="population", value="healthy", quote=sentence, study_label="230-23", locator=span,
        study_locator=dict(pdf.values[0].locators)["study"])], model=TRUTH_MODEL, context=context(pdf, delivery="dl-2"))
    (value,) = [ledger.value(f) for f in later.facts if ledger.value(f).field == "population"]
    assert value.cross_file.link_fact == link and value.delivery == "dl-2" and value.status == "proposed"
    assert ledger.pending_links() == []                                     # inherited: nothing waits
    assert len(ledger.values(field="link.study_id")) == 1                    # the same link, not a second one


def test_a_refused_link_excludes_the_values_and_a_person_may_assign_them_elsewhere(ws, files):
    workbook, pdf = files
    ledger = Ledger(ws)
    record_table(ledger, workbook, "fasting-individual")
    record_table(ledger, workbook, "fed-individual")
    study, fed = _study(ledger, "230-23"), _study(ledger, "231-24")
    synopsis = _synopsis(ledger, pdf)
    _confirm(ledger, "lk-1", study=study.id, file=sha_of(pdf), confirmed=False, why="another protocol of that number")
    for value in synopsis:
        state = ledger.value(value.id)
        assert (state.status, state.status_reason) == ("excluded", "another protocol of that number")
    assert ledger.values(file_sha256=sha_of(pdf)) == []
    (refused,) = ledger.pending_links()
    assert (refused.state, refused.study, refused.values) == ("refused", study.id, 4)
    # the person assigns the stated values to another study: the assignment is the confirmation
    stated = [v.id for v in synopsis if v.field != "link.study_id"]
    IntakeStore(ws).review.append("assignment", Assignment(id="as-1", targets=tuple(stated), study=fed.id,
                                                           why="the synopsis is of 231-24", by="u-1", at=AT).model_dump())
    ledger.refresh()
    moved = [ledger.value(i) for i in stated]
    assert all(v.status == "proposed" and v.entity.study == fed.id and v.cross_file.link_fact == "as-1" for v in moved)
    assert [(p.state, p.study) for p in ledger.pending_links()] == [("refused", study.id)]    # only the link fact is left


def test_a_study_label_with_no_anchor_of_its_own_joins_nothing(ws, files):
    workbook, _pdf = files
    ledger = Ledger(ws)
    record_table(ledger, workbook, "fasting-individual")
    study = _study(ledger, "230-23")
    other = "e" * 64
    entity, link = resolve(ledger, type="study", label="230-23", source=None, file_sha256=other, by="code")
    assert entity.id != study.id and link is None and entity.source is None
    assert ledger.values(field="link.study_id") == []


def test_an_ambiguous_label_lists_the_studies_a_confirmed_alias_names_too(ws):
    """resolve's candidates for a study label are other files' studies with its key or one a person-confirmed alias
    sends it to; the pending link lists the same ones, and the first study of a label waits on nothing."""
    one, two, three = "1" * 64, "2" * 64, "3" * 64
    ledger = Ledger(ws)
    record_rows(ledger, sha=one, sheet="Cover", region="rg-0000000001", caption="Study 230-23",
                constants=(("study_id", "230-23", None),))
    record_rows(ledger, sha=two, sheet="Cover", region="rg-0000000002", caption="Study EXA 230-23 EU",
                constants=(("study_id", "EXA 230-23 EU", None),))
    first, second = _study(ledger, "230-23"), _study(ledger, "EXA 230-23 EU")
    assert ledger.pending_links() == []                                  # two labels, two keys: nothing to settle
    update_review(ws, lambda record: ({**record, "aliases": {"EXA/230-23 (EU)": "230-23"}}, "linked on Inputs"), by="u-1")
    record_rows(ledger, sha=three, sheet="Cover", region="rg-0000000003", caption="Study EXA/230-23 (EU)",
                constants=(("study_id", "EXA/230-23 (EU)", None),))
    third = _study(ledger, "EXA/230-23 (EU)")                           # its key is the second's; its alias the first's
    assert third.id not in (first.id, second.id) and ledger.values(field="link.study_id") == []
    (pending,) = ledger.pending_links(study=third.id)
    assert (pending.state, pending.file_sha256, set(pending.candidates)) == ("ambiguous", three, {first.id, second.id})
    assert ledger.pending_links(study=first.id) == []
    # the second study, made before the alias existed, is that alias's label too: a link for a person to settle
    (later,) = ledger.pending_links(study=second.id)
    assert (later.state, later.candidates) == ("ambiguous", (first.id,))
    _confirm(ledger, "lk-1", study=first.id, file=three, confirmed=True, why="the EU code of 230-23")
    (made,) = ledger.link_files()
    assert (made.from_id, made.into_id) == (third.id, first.id) and ledger.pending_links(study=third.id) == []


def test_a_study_merge_joins_the_arms_of_the_same_name_inside_it(ws):
    """An arm is resolved inside its study: when an explicit link merges a file's study into another, its arm of the same
    name is that study's arm (merged with the same link fact), so an arm-level disagreement is seen; an arm of another
    name moves with its study."""
    one, two = "1" * 64, "2" * 64
    ledger = Ledger(ws)
    record_rows(ledger, sha=one, sheet="Design", region="rg-0000000001", caption="Study 230-40, Cohort 1, 10 mg",
                constants=(("study_id", "230-40", None), ("treatment", "Cohort 1", None), ("dose", 10.0, "mg")))
    record_rows(ledger, sha=two, sheet="Cohort 1", region="rg-0000000002", caption="Study LOC-7 (protocol 230-40), Cohort 1",
                constants=(("study_id", "LOC-7", None), ("link.protocol", "230-40", None), ("treatment", "Cohort 1", None),
                           ("dose", 20.0, "mg")))
    record_rows(ledger, sha=two, sheet="Cohort 2", region="rg-0000000003", caption="Study LOC-7, Cohort 2, 30 mg",
                constants=(("study_id", "LOC-7", None), ("treatment", "Cohort 2", None), ("dose", 30.0, "mg")))
    target, local = _study(ledger, "230-40"), _study(ledger, "LOC-7")
    arms = {(e.label, e.parent): e for e in ledger.entities("arm")}
    assert ledger.conflicts() == []                                     # two studies, nothing to compare yet
    (link,) = ledger.values(field="link.protocol")
    (made,) = ledger.link_files()
    assert (made.type, made.from_id, made.into_id) == ("study", local.id, target.id)
    merges = [line.body for line in IntakeStore(ws).entities.entries("merge")]
    assert [(m["type"], m["from_id"], m["into_id"], m["link_fact"]) for m in merges] == [
        ("study", local.id, target.id, link.id),
        ("arm", arms[("Cohort 1", local.id)].id, arms[("Cohort 1", target.id)].id, link.id)]
    assert ledger.entity(arms[("Cohort 1", local.id)].id).id == arms[("Cohort 1", target.id)].id
    doses = {v.value: v for v in ledger.values(field="dose")}
    assert {v.entity.study for v in doses.values()} == {target.id}
    assert doses[10.0].entity.arm == doses[20.0].entity.arm != doses[30.0].entity.arm == arms[("Cohort 2", local.id)].id
    (conflict,) = ledger.conflicts()
    assert conflict.field == "dose" and set(conflict.values) == {doses[10.0].id, doses[20.0].id}
    assert doses[20.0].cross_file.link_fact == link.id and doses[10.0].cross_file is None
    assert ledger.link_files() == [] and len(IntakeStore(ws).entities.entries("merge")) == 2     # once


# --- an explicit link joins only its own file's study, once ----------------------------------------------------------

G1, G2, F = "1" * 64, "2" * 64, "f" * 64


def _span(word: int) -> str:
    return format_locator(PdfSpan(page=1, first_word=word, last_word=word, box=(10.0 * word, 100.0, 10.0 * word + 8, 110.0)))


def _synopsis_context(sha: str = F) -> ExtractionContext:
    return ExtractionContext(delivery="dl-1", run_id=None, file=file_record(sha, "synopsis.pdf"), parser="pdfplumber",
                             parser_version="1.0")


def _studies(ledger: Ledger) -> list[tuple[str, str]]:
    return sorted((e.id, e.label) for e in ledger.entities("study"))


def test_a_cross_reference_on_a_study_another_files_label_joined_merges_nothing(ws):
    """F's label "230-23" joins G1's study through `link.study_id`; F's sentence also refers to 230-99 (G2's study). That
    cross-reference sits on G1's study, not on a study of F's own: it never merges G1's study into G2's, however often
    `link_files` runs, and G1's own values never become cross-file values."""
    ledger = Ledger(ws)
    record_rows(ledger, sha=G1, sheet="T", region="rg-0000000001", caption="Study 230-23",
                rows=({"time": 1, "value": 12.0},), constants=(("study_id", "230-23", None),))
    record_rows(ledger, sha=G2, sheet="T", region="rg-0000000002", caption="Study 230-99",
                rows=({"time": 1, "value": 15.0},), constants=(("study_id", "230-99", None),))
    before = _studies(ledger)
    quote = "Study 230-23 dosed 50 mg (see Study 230-99 for the food effect)."
    made = ledger.record_prose(facts=[
        ProseFact(field="dose", value=50.0, unit="mg", quote=quote, study_label="230-23", locator=_span(4),
                  study_locator=_span(2)),
        ProseFact(field="link.cross_reference", value="230-99", quote=quote, study_label="230-23", locator=_span(9),
                  study_locator=_span(2))], model=TRUTH_MODEL, context=_synopsis_context())
    (link,) = ledger.values(field="link.study_id")
    (xref,) = ledger.values(field="link.cross_reference")
    assert link.id in made.facts and xref.entity.study == link.entity.study == _study(ledger, "230-23").id
    for _ in range(2):
        assert ledger.link_files() == []
    assert _studies(ledger) == before and IntakeStore(ws).entities.entries("merge") == []
    assert all(v.cross_file is None for v in ledger.values(file_sha256=G1))
    assert [(p.state, p.file_sha256) for p in ledger.pending_links()] == [("unconfirmed", F)]


def test_explicit_links_of_one_study_that_name_two_studies_are_one_ambiguous_link_and_a_rerun_merges_nothing(ws):
    """F's own study X-1 states protocol 230-23 and a cross-reference to 230-99: together two studies, so one ambiguous
    pending link and no merge, on every run (no merge one step further each time)."""
    ledger = Ledger(ws)
    record_rows(ledger, sha=G1, sheet="T", region="rg-0000000001", caption="Study 230-23", constants=(("study_id", "230-23", None),))
    record_rows(ledger, sha=G2, sheet="T", region="rg-0000000002", caption="Study 230-99", constants=(("study_id", "230-99", None),))
    record_rows(ledger, sha=F, sheet="T", region="rg-0000000003", caption="Study X-1 (protocol 230-23; see 230-99)",
                constants=(("study_id", "X-1", None), ("link.protocol", "230-23", None),
                           ("link.cross_reference", "230-99", None)))
    before = _studies(ledger)
    for _ in range(2):
        assert ledger.link_files() == []
    assert _studies(ledger) == before
    (pending,) = ledger.pending_links(study=_study(ledger, "X-1").id)
    assert (pending.state, pending.file_sha256, set(pending.candidates)) == (
        "ambiguous", F, {_study(ledger, "230-23").id, _study(ledger, "230-99").id})
    assert pending.link_fact == ledger.values(field="link.protocol")[0].id


def test_a_study_a_person_kept_apart_is_never_merged_by_the_explicit_link_that_named_both(ws):
    """A protocol number that names two studies of other files is ambiguous; the person confirms one for F: F's study is
    merged into it, once, and the other study (the one the person kept apart) is never merged by code afterwards."""
    ledger = Ledger(ws)
    record_rows(ledger, sha=G1, sheet="T", region="rg-0000000001", caption="Study 230-23", constants=(("study_id", "230-23", None),))
    first = _study(ledger, "230-23")
    store = IntakeStore(ws)
    store.entities.append("entity", lambda seq: Entity(
        id=f"st-{seq}", type="study", label="230-23", key="23023", source=f"{G2}@workbook/1.0#s:'Cover'!A1",
        by="u-1", at=AT).model_dump(mode="json"))
    ledger.refresh()
    (second,) = [e for e in ledger.entities("study") if e.label == "230-23" and e.id != first.id]
    record_rows(ledger, sha=F, sheet="T", region="rg-0000000003", caption="Study LOC-7, protocol 230-23",
                rows=({"time": 1, "value": 11.0},), constants=(("study_id", "LOC-7", None), ("link.protocol", "230-23", None)))
    local = _study(ledger, "LOC-7")
    assert ledger.link_files() == []
    (pending,) = ledger.pending_links(study=local.id)
    assert (pending.state, set(pending.candidates)) == ("ambiguous", {first.id, second.id})
    _confirm(ledger, "lk-1", study=first.id, file=F, confirmed=True, why="the synopsis of the workbook's 230-23")
    (made,) = ledger.link_files()
    assert (made.from_id, made.into_id, made.by) == (local.id, first.id, "u-1")
    for _ in range(2):
        assert ledger.link_files() == []
    assert {e.id for e in ledger.entities("study")} == {first.id, second.id}
    assert [(m.body["from_id"], m.body["into_id"]) for m in IntakeStore(ws).entities.entries("merge")] == [(local.id, first.id)]


# --- a derived fact follows its input's link (conditions 4 and 5) ----------------------------------------------------


def test_nothing_is_derived_from_a_cross_file_value_until_its_link_is_confirmed_and_a_refusal_retires_it_at_once(ws):
    """File B's label joins file A's study EXA-101. B's 0.5 g dose and B's n = 24 wait for a reviewer: no dose in mg is
    derived from them, and A's SE mean (no n of its own) takes no series' n from B. Once the (study, B) link is
    confirmed, both are derived; when it is refused, `derive` (D6 calls it after a link decision) retires them at once,
    and a later confirmation brings the same facts back."""
    ledger = Ledger(ws)
    record_rows(ledger, sha=G1, sheet="PK", region="rg-0000000001", caption="Study EXA-101: Exampleamide plasma",
                rows=({"time": 1, "value": 0.5, "spread": 0.5, "spread_kind": "SE"},),
                constants=(("study_id", "EXA-101", None), ("analyte", synthetic.DRUG, None)))
    record_rows(ledger, sha=G2, sheet="Design", region="rg-0000000002", caption="Study EXA-101, 0.5 g, n = 24",
                constants=(("study_id", "EXA-101", None), ("dose", 0.5, "g"), ("n", 24.0, None)))
    study = _study(ledger, "EXA-101")
    stated = [v for v in ledger.values(file_sha256=G2) if v.field in ("dose", "n")]
    assert len(stated) == 2 and all(v.cross_file is not None and v.entity.study == study.id for v in stated)
    assert ledger.derive() == []
    _confirm(ledger, "lk-1", study=study.id, file=G2, confirmed=True, why="the same protocol")
    made = {f.compute: f for f in ledger.derive()}
    assert set(made) == {DOSE_TO_MG, SD_FROM_SE}
    assert made[DOSE_TO_MG].value == 500.0 and made[SD_FROM_SE].n == 24
    n_fact = next(v for v in stated if v.field == "n")
    assert n_fact.id in made[SD_FROM_SE].derived_from
    _confirm(ledger, "lk-2", study=study.id, file=G2, confirmed=False, why="another protocol of that number")
    assert ledger.derive() == []
    for fact in made.values():
        state = ledger.value(fact.id)
        assert state.status == "excluded" and state.status_reason.startswith(ORPHANED)
    _confirm(ledger, "lk-3", study=study.id, file=G2, confirmed=True, why="the same protocol after all")
    assert ledger.derive() == []                                   # the same facts, back
    assert all(ledger.value(f.id).status == "proposed" for f in made.values())


def test_a_derived_fact_waits_again_when_a_code_merge_makes_its_input_a_cross_file_value(ws):
    """A file's own dose in g gives a dose in mg; an explicit link then merges that file's study into another file's: the
    dose is a cross-file value waiting for a reviewer, and its derived dose is set aside until the link is confirmed."""
    ledger = Ledger(ws)
    record_rows(ledger, sha=G1, sheet="T", region="rg-0000000001", caption="Study 230-40", constants=(("study_id", "230-40", None),))
    record_rows(ledger, sha=F, sheet="T", region="rg-0000000002", caption="Study LOC-7 (protocol 230-40), 0.25 g",
                constants=(("study_id", "LOC-7", None), ("link.protocol", "230-40", None), ("dose", 0.25, "g")))
    (mg,) = ledger.derive()
    (made,) = ledger.link_files()
    state = ledger.value(mg.id)
    assert (state.status, state.status_reason.startswith(UNCONFIRMED)) == ("excluded", True)
    _confirm(ledger, "lk-1", study=made.into_id, file=F, confirmed=True)
    assert ledger.derive() == [] and ledger.value(mg.id).status == "proposed"
