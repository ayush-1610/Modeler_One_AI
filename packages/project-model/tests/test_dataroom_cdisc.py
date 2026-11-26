"""CDISC datasets described by code, and a study's analytes told apart (plan 2026-11-26 §7 phase 2b).

The datasets are made up (Exampleamide and its metabolite M1, two studies, two periods), in the shape a CRO's SDTM PC
dataset has: one line per sample, the drug and its metabolite line by line, the occasion in PCGRPID ("Period 1"), the
time in PCTPTNUM running on across visits (the 24 h sample is on "Day 2"), below the LLOQ written "<0.50", a missing
sample "MS" on a NOT DONE line. No model is called."""

from __future__ import annotations

from pathlib import Path

import pytest

from modeler_intake.source import parse_document
from modeler_project.dataroom import DataRoomStore, room_inputs
from modeler_project.dataroom.assemble import assemble
from modeler_project.dataroom.cdisc import DESCRIBER, describe, describe_room
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.synthetic import PC_STUDIES as STUDIES
from modeler_project.dataroom.synthetic import PC_TIMES as TIMES
from modeler_project.dataroom.synthetic import PC_VARIABLES
from modeler_project.dataroom.synthetic import dataset_csv as _csv
from modeler_project.dataroom.synthetic import pc_dataset_rows as pc_rows
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")
FIXTURES = Path(__file__).parent / "fixtures" / "dataroom"

def _described(data: bytes, name: str = "pc.csv"):
    import hashlib

    doc = parse_document(data, name)
    return describe(name, hashlib.sha256(data).hexdigest(), doc)


def _room(tmp_path: Path, files: dict[str, bytes]) -> DataRoomStore:
    store = DataRoomStore(Workspace(FileProjectStore(tmp_path / "root"), "t1", "p1"))
    for name, data in files.items():
        store.add_upload(name, data, by="user:m")
    read_uploads(store, use_ocr=False, workers=1)
    return store


def test_an_sdtm_pc_dataset_is_described_by_code_one_table_per_study():
    got, notes = _described(_csv(pc_rows()))
    assert notes == [] and got is not None
    assert [t.about for t in got.tables] == list(STUDIES)
    first = got.tables[0]
    roles = {c.label: c.role for c in first.columns}
    assert roles == {"USUBJID": "subject", "PCGRPID": "period", "PCTEST": "analyte", "PCSTRESC": "value",
                     "PCSPEC": "matrix", "PCTPTNUM": "time"}
    assert "VISIT" not in roles                       # the 24 h sample is on Day 2: a visit is not the occasion
    assert (first.kind, first.time_unit, first.value_unit, first.header_lines) == ("concentrations", "h", "ng/mL", [1])
    assert (first.first_line, first.last_line) == (2, 1 + 3 * 2 * 2 * len(TIMES))
    assert "MS" in first.missing_tokens and first.note.startswith(f"described by code ({DESCRIBER})")


def test_a_sas_transport_file_is_described_as_its_csv_export_is():
    """The fixture holds the same lines (made with pyreadstat 1.3.7 from `synthetic.pc_dataset_rows`); its line 2
    holds the labels."""
    got, notes = _described((FIXTURES / "pc_two_analytes.xpt").read_bytes(), "pc.xpt")
    csv_got, _ = _described(_csv(pc_rows()))
    assert notes == [] and got is not None and csv_got is not None
    for a, b in zip(got.tables, csv_got.tables, strict=True):
        assert a.header_lines == [1, 2] and a.first_line == b.first_line + 1
        assert [(c.role, c.label, c.unit) for c in a.columns] == [(c.role, c.label, c.unit) for c in b.columns]
        assert a.part == "sheet:PC" and b.part == "sheet:pc"               # the dataset's name; the CSV file's
        where = {"file", "part", "header_lines", "first_line", "last_line", "skip_lines"}
        assert a.model_dump(exclude=where) == b.model_dump(exclude=where)


@pytest.mark.parametrize(("change", "why"), [
    # PCTPTNUM written in minutes for one time only: no one unit agrees with every line's PCTPT
    (lambda rows: [{**r, "PCTPTNUM": "30"} if r["PCTPT"] == "0.5 h" else r for r in rows], "does not agree"),
    # a free-text time point code cannot check PCTPTNUM against
    (lambda rows: [{**r, "PCTPT": "after the dose"} if r["PCTPT"] == "2 h" else r for r in rows], "writes no time"),
    # two units of the result in one study
    (lambda rows: [{**r, "PCSTRESU": "ug/L"} if r["PCSEQ"] == "3" else r for r in rows], "2 units"),
    # one study's lines apart (the dataset not sorted by STUDYID)
    (lambda rows: rows[1:] + rows[:1], "not one run"),
    # no PCGRPID: the two periods' samples share a subject, an analyte and a time (VISIT is never taken instead)
    (lambda rows: [{k: v for k, v in r.items() if k != "PCGRPID"} for r in rows], "share a subject"),
])
def test_a_pc_dataset_code_is_not_sure_of_is_left_to_the_agents_with_the_reason(change, why):
    rows = change(pc_rows())
    variables = tuple(v for v in PC_VARIABLES if v in rows[0])
    got, notes = _described(_csv(rows, variables))
    assert any(why in n for n in notes), notes
    assert got is None or len(got.tables) < len(STUDIES)


