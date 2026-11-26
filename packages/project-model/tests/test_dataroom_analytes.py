"""A study's analytes told apart (plan 2026-11-26 §7 phase 2b), whoever described the table: the analyte the model
simulates is suggested and the modeler chooses it; a line that names no analyte in a study of several is said, never
guessed into one. The data are made up (`synthetic.pc_dataset_rows`). No model is called."""

from __future__ import annotations

import pytest

from modeler_intake.room_specs import ColumnSpec, Extraction, ProductRef, QuestionCard, TableDescription
from modeler_project.dataroom import DataRoomStore, room_inputs
from modeler_project.dataroom.assemble import assemble, modeled_analyte
from modeler_project.dataroom.cdisc import describe_room
from modeler_project.dataroom.clinical import colliding_samples
from modeler_project.dataroom.extract import read_table
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.synthetic import dataset_csv as _csv
from modeler_project.dataroom.synthetic import delivery, seed
from modeler_project.dataroom.synthetic import pc_dataset_rows as pc_rows
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")


def _card(*names: str) -> QuestionCard:
    return QuestionCard(question="q", products=[ProductRef(name=n, role="test") for n in names])


@pytest.mark.parametrize(("named", "products", "suggested", "why"), [
    # the code of the drug the card names ("EXAM" begins "exampleamide"); a labelled tracer is never suggested
    (["EX-M2", "13C-labeled EXAM", "EXAM"], ["Exampleamide 100 mg tablet"], "EXAM", "the drug the delivery names"),
    (["Drugamide M1 metabolite", "Drugamide"], ["Drugamide 10 mg"], "Drugamide", "the drug the delivery names"),
    # nothing to match: the first the data lists that is not marked a metabolite
    (["M1", "Parentol"], [], "Parentol", "not marked a metabolite"),
    (["EX-M1 Metabolite", "13C-labeled EX-M2"], [], "EX-M1 Metabolite", "the first the data lists"),
])
def test_the_modeled_analyte_suggested_is_the_drug_the_delivery_names(named, products, suggested, why):
    got, said = modeled_analyte(named, [], _card(*products) if products else None)
    assert got == suggested and why in said


def _read(rows, roles):
    import hashlib

    from modeler_intake.source import parse_document

    data = _csv(rows)
    doc = parse_document(data, "pc.csv")
    header = data.decode().splitlines()[0].split(",")
    desc = TableDescription(file="pc.csv", kind="concentrations", part="sheet:pc", header_lines=[1], first_line=2,
                            last_line=len(rows) + 1, time_unit="h", value_unit="ng/mL",
                            columns=[ColumnSpec(index=header.index(n) + 1, role=r, label=n) for n, r in roles.items()])
    return read_table(desc, doc, file="pc.csv", sha256=hashlib.sha256(data).hexdigest())


def test_two_analytes_measured_at_one_time_are_two_samples_not_a_collision():
    rows = [r for r in pc_rows() if r["STUDYID"] == "EX-02" and r["PCGRPID"] == "Period 1"]
    roles = {"USUBJID": "subject", "PCTPTNUM": "time", "PCSTRESC": "value"}
    assert colliding_samples(_read(rows, {**roles, "PCTEST": "analyte"})) == ""
    # the analyte column given another role: the drug's and the metabolite's samples collide, and the hint names it
    said = colliding_samples(_read(rows, {**roles, "PCTEST": "group"}))
    assert said.startswith("18 samples share") and "PCTEST" in said


