"""What a signed Delivery confirmation lands (contracts §6.6, §2, §8.10; plan G6, L-h): datasets whose values are the
truth's, dissolution rows through the register, compound evidence, each written by its owner; what the model's code
does not accept is held back, listed, while the rest lands; nothing is loaded twice against the legacy card; a second
land writes nothing.

Every number is made up (the drug is Exampleamide). Nothing here runs PK-Sim: a landed dataset is checked by the
platform's own code (`check_dataset`, the dissolution register), not simulated."""

from __future__ import annotations

import hashlib
import io
from typing import Any

import pytest
from openpyxl import Workbook

from modeler_intake import synthetic
from modeler_project import client_data
from modeler_project import intake_landing as landing
from modeler_project import intake_review as review
from modeler_project.artifacts import ArtifactKind
from modeler_project.client_data import ingest, submission, submission_id
from modeler_project.dataset_register import dataset, datasets, decide_dataset, propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, check_dataset
from modeler_project.dissolution_register import profiles
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState, SourceRef
from modeler_project.evidence_register import items
from modeler_project.intake_fixtures import write_truth
from modeler_project.intake_records import Confirmation
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import Ledger
from modeler_project.ledger_models import EntityRef
from modeler_project.profile_landing import judged_sd
from modeler_project.sheet_intake import SheetIntakeError, drafts, finish
from modeler_project.workspace import Workspace

from .test_intake_review import (
    AT,
    BY,
    CARD,
    Book,
    clean_study,
    cover,
    covered,
    draw,
    events,
    line_hash,
    project,
    settle,
    sha_of,
    study_of,
    tick_all,
)

pytestmark = pytest.mark.req("T-47", "T-45", "T-48")

SIGNATURE = "sig-0001"


# --- helpers ----------------------------------------------------------------------------------------------------------


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return project(tmp_path)


@pytest.fixture
def library(ws) -> DocumentLibrary:
    return DocumentLibrary(ws)


def plan_of(ws: Workspace, subject: str, reader: Ledger, subject_type: str = "study", library: DocumentLibrary | None = None,
            mol_weight: float | None = None) -> landing.LandingPlan:
    return landing.plan_landing(ws, library, subject_type, subject, reader=reader, matrix=None, mol_weight=mol_weight)  # type: ignore[arg-type]


def confirm(ws: Workspace, subject: str, reader: Ledger, subject_type: str = "study", signature: str = SIGNATURE) -> Confirmation:
    """The confirmation line of a subject as the route records it once every refusal was checked and it was signed."""
    record, sha = review.bound_record(ws, subject_type, subject, reader=reader, **CARD)  # type: ignore[arg-type]
    return review.record_confirmation(ws, subject_type=subject_type, subject=subject, record=record, record_sha256=sha,  # type: ignore[arg-type]
                                      signature_id=signature, manifestation="Reviewed by A. Reviewer", by=BY,
                                      printed_name="A. Reviewer", blinded=False)


def land(ws: Workspace, subject: str, reader: Ledger, subject_type: str = "study", library: DocumentLibrary | None = None,
         signature: str = SIGNATURE):
    """Confirm and land one subject in the route's order: a reviewer's decisions (`settle`), every refusal checked in
    one call (`prepare_confirmation`: no blocker is left, the landing is planned), the signed record, the landing.
    (plan, confirmation, landed)."""
    settle(ws, subject_type, subject, reader)
    record, sha, plan = review.prepare_confirmation(ws, library, subject_type, subject, reader=reader, **CARD,  # type: ignore[arg-type]
                                                    blinded=False)
    confirmation = review.record_confirmation(ws, subject_type=subject_type, subject=subject, record=record,  # type: ignore[arg-type]
                                              record_sha256=sha, signature_id=signature,
                                              manifestation="Reviewed by A. Reviewer", by=BY, printed_name="A. Reviewer",
                                              blinded=False)
    done = landing.land(ws, library, confirmation, plan, by=BY)
    reader.refresh()
    return plan, confirmation, done


def enter(reader: Ledger, study: str, **facts: Any) -> None:
    for field, value in facts.items():
        reader.enter(entity=EntityRef(study=study), field=field, value=value, why="from the protocol", by=BY)


def client_file(ws: Workspace, library: DocumentLibrary, name: str = "client-notes.xlsx") -> str:
    """A small client workbook stored through today's reader, so the file has its client-file record; its sha256."""
    book = Workbook()
    book.active.title = "Notes"
    book.active.append([f"Exampleamide: working notes ({name})"])
    raw = io.BytesIO()
    book.save(raw)
    return ingest(ws, library, raw.getvalue(), name, by=BY)["sha256"]


def number(text: str) -> float | None:
    text = text.strip().rstrip("*")
    try:
        return float(text)
    except ValueError:
        return None


def series_of(found: ObservedDataset, name: str) -> Series:
    (series,) = [s for s in found.series if s.name == name]
    return series


def delivery_in(ws: Workspace, library: DocumentLibrary) -> tuple[Ledger, dict[str, str]]:
    """The synthetic delivery as it stands after arrival in `both`: today's readers stored each file they read, and the
    ledger holds the truth, with every file's coverage."""
    files = synthetic.delivery()
    for file in files[:3]:                                          # the workbook, the PDF, the Word report
        ingest(ws, library, file.data, file.name, by=BY)
    keys = write_truth(ws, files)
    for file in files:
        cover(ws, file)
    # the workbook's stray note with a number is accepted as not data (else it blocks every subject of the delivery)
    review.exclude_regions(ws, file_sha256=sha_of(files[0]), regions=["s:'Summary'!A10"], scope="outside",
                           why="a working note, not data", by=BY)
    return Ledger(ws), keys


def settle_230_23(ws: Workspace, reader: Ledger) -> str:
    """Study 230-23 with nothing left to block its confirmation: its missing facts entered, its link confirmed, its
    failed checks overridden or disposed, the spot check ticked."""
    study = study_of(reader, "230-23")
    enter(reader, study, route="oral", formulation="ir_tablet", intended_use="model_building")
    settle(ws, "study", study, reader)
    return study


# --- a study's datasets ---------------------------------------------------------------------------------------------


def test_a_confirmed_study_becomes_accepted_client_datasets_whose_values_equal_the_truth(ws, library):
    reader, _keys = delivery_in(ws, library)
    workbook, pdf = synthetic.delivery()[:2]
    study = settle_230_23(ws, reader)
    assert review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False) == ()
    assert datasets(ws) == []
    plan, confirmation, done = land(ws, study, reader, library=library)
    assert done.confirmation == confirmation.id and done.datasets == tuple(d.id for d in plan.datasets)
    assert done.pending == plan.held and done.rejected_legacy == () and done.dissolution_records == 0
    landed = {d.analyte: d for d in datasets(ws)}
    assert set(landed) == {synthetic.DRUG, synthetic.METABOLITE} and len(done.datasets) == 2
    parent = landed[synthetic.DRUG]
    # accepted, a client's, named after the confirmation in its source, note and decision
    for found in landed.values():
        assert found.state is EvidenceState.ACCEPTED and found.origin is Origin.CLIENT and found.provider == "CLIENT"
        assert found.extraction == "CELL" and found.purpose == "model_building" and found.matrix == "plasma"
        assert found.source.doc_sha256 == sha_of(workbook) and found.source.locator == f"Delivery confirmation {confirmation.id}"
        assert found.decision_reason == f"confirmed on Delivery ({confirmation.id}, signature {SIGNATURE})"
        assert found.note.startswith(found.decision_reason) and found.decided_by == BY
        assert landing.is_delivery_dataset(found)
    digest = confirmation.record["subject_digest"]
    analyte = next(e.id for e in reader.entities("analyte") if e.label == synthetic.DRUG and e.source.startswith(sha_of(workbook)))
    assert parent.id == "ds-" + hashlib.sha256(f"{digest}||{analyte}|plasma".encode()).hexdigest()[:10]
    # the study record: what the files state (n from the synopsis, the dose and food state from the sheet's title, the
    # LLOQ from its footnote) and what a person entered; nothing assumed
    assert parent.study == {"study_id": "230-23", "n": 24, "route": "oral", "dose_mg": 50.0, "formulation": "ir_tablet",
                            "food_state": "fasted", "n_timepoints": 6, "statistic": "individual", "matrices": ["plasma"],
                            "lloq": 0.5}
    assert (parent.time_unit, parent.unit) == ("h", "ng/ml")
    # every truth value of the table is a point of its series: a number as written, BLQ and "<0.5" as None; a missing
    # sample and an above-range mark are no point, and the note says so
    truth = [v for v in workbook.values if v.table == "fasting-individual" and v.field == "concentration"]
    assert truth
    points = 0
    for value in truth:
        series = series_of(parent, value.subject or "arithmetic mean")
        time = float(value.time)
        if value.value.upper() == "BLQ" or value.value.startswith("<"):
            assert series.values[series.times.index(time)] is None, value
        elif number(value.value) is None or value.value.startswith(">"):
            assert time not in series.times, value
            continue
        else:
            assert series.values[series.times.index(time)] == number(value.value), value
        points += 1
    assert points == sum(len(s.times) for s in parent.series) and "left out" in parent.note
    individuals = [s for s in parent.series if s.statistic == "individual"]
    assert [s.name for s in individuals] == sorted({v.subject for v in truth if v.subject}) and individuals
    assert all(s.error is None and s.error_kind == "none" for s in individuals)
    # the mean row keeps its SD and its n per time; the BLQ pre-dose point has no SD and no longer drops the others
    mean = series_of(parent, "arithmetic mean")
    stated = {float(v.time): v for v in truth if not v.subject}
    assert mean.error_kind == "SD" and mean.values[0] is None and mean.error[0] is None
    assert [e for e in mean.error[1:]] == [float(stated[t].spread) for t in mean.times[1:]]
    assert mean.n_at == tuple(int(stated[t].n) for t in mean.times) and mean.n == mean.n_at[0]
    kept = [i for i, v in enumerate(mean.values) if v is not None]
    assert judged_sd(mean, kept, unit=parent.unit) == {"sd": [float(stated[t].spread) for t in mean.times[1:]]}
    # the metabolite's SE lands as an SE (D1a's profile converts it with its n per time)
    metabolite = series_of(landed[synthetic.METABOLITE], "arithmetic mean")
    assert metabolite.error_kind == "SE" and landed[synthetic.METABOLITE].study["lloq"] == 0.2
    assert landed[synthetic.METABOLITE].study["statistic"] == "mean_sd"
    # the reported PK parameters, their unit as written
    assert {(r.parameter, r.value, r.unit) for r in parent.reported} == {
        (v.field.removeprefix("pk."), float(v.value), v.unit) for v in workbook.values if v.field.startswith("pk.")}
    # a value joined from the synopsis (the n) flags the dataset, and the flag survives check_dataset
    link = next(v for v in reader.values(study=study) if v.field == "link.study_id")
    flag = f"cross_file: {pdf.name} via {link.id}"
    assert flag in parent.flags and flag in check_dataset(parent).flags and pdf.name in parent.note
    assert flag in landed[synthetic.METABOLITE].flags
    # what never lands is listed, and stays in the ledger
    assert any("excretion" in held and "§11.8" in held for held in done.pending)
    assert reader.values(study=study, field="excretion.amount")
    # one audit event for the landing, with the line's hash; each dataset is an artifact its owner wrote
    (event,) = events(ws, "intake.land")
    (line,) = IntakeStore(ws).review.entries("landed")
    assert event.after == {"confirmation": confirmation.id, "datasets": list(done.datasets), "evidence": [],
                           "dissolution_records": 0, "row_hash": line.hash}
    assert {v.status for v in reader.values(study=study)} == {"confirmed"}
    assert review.landing_incomplete(ws, "study", study, confirmation.record_sha256) is None
    assert next(r for r in review.subjects(ws, reader=reader) if r["subject"] == study)["confirmation"]["landed"]
    assert IntakeStore(ws).review.verify() == []


