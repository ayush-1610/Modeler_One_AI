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
    arm_a = next(p for p in study.profiles if p.treatment == "A")
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
