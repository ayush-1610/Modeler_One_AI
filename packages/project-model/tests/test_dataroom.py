"""The Data room's code half (plan 2026-11-21 v2 §8, §9): tables read from an agent's description, facts checked
against their quotes, the analysis sets, mean profiles, NCA beside the client's, dissolution checks and fits,
solubility, decisions, data requests and PK-Sim inputs. A synthetic delivery (Exampleamide); no client data.
"""

from __future__ import annotations

import pytest

from modeler_intake.room import document_parts
from modeler_intake.room_specs import ColumnSpec as C
from modeler_intake.room_specs import Extraction, Fact, ProductRef, QuestionCard, TableDescription
from modeler_intake.source import parse_document
from modeler_project.dataroom.assemble import Inputs, assemble
from modeler_project.dataroom.clinical import subjects_in
from modeler_project.dataroom.extract import check_fact, parse_number, read_table
from modeler_project.dataroom.model import FileView

pytestmark = pytest.mark.req("T-47")

TIMES = (0, 0.5, 1, 2, 4, 8, 12, 24)
# subject, sequence, treatment, period, concentrations ("." missing, 0 below the LLOQ)
PROFILE_A = ("0", "5.1", "12.0", "20.4", "15.2", "8.1", "4.0", "1.1")
PROFILE_B = ("0", "6.0", "13.5", "21.0", "14.1", "7.6", "3.8", "1.0")
ROWS = [("1", "AB", "A", "1", PROFILE_A), ("1", "AB", "B", "2", PROFILE_B),
        ("2", "BA", "B", "1", PROFILE_B), ("2", "BA", "A", "2", PROFILE_A),
        ("3", "AB", "A", "1", PROFILE_A), ("3", "AB", "B", "2", ("0", "0", "0", "0", "0", "0", "0", "0")),   # all BLQ
        ("4", "BA", "B", "1", PROFILE_B), ("4", "BA", "A", "2", ("0", "5.1", "12.0", "20.4", "15.2", ".", ".", ".")),  # stopped
        ("5", "AB", "A", "1", PROFILE_A), ("5", "AB", "B", "2", PROFILE_B[:-1] + (".",)),        # 24 h sample missing
        ("6", "BA", "B", "1", PROFILE_B), ("6", "BA", "A", "2", PROFILE_A)]
CONC = "SUB\tSEQ\tTRT\tPER\t" + "\t".join(f"{t:g}" for t in TIMES) + "\n" + "".join(
    "\t".join((s, q, t, p, *v)) + "\n" for s, q, t, p, v in ROWS)
DISS = "Unit\t5\t10\t15\t30\t45\n" + "".join(f"{u}\t{50 + u}\t{70 + u}\t{80 + u}\t{88 + u % 3}\t{96 + u % 3}\n" for u in range(1, 7)) \
    + "Mean\t53.5\t73.5\t83.5\t91\t97\n"   # 30 min: the units give 89.0, the client wrote 91
SOL = "Medium\tpH\tSolubility\nWater\t6.5\t0.20\npH 1.2 HCl\t1.2\t4.0\n"
NOTES = ("# Study EX-01 synopsis\n\nTreatments: A = reference product (Refamide 100 mg); B = test product.\n"
         "Subjects withdrawn: 4 (adverse event in period 2).\nAll subjects were of Asian origin.\n"
         "Each subject received 100 mg with 240 mL of water after an overnight fast.\n")


def _file(name: str, data: bytes) -> tuple[FileView, object]:
    doc = parse_document(data, name)
    return FileView(path=f"D/{name}", name=name, sha256=doc.file_sha256, kind="delimited"), doc


def _conc_description(part: str) -> TableDescription:
    return TableDescription(file="D/conc.tsv", kind="concentrations", about="EX-01", part=part, header_lines=[1],
                            first_line=2, last_line=len(ROWS) + 1, time_unit="h", value_unit="ng/mL", zero_means_blq=True,
                            columns=[C(index=1, role="subject"), C(index=2, role="sequence"), C(index=3, role="treatment"),
                                     C(index=4, role="period")] + [C(index=5 + i, role="value", time=t) for i, t in enumerate(TIMES)])