def test_the_sheets_count_as_read_and_a_second_land_writes_nothing(ws, library):
    reader, _keys = delivery_in(ws, library)
    workbook, pdf = synthetic.delivery()[:2]
    sid, pdf_sid = submission_id(sha_of(workbook)), submission_id(sha_of(pdf))
    study = settle_230_23(ws, reader)
    waiting = {d["sheet"] for d in drafts(ws)}
    assert {"Fasting", "Fed"} <= waiting                         # today's reading of each sheet waits on its card
    plan, confirmation, done = land(ws, study, reader, library=library)
    assert set(plan.sheets) == {(sid, "Fasting"), (sid, "Summary"), (sid, "Urine"), (pdf_sid, "p1")}
    # the synopsis page the study's facts were read from is recorded on the PDF's file, with no dataset of its own
    (page,) = submission(ws, pdf_sid)["mappings"]
    assert page["recipe"]["tables"] == [{"sheet": "p1"}] and page["datasets"] == []
    # the Delivery recipe names the sheets the bound values are anchored in: sheet_intake counts them as read
    (mapping,) = submission(ws, sid)["mappings"]
    assert mapping["recipe"] == {"recipe_id": f"delivery-{confirmation.id}", "version": 1,
                                 "tables": [{"sheet": "Fasting"}, {"sheet": "Summary"}, {"sheet": "Urine"}]}
    assert mapping["datasets"] == list(done.datasets)
    assert {d["sheet"] for d in drafts(ws)} == waiting - {"Fasting"}          # its legacy draft is gone, the others wait
    with pytest.raises(SheetIntakeError, match="read already"):
        finish(ws, library, sid, "Fasting", {"n": 24, "formulation": "ir_tablet", "purpose": "model_building"}, by=BY)
    # a second land of the same confirmation writes nothing: no artifact version, no line, no event
    before = (len(ws.list()), [len(ws.versions(v.kind, v.id)) for v in ws.list()], len(IntakeStore(ws).review.entries()),
              len(events(ws)))
    again = landing.land(ws, library, confirmation, plan, by=BY)
    assert again == done
    assert (len(ws.list()), [len(ws.versions(v.kind, v.id)) for v in ws.list()], len(IntakeStore(ws).review.entries()),
            len(events(ws))) == before
    assert len(events(ws, "intake.land")) == 1


def test_an_interrupted_landing_completes_with_what_is_missing_and_nothing_twice(ws, library, monkeypatch):
    reader, _keys = delivery_in(ws, library)
    study = settle_230_23(ws, reader)
    plan = plan_of(ws, study, reader, library=library)
    confirmation = confirm(ws, study, reader)                      # every refusal was checked: settle_230_23

    def crash(*args: Any, **kwargs: Any) -> None:
        raise OSError("the disk is full")

    monkeypatch.setattr(landing, "_record_recipes", crash)
    with pytest.raises(OSError):
        landing.land(ws, library, confirmation, plan, by=BY)
    monkeypatch.undo()
    assert [d.state for d in datasets(ws)] == [EvidenceState.ACCEPTED] * 2 and landing.landed(ws, confirmation.id) is None
    # the route finds the confirmation by its record hash and goes straight to the landing: no new signature
    reader.refresh()
    _record, sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
    assert sha == confirmation.record_sha256
    assert review.landing_incomplete(ws, "study", study, sha) == confirmation
    versions = {d.id: len(ws.versions(ArtifactKind.DATASET, d.id)) for d in datasets(ws)}
    done = landing.land(ws, library, confirmation, plan_of(ws, study, reader, library=library), by=BY)
    assert done.datasets == tuple(d.id for d in plan.datasets)
    assert {d.id: len(ws.versions(ArtifactKind.DATASET, d.id)) for d in datasets(ws)} == versions       # nothing twice
    assert len(IntakeStore(ws).review.entries("confirmation")) == 1 == len(IntakeStore(ws).review.entries("landed"))
    assert review.landing_incomplete(ws, "study", study, sha) is None


def test_plan_landing_names_a_missing_study_record_field_instead_of_raising_later(ws, library):
    reader, _keys = delivery_in(ws, library)
    study = study_of(reader, "230-23")
    with pytest.raises(landing.LandingError) as refused:
        plan_of(ws, study, reader)
    assert "230-23: the study record needs route" in str(refused.value) and "needs intended_use" in str(refused.value)
    # the bound record says so too, where the card shows what the landing would hold back
    record, _sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
    assert record["held"] == [f"the landing is refused: {refused.value}"]
    enter(reader, study, route="oral", intended_use="model_building")
    with pytest.raises(landing.LandingError, match="needs formulation"):       # an oral study's dosage form, never assumed
        plan_of(ws, study, reader)
    enter(reader, study, formulation="ir_tablet")
    assert len(plan_of(ws, study, reader).datasets) == 2 and datasets(ws) == []       # planning writes nothing
    # an infusion needs its time; a study with several arms is named per arm
    other = study_of(reader, "230-26")
    enter(reader, other, n=8, route="iv_infusion", intended_use="model_building")
    with pytest.raises(landing.LandingError) as refused:
        plan_of(ws, other, reader)
    assert "230-26-Cohort 1: the study record needs infusion_time_min" in str(refused.value)
    assert "230-26-Cohort 2: the study record needs infusion_time_min" in str(refused.value)
    enter(reader, other, infusion_time_min=30.0)
    planned = plan_of(ws, other, reader)
    assert sorted((d.study["study_id"], d.study["dose_mg"], d.study["infusion_time_min"]) for d in planned.datasets) == [
        ("230-26-Cohort 1", 10.0, 30.0), ("230-26-Cohort 2", 30.0, 30.0)]
    assert all(d.extraction == "TABLE" and d.source.page in (4, 5) for d in planned.datasets)      # read from a PDF


# --- nothing is loaded twice (§2) -------------------------------------------------------------------------------------


def _recorded(ws: Workspace, sid: str, found: ObservedDataset, sheet: str, recipe_id: str) -> ObservedDataset:
    """A legacy dataset as today's sheet reader saves one: proposed, and listed by a recipe of its sheet."""
    made = propose_dataset(ws, found, actor="code")
    client_data.record_mapping(ws, sid, recipe={"recipe_id": recipe_id, "version": 1, "tables": [{"sheet": sheet}]},
                               dataset_ids=[made.id], dissolution=[], by="code")
    return made


def _legacy(study_id: str, sha: str, times: tuple[float, ...], values: tuple[float | None, ...], key: str) -> ObservedDataset:
    study = {"study_id": study_id, "n": 6, "route": "oral", "dose_mg": 100.0, "formulation": "ir_tablet",
             "food_state": "fed", "n_timepoints": len(times), "statistic": "mean", "lloq": 0.5}
    return ObservedDataset(id="ds-" + hashlib.sha256(key.encode()).hexdigest()[:10], kind="profile", study=study,
                           series=(Series(times=times, values=values, n=6),), origin=Origin.CLIENT, extraction="CELL",
                           provider="CLIENT", source=SourceRef(doc_sha256=sha, page=1, title="messy-delivery.xlsx"))


def test_legacy_datasets_of_the_same_source_are_rejected_and_another_studys_table_is_not(ws, library):
    reader, _keys = delivery_in(ws, library)
    workbook = synthetic.delivery()[0]
    sha, sid = sha_of(workbook), submission_id(sha_of(workbook))
    study = study_of(reader, "231-24")
    enter(reader, study, n=6, route="oral", formulation="ir_tablet", intended_use="model_building")
    # today's reader saves the Fed sheet once a person gives what it needs: its datasets wait on the legacy card
    saved = finish(ws, library, sid, "Fed", {"n": 6, "formulation": "ir_tablet", "purpose": "model_building"}, by=BY)
    assert saved and all(dataset(ws, i).state is EvidenceState.PROPOSED for i in saved)
    assert {str(dataset(ws, i).study["study_id"]) for i in saved} == {"231-24"}
    # the same table read under a study id made from the file name: no name in common, the same points
    truth = [v for v in workbook.values if v.table == "fed-individual" and v.field == "concentration" and not v.subject]
    quantified = [(float(v.time), float(v.value)) for v in truth if number(v.value) is not None]
    from_name = _recorded(ws, sid, _legacy("messy-delivery", sha, tuple(t for t, _v in quantified),
                                           tuple(v for _t, v in quantified), "by file name"), "Fed", "legacy-by-name")
    # another study's table on the same sheet: another id, other numbers
    neighbour = _recorded(ws, sid, _legacy("999-99", sha, (0.25, 0.75), (77.7, 66.6), "neighbour"), "Fed", "legacy-neighbour")
    # and a dataset of the same study id read from another file
    elsewhere = propose_dataset(ws, _legacy("231-24", "e" * 64, (1.0,), (5.0,), "elsewhere"), actor="code")
    overlap = {d.id for d in landing.legacy_overlap(ws, "study", study, reader=reader)}
    assert overlap == {*saved, from_name.id} and neighbour.id not in overlap and elsewhere.id not in overlap
    assert landing.legacy_overlap(ws, "product", reader.entities("product")[0].id, reader=reader) == []
    row = next(r for r in review.subjects(ws, reader=reader) if r["subject"] == study)
    assert set(row["loaded_elsewhere"]) == overlap

    # an accepted one refuses the confirmation; rejecting it on the legacy card frees it
    decide_dataset(ws, saved[0], state=EvidenceState.ACCEPTED, reason="confirmed on the client-review card", by=BY)
    loaded = [b for b in review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False)
              if b.code == "LOADED_ON_CLIENT_REVIEW"]
    assert [b.ids for b in loaded] == [(saved[0],)]
    decide_dataset(ws, saved[0], state=EvidenceState.REJECTED, reason="to be confirmed on Delivery", by=BY)
    assert not any(b.code == "LOADED_ON_CLIENT_REVIEW"
                   for b in review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False))

    plan, confirmation, done = land(ws, study, reader, library=library)
    still_proposed = {from_name.id, *saved[1:]}
    assert set(plan.reject_legacy) == still_proposed == set(done.rejected_legacy)
    for legacy_id in still_proposed:
        rejected = dataset(ws, legacy_id)
        assert rejected.state is EvidenceState.REJECTED
        assert rejected.decision_reason == f"replaced by Delivery confirmation {confirmation.id}"
    assert dataset(ws, neighbour.id).state is EvidenceState.PROPOSED and dataset(ws, elsewhere.id).state is EvidenceState.PROPOSED
    accepted = [d for d in datasets(ws) if d.state is EvidenceState.ACCEPTED]
    assert [d.id for d in accepted] == list(done.datasets) and accepted[0].study["study_id"] == "231-24"
    # the legacy routes' guard: what the signed confirmation covers is refused there, by the same overlap
    assert review.covered_by_confirmation(ws, dataset(ws, from_name.id)) == confirmation
    assert review.covered_by_confirmation(ws, dataset(ws, saved[-1])) == confirmation
    for free in (neighbour.id, elsewhere.id, done.datasets[0]):
        assert review.covered_by_confirmation(ws, dataset(ws, free)) is None
    again = _recorded(ws, sid, _legacy("Fed sheet", sha, tuple(t for t, _v in quantified), tuple(v for _t, v in quantified),
                                       "read again"), "Fed", "legacy-again")
    assert review.covered_by_confirmation(ws, again) == confirmation


