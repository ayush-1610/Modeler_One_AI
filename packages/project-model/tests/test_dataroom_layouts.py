"""The Data room on layouts a new delivery brought (2026-11-24: three made-up deliveries, Novaprazole, Zelitrex and
Quorafen, read with hand-written correct descriptions, so each failure here was code's, not the agent's). Each test is
the cell layout, the correct description, and what code must read from it."""

from __future__ import annotations

import pytest

from modeler_intake.room import read_file
from modeler_intake.room_specs import ColumnSpec, TableDescription
from modeler_project.dataroom.clinical import samples_from, study_view, subjects_in
from modeler_project.dataroom.extract import parse_number, read_table, uses_decimal_comma
from modeler_project.dataroom.invitro import dissolution_views

pytestmark = pytest.mark.req("T-47")


def c(i: int, role: str, **kw) -> ColumnSpec:
    return ColumnSpec(index=i, role=role, **kw)


def table(name: str, text: str, desc: TableDescription):
    f = read_file(name, text.encode())
    return read_table(desc.model_copy(update={"file": name}), f.document, file=name, sha256=f.sha256)


def test_a_site_subject_id_is_one_subject_never_a_range():
    # the study's own subjects decide: "01-007" is subject 01-007, not subjects 1 to 7
    assert subjects_in("01-007, 01-016", known={"1-7", "1-16"}) == ["1-7", "1-16"]
    # without them, a subject part written longer than its site, with its zeros, is an id too
    assert subjects_in("01-007") == ["1-7"]
    # a short range stays a range, as the client writes it ("03-05, 07")
    assert subjects_in("03-05, 07") == ["3", "4", "5", "7"]


def test_a_decimal_comma_is_read_as_one_or_left_unread_never_a_thousand_times_too_high():
    assert parse_number("0,058") is None                           # was 58.0
    assert parse_number("1,234") == 1234.0 and parse_number("12,500") == 12500.0
    assert parse_number("0,058", decimal_comma=True) == pytest.approx(0.058)
    assert parse_number("1.234,5", decimal_comma=True) == pytest.approx(1234.5)
    assert uses_decimal_comma(["0,058", "2,9", "BLQ"]) is True
    assert uses_decimal_comma(["2.5", "1,234"]) is False
    assert uses_decimal_comma(["2.5", "2,9"]) is None              # both marks: said, the comma cells left unread
    # a whole table written the European way is read the European way
    csv = "Subject;Period;Treatment;0;1;2\n1;1;A;BLQ;0,058;2,9\n"
    d = TableDescription(file="", kind="concentrations", part="sheet:c", header_lines=[1], first_line=2, last_line=2,
                         time_unit="h", value_unit="ng/mL", columns=[c(1, "subject"), c(2, "period"), c(3, "treatment"),
                                                                    c(4, "value", time=0.0), c(5, "value", time=1.0),
                                                                    c(6, "value", time=2.0)])
    t = table("c.csv", csv, d)
    assert t.decimal_comma
    samples, problems, _unit = samples_from(t)
    assert [s.value for s in samples] == [None, pytest.approx(0.058), pytest.approx(2.9)] and not problems


def test_a_pre_dose_header_is_time_zero():
    csv = "Subject,Period,Treatment,Pre-dose,0.5,1\n101,1,A,BLQ,10,20\n"
    d = TableDescription(file="", kind="concentrations", part="sheet:c", header_lines=[1], first_line=2, last_line=2,
                         time_unit="h", value_unit="ng/mL",
                         columns=[c(1, "subject"), c(2, "period"), c(3, "treatment"), c(4, "value", time=0.0),
                                  c(5, "value", time=0.5), c(6, "value", time=1.0)])
    assert table("c.csv", csv, d).problems == ()