@pytest.fixture
def room():
    files, docs = [], {}
    for name, data in (("conc.tsv", CONC), ("diss.tsv", DISS), ("sol.tsv", SOL), ("synopsis.md", NOTES)):
        view, doc = _file(name, data.encode())
        files.append(view)
        docs[view.sha256] = doc
    part = {f.name: document_parts(docs[f.sha256])[0].name for f in files}
    question = QuestionCard(question="Is the test product bioequivalent in vivo?", products=[
        ProductRef(name="Refamide 100 mg", role="reference"), ProductRef(name="Exampleamide 100 mg", role="test")])
    quote_codes = "Treatments: A = reference product (Refamide 100 mg); B = test product."
    extractions = [
        Extraction(file="D/conc.tsv", tables=[_conc_description(part["conc.tsv"])]),
        Extraction(file="D/diss.tsv", tables=[TableDescription(
            file="D/diss.tsv", kind="dissolution", part=part["diss.tsv"], header_lines=[1], first_line=2, last_line=7,
            summary_lines={"mean": 8}, time_unit="min", value_unit="%", constants={"medium": "pH 6.8 phosphate buffer"},
            columns=[C(index=1, role="unit")] + [C(index=2 + i, role="value", time=t, group="LOT-1")
                                                 for i, t in enumerate((5, 10, 15, 30, 45))])]),
        Extraction(file="D/sol.tsv", tables=[TableDescription(
            file="D/sol.tsv", kind="solubility", part=part["sol.tsv"], header_lines=[1], first_line=2, last_line=3,
            value_unit="mg/mL", columns=[C(index=1, role="medium"), C(index=2, role="ph"), C(index=3, role="solubility")])]),
        Extraction(file="D/synopsis.md", facts=[
            Fact(field="study.treatment_code", subject="A", value="reference product", product="Refamide 100 mg", quote=quote_codes),
            Fact(field="study.treatment_code", subject="B", value="test product", product="Exampleamide 100 mg", quote=quote_codes),
            Fact(field="study.excluded_subjects", subject="EX-01", value="4", note="adverse event in period 2",
                 quote="Subjects withdrawn: 4 (adverse event in period 2)."),
            Fact(field="study.ethnicity", subject="EX-01", value="Asian", quote="All subjects were of Asian origin."),
            Fact(field="study.dose", subject="EX-01", value="100", unit="mg", quote="Each subject received 100 mg"),
            Fact(field="study.water", subject="EX-01", value="240", unit="mL", quote="100 mg with 240 mL of water"),
            Fact(field="product.batch", value="LOT-1", product="Exampleamide 100 mg", quote="B = test product"),   # refused
            Fact(field="substance.mw", value="412.5", unit="g/mol", quote="molecular weight 412.5 g/mol"),          # refused
        ])]
    return files, docs, question, extractions


def test_a_number_is_read_only_when_written_as_one():
    assert [parse_number(t) for t in ("12.5", "1,234.5", "−3", "<0.5", "BLQ", ".", "12,5", "1.2e-3")] == [
        12.5, 1234.5, -3.0, None, None, None, None, 0.0012]


def test_a_subject_list_is_read_with_its_ranges():
    assert subjects_in("03-05, 07, 11 to 13 and 20") == ["3", "4", "5", "7", "11", "12", "13", "20"]


def test_a_table_is_read_cell_by_cell_from_its_description_with_each_cells_place(room):
    files, docs, _q, extractions = room
    conc = files[0]
    table = read_table(extractions[0].tables[0], docs[conc.sha256], file=conc.path, sha256=conc.sha256)
    assert not table.problems and len(table.rows) == len(ROWS)
    first = table.rows[0].cells
    assert [c.text for c in first[:4]] == ["1", "AB", "A", "1"] and first[6].text == "12.0" and first[6].time == 1
    assert first[6].chip.line == 2 and first[6].chip.cell == 7 and first[6].chip.ref == "G2"


def test_a_fact_stands_only_when_its_quote_is_in_the_file_and_its_value_in_the_quote(room):
    files, docs, _q, extractions = room
    synopsis = files[3]
    checked = [check_fact(f, docs[synopsis.sha256], file=synopsis.path, sha256=synopsis.sha256) for f in extractions[3].facts]
    assert [c.ok for c in checked] == [True, True, True, True, True, True, False, False]
    assert "not in its quote" in checked[6].problem and "not in" in checked[7].problem
    assert checked[2].chip.part == "body" and checked[4].number == 100.0