def test_a_correction_supersedes_what_the_earlier_confirmation_landed(ws):
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    _plan, first, done = land(ws, ids["study"], reader)
    (first_id,) = done.datasets
    fact = reader.enter(supersedes=ids["c1"], value=11.5, why="the report says 11.5", by=BY)
    _plan, second, again = land(ws, ids["study"], reader, signature="sig-0002")
    (second_id,) = again.datasets
    assert second.supersedes == first.id and second_id != first_id
    old, new = dataset(ws, first_id), dataset(ws, second_id)
    assert old.state is EvidenceState.REJECTED and old.decision_reason == f"superseded by Delivery confirmation {second.id}"
    assert new.state is EvidenceState.ACCEPTED and 11.5 in new.series[0].values and 11.5 not in old.series[0].values
    assert reader.value(fact.id).confirmation == second.id
    assert [d.id for d in datasets(ws) if d.state is EvidenceState.ACCEPTED] == [second_id]       # one dataset per study


# --- what lands, and what is held back while the rest lands ---------------------------------------------------------------


def _study(book: Book, label: str, **facts: Any) -> dict[str, str]:
    """A study with the facts its record needs (each replaceable), and one analyte; no concentration yet."""
    study, analyte = book.entity("study", label), book.entity("analyte", synthetic.DRUG)
    stated = {"dose": (50.0, {"unit": "mg"}), "n": (12, {}), "route": ("oral", {}), "formulation": ("ir_tablet", {}),
              "food_state": ("fasted", {}), "intended_use": ("model_building", {}), **facts}
    for field, given in stated.items():
        if given is not None:
            book.fact(field, given[0], {"study": study}, **given[1])
    return {"study": study, "analyte": analyte, "profile": {"study": study, "analyte": analyte, "matrix": "plasma"}}


def _points(book: Book, entity: dict[str, Any], values: tuple[Any, ...], *, time_unit: str = "h", unit: str = "ng/mL",
            statistic: str = "arithmetic_mean", **kw: Any) -> list[str]:
    return [book.fact("concentration", value, entity, unit=unit, time=float(i + 1), time_unit=time_unit, statistic=statistic,
                      **kw) for i, value in enumerate(values)]


def test_a_time_unit_lands_as_the_three_the_model_reads_and_a_dose_in_grams_as_milligrams(ws):
    book = Book(ws)
    hours = _study(book, "EXA-501")
    _points(book, hours["profile"], (10.0, 20.0, 12.0), time_unit="hr")
    days = _study(book, "EXA-502", dose=(0.5, {"unit": "g"}))
    _points(book, days["profile"], (5.0, 4.0), time_unit="days")
    weeks = _study(book, "EXA-503")
    _points(book, weeks["profile"], (5.0, 4.0), time_unit="weeks")
    per_kg = _study(book, "EXA-504", dose=(2.0, {"unit": "mg/kg"}))
    _points(book, per_kg["profile"], (5.0, 4.0), time_unit="min")
    odd = _study(book, "EXA-505", dose=(3.0, {"unit": "tablets"}))
    _points(book, odd["profile"], (5.0, 4.0))
    reader = Ledger(ws)
    (found,) = plan_of(ws, hours["study"], reader).datasets
    assert found.time_unit == "h" and found.series[0].times == (1.0, 2.0, 3.0) and found.study["dose_mg"] == 50.0
    # a dose in g has no mg value until the ledger derives it; then the derived fact is the dose, and nothing is retyped
    held = plan_of(ws, days["study"], reader)
    assert held.datasets == () and "no derived dose in mg yet" in held.held[0]
    (derived,) = [f for f in reader.derive() if f.field == "dose"]
    assert (derived.value, derived.unit, derived.compute) == (500.0, "mg", "compute-1/dose_to_mg")
    (found,) = plan_of(ws, days["study"], reader).datasets
    assert found.time_unit == "day" and found.study["dose_mg"] == 500.0 and "dose_per_kg" not in found.study
    # a time unit outside the time table holds the profile back; mg/kg lands with dose_per_kg; another dose unit holds
    plan = plan_of(ws, weeks["study"], reader)
    assert plan.datasets == () and plan.held == (
        f"EXA-503: {synthetic.DRUG} in plasma: a time or its unit is not in the time table (min, h, day): not landed",)
    (found,) = plan_of(ws, per_kg["study"], reader).datasets
    assert (found.time_unit, found.study["dose_mg"], found.study["dose_per_kg"]) == ("min", 2.0, True)
    plan = plan_of(ws, odd["study"], reader)
    assert plan.datasets == () and "the dose unit 'tablets' is outside the mass table" in plan.held[0]
    # the actual sampling times are used when every point has one, and the note says so
    actual = _study(book, "EXA-506")
    for nominal, taken, value in ((1.0, 1.05, 10.0), (2.0, 2.1, 20.0)):
        book.fact("concentration", value, {**actual["profile"], "subject": "001"}, unit="ng/mL", time=nominal, time_unit="h",
                  time_actual=taken, statistic="individual")
    reader.refresh()
    (found,) = plan_of(ws, actual["study"], reader).datasets
    assert found.series[0].times == (1.05, 2.1) and "the actual sampling times" in found.note


def test_a_field_whose_name_carries_its_unit_lands_only_in_that_unit(ws, library):
    """infusion_time_min, dosing_interval_h, strength_mg and percent_dissolved: a value that states no unit or the
    name's own unit lands as written; any other unit holds the arm or the run back, named, and nothing is converted."""
    book = Book(ws)
    infusion = {"route": ("iv_infusion", {}), "formulation": None, "food_state": None}
    stated = _study(book, "EXA-511", **infusion, infusion_time_min=(30.0, {"unit": "minutes"}),
                    dosing_interval_h=(24.0, {"unit": "hr"}))
    bare = _study(book, "EXA-512", **infusion, infusion_time_min=(30.0, {}))
    hours = _study(book, "EXA-513", **infusion, infusion_time_min=(0.5, {"unit": "h"}))
    daily = _study(book, "EXA-514", dosing_interval_h=(1.0, {"unit": "day"}))
    for ids in (stated, bare, hours, daily):
        _points(book, ids["profile"], (10.0, 20.0))
    reader = Ledger(ws)
    (found,) = plan_of(ws, stated["study"], reader).datasets
    assert (found.study["infusion_time_min"], found.study["dosing_interval_h"]) == (30.0, 24.0)
    (found,) = plan_of(ws, bare["study"], reader).datasets
    assert found.study["infusion_time_min"] == 30.0
    for ids, field, written, needs in ((hours, "infusion_time_min", "'h'", "takes min"),
                                       (daily, "dosing_interval_h", "'day'", "takes h")):
        plan = plan_of(ws, ids["study"], reader)
        (held,) = plan.held
        assert plan.datasets == () and field in held and written in held and needs in held and held.endswith("not landed")
        assert "nothing is converted" in held
        value = next(v for v in reader.values(study=ids["study"], field=field))
        assert value.id in held and str(value.value) not in held          # the value is named by its id, never its number
    # a product: a strength in g, and a percent dissolved written as a fraction of 1
    sha = client_file(ws, library)
    notes = Book(ws, sha=sha, name="client-notes.xlsx", sheet="Notes")
    method = {"apparatus": "USP II (paddle)", "rpm": "50", "medium": "HCl buffer", "ph": "1.2", "volume_ml": "900"}

    def product(label: str, strength: tuple[float, str | None], unit: str, values: tuple[float, ...]) -> str:
        made = notes.entity("product", label)
        notes.fact("product_role", "TEST", {"product": made})
        notes.fact("strength_mg", strength[0], {"product": made}, unit=strength[1])
        for i, value in enumerate(values):
            notes.fact("percent_dissolved", value, {"product": made}, unit=unit, time=float(15 * (i + 1)), time_unit="min",
                       statistic="arithmetic_mean", spread=2.0, spread_kind="SD", n=6, conditions=method)
        return made

    good = product("Exampleamide IR tablet", (50.0, "MG"), "percent", (21.0, 55.0))
    grams = product("Exampleamide ER tablet", (0.5, "g"), "%", (21.0, 55.0))
    fraction = product("Exampleamide capsule", (50.0, None), "fraction", (0.21, 0.55))
    reader.refresh()
    ((_sid, rows),) = plan_of(ws, good, reader, "product").dissolution
    assert [(r["values"]["strength_mg"], r["values"]["mean"]) for r in rows] == [(50.0, 21.0), (50.0, 55.0)]
    for made, field, written, needs in ((grams, "strength_mg", "'g'", "takes mg"),
                                        (fraction, "percent_dissolved", "'fraction'", "takes %")):
        plan = plan_of(ws, made, reader, "product")
        (held,) = [text for text in plan.held if "is written in" in text]
        assert plan.dissolution == () and field in held and written in held and needs in held and held.endswith("not landed")


def test_what_the_models_code_refuses_is_held_back_while_the_rest_lands(ws):
    book = Book(ws)
    covered(book)
    ids = _study(book, "EXA-601")
    study = ids["study"]
    good = _points(book, ids["profile"], (10.0, 20.0, 12.0))
    book.fact("lloq", 0.5, ids["profile"], unit="ng/mL")
    analytes = {name: book.entity("analyte", name) for name in ("M-units", "M-occasions", "M-lloqs", "M-negative")}

    def profile(name: str, **labels: Any) -> dict[str, Any]:
        return {"study": study, "analyte": analytes[name], "matrix": "plasma", **labels}

    _points(book, profile("M-units"), (1.0, 2.0), unit="IU/mL")                        # a unit the tables lack
    _points(book, profile("M-occasions", occasion="Day 1"), (1.0, 2.0))                # two occasions
    _points(book, profile("M-occasions", occasion="Day 14"), (3.0, 4.0))
    _points(book, profile("M-lloqs"), (1.0, 2.0))                                      # two LLOQs and no person's entry
    book.fact("lloq", 0.1, profile("M-lloqs"), unit="ng/mL")
    book.fact("lloq", 0.2, profile("M-lloqs"), unit="ng/mL")
    _points(book, profile("M-negative"), (1.0, -2.0))                                  # a negative value
    reader = Ledger(ws)
    plan = plan_of(ws, study, reader)
    (found,) = plan.datasets
    assert found.analyte == synthetic.DRUG and found.series[0].values == (10.0, 20.0, 12.0) and found.study["lloq"] == 0.5
    held = {text.split(": ")[1].split(" in ")[0]: text for text in plan.held}
    assert set(held) == set(analytes)
    assert "a concentration unit the unit tables lack" in held["M-units"]
    assert "OCCASIONS_NOT_LANDED" in held["M-occasions"] and "§11.27" in held["M-occasions"]
    assert "ONE_LLOQ_PER_PROFILE" in held["M-lloqs"] and "no person's lloq entry" in held["M-lloqs"]
    assert "a negative value" in held["M-negative"]
    assert all(text.endswith("not landed") for text in plan.held)
    # no reason names a value or an LLOQ (a blinded study's card shows the reasons too)
    assert not any(token in text for text in plan.held for token in ("0.1", "0.2", "-2", "IU"))
    # the rest lands, and what is held back is on the landing's record
    _plan, confirmation, done = land(ws, study, reader)
    assert done.datasets == (found.id,) and done.pending == plan.held
    assert dataset(ws, found.id).state is EvidenceState.ACCEPTED and len(datasets(ws)) == 1
    assert confirmation.record["held"] == list(plan.held)
    # a person's LLOQ entry for that profile settles it: the next confirmation lands it too
    reader.enter(entity=EntityRef(**profile("M-lloqs")), field="lloq", value=0.1, unit="ng/mL",
                 why="the validation report states 0.1 ng/mL", by=BY)
    later = plan_of(ws, study, reader)
    assert {d.analyte: d.study.get("lloq") for d in later.datasets} == {synthetic.DRUG: 0.5, "M-lloqs": 0.1}
    assert not any("M-lloqs" in text for text in later.held)
    assert all(v.id in {x.id for x in reader.values(study=study)} for v in map(reader.value, good))
    # an LLOQ in another unit than the values is not converted and not put in the study record
    other = _study(book, "EXA-602")
    _points(book, other["profile"], (10.0, 20.0))
    book.fact("lloq", 0.5, other["profile"], unit="nmol/L")
    reader.refresh()
    (found,) = plan_of(ws, other["study"], reader).datasets
    assert "lloq" not in found.study and "not converted" in found.note