def test_lines_that_name_no_analyte_in_a_study_of_several_are_said_and_left_out(tmp_path):
    unnamed = b"Subject,Time (h),Conc (ng/mL)\nEX-02-001,1,9.9\nEX-02-001,2,8.8\n"
    store = DataRoomStore(Workspace(FileProjectStore(tmp_path / "root"), "t1", "p1"))
    store.add_upload("Clinical/pc.csv", _csv(pc_rows()), by="user:m")
    store.add_upload("Clinical/extra.csv", unnamed, by="user:m")
    read_uploads(store, use_ocr=False, workers=1)
    describe_room(store)
    extra = next(f for f in store.files() if f.path == "Clinical/extra.csv")
    store.put_extraction(Extraction(file=extra.path, tables=[TableDescription(
        file=extra.path, kind="concentrations", about="EX-02", part="sheet:extra", header_lines=[1], first_line=2,
        last_line=3, time_unit="h", value_unit="ng/mL",
        columns=[ColumnSpec(index=1, role="subject"), ColumnSpec(index=2, role="time"), ColumnSpec(index=3, role="value")])]),
        extra.sha256, agent={"agent": "A8", "model": "m"})
    view = assemble(room_inputs(store))
    said = [p.message for p in view.problems if p.code == "ANALYTE_NOT_NAMED"]
    assert len(said) == 1 and said[0].startswith("EX-02: 2 concentration lines name no analyte")
    ex02 = next(s for s in view.studies if s.study_id == "EX-02")
    assert all(c.file == "Clinical/pc.csv" for c in ex02.sources)          # the unnamed table is in no analyte's view


def test_a_study_of_one_analyte_reads_as_before(tmp_path):
    store = DataRoomStore(Workspace(FileProjectStore(tmp_path / "root"), "t1", "p1"))
    for name, data in delivery().items():
        store.add_upload(name, data, by="user:m")
    read_uploads(store, use_ocr=False, workers=1)
    seed(store, confirmed=True)
    view = assemble(room_inputs(store))
    assert view.studies and view.other_analytes == ()
    assert not any(d.id.startswith("analyte:") for d in view.decisions)
    assert not any(p.code in ("ANALYTE_NOT_NAMED", "NO_TREATMENT") for s in view.studies for p in s.problems)


@pytest.mark.parametrize(("name", "role"), [("CMAX", "cmax"), ("Cmax", "cmax"), ("AUCLST", "auc_t"), ("AUC0-t", "auc_t"),
                                            ("AUCIFO", "auc_inf"), ("AUC(0-∞)", "auc_inf"), ("t½", "t_half"),
                                            ("LAMZHL", "t_half"), ("TMAX", "tmax"), ("AUC0-24", ""), ("CLO", "")])
def test_a_pk_parameter_is_known_by_its_name_or_cdisc_code(name, role):
    from modeler_project.dataroom.clinical import pk_role

    assert pk_role(name) == role


@pytest.mark.parametrize(("text", "key"), [("Period 2", "2"), ("PERIOD 2", "2"), ("Period II", "2"), ("P2", "2"),
                                           ("2", "2"), ("", ""), ("Day 7", "day 7")])
def test_an_occasion_is_one_key_however_it_is_written(text, key):
    from modeler_project.dataroom.clinical import occasion_key

    assert occasion_key(text) == key


def test_a_parameter_a_long_pk_table_gives_twice_with_two_values_is_not_compared_and_said():
    from modeler_project.dataroom.clinical import _client_pk
    from modeler_project.dataroom.model import Chip, ReadCell, ReadRow, ReadTable

    def row(line, subject, parameter, value):
        return ReadRow(line=line, cells=tuple(ReadCell(role=r, text=t, chip=Chip(file="pk.csv", sha256="x", part="sheet:pk",
                                                                                     line=line, cell=i, text=t))
                                              for i, (r, t) in enumerate((("subject", subject), ("parameter", parameter),
                                                                          ("value", value)), start=1)))

    desc = TableDescription(file="pk.csv", kind="pk_parameters", part="sheet:pk", first_line=2, last_line=4,
                            columns=[ColumnSpec(index=i, role=r) for i, r in enumerate(("subject", "parameter", "value"), 1)])
    table = ReadTable(id="t", description=desc, sha256="x", rows=(row(2, "1", "Cmax", "9.5"), row(3, "1", "Cmax", "9.9"),
                                                                     row(4, "1", "AUC0-t", "80")))
    got, problems = _client_pk([table])
    assert got[("1", "only")] == {"auc_t": 80.0}
    assert [p.code for p in problems] == ["PK_PARAMETER_TWICE"]