def test_dissolution_with_times_down_and_units_across():
    csv = "Time (min),V1,V2,V3\n5,40,42,41\n10,60,62,61\n15,80,79,81\n"
    d = TableDescription(file="", kind="dissolution", part="sheet:d", header_lines=[1], first_line=2, last_line=4,
                         time_unit="min", value_unit="%", constants={"batch": "LOT-1"},
                         columns=[c(1, "time"), c(2, "value", group="LOT-1"), c(3, "value", group="LOT-1"),
                                  c(4, "value", group="LOT-1")])
    views, problems = dissolution_views(table("d.csv", csv, d))
    assert not problems and len(views) == 1
    v = views[0]
    assert (v.batch, v.n_units, v.times_min) == ("LOT-1", 3, (5.0, 10.0, 15.0))
    assert v.mean == pytest.approx((41.0, 61.0, 80.0))


def test_dissolution_with_one_line_per_unit_and_time():
    csv = "Batch,Medium,Vessel,Time (min),% Dissolved\n" + "".join(
        f"LOT-1,pH 6.8,{v},{tm},{40 + tm + v}\n" for v in (1, 2, 3) for tm in (5, 10, 15))
    d = TableDescription(file="", kind="dissolution", part="sheet:l", header_lines=[1], first_line=2, last_line=10,
                         time_unit="min", value_unit="%",
                         columns=[c(1, "batch"), c(2, "medium"), c(3, "unit"), c(4, "time"), c(5, "value")])
    views, problems = dissolution_views(table("l.csv", csv, d))
    assert not problems and len(views) == 1
    v = views[0]
    assert (v.batch, v.medium, v.ph, v.n_units) == ("LOT-1", "pH 6.8", 6.8, 3)
    assert v.mean == pytest.approx((47.0, 52.0, 57.0))


def test_dissolution_values_with_no_time_are_said_not_dropped():
    csv = "Vessel,Result\n1,40\n2,42\n"
    d = TableDescription(file="", kind="dissolution", part="sheet:x", header_lines=[1], first_line=2, last_line=3,
                         time_unit="min", value_unit="%", columns=[c(1, "unit"), c(2, "value")])
    views, problems = dissolution_views(table("x.csv", csv, d))
    assert views == [] and [p.code for p in problems] == ["NO_TIME_FOR_VALUES"]


def test_a_parallel_studys_pk_rows_meet_their_profiles_whatever_the_arm_is_called():
    conc = "Subject,Treatment,Time,Conc\n" + "".join(f"{s},{'R' if s % 2 else 'T'},{t},{v}\n" for s in (1, 2, 3, 4)
                                                  for t, v in ((0, "BLQ"), (1, 10), (2, 8), (4, 5), (8, 2)))
    dc = TableDescription(file="", kind="concentrations", part="sheet:k", header_lines=[1], first_line=2, last_line=21,
                          time_unit="h", value_unit="ng/mL", columns=[c(1, "subject"), c(2, "treatment"), c(3, "time"),
                                                                      c(4, "value")])
    pk = "Subject,Arm,Cmax\n1,Reference,10\n2,Test,10\n3,Reference,10\n4,Test,10\n"
    for columns in ([c(1, "subject"), c(2, "treatment"), c(3, "cmax")], [c(1, "subject"), c(3, "cmax")]):
        dp = TableDescription(file="", kind="pk_parameters", part="sheet:p", header_lines=[1], first_line=2, last_line=5,
                              value_unit="ng/mL", columns=columns)
        sv = study_view("S", concentrations=[table("k.csv", conc, dc)], pk_tables=[table("p.csv", pk, dp)])
        assert sum(1 for r in sv.nca if r.client) == 4
        assert "PK_ROWS_MATCH_NOTHING" not in [p.code for p in sv.problems]


@pytest.mark.parametrize("day_role", ["period", "treatment"])
def test_a_multiple_dose_study_shows_each_day_and_no_auc_to_infinity_at_steady_state(day_role):
    conc = "Subject,Day,0,1,2,4,8,24\n" + "".join(
        f"{s},{d},{'BLQ' if d == 1 else 5},{10 * d},{12 * d},{9 * d},{6 * d},{3 * d}\n" for s in (1, 2, 3) for d in (1, 7))
    d = TableDescription(file="", kind="concentrations", part="sheet:m", header_lines=[1], first_line=2, last_line=7,
                         time_unit="h", value_unit="ng/mL",
                         columns=[c(1, "subject"), c(2, day_role)] + [c(3 + i, "value", time=float(x))
                                                                      for i, x in enumerate((0, 1, 2, 4, 8, 24))])
    sv = study_view("MD", concentrations=[table("m.csv", conc, d)])
    codes = [p.code for p in sv.problems]
    assert "MULTIPLE_DOSE" in codes and "REPLICATE_DESIGN" not in codes
    by_day = {(e.treatment, e.metric) for e in sv.exposures if e.value is not None}
    assert ("1", "auc_inf") in by_day and ("7", "auc_t") in by_day and ("7", "cmax") in by_day
    assert ("7", "auc_inf") not in {(e.treatment, e.metric) for e in sv.exposures}