def test_a_spread_lands_only_as_the_rules_say(ws):
    book = Book(ws)
    ids = _study(book, "EXA-701")
    study = ids["study"]
    cases = {"plain-sd": ("geometric_mean", "SD"), "geo-sd": ("geometric_mean", "geoSD"), "cv": ("arithmetic_mean", "CV%"),
             "geo-cv": ("arithmetic_mean", "geoCV%"), "median": ("median", "SD"), "no-kind": ("arithmetic_mean", None)}
    for name, (statistic, kind) in cases.items():
        analyte = book.entity("analyte", name)
        entity = {"study": study, "analyte": analyte, "matrix": "plasma"}
        for i, (value, spread) in enumerate(((10.0, 1.5), (20.0, 1.4))):
            book.fact("concentration", value, entity, unit="ng/mL", time=float(i + 1), time_unit="h", statistic=statistic,
                      spread=spread, spread_kind=kind, n=12)
    reader = Ledger(ws)
    plan = plan_of(ws, study, reader)
    landed = {d.analyte: d for d in plan.datasets}
    assert set(landed) == set(cases)                                # every profile lands; only its spread may not
    series = {name: found.series[0] for name, found in landed.items()}
    # a geometric mean with a plain "SD": no error, and the note says why (§11.5: ambiguous)
    assert series["plain-sd"].error is None and series["plain-sd"].error_kind == "none"
    assert "the SD of the geometric mean is not landed (intake rules landing.spreads_landed)" in landed["plain-sd"].note
    assert "it stays in the ledger" in landed["plain-sd"].note
    # a source that says geometric SD lands it as SD (D1a sends it as a geometric factor); a CV% stays a CV%
    assert (series["geo-sd"].error, series["geo-sd"].error_kind, series["geo-sd"].statistic) == ((1.5, 1.4), "SD", "geometric_mean")
    assert (series["cv"].error, series["cv"].error_kind) == ((1.5, 1.4), "CV%")
    for name in ("geo-cv", "median"):
        assert series[name].error is None and "is not landed" in landed[name].note
    # a spread of no stated kind is held back, listed; its values land
    assert series["no-kind"].error is None and series["no-kind"].values == (10.0, 20.0)
    assert [text for text in plan.held if "SPREAD_KIND_MISSING" in text] and len(plan.held) == 1
    assert all(s.n == 12 and s.n_at is None for s in series.values())
    # an interval is not landed (a series has none), and the note names it
    other = _study(book, "EXA-702")
    book.fact("concentration", 10.0, other["profile"], unit="ng/mL", time=1.0, time_unit="h", statistic="arithmetic_mean",
              interval=(8.0, 12.0), interval_kind="CI", interval_level=90.0)
    reader.refresh()
    (found,) = plan_of(ws, other["study"], reader).datasets
    assert "intervals (CI, range) are not landed" in found.note and found.series[0].error is None


# --- a product's dissolution ----------------------------------------------------------------------------------------------


def test_dissolution_rows_become_profiles_through_the_register_with_their_sd_and_n(ws, library):
    reader, _keys = delivery_in(ws, library)
    workbook = synthetic.delivery()[0]
    sid = submission_id(sha_of(workbook))
    (product,) = [e.id for e in reader.entities("product") if e.label == "Exampleamide IR tablet"]
    truth = [v for v in workbook.values if v.field == "percent_dissolved"]
    vessels = [v for v in truth if v.table == "dissolution-vessels"]
    summary = [v for v in truth if v.table == "dissolution-summary"]
    plan = plan_of(ws, product, reader, "product")
    ((plan_sid, rows),) = plan.dissolution
    assert plan_sid == sid and plan.datasets == () and plan.evidence == ()
    # template-shaped rows: one per time and run, the vessels or the mean, SD and n, each value with its cell
    by_medium = {medium: [r for r in rows if r["values"]["medium"] == medium] for medium in ("HCl buffer", "phosphate buffer")}
    assert len(by_medium["HCl buffer"]) == len({v.time for v in vessels}) and len(by_medium["phosphate buffer"]) == len(summary)
    first = by_medium["HCl buffer"][0]["values"]
    assert {k: first[k] for k in ("product", "role", "strength_mg", "batch", "ph", "time_unit")} == {
        "product": "Exampleamide IR tablet", "role": "TEST", "strength_mg": 50.0, "batch": "L2301", "ph": 1.2,
        "time_unit": "min"}
    names = sorted({v.vessel for v in vessels}, key=lambda name: int(name.split()[-1]))
    for value in vessels:
        row = next(r for r in by_medium["HCl buffer"] if r["values"]["time"] == float(value.time))
        column = f"vessel_{names.index(value.vessel) + 1}"
        assert row["values"][column] == float(value.value) and row["cells"][column] == value.locator
    for value in summary:
        row = next(r for r in by_medium["phosphate buffer"] if r["values"]["time"] == float(value.time))
        assert (row["values"]["mean"], row["values"]["sd"], row["values"]["n"]) == (float(value.value), float(value.spread), 12)
        assert row["cells"]["mean"] == value.locator and row["cells"]["sd"] == dict(value.locators)["spread"]
    # what else the product's tables state stays in the ledger, listed
    assert any("product attributes" in text and "§11.28" in text for text in plan.held)
    before = {p["id"] for p in profiles(ws)}
    _plan, confirmation, done = land(ws, product, reader, "product", library=library)
    assert done.dissolution_records == len(rows) and done.datasets == () == done.evidence
    stored = submission(ws, sid)["dissolution"]
    assert len(stored) == len(rows) and {r["tag"] for r in stored} == {f"delivery-{confirmation.id}"}
    made = [p for p in profiles(ws) if p["id"] not in before and "times_min" in p]
    assert len(made) == 2
    by_ph = {p["key"]["ph"]: p for p in made}
    assert by_ph[1.2]["n"] == len(names) == len(by_ph[1.2]["vessels"]) and by_ph[1.2]["key"]["batch"] == "L2301"
    assert by_ph[6.8]["n"] == 12 and by_ph[6.8]["vessels"] == []                     # the summary keeps its n = 12
    assert by_ph[6.8]["sd"] == [float(v.spread) for v in sorted(summary, key=lambda v: float(v.time))]
    assert by_ph[6.8]["mean"] == [float(v.value) for v in sorted(summary, key=lambda v: float(v.time))]
    assert by_ph[6.8]["times_min"] == sorted(float(v.time) for v in summary)
    # the Dissolution sheet counts as read: its legacy draft is gone; a second land writes nothing
    assert "Dissolution" not in {d["sheet"] for d in drafts(ws)}
    versions = len(ws.versions(ArtifactKind.CLIENT_SUBMISSION, sid))
    assert landing.land(ws, library, confirmation, plan, by=BY) == done
    assert len(ws.versions(ArtifactKind.CLIENT_SUBMISSION, sid)) == versions
    # a document re-read of the file keeps the rows the confirmation landed
    client_data.record_document_reading(ws, sid, facts=[], dissolution=[], links=[], compositions=[], figures=[],
                                        datasets=[], refused=[], digitization=[], summary="read again", run_id="ar_1", by="code")
    assert len(submission(ws, sid)["dissolution"]) == len(rows)


def test_two_runs_that_differ_only_in_temperature_are_held_back_and_a_file_with_no_record_waits(ws, library):
    sha = client_file(ws, library)
    book = Book(ws, sha=sha, name="client-notes.xlsx", sheet="Notes")
    covered(book)
    product = book.entity("product", "Exampleamide ER tablet")
    batch = book.entity("batch", "B501", parent=product)
    on = {"product": product, "batch": batch}
    book.fact("product_role", "TEST", {"product": product})
    method = {"apparatus": "USP II (paddle)", "rpm": "50", "medium": "phosphate buffer", "ph": "6.8", "volume_ml": "900"}

    def run(conditions: dict[str, str], values: tuple[float, ...], target: Book = book, entity: dict[str, str] = on) -> None:
        for i, value in enumerate(values):
            target.fact("percent_dissolved", value, entity, unit="%", time=float(15 * (i + 1)), time_unit="min",
                        statistic="arithmetic_mean", spread=2.0, spread_kind="SD", n=6, conditions=conditions)

    run({**method, "temperature_c": "37"}, (40.0, 70.0, 95.0))
    run({**method, "temperature_c": "25"}, (30.0, 55.0, 80.0))                       # the same key, another temperature
    run({**method, "medium": "HCl buffer", "ph": "1.2", "temperature_c": "37"}, (50.0, 80.0, 99.0))
    reader = Ledger(ws)
    plan = plan_of(ws, product, reader, "product")
    ((sid, rows),) = plan.dissolution
    assert sid == submission_id(sha) and {r["values"]["medium"] for r in rows} == {"HCl buffer"} and len(rows) == 3
    assert rows[0]["values"] == {"product": "Exampleamide ER tablet", "role": "TEST", "strength_mg": None, "batch": "B501",
                                 "apparatus": "USP II (paddle)", "rpm": 50.0, "medium": "HCl buffer", "ph": 1.2,
                                 "volume_ml": 900.0, "time": 15.0, "time_unit": "min", "mean": 50.0, "sd": 2.0, "n": 6}
    (held,) = [text for text in plan.held if "DISSOLUTION_RUNS_NOT_KEYED" in text]
    assert "temperature or surfactant" in held and "one would overwrite the other" in held and "pH 6.8" in held
    _plan, _confirmation, done = land(ws, product, reader, "product", library=library)
    assert done.dissolution_records == 3 and held in done.pending
    (profile,) = [p for p in profiles(ws) if "times_min" in p]
    assert profile["key"]["medium"] == "HCl buffer" and profile["n"] == 6 and profile["sd"] == [2.0, 2.0, 2.0]
    # a file today's reader refused has no client-file record: its rows wait, named (§11.13)
    other = Book(ws, sha=hashlib.sha256(b"a semicolon-separated listing").hexdigest(), name="listing.csv", sheet="listing")
    refused = other.entity("product", "Exampleamide oral solution")
    run({**method, "temperature_c": "37"}, (60.0, 90.0), target=other, entity={"product": refused})
    reader.refresh()
    plan = plan_of(ws, refused, reader, "product")
    assert plan.dissolution == () and "listing.csv has no client-file record" in plan.held[0] and "§11.13" in plan.held[0]
    # a mean with another spread than an SD is not a row the register takes
    third = book.entity("product", "Exampleamide capsule")
    for i, value in enumerate((40.0, 70.0)):
        book.fact("percent_dissolved", value, {"product": third}, unit="%", time=float(15 * (i + 1)), time_unit="min",
                  statistic="arithmetic_mean", spread=5.0, spread_kind="CV%", n=6, conditions=method)
    reader.refresh()
    plan = plan_of(ws, third, reader, "product")
    assert plan.dissolution == () and "the register takes an SD" in plan.held[0]