def test_the_sets_follow_the_rules_and_say_why_each_subject_is_out(room):
    files, docs, question, extractions = room
    view = assemble(Inputs(files=files, docs=docs, question=question, extractions=extractions))
    (study,) = view.studies
    sets = {s.name: s.subjects for s in study.sets}
    assert sets["dosed"] == ("1", "2", "3", "4", "5", "6")
    assert sets["completed"] == ("1", "2", "3", "5", "6")             # 4 withdrawn (the client says so, and stopped early)
    assert sets["modeling"] == ("1", "2", "5", "6")                   # 3: every sample below the LLOQ in period 2
    assert sets["auc"] == ("1", "2", "6")                             # 5: the 24 h sample missing
    assert "LLOQ" in study.excluded["3"] and "adverse event" in study.excluded["4"]
    assert [a.role for a in study.arms] == ["reference", "test"]


def test_mean_profiles_count_below_the_lloq_as_zero_and_leave_it_out_of_the_geometric_mean(room):
    files, docs, question, extractions = room
    (study,) = assemble(Inputs(files=files, docs=docs, question=question, extractions=extractions)).studies
    arm_a = next(p for p in study.profiles if p.treatment == "A" and p.analysis_set == "modeling")
    at_1h = next(p for p in arm_a.points if p.time_h == 1)
    assert (arm_a.n_subjects, at_1h.n, at_1h.mean, round(at_1h.geomean, 6)) == (4, 4, 12.0, 12.0)
    predose = next(p for p in arm_a.points if p.time_h == 0)
    assert (predose.mean, predose.n_geo, predose.geomean, predose.n_blq) == (0.0, 0, None, 4)


def test_exposure_per_arm_uses_the_modeling_set_for_cmax_and_the_auc_set_for_auc(room):
    files, docs, question, extractions = room
    (study,) = assemble(Inputs(files=files, docs=docs, question=question, extractions=extractions)).studies
    cmax_a = next(e for e in study.exposures if e.treatment == "A" and e.metric == "cmax")
    auc_a = next(e for e in study.exposures if e.treatment == "A" and e.metric == "auc_t")
    assert (cmax_a.n, cmax_a.value, auc_a.n) == (4, 20.4, 3)


def test_dissolution_is_averaged_from_the_units_and_checked_against_the_clients_mean(room):
    files, docs, question, extractions = room
    view = assemble(Inputs(files=files, docs=docs, question=question, extractions=extractions))
    (profile,) = view.dissolution
    assert profile.n_units == 6 and profile.times_min == (5, 10, 15, 30, 45) and profile.mean[0] == 53.5
    assert profile.product == ""                                      # LOT-1's batch fact was refused: no product guessed
    assert profile.weibull["converged"] and profile.plateau is False and profile.very_rapid is False
    (differs,) = [p for p in profile.problems if p.code == "MEAN_ROW_DIFFERS"]
    assert differs.message.startswith("30 min") and differs.where.line == 8


def test_solubility_gives_the_volume_the_dose_needs(room):
    files, docs, question, extractions = room
    view = assemble(Inputs(files=files, docs=docs, question=question, extractions=extractions))
    water = next(r for r in view.solubility if r.medium == "Water")
    assert (water.solubility_mg_ml, water.volume_for_dose_ml, water.fraction_in_glass) == (0.2, 500.0, 0.5)


def test_decisions_requests_and_inputs_say_what_is_proposed_and_what_is_missing(room):
    files, docs, question, extractions = room
    view = assemble(Inputs(files=files, docs=docs, question=question, extractions=extractions,
                           decisions={"population:EX-01": {"chosen": "European_ICRP_2002", "reason": "sensitivity", "by": "u"}}))
    decisions = {d.id: d for d in view.decisions}
    assert decisions["analysis-set:EX-01"].suggested == "modeling"
    assert decisions["population:EX-01"].suggested == "Asian_Tanaka_1996"
    assert decisions["population:EX-01"].chosen == "European_ICRP_2002"
    assert decisions["solubility-ref"].suggested == "sol-0"          # water
    titles = [r.title for r in view.requests]
    assert any("Subject 3" in t and "LLOQ" in t for t in titles)
    assert "Molecular weight" in titles                               # its fact was refused: Missing, asked for
    inputs = {(r.block, r.owner, r.name): r for r in view.inputs}
    assert inputs[("individual", "EX-01", "Population")].value == "European_ICRP_2002"
    assert inputs[("compound", "", "phys.mw")].status == "missing"
    assert inputs[("compound", "", "phys.solubility.ref")].value == 0.2
    assert inputs[("protocol", "EX-01 · A", "InputDose")].value == 100.0
    assert any(p.code == "FACT_REFUSED" for p in view.problems)


DISS_REF = "Unit\t5\t10\t15\t30\t45\n" + "".join(f"{u}\t{55 + u}\t{75 + u}\t{84 + u}\t{90 + u % 3}\t{97 + u % 3}\n" for u in range(1, 7))
BATCHES = "Batches: LOT-1 is the test product; LOT-R is the reference product.\n"