def test_a_subjects_dataset_is_described_with_each_unit_and_one_line_per_subject():
    variables = ("STUDYID", "USUBJID", "SEX", "AGE", "AGEU", "WEIGHT", "WEIGHTU", "HEIGHT", "HEIGHTU", "RACE", "ARM")
    rows = [{"STUDYID": "EX-02", "USUBJID": f"EX-02-00{s}", "SEX": "MF"[s % 2], "AGE": str(20 + s), "AGEU": "YEARS",
             "WEIGHT": str(70 + s), "WEIGHTU": "kg", "HEIGHT": str(175 + s), "HEIGHTU": "cm", "RACE": "WHITE",
             "ARM": "Exampleamide"} for s in (1, 2, 3)]
    got, notes = _described(_csv(rows, variables), "dm.csv")
    assert notes == [] and got is not None
    (table,) = got.tables
    assert table.kind == "demographics" and table.about == "EX-02"
    assert [(c.label, c.role, c.unit) for c in table.columns] == [
        ("USUBJID", "subject", ""), ("SEX", "sex", ""), ("AGE", "age", "YEARS"), ("WEIGHT", "weight", "kg"),
        ("HEIGHT", "height", "cm"), ("RACE", "race", "")]
    twice, notes = _described(_csv(rows + rows[:1], variables), "dm.csv")
    assert twice is None and "more than one line" in notes[0]


def test_the_room_reads_each_analyte_as_its_own_profiles_and_the_modeler_chooses_the_modeled_one(tmp_path):
    store = _room(tmp_path, {"Clinical/pc.csv": _csv(pc_rows())})
    described, notes = describe_room(store)
    assert described == ["Clinical/pc.csv"] and notes == []
    (f,) = store.files()
    assert store.extraction(f.sha256)[1] == {"agent": "code", "describer": DESCRIBER}
    assert [(a["stage"], a["model"], a["identity"]) for a in store.authors()] == [("extract", "code", DESCRIBER)]

    view = assemble(room_inputs(store))
    assert [(s.study_id, s.analyte) for s in view.studies] == [("EX-02", "Exampleamide"), ("EX-03", "Exampleamide")]
    assert [(s.study_id, s.analyte) for s in view.other_analytes] == [
        ("EX-02", "Exampleamide-M1 Metabolite"), ("EX-03", "Exampleamide-M1 Metabolite")]
    choice = next(d for d in view.decisions if d.id == "analyte:EX-02")
    assert choice.suggested == "Exampleamide" and [o.label for o in choice.options] == [
        "Exampleamide: 42 samples", "Exampleamide-M1 Metabolite: 42 samples"]          # 3 subjects, 2 periods, 7 times
    study = view.studies[0]
    assert study.periods == ("Period 1", "Period 2") and study.times_h[-1] == 24.0   # one profile runs across visits
    assert len(study.nca) == 6 and study.concentration_unit == "ng/mL"
    assert {s.name: len(s.subjects) for s in study.sets}["dosed"] == 3
    assert any(p.code == "NO_TREATMENT" for p in study.problems)         # SDTM PC names no treatment: said
    assert not any(p.code in ("SAMPLE_CONFLICT", "UNREADABLE_VALUE") for p in study.problems)

    store.decide("analyte:EX-02", "Exampleamide-M1 Metabolite", by="user:m", reason="a metabolite model")
    again = assemble(room_inputs(store))
    assert [s.analyte for s in again.studies] == ["Exampleamide-M1 Metabolite", "Exampleamide"]
    assert next(d for d in again.decisions if d.id == "analyte:EX-02").chosen == "Exampleamide-M1 Metabolite"


def test_a_file_an_agent_described_stays_as_it_is_unless_described_again(tmp_path):
    from modeler_intake.room_specs import Extraction

    store = _room(tmp_path, {"Clinical/pc.csv": _csv(pc_rows())})
    (f,) = store.files()
    store.put_extraction(Extraction(file=f.path), f.sha256, agent={"agent": "A8", "model": "m"})
    assert describe_room(store) == ([], [])
    assert store.extraction(f.sha256)[1]["agent"] == "A8"
    assert describe_room(store, redo=True)[0] == ["Clinical/pc.csv"]
    assert store.extraction(f.sha256)[1]["agent"] == "code"