def _dissolution_product(ws: Workspace, library: DocumentLibrary, label: str = "Exampleamide ER tablet"):
    """A product of a stored client file with its role, and a function that writes one run of mean values."""
    sha = client_file(ws, library)
    book = Book(ws, sha=sha, name="client-notes.xlsx", sheet="Notes")
    product = book.entity("product", label)
    book.fact("product_role", "TEST", {"product": product})
    covered(book)

    def run(conditions: dict[str, str], values: tuple[float, ...], entity: str = product) -> None:
        for i, value in enumerate(values):
            book.fact("percent_dissolved", value, {"product": entity}, unit="%", time=float(15 * (i + 1)), time_unit="min",
                      statistic="arithmetic_mean", spread=2.0, spread_kind="SD", n=6, conditions=conditions)

    return book, product, run


METHOD = {"apparatus": "USP II (paddle)", "rpm": "50", "medium": "HCl buffer", "ph": "1.2", "volume_ml": "900"}


def test_a_numeric_condition_written_as_text_is_held_back_and_never_written(ws, library):
    """rpm, pH and volume are numbers of the profile key. A run that writes one as text ("50 rpm") is held back with
    the reason, before anything is signed; `record_delivery_rows` refuses such a row before it writes anything, so a
    register rebuild never meets a key it cannot read."""
    _book, product, run = _dissolution_product(ws, library)
    run(METHOD, (50.0, 80.0))
    run({**METHOD, "medium": "phosphate buffer", "ph": "6.8", "rpm": "50 rpm"}, (40.0, 70.0))
    run({**METHOD, "medium": "acetate buffer", "ph": "4.5", "volume_ml": "900 mL"}, (45.0, 75.0))
    reader = Ledger(ws)
    plan = plan_of(ws, product, reader, "product")
    ((sid, rows),) = plan.dissolution
    assert {r["values"]["medium"] for r in rows} == {"HCl buffer"} and len(rows) == 2
    held = [text for text in plan.held if "not a number" in text]
    assert len(held) == 2 and all(text.endswith("not landed") for text in held)
    assert any("rpm is written '50 rpm'" in text and "phosphate buffer" in text for text in held)
    assert any("volume_ml is written '900 mL'" in text and "acetate buffer" in text for text in held)
    # the owner of the client file's rows checks their types before it writes: nothing is stored, nothing is rebuilt
    versions = len(ws.versions(ArtifactKind.CLIENT_SUBMISSION, sid))
    for name, value in (("rpm", "50 rpm"), ("volume_ml", "900 mL"), ("ph", "pH 6.8"), ("mean", "40"), ("n", 6.5),
                        ("time", None), ("time_unit", "weeks"), ("strength_mg", True)):
        bad = {"values": {**rows[0]["values"], name: value}, "cells": {}}
        with pytest.raises(ValueError, match=name):
            client_data.record_delivery_rows(ws, sid, [rows[0], bad], tag="delivery-cf-9", by=BY)
    assert len(ws.versions(ArtifactKind.CLIENT_SUBMISSION, sid)) == versions and submission(ws, sid)["dissolution"] == []
    assert profiles(ws) == []
    # the run that can land lands; the register holds exactly what the landing says
    _plan, _confirmation, done = land(ws, product, reader, "product", library=library)
    assert done.dissolution_records == 2 and set(held) <= set(done.pending)
    (profile,) = [p for p in profiles(ws) if "times_min" in p]
    assert profile["key"]["medium"] == "HCl buffer" and profile["key"]["rpm"] == 50.0


# --- the compound's evidence --------------------------------------------------------------------------------------------


def test_a_compound_value_lands_as_evidence_and_one_outside_its_physical_range_stays_proposed(ws, library):
    sha = client_file(ws, library, "physchem.xlsx")
    book = Book(ws, sha=sha, name="physchem.xlsx", sheet="Notes")
    good = book.fact("bind.fu", 0.09, {}, conditions={"species": "human"})
    odd = book.fact("phys.logp", 25.0, {})
    covered(book)
    reader = Ledger(ws)
    assert [v.id for v in reader.values(compound=True)] == [good, odd] and review.unassigned(ws, reader=reader) == []
    plan = plan_of(ws, "compound", reader, "compound")
    assert plan.datasets == () and plan.dissolution == ()
    by_target = {item.target: item for item in plan.evidence}
    assert set(by_target) == {"bind.fu", "phys.logp"}
    assert by_target["bind.fu"].flags == () and by_target["bind.fu"].value_pksim == 0.09
    assert any(flag.startswith("outside_physical_range") for flag in by_target["phys.logp"].flags)
    assert plan.held == ("ev phys.logp: outside_physical_range (lands PROPOSED)",)
    assert all(item.provider == "CLIENT" and item.source.doc_sha256 == sha and item.source.locator.startswith("s:'Notes'!")
               for item in plan.evidence)
    assert items(ws) == []                                         # planning writes nothing
    # the card shows it before signing, and the record binds it
    _plan, confirmation, done = land(ws, "compound", reader, "compound", library=library)
    assert confirmation.subject == "compound" and confirmation.record["held"] == list(plan.held)
    assert done.evidence == tuple(item.id for item in plan.evidence) and done.pending == plan.held
    stored = {item.target: item for item in items(ws)}
    assert stored["bind.fu"].state is EvidenceState.ACCEPTED
    assert stored["bind.fu"].decision_reason == f"confirmed on Delivery ({confirmation.id}, signature {SIGNATURE})"
    assert stored["phys.logp"].state is EvidenceState.PROPOSED and stored["phys.logp"].decided_by is None
    assert stored["bind.fu"].note.startswith("confirmed on Delivery") and f"ledger value {good}" in stored["bind.fu"].note
    # a second land writes nothing; the held value still waits for a person
    versions = {item.id: len(ws.versions(ArtifactKind.EVIDENCE, item.id)) for item in items(ws)}
    assert landing.land(ws, library, confirmation, plan, by=BY) == done
    assert {item.id: len(ws.versions(ArtifactKind.EVIDENCE, item.id)) for item in items(ws)} == versions
    (event,) = events(ws, "intake.land")
    assert event.after["evidence"] == list(done.evidence) and event.after["row_hash"] == IntakeStore(ws).review.entries("landed")[0].hash
    assert line_hash(ws, confirmation.id) and AT


def test_a_later_confirmation_of_the_same_values_keeps_the_dataset_and_names_itself(ws):
    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    _plan, first, done = land(ws, ids["study"], reader)
    (dataset_id,) = done.datasets
    # the values are the same, a decision is new: another record, another confirmation, the same dataset
    review.dispose(ws, subject=ids["study"], req_id="REQ-fe.meal", disposition="not_needed", why="a fasted study", by=BY)
    _plan, second, again = land(ws, ids["study"], reader, signature="sig-0002")
    assert second.id != first.id and second.supersedes == first.id and again.datasets == (dataset_id,)
    found = dataset(ws, dataset_id)
    assert found.state is EvidenceState.ACCEPTED and len(datasets(ws)) == 1
    assert found.decision_reason == f"confirmed on Delivery ({second.id}, signature sig-0002)"
    assert found.source.locator == f"Delivery confirmation {first.id}"               # where it first landed


# --- D6's edits beside the landing: a series' spread with a point that states none; the rows a confirmation lands --------


def _template_with_a_blq_row() -> bytes:
    from openpyxl import load_workbook

    from modeler_intake.client_template import build_template

    book = load_workbook(io.BytesIO(build_template()))
    studies = book["Studies"]
    header = [c.value.rstrip("*") for c in studies[1]]
    for arm in ("A", "B"):
        row = dict(study_id="EXA-801", treatment=arm, design="SD", population="healthy", n=12, route="oral", dose=50,
                   dose_unit="mg", formulation="ir_tablet", food_state="fasted", lloq=0.5, lloq_unit="ng/ml",
                   intended_use="model_building")
        studies.append([row.get(h) for h in header])
    # arm A: a pre-dose row below the LLOQ that states no SD; arm B: a quantified row that states none
    for arm, rows in (("A", ((0, "BLQ", None), (1, 42.6, 3.5), (2, 32.1, 1.6))),
                      ("B", ((0, "BLQ", None), (1, 42.6, None), (2, 32.1, 1.6)))):
        for time, mean, sd in rows:
            book["PK_Summary"].append(["EXA-801", arm, time, "h", "arithmetic_mean", mean, sd, "SD" if sd else None, 12, "ng/ml"])
    raw = io.BytesIO()
    book.save(raw)
    return raw.getvalue()


def test_a_blq_row_without_a_spread_no_longer_drops_its_series_spread(ws, library):
    from modeler_intake.records import ConcentrationObservation
    from modeler_intake.records import SourceRef as CellRef
    from modeler_project.blinding import redact_dataset
    from modeler_project.sheet_intake import _points

    # the client template's summary sheet (today's no-AI reading)
    answer = ingest(ws, library, _template_with_a_blq_row(), "client-data.xlsx", by=BY)
    by_arm = {str(d.study["study_id"]): d for d in datasets(ws)}
    assert set(by_arm) == {"EXA-801-A", "EXA-801-B"} and answer["template"]
    kept = by_arm["EXA-801-A"].series[0]
    assert (kept.values, kept.error, kept.error_kind) == ((None, 42.6, 32.1), (None, 3.5, 1.6), "SD")
    dropped = by_arm["EXA-801-B"].series[0]                         # a value with no spread still leaves the series without
    assert (dropped.error, dropped.error_kind) == (None, "none")
    # the dataset is checked as before, and the campaign's profile judges only the kept points: an SD for each of them
    assert check_dataset(by_arm["EXA-801-A"]).series[0].error == (None, 3.5, 1.6)
    assert judged_sd(kept, [1, 2], unit="ng/ml") == {"sd": [3.5, 1.6]}
    # a blinded dataset's errors are withheld whole, as before (D-15)
    assert redact_dataset(by_arm["EXA-801-A"].to_content())["series"][0]["error"] is None

    # a recipe's records (the sheet reader's datasets, and the draft's points on its card)
    def record(series: str, time: float, value: float | None, sd: float | None, blq: bool = False) -> ConcentrationObservation:
        return ConcentrationObservation(
            study_id="EXA-802", analyte=synthetic.DRUG, matrix="plasma", series=series, statistic="arithmetic_mean", time=time,
            time_unit="h", value=value, unit="ng/mL", below_lloq=blq, lloq=0.5, sd=sd, n=12, dose=50.0, dose_unit="mg",
            route="oral", formulation="ir_tablet", food_state="fasted",
            source=CellRef(file_sha256="a" * 64, recipe_id="r1", recipe_version=1, cells={"value": "Sheet1!B5"}))

    records = [record("keeps", 0.0, None, None, blq=True), record("keeps", 1.0, 42.6, 3.5), record("keeps", 2.0, 32.1, 1.6),
               record("drops", 0.0, None, None, blq=True), record("drops", 1.0, 42.6, None), record("drops", 2.0, 32.1, 1.6),
               record("none", 0.0, None, None, blq=True), record("none", 1.0, 42.6, None)]
    (made,) = client_data.datasets_from_observations(records, study={"n": 12}, sha="a" * 64, filename="made-up.xlsx",
                                                     library=library)
    by_name = {s.name: s for s in made.series}
    assert (by_name["keeps"].error, by_name["keeps"].error_kind) == ((None, 3.5, 1.6), "SD")
    assert (by_name["drops"].error, by_name["drops"].error_kind) == (None, "none")
    assert (by_name["none"].error, by_name["none"].error_kind) == (None, "none")       # no spread at all is no spread
    assert check_dataset(made).series == made.series

    class Checked:                                                   # what `_points` reads of a checked reading
        concentrations = records

    class Form:
        lloq = 0.5

    drawn = {s["name"]: s for s in _points(Checked(), Form())["series"]}  # type: ignore[arg-type]
    assert (drawn["keeps"]["error"], drawn["keeps"]["error_kind"]) == ([None, 3.5, 1.6], "SD")
    assert (drawn["drops"]["error"], drawn["drops"]["error_kind"]) == (None, "none")
    # a series whose error column has another length than its times is still refused
    with pytest.raises(ValueError, match="error column length differs"):
        check_dataset(made.model_copy(update={"series": (by_name["keeps"].model_copy(update={"error": (None, 3.5)}),)}))


