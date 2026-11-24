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
