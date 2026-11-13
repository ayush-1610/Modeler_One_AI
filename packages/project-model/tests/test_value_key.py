"""T-47, T-21: the value key (contracts §8.1, §13) loads exactly as the analysts wrote it, or is refused with its cell.

Every cell of a key is text: a typed number, date or bool is refused with its cell named, so 0123, 001, 12.40 and 1:30
are never re-typed by a loader. The template round-trips; the synthetic files' truth makes a key; the v1 YAML key still
loads through delivery_report. No real key is written: the files are the synthetic Exampleamide ones.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from modeler_intake import synthetic
from modeler_project import delivery_report
from modeler_project.value_key import (
    HEADER_COLUMNS,
    KEY_COLUMNS,
    SCHEMA,
    TEMPLATE_ROWS,
    Reading,
    ValueKeyError,
    conditions_key,
    decimal_mark,
    format_conditions,
    key_from_truth,
    key_marks,
    label_key,
    load_key,
    parse_conditions,
    read_value,
    readings_equal,
    study_groups,
    template_workbook,
    time_minutes,
    to_decimal,
    unit_key,
    where_key,
    where_places,
    write_key,
)

pytestmark = pytest.mark.req("T-47", "T-21")

HEADER = {"schema": SCHEMA, "delivery": "D-001", "analyst": "analyst A", "date": "2026-11-13", "status": "draft"}
ROW = {"file": "listing.xlsx", "where": "Fasting", "table": "Table 1", "study": "230-23", "arm": "", "analyte": "Exampleamide",
       "matrix": "plasma", "subject": "001", "field": "concentration", "time": "1:30", "time_unit": "h", "value": "12.40",
       "unit": "ng/mL", "note": ""}


def _column(name: str) -> int:
    return KEY_COLUMNS.index(name) + 1


def _letter(name: str) -> str:
    return get_column_letter(_column(name))


def _filled(rows: list[dict[str, object]], *, header: dict[str, object] | None = None,
            edit: Callable[[object], None] | None = None) -> bytes:
    """The template filled with openpyxl as an analyst would: each value written into its column (a str stays text;
    an int, a float or a date is a typed cell, which the loader must refuse)."""
    wb = load_workbook(io.BytesIO(template_workbook()))
    values = {**HEADER, **(header or {})}
    for column, name in enumerate(HEADER_COLUMNS, start=1):
        wb["Header"].cell(row=2, column=column, value=values[name])
    for r, row in enumerate(rows, start=2):
        for column, name in enumerate(KEY_COLUMNS, start=1):
            if row.get(name) not in (None, ""):
                wb["Key"].cell(row=r, column=column, value=row[name])
    if edit is not None:
        edit(wb)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_the_template_is_text_everywhere_and_round_trips():
    data = template_workbook()
    empty = load_key(data, "key.xlsx")
    assert (empty.schema_id, empty.status, empty.rows, empty.studies, empty.not_data) == (SCHEMA, "draft", (), (), ())
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Header", "Key", "Studies", "Not data", "Read me"]
    key = wb["Key"]
    assert [c.value for c in key[1]] == list(KEY_COLUMNS)
    for column in range(1, len(KEY_COLUMNS) + 1):
        assert key.cell(row=2, column=column).number_format == "@"
        assert key.cell(row=TEMPLATE_ROWS + 1, column=column).number_format == "@"
    # filled as an analyst writes it: every text exactly as written, the optional columns and the Studies sheet too
    rows = [ROW, {**ROW, "subject": "0123", "time": "0.50", "value": "BLQ", "note": "pre-dose"},
            {**ROW, "subject": "", "field": "percent_dissolved", "product": "Exampleamide IR tablet", "batch": "L2301",
             "vessel": "Vessel 1", "period": "2", "conditions": "medium=0.1 N HCl;ph=1.20", "time": "15", "time_unit": "min",
             "value": "<0.5", "unit": "%"}]

    def studies(wb):
        sheet = wb["Studies"]
        for column, text in enumerate(("230-23", "Study 23023; 230/23", "healthy", "", "oral", "fasted", "vbe"), start=1):
            if text:
                sheet.cell(row=2, column=column, value=text)

    loaded = load_key(_filled(rows, edit=studies), "key.xlsx")
    assert (loaded.delivery, loaded.analyst, loaded.date, loaded.status) == ("D-001", "analyst A", "2026-11-13", "draft")
    assert [r.row for r in loaded.rows] == [2, 3, 4]
    assert [(r.subject, r.time, r.value) for r in loaded.rows] == [("001", "1:30", "12.40"), ("0123", "0.50", "BLQ"),
                                                                    ("", "15", "<0.5")]
    third = loaded.rows[2]
    assert (third.product, third.batch, third.vessel, third.period, third.conditions) == (
        "Exampleamide IR tablet", "L2301", "Vessel 1", "2", "medium=0.1 N HCl;ph=1.20")
    assert loaded.rows[1].note == "pre-dose"
    assert loaded.studies == ({"study": "230-23", "names": "Study 23023; 230/23", "population": "healthy",
                               "special_population": "", "route": "oral", "food_state": "fasted", "application": "vbe",
                               "row": "2"},)
    # written back by write_key, the same key comes out
    again = load_key(write_key(HEADER, [r.model_dump(exclude={"row"}) for r in loaded.rows], loaded.studies), "k.xlsx")
    assert again.rows == loaded.rows and again.studies == loaded.studies


@pytest.mark.parametrize(("column", "typed"), [("value", 12.4), ("time", 1.5), ("subject", 1), ("study", 23023)])
def test_a_typed_cell_in_a_text_column_is_refused_with_its_cell(column, typed):
    with pytest.raises(ValueKeyError, match=rf"^Key!{_letter(column)}3: .* is not text"):
        load_key(_filled([ROW, {**ROW, column: typed}]), "key.xlsx")


def test_a_typed_date_in_the_header_is_refused():
    from datetime import date

    with pytest.raises(ValueKeyError, match=r"^Header!D2: "):
        load_key(_filled([ROW], header={"date": date(2026, 11, 13)}), "key.xlsx")


def test_an_unknown_field_is_refused_with_its_cell():
    with pytest.raises(ValueKeyError, match=rf"^Key!{_letter('field')}3: unknown field 'concentraton'"):
        load_key(_filled([ROW, {**ROW, "field": "concentraton"}]), "key.xlsx")
    with pytest.raises(ValueKeyError, match=rf"^Key!{_letter('field')}2: the field is empty"):
        load_key(_filled([{**ROW, "field": ""}]), "key.xlsx")
    # the ledger's vocabulary is the key's: pk parameters, CPF ids and relations are fields
    for field in ("pk.Cmax", "phys.logp", "bind.fu", "relation.ddi_ratio.AUC_inf", "excretion.amount"):
        assert load_key(_filled([{**ROW, "field": field}]), "key.xlsx").rows[0].field == field


@pytest.mark.parametrize(("edit", "message"), [
    (lambda wb: wb.create_sheet("Notes"), r"unknown sheet 'Notes'"),
    (lambda wb: wb.remove(wb["Header"]), r"the sheet 'Header' is missing"),
    (lambda wb: wb["Key"].cell(row=1, column=len(KEY_COLUMNS) + 1, value="anlyte"),
     rf"^Key!{get_column_letter(len(KEY_COLUMNS) + 1)}1: unknown column 'anlyte'"),
    (lambda wb: wb["Key"].cell(row=1, column=4, value="file"), r"^Key!D1: the column 'file' is named twice"),
    (lambda wb: setattr(wb["Key"].cell(row=1, column=_column("value")), "value", None),
     r"^Key!1: the column value is missing"),
    (lambda wb: wb["Key"].cell(row=2, column=len(KEY_COLUMNS) + 2, value="stray"),
     rf"^Key!{get_column_letter(len(KEY_COLUMNS) + 2)}2: a cell under no column name"),
    (lambda wb: wb["Header"].cell(row=2, column=1, value="value-key/1"), r"^Header!2: schema 'value-key/1'"),
    (lambda wb: wb["Header"].cell(row=2, column=5, value="final"), r"^Header!2: status 'final'"),
    (lambda wb: wb["Header"].cell(row=3, column=1, value=SCHEMA), r"^Header!2: the header is one row"),
    (lambda wb: wb["Key"].cell(row=2, column=_column("conditions"), value="colour=red"),
     rf"^Key!{_letter('conditions')}2: unknown condition 'colour'"),
    (lambda wb: wb["Key"].cell(row=2, column=_column("conditions"), value="medium"),
     rf"^Key!{_letter('conditions')}2: 'medium' is not name=value"),
    (lambda wb: wb["Key"].cell(row=2, column=_column("conditions"), value="medium=water;colour=red"),
     rf"^Key!{_letter('conditions')}2: unknown condition 'colour'"),
    (lambda wb: wb["Studies"].cell(row=2, column=2, value="230/23"), r"^Studies!A2: the study is empty"),
])
def test_a_key_the_loader_cannot_read_is_refused_with_its_sheet_and_cell(edit, message):
    with pytest.raises(ValueKeyError, match=message):
        load_key(_filled([ROW], edit=edit), "key.xlsx")


def test_a_key_that_is_no_workbook_or_a_yaml_key_is_refused():
    with pytest.raises(ValueKeyError, match="not a readable workbook"):
        load_key(b"not a workbook", "key.xlsx")
    with pytest.raises(ValueKeyError, match=r"the v1 key .*delivery_report"):
        load_key(b"files: []\n", "key.yaml")


def test_the_optional_columns_may_be_left_out():
    def drop(wb):
        sheet = wb["Key"]
        for name in ("product", "batch", "vessel", "period", "occasion", "sequence", "conditions", "statistic", "spread",
                     "spread_kind", "n"):
            sheet.delete_cols([c.value for c in sheet[1]].index(name) + 1)
    loaded = load_key(_filled([], edit=drop), "key.xlsx")
    assert loaded.rows == ()

    def fill(wb):
        drop(wb)
        names = [c.value for c in wb["Key"][1]]
        for name, text in ROW.items():
            if text:
                wb["Key"].cell(row=2, column=names.index(name) + 1, value=text)
    row = load_key(_filled([], edit=fill), "key.xlsx").rows[0]
    assert (row.product, row.batch, row.vessel, row.period, row.conditions, row.value) == ("", "", "", "", "", "12.40")


def test_the_v1_yaml_key_still_loads_through_delivery_report(tmp_path):
    path = tmp_path / "delivery-key.yaml"
    path.write_text("files:\n  - name: listing.xlsx\n    study: '230-23'\nstudies:\n  - id: '230-23'\n"
                    "dissolution:\n  - product: Exampleamide IR tablet\n    ph: [1.2, 6.8]\n", encoding="utf-8")
    key = delivery_report.load_key(path)
    assert key["files"][0]["name"] == "listing.xlsx" and key["studies"][0]["id"] == "230-23"


def test_the_truth_makes_a_key_with_every_value_as_written():
    files = synthetic.delivery()
    key = load_key(key_from_truth(files), "truth.xlsx")
    truth = [(f.name, v) for f in files for v in f.values]
    assert len(key.rows) == len(truth)
    for row, (name, value) in zip(key.rows, truth, strict=True):
        assert (row.file, row.table, row.field, row.study, row.arm, row.subject, row.value, row.unit) == (
            name, value.table, value.field, value.study, value.arm, value.subject, value.value, value.unit)
        assert parse_conditions(row.conditions) == dict(value.conditions)
        assert (row.statistic, row.spread, row.spread_kind, row.n, row.occasion) == (
            value.statistic, value.spread, value.spread_kind, value.n, value.occasion)
    written = {r.value for r in key.rows}
    assert {"BLQ", "<0.5", ">1000", "NS", "12.3*", "12,5", "12.4037"} <= written
    wheres = {(r.file, r.where) for r in key.rows}
    assert ("messy-delivery.xlsx", "Fasting") in wheres and ("study-report.pdf", "2") in wheres
    assert ("design-report.docx", "") in wheres and ("concentrations.csv", "concentrations") in wheres
    assert {(r.statistic, r.spread_kind) for r in key.rows if r.spread} >= {("arithmetic_mean", "SD"),
                                                                             ("arithmetic_mean", "SE")}
    template = load_key(key_from_truth([synthetic.template_workbook()]), "truth.xlsx")
    assert [(n["where"], n["table"]) for n in template.not_data] == [("README", "template-readme")]


@pytest.mark.parametrize(("text", "number"), [
    ("12.40", "12.40"), ("12,5", "12.5"), ("1,234.5", "1234.5"), ("1.234,5", "1234.5"), ("1.234.567", "1234567"),
    ("12.3*", "12.3"), ("−0.5", "-0.5"), ("1e-3", "0.001"), (".5", "0.5"), ("55%", "55"),
    ("15.01.2024", None), ("1.2.3", None), ("12.3 (4.5)", None), ("NS", None), ("", None), ("1,234", None),
    ("1 234,5", "1234.5"), ("0.125", "0.125"),
])
def test_a_number_is_read_exactly_as_written(text, number):
    found = to_decimal(text)
    assert (str(found) if found is not None else None) == (number if number is None else str(Decimal(number)))
    if number == "12.40":
        assert found.as_tuple().exponent == -2         # the written decimals are kept: the rounding rule needs them


@pytest.mark.parametrize(("field", "text", "reading"), [
    ("concentration", "BLQ", Reading("blq")),
    ("concentration", "BLOQ", Reading("blq")),
    ("concentration", "<LLOQ", Reading("blq")),
    ("concentration", "<0.5", Reading("blq", Decimal("0.5"))),
    ("concentration", ">1000", Reading("above", Decimal(1000))),
    ("concentration", "NS", Reading("missing", text="ns")),
    ("concentration", "n/a", Reading("missing", text="n/a")),
    ("concentration", "12.3 (4.5)", Reading("unreadable")),
    ("concentration", "  ", Reading("empty")),
    ("release", "immediate release", Reading("text", text="IR")),
    ("food_state", "Fasted", Reading("text", text="FASTED")),
    ("study_id", "230/23", Reading("text", text="23023")),
    ("dosage_form", "Film-coated  tablet", Reading("text", text="film-coated tablet")),
])
def test_a_value_is_read_for_its_field(field, text, reading):
    assert read_value(field, text) == reading


@pytest.mark.parametrize(("text", "point", "comma"), [
    ("1,234", "1234", "1.234"), ("1.234", "1.234", "1234"), ("-1,234", "-1234", "-1.234"), ("12,345", "12345", "12.345"),
])
def test_a_single_separator_before_three_digits_is_settled_by_its_table_never_guessed(text, point, comma):
    assert to_decimal(text) is None and read_value("pk.AUC_last", text) == Reading("ambiguous")
    assert str(to_decimal(text, "point")) == point and str(to_decimal(text, "comma")) == comma
    assert read_value("pk.AUC_last", text, "point") == Reading("number", Decimal(point))
    assert read_value("concentration", f"<{text}") == Reading("ambiguous")


def test_space_groups_and_unambiguous_marks():
    for text in ("1 234,5", "1 234.5", "1\u00a0234,5", "1\u202f234.5", "1\u2009234,5"):
        assert to_decimal(text) == Decimal("1234.5"), text
    assert to_decimal("12 345") == Decimal(12345) and to_decimal("12 34") is None
    # 0.125 and 12.5 are no thousands group; repeated or mixed separators say which is the mark
    assert (to_decimal("0.125"), to_decimal("0,125"), to_decimal("12,5")) == (Decimal("0.125"), Decimal("0.125"),
                                                                             Decimal("12.5"))
    marks = {t: decimal_mark(t) for t in ("12.5", "12,5", "1,234.5", "1.234.567", "1 234,5", "1,234", "12", "x")}
    assert marks == {"12.5": "point", "12,5": "comma", "1,234.5": "point", "1.234.567": "comma", "1 234,5": "comma",
                     "1,234": None, "12": None, "x": None}
    assert to_decimal("1,2.5") is None                    # a group of one digit is no group


def test_the_rows_of_a_table_settle_its_marks():
    rows = [{**ROW, "where": "2", "table": "PK", "field": "pk.AUC_last", "time": "", "time_unit": "", "value": "1,523",
             "unit": "ng*h/mL"},
            {**ROW, "where": "2", "table": "PK", "field": "pk.Cmax", "time": "", "time_unit": "", "value": "31.4"},
            {**ROW, "where": "3", "table": "PK", "field": "pk.AUC_last", "time": "", "time_unit": "", "value": "1.523",
             "unit": "ng*h/mL"},
            {**ROW, "where": "3", "table": "PK", "field": "pk.Cmax", "time": "", "time_unit": "", "value": "31,4"},
            {**ROW, "where": "4", "table": "PK", "field": "pk.AUC_last", "time": "", "time_unit": "", "value": "1,523",
             "unit": "ng*h/mL"},
            {**ROW, "where": "5", "table": "PK", "value": "12.5"}, {**ROW, "where": "5", "table": "PK", "value": "1,5"}]
    key = load_key(write_key(HEADER, rows), "k.xlsx")
    marks = key_marks(key.rows)
    assert [marks[r.row] for r in key.rows] == ["point", "point", "comma", "comma", None, None, None]
    assert [read_value(r.field, r.value, marks[r.row]).number for r in key.rows[:4]] == [
        Decimal(1523), Decimal("31.4"), Decimal(1523), Decimal("31.4")]
    assert read_value("pk.AUC_last", key.rows[4].value, marks[key.rows[4].row]).kind == "ambiguous"


def test_pages_ranges_and_where_as_two_keys_compare_it():
    assert where_places("2-3") == (("sheet", "2-3"), ("page", "2"), ("page", "3"))
    assert where_places("pp. 2–4")[1:] == (("page", "2"), ("page", "3"), ("page", "4"))
    assert where_places("page 12")[1:] == where_places("p. 12")[1:] == where_places("12")[1:] == (("page", "12"),)
    assert where_places("2, 5")[1:] == (("page", "2"), ("page", "5"))
    assert where_places("Fasting") == (("sheet", "fasting"),) and where_places("Pharmacokinetics")[1:] == ()
    assert where_places("3-1")[1:] == () and where_places("1-5000")[1:] == () and where_places("") == ()
    assert where_key("p. 2") == where_key("2") == where_key("page 2") != where_key("3")
    assert where_key("Fasting") == where_key("fasting") != where_key("Fed")


def test_a_condition_value_may_hold_a_semicolon():
    assert parse_conditions("medium=phosphate buffer; pH 6.8;ph=6.8") == {"medium": "phosphate buffer; pH 6.8",
                                                                          "ph": "6.8"}
    text = format_conditions({"medium": "phosphate buffer; pH 6.8", "ph": "6.8"})
    assert parse_conditions(text) == {"medium": "phosphate buffer; pH 6.8", "ph": "6.8"}
    with pytest.raises(ValueError, match="unknown condition 'colour'"):
        parse_conditions("medium=water; colour=red")


def test_codes_keep_their_punctuation_names_do_not():
    assert label_key("subject", "1-01") != label_key("subject", "10-1")
    assert label_key("subject", "0-11") != label_key("subject", "01-1")
    assert label_key("subject", "S 001") == label_key("subject", "s  001") and label_key("subject", "1‐01") == "1-01"
    assert label_key("vessel", "Vessel 1") == label_key("vessel", "vessel_1")
    assert label_key("study", "230-23") == label_key("study", "230/23")          # a name: punctuation aside


def test_readings_units_times_and_conditions_compare_as_code_reads_them():
    assert readings_equal(read_value("concentration", "12.40"), read_value("concentration", "12.4"))
    assert not readings_equal(read_value("concentration", "BLQ"), read_value("concentration", "<0.5"))
    assert readings_equal(read_value("concentration", "NS"), read_value("concentration", "missing"))
    assert unit_key("concentration", "ng/ml") == unit_key("concentration", "ng/mL") != unit_key("concentration", "µg/mL")
    assert unit_key("percent_dissolved", "%") == unit_key("percent_dissolved", "percent")
    assert unit_key("pk.AUC_last", "ng*h/mL") == unit_key("pk.AUC_last", "NG*H/ML")      # no table: text, case aside
    assert unit_key("dose", "") == "" != unit_key("percent_dissolved", "fraction")
    assert time_minutes("0.5", "h") == 30.0 and time_minutes("2", "day") == 2880.0 and time_minutes("", "") is None
    for time, unit, message in (("1:30", "h", "not a number"), ("1", "", "no unit"), ("1", "fortnight", "not known")):
        with pytest.raises(ValueError, match=message):
            time_minutes(time, unit)
    assert conditions_key(parse_conditions("ph=1.20; medium=0.1 N HCl")) == conditions_key({"medium": "0.1 n hcl",
                                                                                           "ph": "1.2"})


def test_a_study_and_its_other_names_are_one_study():
    key = load_key(write_key(HEADER, [ROW], [{"study": "230-23", "names": "Study 23023; 230/23-A"},
                                             {"study": "231-24", "names": "230/23-A"}]), "k.xlsx")
    groups = study_groups(key)
    assert groups["23023"] == groups["STUDY23023"] == groups["23023A"] == groups["23124"]
    # a routing tag the template does not name is a column of its own, kept as written
    tagged = load_key(write_key(HEADER, [ROW], [{"study": "230-23", "species": "Human", "route": "oral"}]), "k.xlsx")
    assert tagged.studies[0] == {"study": "230-23", "names": "", "population": "", "special_population": "", "route": "oral",
                                 "food_state": "", "application": "", "species": "Human", "row": "2"}