def test_record_delivery_rows_appends_tagged_rows_once_and_the_register_rebuilds(ws, library):
    sha = client_file(ws, library)
    sid = submission_id(sha)

    def row(time: float, mean: float, medium: str = "HCl buffer") -> dict[str, Any]:
        return {"values": {"product": "Exampleamide IR tablet", "role": "TEST", "strength_mg": 50.0, "batch": "L2301",
                           "apparatus": "USP II", "rpm": 50.0, "medium": medium, "ph": 1.2, "volume_ml": 900.0, "time": time,
                           "time_unit": "min", "mean": mean, "sd": 2.0, "n": 12},
                "cells": {"mean": f"s:'Dissolution'!J{int(time)}"}}

    assert client_data.record_delivery_rows(ws, sid, [row(15, 40.0), row(30, 80.0)], tag="delivery-cf-7", by=BY) == 2
    stored = submission(ws, sid)["dissolution"]
    assert [r["tag"] for r in stored] == ["delivery-cf-7"] * 2 and stored[0]["values"]["mean"] == 40.0
    (profile,) = [p for p in profiles(ws) if "times_min" in p]
    assert (profile["mean"], profile["sd"], profile["n"]) == ([40.0, 80.0], [2.0, 2.0], 12)
    # the same rows again: nothing is written (a second land); other rows of the same tag replace the earlier ones
    versions = len(ws.versions(ArtifactKind.CLIENT_SUBMISSION, sid))
    assert client_data.record_delivery_rows(ws, sid, [row(15, 40.0), row(30, 80.0)], tag="delivery-cf-7", by=BY) == 2
    assert len(ws.versions(ArtifactKind.CLIENT_SUBMISSION, sid)) == versions
    client_data.record_delivery_rows(ws, sid, [row(15, 41.0)], tag="delivery-cf-7", by=BY)
    client_data.record_delivery_rows(ws, sid, [row(15, 55.0, "phosphate buffer")], tag="delivery-cf-9", by=BY)
    stored = submission(ws, sid)["dissolution"]
    assert [(r["tag"], r["values"]["mean"]) for r in stored] == [("delivery-cf-7", 41.0), ("delivery-cf-9", 55.0)]
    # no rows: that tag's rows are removed (a superseded confirmation), the other's stay
    assert client_data.record_delivery_rows(ws, sid, [], tag="delivery-cf-7", by=BY) == 0
    assert [r["tag"] for r in submission(ws, sid)["dissolution"]] == ["delivery-cf-9"]
    # refused: a tag that is not a confirmation's, a row that is not template-shaped, a file with no record
    for bad_tag in ("cf-7", "delivery-", "delivery-../x", "delivery-cf-0", ""):
        with pytest.raises(client_data.ClientDataError):
            client_data.record_delivery_rows(ws, sid, [row(15, 40.0)], tag=bad_tag, by=BY)
    with pytest.raises(client_data.ClientDataError):
        client_data.record_delivery_rows(ws, sid, [{"values": [1, 2]}], tag="delivery-cf-7", by=BY)
    with pytest.raises(client_data.ClientDataError):
        client_data.record_delivery_rows(ws, "file-000000000000", [row(15, 40.0)], tag="delivery-cf-7", by=BY)
    assert [r["tag"] for r in submission(ws, sid)["dissolution"]] == ["delivery-cf-9"]


def test_a_filled_client_template_is_confirmed_on_its_legacy_card_only(ws, library):
    template = synthetic.template_workbook()
    answer = ingest(ws, library, template.data, template.name, by=BY)
    assert answer["template"] and datasets(ws)                     # today's no-AI path read it: its datasets wait there
    write_truth(ws, [template])
    cover(ws, template)
    reader = Ledger(ws)
    rows = review.subjects(ws, reader=reader)
    assert rows and {r["confirm_on"] for r in rows} == {"client-review"}
    study = study_of(reader, "EXA-101")
    found = [b for b in review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False)
             if b.code == "LOADED_ON_CLIENT_REVIEW"]
    assert len(found) == 1 and "filled client-data template" in found[0].detail and "read-only" in found[0].detail
    # the same study with values from another file too is Delivery's to confirm
    Book(ws, sheet="Notes").fact("age_mean", 33.0, {"study": study})
    reader.refresh()
    assert next(r for r in review.subjects(ws, reader=reader) if r["subject"] == study)["confirm_on"] == "delivery"


# --- regressions of the D6-PM review (2026-11-14) -------------------------------------------------------------------------


def test_an_interrupted_dissolution_landing_rebuilds_the_register_when_it_completes(ws, library, monkeypatch):
    """The rows are stored, then the register's rebuild fails (a crash between the two). The landing has no `landed`
    line; landing again rebuilds the register although the rows are stored already, and only then says it landed."""
    from modeler_project import dissolution_register

    _book, product, run = _dissolution_product(ws, library)
    run(METHOD, (50.0, 80.0))
    reader = Ledger(ws)
    settle(ws, "product", product, reader)
    record, sha, plan = review.prepare_confirmation(ws, library, "product", product, reader=reader, **CARD, blinded=False)
    confirmation = review.record_confirmation(ws, subject_type="product", subject=product, record=record, record_sha256=sha,
                                              signature_id=SIGNATURE, manifestation="Reviewed by A. Reviewer", by=BY,
                                              printed_name="A. Reviewer", blinded=False)
    real = dissolution_register.rebuild

    def crash(*args: Any, **kwargs: Any) -> None:
        raise OSError("the disk is full")

    monkeypatch.setattr(dissolution_register, "rebuild", crash)
    with pytest.raises(OSError):
        landing.land(ws, library, confirmation, plan, by=BY)
    monkeypatch.setattr(dissolution_register, "rebuild", real)
    assert landing.landed(ws, confirmation.id) is None and profiles(ws) == []
    assert len(submission(ws, plan.dissolution[0][0])["dissolution"]) == 2          # the rows were stored before the crash
    done = landing.land(ws, library, confirmation, plan, by=BY)
    (profile,) = [p for p in profiles(ws) if "times_min" in p]
    assert done.dissolution_records == 2 and profile["mean"] == [50.0, 80.0]


def test_a_landed_study_merged_into_another_is_set_aside_when_the_merged_study_lands(ws):
    """The earlier confirmation was recorded under the study's own id; after a merge the ledger knows the study by
    another. The later landing follows the merge (as `supersedes` does) and sets the earlier dataset aside: the same
    points are never accepted twice."""
    from modeler_project import ledger_entities

    book = Book(ws)
    first = clean_study(book, "EXA-401", points=3)
    covered(book)
    reader = Ledger(ws)
    _plan, early, done = land(ws, first["study"], reader)
    (early_id,) = done.datasets
    # the same study under a second label, with two later samples of its own
    second = book.entity("study", "EXA-401 (CSR)")
    for i in range(2):
        book.fact("concentration", 50.0 + i, {"study": second, "analyte": first["analyte"], "matrix": "plasma", "subject": "001"},
                  unit="ng/mL", time=float(10 + i), time_unit="h", statistic="individual")
    ledger_entities.merge(reader, type="study", from_id=first["study"], into_id=second, link_fact=None,
                          why="one study, two labels", by=BY)
    reader.refresh()
    _plan, late, again = land(ws, second, reader, signature="sig-0002")
    (late_id,) = again.datasets
    assert late.supersedes == early.id and late_id != early_id
    old, new = dataset(ws, early_id), dataset(ws, late_id)
    assert old.state is EvidenceState.REJECTED and old.decision_reason == f"superseded by Delivery confirmation {late.id}"
    assert new.state is EvidenceState.ACCEPTED and new.series[0].values == (10.0, 11.0, 12.0, 50.0, 51.0)
    assert [d.id for d in datasets(ws) if d.state is EvidenceState.ACCEPTED] == [late_id]


def test_a_value_in_another_studys_accepted_dataset_blocks_until_that_study_is_confirmed_again(ws):
    """Values of a confirmed, landed study are assigned to another study. The other study cannot be confirmed while the
    first study's dataset, which still holds them, is accepted: nothing is loaded twice."""
    book = Book(ws)
    first = clean_study(book, "EXA-401", points=3)
    second = clean_study(book, "EXA-402", points=0)
    covered(book)
    reader = Ledger(ws)
    _plan, early, done = land(ws, first["study"], reader)
    (early_id,) = done.datasets
    moved = [first["c0"], first["c1"], first["c2"]]
    review.assign(ws, targets=moved, study=second["study"], why="these samples are study 402's", by=BY)
    reader.refresh()
    settle(ws, "study", second["study"], reader)
    (blocker,) = review.blockers(ws, "study", second["study"], reader=reader, **CARD, blinded=False)
    assert blocker.code == "LOADED_ON_CLIENT_REVIEW" and blocker.ids == (early_id,)
    assert early_id in blocker.detail and early.id in blocker.detail and "EXA-401" in blocker.detail
    assert "nothing is loaded twice" in blocker.detail and "10.0" not in blocker.detail
    with pytest.raises(review.ConfirmationRefused) as refused:
        review.prepare_confirmation(ws, None, "study", second["study"], reader=reader, **CARD, blinded=False)
    assert [b.code for b in refused.value.blockers] == ["LOADED_ON_CLIENT_REVIEW"]
    assert [d.id for d in datasets(ws)] == [early_id]                                # nothing was written
    # the first study confirmed again (it no longer has the samples) sets its dataset aside; then the second lands
    _plan, _again, redone = land(ws, first["study"], reader, signature="sig-0002")
    assert redone.datasets == () and dataset(ws, early_id).state is EvidenceState.REJECTED
    assert review.blockers(ws, "study", second["study"], reader=reader, **CARD, blinded=False) == ()
    _plan, _late, later = land(ws, second["study"], reader, signature="sig-0003")
    accepted = [d for d in datasets(ws) if d.state is EvidenceState.ACCEPTED]
    assert [d.id for d in accepted] == list(later.datasets) and len(accepted) == 1
    assert accepted[0].series[0].values == (10.0, 11.0, 12.0) and accepted[0].study["study_id"] == "EXA-402"
    # a product's or the compound's values are never a study's dataset: they are not blocked by this rule
    assert review.blockers(ws, "study", first["study"], reader=reader, **CARD, blinded=False) == ()