def test_not_detected_named_below_the_lloq_leaves_the_default_missing_list():
    csv = "Subject,Period,Treatment,0,1,2,4\n1,1,A,ND,10,8,ND\n"
    cols = [c(1, "subject"), c(2, "period"), c(3, "treatment")] + [c(4 + i, "value", time=float(x)) for i, x in enumerate((0, 1, 2, 4))]
    d = TableDescription(file="", kind="concentrations", part="sheet:n", header_lines=[1], first_line=2, last_line=2,
                         time_unit="h", value_unit="ng/mL", columns=cols, blq_tokens=["BLQ", "ND"])
    t = table("n.csv", csv, d)
    samples, _problems, _unit = samples_from(t)
    assert t.problems == () and [(s.time_h, s.blq, s.missing) for s in samples] == [
        (0.0, True, False), (1.0, False, False), (2.0, False, False), (4.0, True, False)]
    # the description itself naming ND as both is still refused
    both = d.model_copy(update={"missing_tokens": ["ND"]})
    assert [p.code for p in table("n.csv", csv, both).problems] == ["TOKEN_BOTH_MISSING_AND_BLQ"]


# --- what the AI may describe wrong, and code now refuses or says (the second layer, 2026-11-24) ------------------------

def _doc(name: str, text: str):
    from modeler_intake.source import parse_document
    from modeler_project.dataroom.model import FileView

    doc = parse_document(text.encode(), name)
    return FileView(path=f"D/{name}", name=name, sha256=doc.file_sha256, kind="delimited"), doc


def test_a_quoted_decimal_comma_or_bound_is_never_a_wrong_number():
    from modeler_project.dataroom.extract import is_bound, number_of
    from modeler_project.dataroom.invitro import _ph_of

    assert number_of("0,058 mg/mL", "mg/mL") is None                  # was 58: left for the modeler, never guessed
    assert number_of("> 20 mg/mL", "mg/mL") is None and is_bound("NLT 85 %") and not is_bound("85 %")
    assert _ph_of("phosphate buffer pH 4,5") == 4.5                    # was 4.0
    assert number_of("1,234 mg", "mg") == 1234.0                       # a thousands separator stays one


def test_a_marker_the_files_legend_defines_otherwise_is_refused():
    csv = ("Subject,Period,Treatment,0,1,2\n1,1,A,NQ,10,NQ\n2,1,A,NQ,12,NS\n"
           "NQ = not quantifiable (< 0.20 ng/mL); NS = no sample\n")
    cols = [c(1, "subject"), c(2, "period"), c(3, "treatment")] + [c(4 + i, "value", time=float(x)) for i, x in enumerate((0, 1, 2))]
    wrong = TableDescription(file="", kind="concentrations", part="sheet:c", header_lines=[1], first_line=2, last_line=3,
                             time_unit="h", value_unit="ng/mL", columns=cols, missing_tokens=["NS", "NQ"])
    problems = table("c.csv", csv, wrong).problems
    assert [p.code for p in problems] == ["MARKER_IS_BELOW_LLOQ"] and "NQ = not quantifiable" in problems[0].message
    right = wrong.model_copy(update={"missing_tokens": ["NS"], "blq_tokens": ["NQ"]})
    assert table("c.csv", csv, right).problems == ()