def _published_room(room, extra_facts=()):
    files, docs, question, extractions = room
    files, docs = list(files), dict(docs)
    extra = []
    for name, data in (("diss_ref.tsv", DISS_REF), ("batches.txt", BATCHES)):
        view, doc = _file(name, data.encode())
        files.append(view)
        docs[view.sha256] = doc
        extra.append((view, doc))
    (_ref_view, ref_doc), _ = extra
    extractions = list(extractions) + [
        Extraction(file="D/diss_ref.tsv", tables=[TableDescription(
            file="D/diss_ref.tsv", kind="dissolution", part=document_parts(ref_doc)[0].name, header_lines=[1], first_line=2,
            last_line=7, time_unit="min", value_unit="%", constants={"medium": "pH 6.8 phosphate buffer"},
            columns=[C(index=1, role="unit")] + [C(index=2 + i, role="value", time=t, group="LOT-R")
                                                 for i, t in enumerate((5, 10, 15, 30, 45))])]),
        Extraction(file="D/synopsis.md", facts=[
            Fact(field="study.fasting", subject="EX-01", value="overnight fast", quote="after an overnight fast")]),
        Extraction(file="D/batches.txt", facts=[
            Fact(field="product.batch", value="LOT-1", product="Exampleamide 100 mg", quote="LOT-1 is the test product"),
            Fact(field="product.batch", value="LOT-R", product="Refamide 100 mg", quote="LOT-R is the reference product")])]
    for name, text, fact in extra_facts:
        v, d = _file(name, text.encode())
        files.append(v)
        docs[v.sha256] = d
        extractions.append(Extraction(file=f"D/{name}", facts=[fact]))
    _published_room.last = (files, docs, extractions)  # type: ignore[attr-defined]
    view = assemble(Inputs(files=files, docs=docs, question=question, question_confirmed=True, extractions=extractions))
    decisions = {d.id: {"chosen": d.suggested, "reason": "as suggested", "by": "user:m"} for d in view.decisions}
    return assemble(Inputs(files=files, docs=docs, question=question, question_confirmed=True, extractions=extractions,
                           decisions=decisions))


def test_nothing_is_sent_while_a_decision_waits_or_an_arm_has_no_release(room):
    from modeler_project.dataroom.publish import plan_publication

    files, docs, question, extractions = room
    view = assemble(Inputs(files=files, docs=docs, question=question, question_confirmed=False, extractions=extractions))
    blocked = " ".join(plan_publication(view, by="user:m").blocked)
    assert "decisions waiting" in blocked and "not confirmed" in blocked and "has no release input" in blocked


def test_send_to_the_model_lands_the_arms_profiles_and_the_release_once(room, tmp_path):
    from modeler_project import dataset_register, evidence_register
    from modeler_project.dataroom.publish import plan_publication, publish
    from modeler_project.store import FileProjectStore
    from modeler_project.workspace import Workspace

    view = _published_room(room)
    plan = plan_publication(view, by="user:m")
    assert plan.blocked == ()
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    first = publish(ws, view, by="user:m", reason="inputs confirmed")
    assert first["datasets"] == 2 and first["evidence"] >= 8 and first["skipped"] == 0
    assert publish(ws, view, by="user:m", reason="again") == {"evidence": 0, "datasets": 0, "skipped": first["evidence"] + 2}
    landed = {d.study["study_id"]: d for d in dataset_register.datasets(ws)}
    arm_a = landed["EX-01-A"]
    assert arm_a.state == "ACCEPTED" and arm_a.study["n"] == 4 and arm_a.study["dose_mg"] == 100.0
    # no demographics table: the individual is left for a person to give (D-29), never a silent default
    assert arm_a.study["formulation_name"] == "Refamide_100_mg" and arm_a.study["demographics"] is None
    assert arm_a.demographics_choice is None and arm_a.study["water_ml_per_kg"] is None
    assert [s.statistic for s in arm_a.series] == ["arithmetic_mean", "geometric_mean"] and arm_a.series[0].values[0] is None
    targets = {e.target: e for e in evidence_register.items(ws)}
    assert targets["form.Refamide_100_mg.type"].value == "Weibull" and targets["phys.solubility.ref"].value == 0.2
    assert all(e.state == "ACCEPTED" for e in targets.values())