@pytest.mark.req("T-47", "T-45", "T-48", "F-403", "T-06")
def test_record_confirmation_refuses_a_cross_file_link_that_waits(ws, library):
    """A value joined from another file counts only once a reviewer confirmed the link (the owner's condition 4). With
    everything else settled and the spot check ticked, `record_confirmation` itself refuses: nothing is recorded, and
    the n read from the synopsis lands in no dataset."""
    reader, _keys = delivery_in(ws, library)
    study = study_of(reader, "230-23")
    enter(reader, study, route="oral", formulation="ir_tablet", intended_use="model_building")
    reader.refresh()
    card = review.card(ws, "study", study, reader=reader, **CARD, blinded=False)
    for check in card.checks:
        if check.severity != "fail":
            continue
        if check.code == "REQUIRED_ITEM_UNDISPOSED":
            for item in card.requirements:
                if item.status == "missing" and item.req_id in check.message:
                    review.dispose(ws, subject=study, req_id=item.req_id, disposition="ask_client", why="asked", by=BY)
        else:
            review.override(ws, subject=study, check_id=check.id, why="read against the source: as written", by=BY)
    tick_all(ws, draw(ws, study, reader=reader))
    assert [b.code for b in review.blockers(ws, "study", study, reader=reader, **CARD, blinded=False)] == ["LINK_UNCONFIRMED"]
    record, sha = review.bound_record(ws, "study", study, reader=reader, **CARD)
    with pytest.raises(review.ConfirmationRefused) as refused:
        review.record_confirmation(ws, subject_type="study", subject=study, record=record, record_sha256=sha,
                                   signature_id=SIGNATURE, manifestation="Reviewed by A. Reviewer", by=BY,
                                   printed_name="A. Reviewer", blinded=False)
    assert [b.code for b in refused.value.blockers] == ["LINK_UNCONFIRMED"]
    assert IntakeStore(ws).review.entries("confirmation") == [] and datasets(ws) == []


def test_a_later_confirmation_whose_plan_differs_writes_the_dataset_again_under_the_same_id(ws, monkeypatch):
    """A dataset's id hashes the subject's digest, arm, analyte and matrix: a later plan can give the same id other
    content (the study's label after a merge; a spread the rules no longer land). The landing never skips it: the new
    content is a new version of the same dataset, written by the register, and decided under the later confirmation."""
    from modeler_project import ledger_entities

    book = Book(ws)
    ids = _study(book, "EXA-801")
    covered(book)
    for i, (value, spread) in enumerate(((10.0, 1.5), (20.0, 1.4))):
        book.fact("concentration", value, ids["profile"], unit="ng/mL", time=float(i + 1), time_unit="h",
                  statistic="geometric_mean", spread=spread, spread_kind="geoSD", n=12)
    reader = Ledger(ws)
    _plan, first, done = land(ws, ids["study"], reader)
    (dataset_id,) = done.datasets
    stored = dataset(ws, dataset_id)
    assert stored.study["study_id"] == "EXA-801" and stored.series[0].error == (1.5, 1.4)
    versions = len(ws.versions(ArtifactKind.DATASET, dataset_id))
    # the study gets another label (a merge), and the rules stop landing a geometric SD: the digest is the same
    target = book.entity("study", "EXA-801 (CSR)")
    ledger_entities.merge(reader, type="study", from_id=ids["study"], into_id=target, link_fact=None,
                          why="one study, two labels", by=BY)
    reader.refresh()
    rules = landing.load_rules()
    changed = rules.model_copy(update={"landing": rules.landing.model_copy(update={
        "spreads_landed": {**rules.landing.spreads_landed, "geometric_mean": {}}})})
    monkeypatch.setattr(landing, "load_rules", lambda: changed)
    later_plan, second, again = land(ws, target, reader, signature="sig-0002")
    assert again.datasets == (dataset_id,) and second.supersedes == first.id
    (planned,) = later_plan.datasets
    assert planned.study["study_id"] == "EXA-801 (CSR)" and planned.series[0].error is None
    found = dataset(ws, dataset_id)
    assert found.study == planned.study and found.series == planned.series and found.flags == planned.flags
    assert found.state is EvidenceState.ACCEPTED and len(datasets(ws)) == 1          # never a second id for the profile
    assert found.decision_reason == f"confirmed on Delivery ({second.id}, signature sig-0002)"
    assert found.note.startswith(found.decision_reason) and "is not landed" in found.note
    assert found.source.locator == f"Delivery confirmation {second.id}" and found.proposed_by == stored.proposed_by
    assert len(ws.versions(ArtifactKind.DATASET, dataset_id)) == versions + 2        # the new content, then its decision
    # landing the same plan again writes nothing
    assert landing.land(ws, None, second, later_plan, by=BY) == again
    assert len(ws.versions(ArtifactKind.DATASET, dataset_id)) == versions + 2


def test_a_concentration_written_as_text_is_left_out_and_named_never_a_crash(ws):
    """The ledger keeps a text-valued row as written (contracts §6.3). It is no point of a profile: left out and named
    in the note, as a missing-sample mark is; planning and the bound record never raise for it."""
    book = Book(ws)
    covered(book)
    ids = _study(book, "EXA-811")
    subject = {**ids["profile"], "subject": "001"}
    _points(book, subject, (10.0, 20.0), statistic="individual")
    text = book.fact("concentration", "12.3 (haemolysed)", subject, unit="ng/mL", time=8.0, time_unit="h",
                     statistic="individual", method="cell")
    reader = Ledger(ws)
    plan = plan_of(ws, ids["study"], reader)
    (found,) = plan.datasets
    assert (found.series[0].times, found.series[0].values) == ((1.0, 2.0), (10.0, 20.0))
    assert "values written as text, not as a number, are left out: they stay in the ledger" in found.note
    assert "12.3" not in found.note and "haemolysed" not in found.note and plan.held == ()
    record, _sha = review.bound_record(ws, "study", ids["study"], reader=reader, **CARD)
    assert record["held"] == [] and reader.value(text).status == "proposed"


def test_the_study_record_reads_a_design_tables_numbers_as_well_as_facts(ws):
    """A study-design table's numeric columns are rows of an extract (contracts §6.3), not facts. The study record reads
    every active value: the dose and the n of such a table are not asked for again."""
    from .test_ledger_support import record_rows

    book = Book(ws)
    covered(book)
    reader = Ledger(ws)
    record_rows(reader, sheet="Design", region="rg-00000000d1", caption="Study EXA-821 design", sha=book.sha,
                kind="study_design", constants=(("study_id", "EXA-821", None),),
                rows=({"field": "dose", "value": 50.0, "unit": "mg", "statistic": None},
                      {"field": "n", "value": 12, "unit": None, "statistic": None}))
    record_rows(reader, sheet="Conc", region="rg-00000000c1", caption="Study EXA-821 Exampleamide plasma mean", sha=book.sha,
                constants=(("study_id", "EXA-821", None), ("analyte", synthetic.DRUG, None), ("route", "iv_bolus", None),
                           ("intended_use", "model_building", None)),
                rows=tuple({"time": float(t), "value": 10.0 * t, "n": 12, "labels": {"matrix": "plasma"}} for t in (1, 2, 3)))
    reader.refresh()
    study = study_of(reader, "EXA-821")
    stated = {v.field: v for v in reader.values(study=study) if v.field in ("dose", "n")}
    assert all(v.id.startswith("tx-") for v in stated.values()) and len(stated) == 2       # extract values, not facts
    (found,) = plan_of(ws, study, reader).datasets
    assert (found.study["dose_mg"], found.study["n"], found.study["route"]) == (50.0, 12, "iv_bolus")
    assert found.series[0].values == (10.0, 20.0, 30.0)


def test_a_legacy_reading_is_replaced_only_where_its_profiles_are_landed_and_never_silently(ws, library):
    """A reading of the same sheet confirmed on the client-review card keeps its dissolution records unless every
    profile it holds is landed here (then it is replaced, and the plan says so). A reading that holds the landed
    profile together with others is not replaced: the run is held back, and nothing is dropped."""
    book, first, run = _dissolution_product(ws, library, "Exampleamide IR tablet")
    sid = submission_id(book.sha)

    def product(label: str) -> str:
        made = book.entity("product", label)
        book.fact("product_role", "TEST", {"product": made})
        return made

    def read_on_the_legacy_card(recipe_id: str, *labels: str) -> None:
        """Today's sheet reader's records of these products' profiles (two vessels), confirmed on its card."""
        records = [{"batch": "", "medium": "HCl buffer", "product": label, "role": "TEST", "strength_mg": None,
                    "volume_ml": 900.0, "ph": 1.2, "apparatus": "USP II (paddle)", "rpm": 50.0, "vessel": f"V{v}", "time": t,
                    "time_unit": "min", "percent_dissolved": p + v,
                    "source": {"file_sha256": book.sha, "recipe_id": recipe_id, "recipe_version": 1,
                               "cells": {"value": f"Notes!B{row}"}}}
                   for label in labels for v in (1, 2) for row, (t, p) in enumerate(((15.0, 30.0), (30.0, 60.0)), start=20)]
        client_data.record_mapping(ws, sid, recipe={"recipe_id": recipe_id, "version": 1, "tables": [{"sheet": "Notes"}]},
                                   dataset_ids=[], dissolution=records, by=BY)

    def register() -> dict[str, list[float]]:
        return {p["key"]["product"]: p["mean"] for p in profiles(ws) if "times_min" in p}

    def recipes() -> dict[str, Any]:
        return {m["recipe"]["recipe_id"]: m.get("replaced_by") for m in submission(ws, sid)["mappings"]}

    # 1. another product's profile on the same sheet: untouched by this product's landing
    run(METHOD, (21.0, 55.0))
    read_on_the_legacy_card("r-other", "Comparamide tablet")
    reader = Ledger(ws)
    plan, confirmation, _done = land(ws, first, reader, "product", library=library)
    assert not any("r-other" in text for text in plan.held)
    assert register() == {"Comparamide tablet": [31.5, 61.5], "Exampleamide IR tablet": [21.0, 55.0]}
    assert recipes() == {"r-other": None, f"delivery-{confirmation.id}": None}
    assert len(submission(ws, sid)["dissolution_records"]) == 4
    # 2. a reading that holds this profile and no other: replaced by the confirmed rows, and the plan says so
    second = product("Exampleamide ER tablet")
    run(METHOD, (33.0, 66.0), second)
    read_on_the_legacy_card("r-same", "Exampleamide ER tablet")
    assert register()["Exampleamide ER tablet"] == [31.5, 61.5]
    reader.refresh()
    plan, confirmation, done = land(ws, second, reader, "product", library=library)
    (listed,) = [text for text in plan.held if "r-same" in text]
    assert "replaces" in listed and "client-review" in listed and listed in done.pending
    assert register()["Exampleamide ER tablet"] == [33.0, 66.0] and recipes()["r-same"] == f"delivery-{confirmation.id}"
    assert register()["Comparamide tablet"] == [31.5, 61.5] and recipes()["r-other"] is None
    # 3. a reading that holds this profile together with another's: not replaced; the run is held back, nothing dropped
    third = product("Exampleamide capsule")
    run(METHOD, (44.0, 77.0), third)
    read_on_the_legacy_card("r-both", "Exampleamide capsule", "Comparamide capsule")
    reader.refresh()
    plan, _confirmation, done = land(ws, third, reader, "product", library=library)
    (listed,) = [text for text in plan.held if "r-both" in text]
    assert plan.dissolution == () and done.dissolution_records == 0 and listed.endswith("not landed")
    assert "client-review" in listed and "1 other" in listed
    assert register()["Exampleamide capsule"] == [31.5, 61.5] == register()["Comparamide capsule"]
    assert recipes()["r-both"] is None and len(submission(ws, sid)["dissolution_records"]) == 4 + 8