def test_a_count_is_not_a_list_of_subjects():
    from modeler_intake.room_specs import Fact
    from modeler_project.dataroom.extract import check_fact

    view, doc = _doc("s.md", "The statistical analysis included 18 subjects.\nSubjects 1, 2 and 5 completed.\n")
    count = Fact(field="study.statistical_set", subject="S", value="18 subjects",
                 quote="The statistical analysis included 18 subjects.")
    got = check_fact(count, doc, file=view.path, sha256=view.sha256)
    assert not got.ok and "a set lists its subjects" in got.problem
    one = Fact(field="study.completed_subjects", subject="S", value="1, 2 and 5", quote="Subjects 1, 2 and 5 completed.")
    assert check_fact(one, doc, file=view.path, sha256=view.sha256).ok


def test_lines_that_collide_point_to_the_column_that_separates_them():
    from modeler_project.dataroom.clinical import colliding_samples

    conc = "Subject,Day,0,1,2\n" + "".join(f"{s},{d},0,{10 * d},{5 * d}\n" for s in (1, 2) for d in (1, 7))
    as_group = TableDescription(file="", kind="concentrations", part="sheet:m", header_lines=[1], first_line=2, last_line=5,
                                time_unit="h", value_unit="ng/mL",
                                columns=[c(1, "subject"), c(2, "group")] + [c(3 + i, "value", time=float(x))
                                                                            for i, x in enumerate((0, 1, 2))])
    why = colliding_samples(table("m.csv", conc, as_group))
    assert why.startswith("4 samples share a subject") and "column 2 (Day)" in why and "the period" in why
    as_period = as_group.model_copy(update={"columns": [c(1, "subject"), c(2, "period")] + as_group.columns[2:]})
    assert colliding_samples(table("m.csv", conc, as_period)) == ""


def test_names_and_codes_meet_however_the_files_write_them():
    from modeler_project.dataroom.clinical import _code_key
    from modeler_project.dataroom.invitro import named_in

    assert named_in("Tablet, Lot NP-R-2201", ["NP-R-2201", "NP-C-2305"]) == "NP-R-2201"
    assert named_in("Zelitrex 10 mg tablet, batch ZT-R-118", ["Zelitrex 10 mg tablet", "Zelitrex 10 mg capsule"]) == \
        "Zelitrex 10 mg tablet"
    assert named_in("Lot 9", ["NP-R-2201"]) is None
    assert {_code_key(x) for x in ("Treatment R", "Trt. R", "Arm R", "R")} == {"r"}


def test_the_client_auc_to_infinity_is_checked_subject_by_subject():
    conc = "Subject,Period,Treatment,0,1,2,4,8,12\n" + "".join(
        f"{s},1,A,0,10,8,5,2.5,1.25\n" for s in (1, 2, 3))
    d = TableDescription(file="", kind="concentrations", part="sheet:c", header_lines=[1], first_line=2, last_line=4,
                         time_unit="h", value_unit="ng/mL", zero_means_blq=True,
                         columns=[c(1, "subject"), c(2, "period"), c(3, "treatment")] + [c(4 + i, "value", time=float(x))
                                                                                         for i, x in enumerate((0, 1, 2, 4, 8, 12))])
    ours = study_view("S", concentrations=[table("c.csv", conc, d)])
    inf = {r.subject: r.auc_inf for r in ours.nca}
    pk = "Subject,Period,AUCinf\n" + "".join(f"{s},1,{inf[s] * (1.04 if s == '2' else 1.0):.4f}\n" for s in ("1", "2", "3"))
    dp = TableDescription(file="", kind="pk_parameters", part="sheet:p", header_lines=[1], first_line=2, last_line=4,
                          value_unit="ng/mL", columns=[c(1, "subject"), c(2, "period"), c(3, "auc_inf")])
    sv = study_view("S", concentrations=[table("c.csv", conc, d)], pk_tables=[table("p.csv", pk, dp)])
    off = [p.message for p in sv.problems if p.code == "NCA_DIFFERS"]
    assert len(off) == 1 and off[0].startswith("subject 2")


def test_each_arm_says_its_own_food_state():
    from modeler_project.dataroom.assemble import food_of

    assert food_of("Novaprazole 40 mg tablet, fasted") == "fasted"
    assert food_of("Novaprazole 40 mg tablet after a high-fat breakfast") == "fed"
    assert food_of("tablet with a standard meal after an overnight fast") == "fed"
    assert food_of("reference product") is None