def test_a_facts_number_is_the_value_not_a_count_or_a_tolerance():
    from modeler_project.dataroom.extract import number_of

    cases = [("1 x 90 mg", "mg"), ("240±2 mL", "mL"), ("30 +/- 6", "years"), ("0.500", ""), ("18-44", ""), ("0 / 0.5 / 1", "h")]
    assert [number_of(v, u) for v, u in cases] == [90.0, 240.0, 30.0, 0.5, None, None]


def test_one_sentence_defining_several_treatment_codes_gives_one_arm_per_code(room):
    files, docs, question, extractions = room
    synopsis = Extraction(file="D/synopsis.md", facts=[Fact(
        field="study.treatment_code", value="A = reference product (Refamide 100 mg); B = test product",
        quote="Treatments: A = reference product (Refamide 100 mg); B = test product.")])
    view = assemble(Inputs(files=files, docs=docs, question=question, extractions=[extractions[0], synopsis]))
    (study,) = view.studies
    assert [(a.treatment, a.role, a.product) for a in study.arms] == [
        ("A", "reference", "Refamide 100 mg"), ("B", "test", "Exampleamide 100 mg")]


def _page_pdf(rows: list[list[tuple[float, str]]]) -> bytes:
    """A one-page PDF: each row a line of (x, text) cells, 16 points apart."""
    ops = "\n".join(f"BT /F1 10 Tf {x} {700 - 16 * r} Td ({text}) Tj ET" for r, row in enumerate(rows) for x, text in row)
    stream = ops.encode("latin-1")
    objects = [b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n", b"2 0 obj << /Type /Pages /Kids [4 0 R] /Count 1 >> endobj\n",
               b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n",
               (b"4 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                b"/Contents 5 0 R >> endobj\n"),
               f"5 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n"]
    body, offsets = b"%PDF-1.4\n", []
    for obj in objects:
        offsets.append(len(body))
        body += obj
    xref = len(body)
    body += f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return body + f"trailer << /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_a_page_line_missing_a_cell_has_its_cells_placed_under_their_columns():
    cols = (72, 160, 240, 320)
    pdf = _page_pdf([list(zip(cols, ("Unit", "5", "10", "15"), strict=True)), list(zip(cols, ("1", "81", "88", "90"), strict=True)),
                     [(72, "2"), (160, "80"), (320, "91")]])   # vessel 2 has no 10 min value
    doc = parse_document(pdf, "diss.pdf")
    desc = TableDescription(file="diss.pdf", kind="dissolution", part="p1", header_lines=[1], first_line=2, last_line=3,
                            columns=[C(index=1, role="unit")] + [C(index=i + 2, role="value", time=t) for i, t in enumerate((5, 10, 15))])
    table = read_table(desc, doc, file="diss.pdf", sha256=doc.file_sha256)
    assert not table.problems
    second = {c.time: c.text for c in table.rows[1].cells if c.role == "value"}
    assert second == {5: "80", 10: "", 15: "91"}


def test_an_existing_projects_client_files_open_in_the_data_room_once(tmp_path):
    from modeler_project.dataroom.reading import import_existing
    from modeler_project.dataroom.store import DataRoomStore
    from modeler_project.intake_files import open_delivery, record_arrival
    from modeler_project.store import FileProjectStore
    from modeler_project.workspace import Workspace

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    delivery = open_delivery(ws, by="user:m")
    for name, data in (("conc.tsv", CONC.encode()), ("synopsis.md", NOTES.encode()), ("again.tsv", CONC.encode())):
        record_arrival(ws, data, name, delivery=delivery, by="user:m")
    store = DataRoomStore(ws)
    added = import_existing(store, by="user:m")
    assert [u["name"] for u in added] == ["conc.tsv", "synopsis.md"]
    assert import_existing(store, by="user:m") == [] and len(store.uploads()) == 2


# --- the independent review's cases (2026-11-22) -------------------------------------------------------------------


def _study(conc: str, columns: list, *, pk: str = "", pk_columns: list | None = None, facts: list | None = None,
           time_unit: str = "h", value_unit: str = "ng/mL", extra: tuple[str, str] | None = None):
    """A study view from tab-separated concentration (and PK) text and its column roles."""
    from modeler_project.dataroom.clinical import study_view
    from modeler_project.dataroom.model import CheckedFact

    def table(text: str, cols: list, kind: str, name: str):
        doc = parse_document(text.encode(), name)
        part = document_parts(doc)[0]
        desc = TableDescription(file=name, kind=kind, about="EX", part=part.name, header_lines=[1], first_line=2,
                                last_line=len(part.lines), time_unit=time_unit, value_unit=value_unit, zero_means_blq=True,
                                columns=cols)
        return read_table(desc, doc, file=name, sha256=doc.file_sha256)

    tables = [table(conc, columns, "concentrations", "conc.tsv")]
    if extra:
        tables.append(table(extra[0], columns, "concentrations", extra[1]))
    pk_tables = [table(pk, pk_columns, "pk_parameters", "pk.tsv")] if pk else []
    checked = [CheckedFact(fact=f, ok=True, number=None) for f in (facts or [])]
    return study_view("EX", concentrations=tables, pk_tables=pk_tables, facts=checked)


def _wide(header: str, n_fixed: int, times: tuple) -> list:
    roles = header.split("\t")[:n_fixed]
    return [C(index=i + 1, role=r) for i, r in enumerate(roles)] + [C(index=n_fixed + 1 + i, role="value", time=t)
                                                                      for i, t in enumerate(times)]


T6 = (0, 1, 2, 4, 8, 12)
P_A, P_B = "0\t10\t20\t15\t8\t3", "0\t14\t24\t18\t9\t4"


def test_a_crossover_listed_without_periods_keeps_each_treatment_a_profile_of_its_own():
    rows = "".join(f"{s}\tA\t{P_A}\n{s}\tB\t{P_B if s != 3 else '0\t0\t0\t0\t0\t0'}\n" for s in (1, 2, 3, 4))
    view = _study("subject\ttreatment\t" + "\t".join(map(str, T6)) + "\n" + rows, _wide("subject\ttreatment", 2, T6))
    sets = {s.name: s.subjects for s in view.sets}
    assert sets["modeling"] == ("1", "2", "4")                       # 3 is below the LLOQ throughout B
    arm_a = next(p for p in view.profiles if p.treatment == "A" and p.analysis_set == "modeling")
    at_1h = next(p for p in arm_a.points if p.time_h == 1)
    assert (arm_a.n_subjects, at_1h.n, at_1h.mean) == (3, 3, 10.0)
    assert {(r.subject, r.treatment) for r in view.nca} >= {("1", "A"), ("1", "B")}


def test_a_replicate_design_counts_each_subject_once_per_arm():
    rows = "".join(f"{s}\t{p}\t{'A' if (p + s) % 2 else 'B'}\t{P_A if (p + s) % 2 else P_B}\n" for s in (1, 2) for p in (1, 2, 3, 4))
    view = _study("subject\tperiod\ttreatment\t" + "\t".join(map(str, T6)) + "\n" + rows, _wide("subject\tperiod\ttreatment", 3, T6))
    arm_a = next(p for p in view.profiles if p.treatment == "A" and p.analysis_set == "modeling")
    assert arm_a.n_subjects == 2 and next(p for p in arm_a.points if p.time_h == 2).n == 2
    assert any(p.code == "REPLICATE_DESIGN" for p in view.problems)
    assert next(e for e in view.exposures if e.treatment == "A" and e.metric == "cmax").n == 2


def test_a_long_listing_counts_a_withdrawn_subjects_absent_rows_as_missing():
    long = "subject\ttreatment\ttime\tconc\n"
    for s in (1, 2, 3):
        for t, c in zip(T6, P_A.split("\t"), strict=True):
            if s == 3 and t > 2:
                continue   # subject 3 withdrew after 2 h: its later rows are not in the listing at all
            long += f"{s}\tA\t{t}\t{c}\n"
    cols = [C(index=1, role="subject"), C(index=2, role="treatment"), C(index=3, role="time"), C(index=4, role="value")]
    view = _study(long, cols)
    sets = {s.name: s.subjects for s in view.sets}
    assert sets["completed"] == ("1", "2") and "stopped early" in view.excluded["3"]


def test_the_same_samples_in_two_files_count_once_and_a_differing_value_is_a_conflict():
    head = "subject\tperiod\ttreatment\t" + "\t".join(map(str, T6)) + "\n"
    one = head + "".join(f"{s}\t1\tA\t{P_A}\n" for s in (1, 2, 3, 4))
    other = head + "".join(f"{s}\t1\tA\t{P_A if s != 2 else '0\t2.0\t20\t15\t8\t3'}\n" for s in (1, 2, 3, 4))
    view = _study(one, _wide("subject\tperiod\ttreatment", 3, T6), extra=(other, "appendix.tsv"))
    at_1h = next(p for p in next(p for p in view.profiles if p.analysis_set == "modeling").points if p.time_h == 1)
    assert at_1h.n == 4 and at_1h.mean == 10.0
    (conflict,) = [p for p in view.problems if p.code == "SAMPLE_CONFLICT"]
    assert "subject 2" in conflict.message and "appendix.tsv" in conflict.message


def test_the_clients_pk_rows_keyed_by_treatment_are_compared_and_prefixed_ids_join():
    from modeler_project.dataroom.clinical import subjects_in

    conc = "subject\ttreatment\t" + "\t".join(map(str, T6)) + "\n" + "".join(f"S0{s}\tA\t{P_A}\n" for s in (1, 2, 3))
    pk = "subject\ttreatment\tCmax\n" + "".join(f"S0{s}\tA\t{30 if s == 2 else 20}\n" for s in (1, 2, 3))
    view = _study(conc, _wide("subject\ttreatment", 2, T6), pk=pk,
                  pk_columns=[C(index=1, role="subject"), C(index=2, role="treatment"), C(index=3, role="cmax")],
                  facts=[Fact(field="study.excluded_subjects", value="S03", note="vomited", quote="x")])
    assert {s.name: s.subjects for s in view.sets}["modeling"] == ("1", "2")   # S03 excluded, as the client says
    assert [p.message.split(":")[0] for p in view.problems if p.code == "NCA_DIFFERS"] == ["subject 2, treatment A"]
    assert subjects_in("101-001, 101-005") == ["101-1", "101-5"] and subjects_in("S06, S09") == ["6", "9"]
    assert subjects_in("34, 35 38, 40") == ["34", "35", "38", "40"] and subjects_in("03-05") == ["3", "4", "5"]


def test_a_time_unit_written_with_words_is_read_and_an_unknown_one_blocks():
    head = "subject\tperiod\ttreatment\t" + "\t".join(f"{t * 60:g}" for t in T6) + "\n"
    rows = "".join(f"{s}\t1\tA\t{P_A}\n" for s in (1, 2, 3))
    minutes = _study(head + rows, _wide("subject\tperiod\ttreatment", 3, tuple(t * 60 for t in T6)), time_unit="min post-dose")
    assert minutes.times_h == T6
    unknown = _study(head + rows, _wide("subject\tperiod\ttreatment", 3, tuple(t * 60 for t in T6)), time_unit="ticks")
    assert any(p.code == "TIME_UNIT_NOT_STATED" and p.severity == "error" for p in unknown.problems)


def test_a_value_is_in_its_quote_only_as_a_whole_number_or_word():
    from modeler_project.dataroom.extract import _value_in_quote, number_of

    assert not _value_in_quote("10", "Each subject received 100 mg with 240 mL of water")
    assert _value_in_quote("100", "Each subject received 100 mg") and _value_in_quote("0.500", "LOQ : 0.5")
    assert [number_of(v, u) for v, u in (("2 x 50 mg", "mg"), ("2,5 mg", "mg"), ("0,25 mg/mL", ""))] == [100.0, None, None]


def test_a_description_shifted_by_one_column_is_caught_by_each_columns_own_header():
    doc = parse_document((b"Unit\t0\t0.5\t1\t2\n1\t0\t5.1\t12\t20\n"), "d.tsv")
    part = document_parts(doc)[0].name
    shifted = [C(index=1, role="subject")] + [C(index=3 + i, role="value", time=t) for i, t in enumerate((0, 0.5, 1))]
    desc = TableDescription(file="d.tsv", kind="concentrations", part=part, header_lines=[1], first_line=2, last_line=2,
                            columns=shifted)
    problems = read_table(desc, doc, file="d.tsv", sha256=doc.file_sha256).problems
    assert [p.code for p in problems] == ["TIME_NOT_IN_HEADER"] * 3


def test_the_published_dataset_is_the_chosen_sets_own_profile_with_its_arms_n(room, tmp_path):
    from modeler_project.dataroom.publish import plan_publication

    view = _published_room(room)
    question = room[2]
    files, docs, extractions = _published_room.last  # type: ignore[attr-defined]
    decisions = {d.id: {"chosen": d.suggested, "by": "u"} for d in view.decisions} | {
        "analysis-set:EX-01": {"chosen": "completed", "by": "u", "reason": "all completers"}}
    chosen = assemble(Inputs(files=files, docs=docs, question=question, question_confirmed=True, extractions=extractions,
                             decisions=decisions))
    plan = plan_publication(chosen, by="u")
    arm_b = next(d for d in plan.datasets if d.study["study_id"] == "EX-01-B")
    at_2h = arm_b.series[0].values[arm_b.series[0].times.index(2)]
    assert arm_b.study["n"] == 5 and arm_b.series[0].n == 5 and round(at_2h, 6) == 16.8   # subject 3: all BLQ in B
    assert "completed" in arm_b.note.lower()


def test_meal_times_are_read_with_their_unit_and_direction_and_a_clock_time_is_not():
    from modeler_project.dataroom.assemble import meal_times

    assert meal_times("lunch 4 h and dinner 10 h after dosing") == [4.0, 10.0]
    assert meal_times("a high-fat breakfast 30 minutes before dosing") == [-0.5]
    assert meal_times("meals at 4, 8 and 12 hours post-dose") == [4.0, 8.0, 12.0]
    assert meal_times("breakfast at 07:30") is None


def test_fraction_unbound_is_converted_once_from_what_the_words_say():
    from modeler_project.dataroom.assemble import fraction_unbound

    assert fraction_unbound(95.0, "%", "Plasma protein binding was 95%") == (0.05, "from 95 % bound")
    assert fraction_unbound(5.0, "%", "fu 5 % in human plasma")[0] == 0.05
    assert fraction_unbound(0.05, "", "fraction unbound 0.05") == (0.05, "")
    assert fraction_unbound(95.0, "%", "95 %")[0] is None


def test_the_pka_type_is_read_never_assumed_and_the_population_matches_whole_words():
    from modeler_project.dataroom.assemble import pka_type, population_of, sex_of

    assert (pka_type("The carboxylic acid has a pKa of 4.2"), pka_type("pKa 8.9 (basic amine)"), pka_type("pKa 6.5")) == (
        "acid", "base", None)
    assert population_of("Caucasian") == "European_ICRP_2002" and population_of("Asian Indian") == "Asian_Tanaka_1996"
    assert population_of("White American") == "WhiteAmerican_NHANES_1997" and population_of("Martian") is None
    assert (sex_of("healthy women"), sex_of("male volunteers"), sex_of("males and females"), sex_of("adults")) == (
        "FEMALE", "MALE", "MIXED", None)


def test_codes_stop_at_the_sentence_or_the_next_code():
    from modeler_project.dataroom.assemble import _code_pairs

    assert _code_pairs("A: Refamide 100 mg tablet (Lot R-12). Treatment B: Exampleamide 100 mg tablet (Lot T-07)") == [
        ("A", "Refamide 100 mg tablet (Lot R-12)"), ("B", "Exampleamide 100 mg tablet (Lot T-07)")]
    assert _code_pairs("B = test product; A = reference product") == [("B", "test product"), ("A", "reference product")]


def test_f2_pairs_only_profiles_run_under_the_same_conditions_and_reformulated_against_original():
    from modeler_project.dataroom.invitro import _quantity, f2_pairs
    from modeler_project.dataroom.model import DissolutionView

    def view(i, product, medium, rpm=50.0):
        return DissolutionView(id=f"d{i}", product=product, medium=medium, ph=6.8, rpm=rpm, n_units=12,
                               times_min=(5, 10, 15, 30), mean=(30, 50, 70, 90), sd=(2, 2, 2, 2))

    roles = {"R": "reference", "T": "test", "O": "original", "N": "reformulated"}
    pairs = f2_pairs([view(1, "R", "pH 6.8 phosphate"), view(2, "T", "pH 6.8 phosphate + 1% SLS"), view(3, "T", "pH 6.8 phosphate"),
                      view(4, "O", "pH 6.8 phosphate", rpm=75), view(5, "N", "pH 6.8 phosphate", rpm=75)], roles)
    assert {(p.test, p.reference) for p in pairs} == {("d3", "d1"), ("d5", "d4")}
    assert _quantity("900 mL at 37 ± 0.5 °C", {"ml": 1.0, "l": 1000.0}) == 900.0


def test_sources_that_disagree_block_sending_until_a_person_chooses(room):
    from modeler_project.dataroom.publish import plan_publication

    view = _published_room(room, extra_facts=[
        ("mw1.txt", "Molecular weight: 412.5 g/mol\n", Fact(field="substance.mw", value="412.5", unit="g/mol",
                                                             quote="Molecular weight: 412.5 g/mol")),
        ("mw2.txt", "MW 421.5 g/mol (free base)\n", Fact(field="substance.mw", value="421.5", unit="g/mol",
                                                         quote="MW 421.5 g/mol (free base)"))])
    mw = next(r for r in view.inputs if r.name == "phys.mw")
    assert mw.status == "conflict"
    assert any("sources disagree" in b for b in plan_publication(view, by="u").blocked)