def test_a_persons_lloq_entry_wins_for_the_profile_it_names(ws):
    """An entry that names its analyte settles that profile. An entry that names none settles a study with one analyte
    profile; in a study with several it replaces no profile's stated LLOQ, and each dataset's note says so."""
    book = Book(ws)
    covered(book)
    ids = _study(book, "EXA-831")
    study, parent = ids["study"], ids["profile"]
    metabolite = {"study": study, "analyte": book.entity("analyte", "Exampleamide-M1"), "matrix": "plasma"}
    _points(book, parent, (10.0, 20.0))
    _points(book, metabolite, (1.0, 2.0))
    book.fact("lloq", 0.5, parent, unit="ng/mL")
    book.fact("lloq", 0.2, metabolite, unit="ng/mL")
    reader = Ledger(ws)

    def lloqs() -> dict[str, Any]:
        reader.refresh()
        return {d.analyte: d.study.get("lloq") for d in plan_of(ws, study, reader).datasets}

    assert lloqs() == {synthetic.DRUG: 0.5, "Exampleamide-M1": 0.2}
    reader.enter(entity=EntityRef(study=study), field="lloq", value=1.0, unit="ng/mL", why="the validation report", by=BY)
    assert lloqs() == {synthetic.DRUG: 0.5, "Exampleamide-M1": 0.2}                # the stated LLOQs stay
    for found in plan_of(ws, study, reader).datasets:
        assert "a person's lloq entry names no analyte" in found.note and "1.0" not in found.note
    reader.enter(entity=EntityRef(**metabolite), field="lloq", value=0.25, unit="ng/mL", why="the metabolite's assay", by=BY)
    assert lloqs() == {synthetic.DRUG: 0.5, "Exampleamide-M1": 0.25}               # the entry that names its analyte wins
    # a study with one analyte profile: an entry that names no analyte is that profile's
    single = _study(book, "EXA-832")
    _points(book, single["profile"], (10.0, 20.0))
    book.fact("lloq", 0.5, single["profile"], unit="ng/mL")
    reader.refresh()
    reader.enter(entity=EntityRef(study=single["study"]), field="lloq", value=1.0, unit="ng/mL", why="the report", by=BY)
    reader.refresh()
    (found,) = plan_of(ws, single["study"], reader).datasets
    assert found.study["lloq"] == 1.0 and "names no analyte" not in found.note


def test_a_template_spread_with_no_kind_is_named_never_dropped_silently(ws, library):
    """Today's template reader: rows that state a variability and no variability_kind. The file is read (it raised
    before D6), the series has no spread, and an issue names the rows: a spread is never dropped without a word."""
    from openpyxl import load_workbook

    from modeler_intake.client_template import build_template

    book = load_workbook(io.BytesIO(build_template()))
    header = [c.value.rstrip("*") for c in book["Studies"][1]]
    row = dict(study_id="EXA-841", treatment="A", design="SD", population="healthy", n=12, route="oral", dose=50,
               dose_unit="mg", formulation="ir_tablet", food_state="fasted", lloq=0.5, lloq_unit="ng/ml",
               intended_use="model_building")
    book["Studies"].append([row.get(h) for h in header])
    for time, mean, sd in ((0.5, 12.0, 2.0), (1, 42.6, 3.5), (2, 32.1, 1.6)):
        book["PK_Summary"].append(["EXA-841", "A", time, "h", "arithmetic_mean", mean, sd, None, 12, "ng/ml"])
    raw = io.BytesIO()
    book.save(raw)
    answer = ingest(ws, library, raw.getvalue(), "client-data.xlsx", by=BY)
    (found,) = datasets(ws)
    assert (found.series[0].values, found.series[0].error, found.series[0].error_kind) == ((12.0, 42.6, 32.1), None, "none")
    (issue,) = [i for i in answer["issues"] if i["code"] == "SPREAD_KIND_MISSING"]
    assert "variability_kind" in issue["message"] and "without its spread" in issue["message"]
    assert issue["location"].startswith("PK_Summary!")


def test_a_landing_that_loses_the_race_for_a_version_ends_as_the_other_landing_did(ws, monkeypatch):
    """Two landings of the same confirmation (a double submit): the one that finds the version it was about to write
    already written takes the dataset as landed by the other, and both end with the one `landed` line."""
    import threading

    from modeler_project.store import ImmutableVersionError

    book = Book(ws)
    ids = clean_study(book)
    covered(book)
    reader = Ledger(ws)
    settle(ws, "study", ids["study"], reader)
    record, sha, plan = review.prepare_confirmation(ws, None, "study", ids["study"], reader=reader, **CARD, blinded=False)
    confirmation = review.record_confirmation(ws, subject_type="study", subject=ids["study"], record=record,
                                              record_sha256=sha, signature_id=SIGNATURE, manifestation="Reviewed", by=BY,
                                              printed_name="A. Reviewer", blinded=False)
    real = {"propose": landing.propose_dataset, "decide": landing.decide_dataset}

    def lost(name: str):
        def write(*args: Any, **kwargs: Any) -> None:
            real[name](*args, **kwargs)                    # the other landing writes the version first
            raise ImmutableVersionError(f"dataset/{plan.datasets[0].id} already exists; versions are immutable")
        return write

    monkeypatch.setattr(landing, "propose_dataset", lost("propose"))
    monkeypatch.setattr(landing, "decide_dataset", lost("decide"))
    done = landing.land(ws, None, confirmation, plan, by=BY)
    monkeypatch.undo()
    (found,) = datasets(ws)
    assert done.datasets == (found.id,) and found.state is EvidenceState.ACCEPTED
    assert found.decision_reason == f"confirmed on Delivery ({confirmation.id}, signature {SIGNATURE})"
    assert len(ws.versions(ArtifactKind.DATASET, found.id)) == 2 and len(events(ws, "intake.land")) == 1
    # and for real: four landings at once of another study's confirmation, no error, one line, one event
    other_book = Book(ws, sha=hashlib.sha256(b"Exampleamide: a second made-up file").hexdigest(), name="second.xlsx")
    other = clean_study(other_book, "EXA-402")
    covered(other_book)
    reader.refresh()
    settle(ws, "study", other["study"], reader)
    record, sha, plan = review.prepare_confirmation(ws, None, "study", other["study"], reader=reader, **CARD, blinded=False)
    errors: list[str] = []

    def go() -> None:
        try:
            made = review.record_confirmation(ws, subject_type="study", subject=other["study"], record=record,
                                              record_sha256=sha, signature_id="sig-0002", manifestation="Reviewed", by=BY,
                                              printed_name="A. Reviewer", blinded=False)
            landing.land(ws, None, made, plan, by=BY)
        except (RuntimeError, ValueError, OSError) as exc:  # a lost version is a RuntimeError; a refusal a ValueError
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=go) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(IntakeStore(ws).review.entries("confirmation")) == 2 == len(IntakeStore(ws).review.entries("landed"))
    assert len(events(ws, "intake.land")) == 2 and {d.state for d in datasets(ws)} == {EvidenceState.ACCEPTED}
    assert IntakeStore(ws).review.verify() == []


def test_land_refuses_a_plan_that_is_not_the_confirmations_subject(ws):
    """A plan says whose it is (subject type, subject, digest). `land` writes it only under a confirmation of that
    subject as the record bound it: another study's plan, or a plan made after the values changed, is refused."""
    book = Book(ws)
    first = clean_study(book, "EXA-401", points=3)
    second = clean_study(book, "EXA-402", points=2)
    covered(book)
    reader = Ledger(ws)
    settle(ws, "study", first["study"], reader)
    record, sha, plan = review.prepare_confirmation(ws, None, "study", first["study"], reader=reader, **CARD, blinded=False)
    assert (plan.subject_type, plan.subject, plan.subject_digest) == ("study", first["study"], record["subject_digest"])
    other = plan_of(ws, second["study"], reader)
    assert other.subject == second["study"] and other.subject_digest != plan.subject_digest
    confirmation = review.record_confirmation(ws, subject_type="study", subject=first["study"], record=record,
                                              record_sha256=sha, signature_id=SIGNATURE, manifestation="Reviewed", by=BY,
                                              printed_name="A. Reviewer", blinded=False)
    with pytest.raises(ValueError, match="not the plan of"):
        landing.land(ws, None, confirmation, other, by=BY)
    reader.enter(supersedes=first["c0"], value=9.0, why="a correction after the confirmation", by=BY)
    reader.refresh()
    with pytest.raises(ValueError, match="not the plan of"):
        landing.land(ws, None, confirmation, plan_of(ws, first["study"], reader), by=BY)
    assert datasets(ws) == [] and landing.landed(ws, confirmation.id) is None and events(ws, "intake.land") == []
    done = landing.land(ws, None, confirmation, plan, by=BY)
    assert done.datasets == tuple(d.id for d in plan.datasets) and [d.study["study_id"] for d in datasets(ws)] == ["EXA-401"]


def test_study_facts_with_no_place_in_the_study_record_are_listed(ws):
    """What the landing does not write is listed with its reason: a study's facts that a dataset's study record has no
    field for (the salt form, the mean age) are named in `held`, on the card before signing and in `Landed.pending`."""
    book = Book(ws)
    ids = clean_study(book)                         # states salt_or_base and age_mean beside what the record takes
    covered(book)
    reader = Ledger(ws)
    plan = plan_of(ws, ids["study"], reader)
    listed = "EXA-401: study facts with no place in the study record (age_mean, salt_or_base): kept in the ledger"
    assert plan.held == (listed,)
    (found,) = plan.datasets
    assert "age_mean" not in found.study and "salt_or_base" not in found.study and found.study["population_type"] == "healthy"
    _plan, confirmation, done = land(ws, ids["study"], reader)
    assert done.pending == plan.held and confirmation.record["held"] == list(plan.held)
    # the names of its entities and the facts the record takes are not listed
    other = _study(book, "EXA-851")
    _points(book, other["profile"], (10.0, 20.0))
    reader.refresh()
    assert plan_of(ws, other["study"], reader).held == ()


def test_an_individual_pk_parameter_keeps_its_subject(ws):
    """A report's parameter table lists one Cmax per subject. Each lands as a reported parameter that names its subject
    (a `ReportedPK` has no subject of its own: its statistic says "individual (subject 001)"), before the summary
    statistics, so the dataset's own NCA check still compares the mean profile with the mean."""
    book = Book(ws)
    covered(book)
    ids = _study(book, "EXA-861")
    profile = ids["profile"]
    _points(book, profile, (10.0, 20.0, 12.0))
    book.fact("pk.Cmax", 20.4, profile, unit="ng/mL", statistic="arithmetic_mean", spread=6.0, spread_kind="SD", method="cell")
    for subject, cmax in (("002", 21.5), ("001", 13.0), ("003", 26.7)):
        book.fact("pk.Cmax", cmax, {**profile, "subject": subject}, unit="ng/mL", statistic="individual", method="cell")
    reader = Ledger(ws)
    (found,) = plan_of(ws, ids["study"], reader).datasets
    assert [(r.parameter, r.value, r.unit, r.statistic) for r in found.reported] == [
        ("Cmax", 13.0, "ng/mL", "individual (subject 001)"), ("Cmax", 21.5, "ng/mL", "individual (subject 002)"),
        ("Cmax", 26.7, "ng/mL", "individual (subject 003)"), ("Cmax", 20.4, "ng/mL", "arithmetic_mean")]
    assert found.reported[-1].variability == "6 SD" and not any(flag.startswith("nca_mismatch") for flag in found.flags)
