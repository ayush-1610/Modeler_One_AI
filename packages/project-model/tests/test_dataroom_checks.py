"""The dose in both bases and the delivery-wide checks (plan 2026-11-26 §7 phase 3; the corpus audit's R03, R07, R14).
The facts and tables are made up. No model is called."""

from __future__ import annotations

import hashlib

import pytest

from modeler_intake.room_specs import ColumnSpec, Fact, TableDescription
from modeler_intake.source import parse_document
from modeler_project.dataroom.detectors import lot_conflicts, not_the_drug, personal_data, simulated_concentrations
from modeler_project.dataroom.dosecard import dose_card
from modeler_project.dataroom.extract import read_table
from modeler_project.dataroom.model import CheckedFact, FileView

pytestmark = pytest.mark.req("T-47")


def _fact(field: str, value: str, *, number: float | None = None, subject: str = "", quote: str = "", product: str = "",
          file: str = "a.pdf", note: str = "") -> CheckedFact:
    return CheckedFact(fact=Fact(field=field, value=value, subject=subject, quote=quote or value, product=product, file=file,
                                 note=note), ok=True, number=number)


SALT_MW = _fact("substance.mw", "393.9 g/mol", number=393.9, subject="Drugamide hydrochloride")
BASE_MW = _fact("substance.mw", "357.4 g/mol", number=357.4, subject="Drugamide free base")


def test_a_salt_dose_is_given_to_pk_sim_as_the_free_base_with_both_bases_recorded():
    """R14: P01's model was given a salt dose against the base's molecular weight (+46 % molar dose)."""
    card, problems = dose_card([_fact("study.dose", "100 mg", number=100, quote="100 mg Drugamide hydrochloride"),
                                SALT_MW, BASE_MW, _fact("substance.salt", "hydrochloride")])
    assert problems == [] and card.basis == "salt" and (card.mw_salt, card.mw_base) == (393.9, 357.4)
    assert card.dose_as_salt_mg == 100 and card.dose_as_base_mg == pytest.approx(100 * 357.4 / 393.9, abs=1e-4)
    assert card.molar_dose_umol == pytest.approx(card.dose_as_base_mg / 357.4 * 1000, abs=1e-3)
    assert "× MW(base) 357.4 / MW(salt) 393.9" in card.rule


def test_a_dose_equivalent_to_the_base_is_the_base_and_its_salt_amount_is_recorded():
    card, problems = dose_card([_fact("product.strength", "90 mg", number=90,
                                      quote="Drugamide hydrochloride equivalent to 90 mg Drugamide"), SALT_MW, BASE_MW])
    assert problems == [] and card.basis == "base" and card.dose_as_base_mg == 90
    assert card.dose_as_salt_mg == pytest.approx(90 * 393.9 / 357.4, abs=1e-4)


def test_what_the_dose_card_cannot_know_is_said():
    _card, problems = dose_card([_fact("study.dose", "100 mg", number=100), _fact("substance.salt", "mesylate")])
    assert [p.code for p in problems] == ["DOSE_BASIS_UNKNOWN"]
    _card, problems = dose_card([_fact("study.dose", "100 mg", number=100, quote="100 mg as the mesylate salt"), BASE_MW])
    assert [p.code for p in problems] == ["DOSE_BASIS_NEEDS_MW"]
    _card, problems = dose_card([_fact("study.dose", "100 mg", number=100, quote="100 mg hydrochloride"),
                                 SALT_MW.model_copy(update={"number": 300.0}), BASE_MW])
    assert [p.code for p in problems] == ["SALT_MW_NOT_HEAVIER", "DOSE_BASIS_NEEDS_MW"]
    card, problems = dose_card([_fact("study.dose", "100 mg", number=100), BASE_MW])
    assert problems == [] and card.basis == "unknown" and card.dose_as_base_mg == 100   # no salt form: the molecule's
    assert dose_card([BASE_MW]) == (None, [])


def _table(text: str, kind: str = "concentrations", columns=(("subject", None), ("time", None), ("value", None))):
    data = text.encode()
    doc = parse_document(data, "conc.csv")
    sha = hashlib.sha256(data).hexdigest()
    desc = TableDescription(file="conc.csv", kind=kind, part="sheet:conc", header_lines=[1], first_line=2,
                            last_line=text.count("\n"), time_unit="h", value_unit="ng/mL",
                            columns=[ColumnSpec(index=i, role=r) for i, (r, _t) in enumerate(columns, start=1)])
    return read_table(desc, doc, file="conc.csv", sha256=sha), {sha: doc}


def test_concentrations_on_a_simulators_grid_or_unrounded_are_said_to_look_simulated():
    """R03: P25 took simulated curves for observed data."""
    grid = "Subject,Time,Conc\n" + "".join(f"1,{0.1 * k:.1f},{12.3456789 / (1 + k):.7f}\n" for k in range(1, 61))
    table, docs = _table(grid)
    (said,) = simulated_concentrations([table], docs)
    assert said.code == "LOOKS_SIMULATED" and "60 sampling times every 0.1 h" in said.message and "unrounded" in said.message
    observed = "Subject,Time,Conc\n" + "".join(f"{s},{t},{v}\n" for s in (1, 2) for t, v in
                                               ((0.5, "4.1"), (1, "9.8"), (2, "16.9"), (4, "12.4"), (8, "5.6"), (24, "0.6")))
    table, docs = _table(observed)
    assert simulated_concentrations([table], docs) == []


def test_a_lot_given_for_two_products_or_written_two_ways_is_said():
    """R07: P04 had lot CA1021001 against …002."""
    facts = [_fact("product.batch", "CA1021001", product="Test 10 mg", file="CSR.pdf"),
             _fact("product.batch", "CA1021002", product="Test 10 mg", file="CoA.pdf"),
             _fact("product.batch", "R-55", product="Reference 10 mg", file="CSR.pdf"),
             _fact("product.batch", "R-55", product="Test 10 mg", file="Protocol.pdf")]
    codes = sorted(p.code for p in lot_conflicts(facts))
    assert codes == ["LOT_CONFLICT", "LOT_TWO_PRODUCTS"]
    assert lot_conflicts(facts[:1] + [_fact("product.batch", "XB7730", product="Test 10 mg", file="CoA.pdf")]) == []


def _file(path: str, data: bytes):
    doc = parse_document(data, path)
    sha = hashlib.sha256(data).hexdigest()
    return FileView(path=path, name=path, sha256=sha, kind="document"), {sha: doc}


def test_a_document_that_never_names_the_drug_is_asked_about():
    other, docs = _file("Clinical/report.txt", ("The study of Otheramide in 24 healthy volunteers. " * 12).encode())
    (said,) = not_the_drug([other], docs, ["Drugamide 100 mg tablet"])
    assert said.code == "FILE_NAMES_NOT_THE_DRUG" and "never names Drugamide" in said.message
    assert said.where is not None and said.where.file == "Clinical/report.txt"         # shown on its file (slice 5d)
    ours, docs = _file("Clinical/report.txt", ("The study of Drugamide in 24 healthy volunteers. " * 12).encode())
    assert not_the_drug([ours], docs, ["Drugamide 100 mg tablet"]) == []
    assert not_the_drug([other], docs, []) == []                                          # no drug known: nothing said


def test_a_subject_listing_with_identifying_columns_is_personal_data():
    listing, docs = _file("Clinical/subjects.csv", b"Subject,Initials,Date of Birth,Sex,Age\n001,J.D.,1985-03-12,M,39\n")
    (said,) = personal_data([listing], docs)
    assert said.code == "PERSONAL_DATA" and "'Initials'" in said.message and "'Date of Birth'" in said.message
    assert said.where is not None and (said.where.file, said.where.line) == ("Clinical/subjects.csv", 1)   # its header line
    plain, docs = _file("Clinical/subjects.csv", b"Subject,Sex,Age,Weight (kg)\n001,M,39,72\n")
    assert personal_data([plain], docs) == []
    composition, docs = _file("CMC/composition.csv", b"Name,Function,mg per tablet\nLactose,filler,120\n")
    assert personal_data([composition], docs) == []                                    # an excipient's name is not a person's


def test_a_spreadsheet_formula_error_is_said_as_one_not_as_an_unreadable_value():
    """Plan 2026-11-26 phase 4: corpus workbooks held #REF! and #DIV/0! where a value was expected."""
    from modeler_project.dataroom.clinical import samples_from

    table, _docs = _table("Subject,Time,Conc\n1,1,9.8\n1,2,#REF!\n1,4,n.q.\n")
    _samples, problems, _unit = samples_from(table)
    codes = {p.code: p.message for p in problems}
    assert codes.keys() == {"SPREADSHEET_ERROR", "UNREADABLE_VALUE"}
    assert "a broken formula" in codes["SPREADSHEET_ERROR"] and "'#REF!'" in codes["SPREADSHEET_ERROR"]


def test_a_file_no_extraction_points_into_is_still_checked_for_personal_data(tmp_path):
    """Slice 5d: the room loads only the documents an extraction points into, so the file's own check is made when it
    is read and kept on the file; the room says it on the file, and Needs you asks about it."""
    from modeler_project.dataroom import DataRoomStore, room_view
    from modeler_project.dataroom.reading import read_uploads
    from modeler_project.store import FileProjectStore
    from modeler_project.workspace import Workspace

    store = DataRoomStore(Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    store.add_upload("subjects.csv", b"Subject,Initials,Date of Birth,Sex,Age\n001,A.B.,1990-01-01,M,34\n", by="u")
    store.add_upload("notes.txt", b"Plain notes about the study schedule.\n", by="u")
    (listing, notes) = sorted(read_uploads(store, use_ocr=False, workers=1), key=lambda f: f.path)[::-1]
    assert [c.code for c in listing.checks] == ["PERSONAL_DATA"] and notes.checks == ()
    assert "checks" not in notes.model_dump()                 # a file with none is stored as before
    view = room_view(store)
    assert [(p.code, p.where.file) for p in view.problems if p.where] == [("PERSONAL_DATA", "subjects.csv")]
    files = next(s for g in view.layout for s in g.sections if s.id == "files")
    assert [view.problems[i].code for i in files.checks] == ["PERSONAL_DATA"]
    assert any(n.id == "check:PERSONAL_DATA:" and n.section == "files" for n in view.needs_you)
