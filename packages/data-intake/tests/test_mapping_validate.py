"""D3: a mapping spec checked on one region before anything is executed (contracts §6.2, §8.5). One test per finding
code; a cached spec re-reads each region's own title and units; a constant is always code's reading of its cite.
Software test data (the made-up Exampleamide)."""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_intake.client_template import SHEETS
from modeler_intake.mapping.execute import execute, read_constant, read_text_constant
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import Cite, ColumnMap, Constant, KeyMap, MappingSpec, RowRule
from modeler_intake.source_model import RegionGrid

pytestmark = pytest.mark.req("T-47")

MESSY = synthetic.messy_workbook()
GRID = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)", "SD"], [1, 12.5, 1.1], [2, 8.4, 0.9]],
                            caption=["Study EX-7, 50 mg, fasted"], below=[["LLOQ = 0.5 ng/mL"]])
SPEC = MappingSpec(kind="pk_summary", layout="wide_series", header_rows=1, first_data_row=2, field="concentration",
                   time_unit="h", time_unit_cite=Cite(row=1, column=1), value_unit="ng/mL",
                   value_unit_cite=Cite(row=1, column=2), statistic="arithmetic_mean", lloq=Cite(near="below", line=1),
                   columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"),
                            ColumnMap(column=3, role="spread", spread_kind="SD", of=2)),
                   constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+),"),
                              Constant(field="dose", cite=Cite(near="caption", line=1)),
                              Constant(field="food_state", cite=Cite(near="caption", line=1))))


def _codes(spec: MappingSpec, grid: RegionGrid = GRID) -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in validate_spec(spec, grid)]


def _with(**changes) -> MappingSpec:
    return SPEC.model_copy(update=changes)


def test_a_spec_that_reads_its_region_has_no_finding():
    assert validate_spec(SPEC, GRID) == ()
    for file in (MESSY, synthetic.pdf_report(), synthetic.word_report(), synthetic.delimited(), synthetic.template_workbook()):
        for table in file.tables:
            assert [f for f in validate_spec(table.spec, synthetic.truth_grid(file, table.id)) if f.severity == "error"] == []


# --- one test per finding code -----------------------------------------------------------------------------------------


def test_cell_outside_region():
    assert _codes(_with(value_unit_cite=Cite(row=9, column=2))) == [("CELL_OUTSIDE_REGION", "error")]
    assert _codes(_with(lloq=Cite(near="below", line=2))) == [("CELL_OUTSIDE_REGION", "error")]
    assert _codes(_with(constants=(Constant(field="dose", cite=Cite(near="above", line=1)),))) == [
        ("CELL_OUTSIDE_REGION", "error")]
    spec = _with(columns=(*SPEC.columns, ColumnMap(column=4, role="ignore", reason="x")))
    assert ("CELL_OUTSIDE_REGION", "error") in _codes(spec)


@pytest.mark.parametrize(("changes", "words"), [
    (dict(columns=(ColumnMap(column=2, role="value"), ColumnMap(column=3, role="spread", of=2))), "no time source"),
    (dict(time_row=1, layout="wide_times"), "two nominal time sources"),
    (dict(columns=(ColumnMap(column=1, role="time"), ColumnMap(column=3, role="spread", of=2))), "no value column"),
    (dict(columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"),
                   ColumnMap(column=3, role="spread", of=1))), "not a value column"),
    (dict(layout="wide_times", time_row=2, columns=(ColumnMap(column=2, role="value"),)), "not above the data"),
    (dict(columns=(ColumnMap(column=1, role="time", cell_form="value (spread)"), ColumnMap(column=2, role="value"))),
     "cell_form"),
    (dict(columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"),
                   ColumnMap(column=3, role="condition", condition="colour"))), "condition 'colour'"),
    (dict(header_rows=2), "header rows end above"),
    (dict(columns=(ColumnMap(column=1, role="time"), ColumnMap(column=1, role="value"))), "mapped twice"),
    (dict(layout="key_value", columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"))), "keys"),
])
def test_layout(changes, words):
    findings = validate_spec(_with(**changes), GRID)
    assert any(f.code == "LAYOUT" and words in f.message for f in findings), findings


def test_unknown_field():
    assert _codes(_with(field="concentrations")) == [("UNKNOWN_FIELD", "error")]
    assert _codes(_with(constants=(Constant(field="alt.foo", cite=Cite(near="caption", line=1)),))) == [
        ("UNKNOWN_FIELD", "error")]


def test_number_typed():
    """Code reads a number from its cite; the model never types one, not even as the text it read."""
    typed = _with(constants=(Constant(field="dose", cite=Cite(near="caption", line=1), text="50"),))
    patterned = _with(constants=(Constant(field="dose", cite=Cite(near="caption", line=1), pattern=r"(\d+) mg"),))
    assert _codes(typed) == [("NUMBER_TYPED", "error")] and _codes(patterned) == [("NUMBER_TYPED", "error")]


def test_constant_not_stated():
    assert _codes(_with(constants=(Constant(field="n", cite=Cite(near="caption", line=1)),))) == [
        ("CONSTANT_NOT_STATED", "error")]                              # "EX-7" and "50": no single number of n
    assert _codes(_with(constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Trial (\S+)"),))) == [
        ("CONSTANT_NOT_STATED", "error")]
    assert _codes(_with(constants=(Constant(field="route", cite=Cite(near="caption", line=1)),))) == [
        ("CONSTANT_NOT_STATED", "error")]
    assert _codes(_with(lloq=Cite(row=1, column=2))) == [("CONSTANT_NOT_STATED", "error")]


def test_a_constant_whose_code_reading_differs_from_its_text_fails():
    good = _with(constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+),",
                                     text="ex 7"),))
    assert _codes(good) == []                                           # name_key: case, spaces, punctuation aside
    for constant in (Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+),", text="EX-8"),
                     Constant(field="food_state", cite=Cite(near="caption", line=1), text="fed")):
        assert _codes(_with(constants=(constant,))) == [("CONSTANT_NOT_STATED", "error")]


def test_unit_not_cited():
    assert _codes(_with(value_unit_cite=None)) == []                    # the header band writes ng/mL
    assert _codes(_with(value_unit="µg/mL", value_unit_cite=None)) == [("UNIT_NOT_CITED", "error")]


def test_a_typed_unit_not_written_at_its_cite_fails_unit_not_stated():
    assert _codes(_with(value_unit="µg/mL")) == [("UNIT_NOT_STATED", "error")]
    assert _codes(_with(time_unit="min")) == [("UNIT_NOT_STATED", "error")]
    assert _codes(_with(value_unit="ng/ml")) == []                      # the same unit, as the header spells it: ng/mL
    assert _codes(_with(time_unit="hours")) == []                       # h and hours are one unit of time
    product = synthetic.truth_grid(MESSY, "product-batches")
    spec = next(t.spec for t in MESSY.tables if t.id == "product-batches")
    other = spec.model_copy(update={"columns": tuple(c.model_copy(update={"unit": "nm"}) if c.column == 7 else c
                                                     for c in spec.columns)})
    assert _codes(other, product) == [("UNIT_NOT_STATED", "error")]    # no table for µm: the text must write it verbatim


def test_unit_not_in_tables_is_a_warning_and_the_unit_is_kept():
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/dL)"], [1, 12.5]])
    spec = MappingSpec(kind="pk_summary", layout="wide_series", header_rows=1, first_data_row=2, field="concentration",
                       value_unit="ng/dL", value_unit_cite=Cite(row=1, column=2),
                       columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")))
    assert _codes(spec, grid) == [("UNIT_NOT_IN_TABLES", "warn")]
    (row,) = execute(spec, grid).rows
    assert row.unit == "ng/dL"


def test_bad_pattern():
    for constant in (Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+"),
                     Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study \S+,"),
                     Constant(field="food_state", cite=Cite(near="caption", line=1), pattern=r"(fasted)")):
        assert _codes(_with(constants=(constant,))) == [("BAD_PATTERN", "error")]
    assert _codes(_with(row_rules=(RowRule(column=1, pattern="mean(", role="arithmetic_mean"),))) == [("BAD_PATTERN", "error")]


def test_token_is_number():
    assert _codes(_with(missing_tokens=("0",))) == [("TOKEN_IS_NUMBER", "error")]
    assert _codes(_with(below_lloq_tokens=("<0.5",))) == [("TOKEN_IS_NUMBER", "error")]
    assert _codes(_with(below_lloq_tokens=("BLQ", "<LLOQ"), missing_tokens=("NS",))) == []


def test_reason_missing():
    assert _codes(_with(row_rules=(RowRule(column=1, pattern="cv", role="exclude"),))) == [("REASON_MISSING", "error")]
    assert _codes(_with(columns=(*SPEC.columns[:2], ColumnMap(column=3, role="ignore")))) == [("REASON_MISSING", "error")]
    assert _codes(MappingSpec(kind="not_data", layout="long", header_rows=0, first_data_row=1)) == [
        ("REASON_MISSING", "error")]


def test_header_holds_numbers_is_a_warning():
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)", "A", "B"], [None, None, 1, 2], [1, 12.5, None, None],
                                 [2, 8.4, None, None]])
    spec = _with(header_rows=2, first_data_row=3, constants=(), lloq=None,
                 columns=(*SPEC.columns[:2], ColumnMap(column=3, role="ignore", reason="x"),
                          ColumnMap(column=4, role="ignore", reason="x")))
    assert _codes(spec, grid) == [("HEADER_HOLDS_NUMBERS", "warn")]


def test_header_rows_that_swallow_data_rows_are_refused():
    """A data row counted as header would leave its numbers 'header' (accounted) and unread: refused, also for values
    written with their spread, which no bare-number count sees."""
    bare = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)"], [1, 12.5], [2, 8.4], [3, 6.1]])
    spec = _with(header_rows=2, first_data_row=3, constants=(), lloq=None, columns=SPEC.columns[:2])
    assert _codes(spec, bare) == [("HEADER_ROWS_HOLD_VALUES", "error")]
    split = RegionGrid.from_rows([["Time (h)", "Mean (SD) ng/mL"], [0.5, "12.3 (4.5)"], [1, "15.1 (3.2)"], [2, "9.8 (2.1)"]])
    spec = MappingSpec(kind="pk_summary", layout="long", header_rows=3, first_data_row=4, field="concentration",
                       statistic="arithmetic_mean", columns=(ColumnMap(column=1, role="time"), ColumnMap(
                           column=2, role="value", cell_form="value (spread)", spread_kind="SD")))
    assert [f.location for f in validate_spec(spec, split)] == ["header row 2", "header row 3"]
    assert validate_spec(spec.model_copy(update={"header_rows": 1, "first_data_row": 2}), split) == ()


def test_a_typed_statistic_or_spread_kind_must_agree_with_the_words_of_its_header_or_label():
    grid = RegionGrid.from_rows([["Time (h)", "Geometric mean (ng/mL)", "SEM", "N"], [1, 12.3, 1.1, 12]])
    spec = MappingSpec(kind="pk_summary", layout="long", header_rows=1, first_data_row=2, field="concentration",
                       columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value", statistic="arithmetic_mean"),
                                ColumnMap(column=3, role="spread", spread_kind="SD"), ColumnMap(column=4, role="n")))
    assert [(f.code, f.location) for f in validate_spec(spec, grid)] == [
        ("STATISTIC_NOT_STATED", "columns[1].statistic"), ("SPREAD_KIND_NOT_STATED", "columns[2].spread_kind")]
    right = spec.model_copy(update={"columns": (spec.columns[0], ColumnMap(column=2, role="value", statistic="geometric_mean"),
                                                ColumnMap(column=3, role="spread", spread_kind="SE"), spec.columns[3])})
    assert validate_spec(right, grid) == ()
    # a bare "Mean" names a mean of either kind; "CV%" with no "geo" may be a geometric CV
    loose = RegionGrid.from_rows([["Time (h)", "Mean (ng/mL)", "CV%"], [1, 12.3, 30]])
    spec = _with(constants=(), lloq=None, value_unit=None, value_unit_cite=None, statistic=None, columns=(
        ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value", statistic="geometric_mean"),
        ColumnMap(column=3, role="spread", spread_kind="geoCV%", of=2)))
    assert validate_spec(spec, loose) == ()
    rows = RegionGrid.from_rows([["", 0.5, 1], ["Geo mean", 12.3, 20.1], ["SE", 3.1, 4.2]])
    spec = MappingSpec(kind="pk_summary", layout="wide_times", header_rows=1, first_data_row=2, time_row=1,
                       field="concentration", columns=(ColumnMap(column=1, role="arm"), ColumnMap(column=2, role="value"),
                                                       ColumnMap(column=3, role="value")),
                       row_rules=(RowRule(column=1, pattern="geo mean", role="arithmetic_mean"),
                                  RowRule(column=1, pattern="se", role="spread", spread_kind="SD")))
    assert [(f.code, f.location) for f in validate_spec(spec, rows)] == [
        ("STATISTIC_NOT_STATED", "row_rules[0]"), ("SPREAD_KIND_NOT_STATED", "row_rules[1]")]


@pytest.mark.parametrize(("pattern", "words"), [
    (r"(\w+\s?)+", "repeated group"), (r"(a|ab)+c", "repeated group"), (r"(mean)\1", "refers back"),
    (r"\s*mean\s*\(\s*sd\s*\)\s*", "at most 3"), ("x" * 201, "longer than 200"), (r"mean(", "not a valid"),
])
def test_a_pattern_that_could_run_without_end_is_bad(pattern, words):
    found = validate_spec(_with(row_rules=(RowRule(column=1, pattern=pattern, role="exclude", reason="x"),)), GRID)
    assert [(f.code, f.location) for f in found] == [("BAD_PATTERN", "row_rules[0]")] and words in found[0].message
    keyed = validate_spec(_with(keys=(KeyMap(pattern=pattern, field="pk.Cmax"),)), GRID)
    assert [(f.code, f.location) for f in keyed] == [("BAD_PATTERN", "keys[0]")]


@pytest.mark.parametrize("title", ["Study EX-7: plasma Exampleamide after single doses of 10-30 mg, pooled",
                                   "Study EX-7: plasma Exampleamide after single doses of 10 to 30 mg",
                                   "Study EX-7: plasma Exampleamide after 10, 20 or 30 mg"])
def test_a_range_or_a_list_of_doses_states_no_one_dose(title):
    grid = RegionGrid.from_rows([list(r) for r in (("Time (h)", "Conc (ng/mL)", "SD"), (1, 12.5, 1.1))], caption=[title])
    spec = _with(constants=(Constant(field="dose", cite=Cite(near="caption", line=1)),), lloq=None)
    assert _codes(spec, grid) == [("CONSTANT_NOT_STATED", "error")]
    urine = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)", "SD"], [1, 12.5, 1.1]], caption=["Urine collected 0-24 h"])
    spec = _with(constants=(Constant(field="interval_start_h", cite=Cite(near="caption", line=1)),
                            Constant(field="interval_end_h", cite=Cite(near="caption", line=1))), lloq=None)
    assert validate_spec(spec, urine) == ()
    assert [(c.field, c.value, c.unit) for c in execute(spec, urine).constants] == [] and {
        tuple(sorted(r.conditions.items())) for r in execute(spec, urine).rows} == {
        (("interval_end_h", "24"), ("interval_start_h", "0"))}


def test_a_count_or_a_ph_is_never_read_from_a_number_of_another_unit():
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)", "SD"], [1, 12.5, 1.1]],
                                caption=["Exampleamide 50 mg single dose, mean plasma concentrations"])
    for name in ("n", "ph"):
        spec = _with(constants=(Constant(field=name, cite=Cite(near="caption", line=1)),), lloq=None)
        assert _codes(spec, grid) == [("CONSTANT_NOT_STATED", "error")]
    assert read_constant("n", "Mean plasma concentrations in 24 healthy subjects") == (24.0, None)
    assert read_constant("n", "50 mg in 24 healthy subjects") == (24.0, None)
    assert read_constant("ph", "phosphate buffer pH 6.8") == (6.8, None)
    assert read_constant("ph", "pH 1.2 to 6.8") is None


def test_a_constant_is_read_under_the_regions_decimal_mark():
    comma = RegionGrid.from_rows([["Zeit (h)", "Konz (ng/mL)"], ["0,5", "12,5"], ["1", "14,25"]],
                                 caption=["Exampleamide Dosis 1.000 mg; LLOQ 0.500 ng/mL"])
    spec = MappingSpec(kind="pk_summary", layout="long", header_rows=1, first_data_row=2, field="concentration",
                       statistic="arithmetic_mean", columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")),
                       constants=(Constant(field="dose", cite=Cite(near="caption", line=1)),))
    found = validate_spec(spec, comma)
    assert [(f.code, f.location) for f in found] == [("CONSTANT_NOT_STATED", "constants[0] (dose)")]
    assert "'1.000' as ambiguous in this comma-decimal region" in found[0].message
    assert [f.code for f in validate_spec(spec.model_copy(update={"constants": (), "lloq": Cite(near="caption", line=1)}),
                                          comma)] == ["CONSTANT_NOT_STATED"]
    point = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)"], [0.5, 12.5]], caption=["Exampleamide 1,000 mg"])
    assert [f.code for f in validate_spec(spec, point)] == ["CONSTANT_NOT_STATED"]
    assert read_constant("dose", "Dosis 1.000 mg", decimal="comma") is None
    assert read_constant("dose", "Dosis 1.000 mg", decimal="point") == (1.0, "mg")
    assert read_constant("dose", "Dosis 2,5 mg", decimal="comma") == (2.5, "mg")
    assert read_constant("dose", "Dosis 2,5 mg", decimal="point") is None
    assert read_constant("dose", "Dose 1,000 mg") is None and read_constant("dose", "Dose 1.000 mg") is None


# --- a cached spec re-reads every region ---------------------------------------------------------------------------------


def test_two_sheets_with_one_layout_and_two_titles_give_two_studies_and_two_doses():
    spec = next(t.spec for t in MESSY.tables if t.id == "fasting-individual")      # the cached spec of the first sheet
    fasting, fed = (execute(spec, synthetic.truth_grid(MESSY, table)) for table in ("fasting-individual", "fed-individual"))
    for result, study, dose, food in ((fasting, "230-23", 50.0, "fasted"), (fed, "231-24", 100.0, "fed")):
        constants = {c.field: c.value for c in result.constants}
        assert (constants["study_id"], constants["dose"], constants["food_state"]) == (study, dose, food)
        assert {r.labels["study"] for r in result.rows} == {study}


def test_a_cached_spec_on_a_header_with_another_unit_fails_and_falls_through():
    spec = next(t.spec for t in MESSY.tables if t.id == "fasting-individual")
    grid = synthetic.truth_grid(MESSY, "fasting-individual")
    cells = dict(grid.cells)
    cells[(1, 2)] = cells[(1, 2)].__class__(**{**cells[(1, 2)].__dict__, "text": "Exampleamide plasma concentration (µg/L) "
                                                                                 "by time after dose (h)"})
    import dataclasses

    other = dataclasses.replace(grid, cells=cells)
    assert ("UNIT_NOT_STATED", "error") in _codes(spec, other)


# --- choices and readings -------------------------------------------------------------------------------------------------


def test_a_choice_constant_reads_every_choice_column_of_the_template_studies_row():
    columns = [c.name for c in SHEETS["Studies"]]
    row = dict(design="MD", crossover="no", population="healthy", special_population="pediatric", route="iv_infusion",
               dose_unit="mg/kg", salt_or_base="salt", product_role="RLD", formulation="ir_capsule", food_state="fed",
               matrix="plasma", intended_use="external_validation")
    grid = RegionGrid.from_rows([columns, [row.get(c, "") for c in columns]])
    for name, choice in row.items():
        cite = Cite(row=2, column=columns.index(name) + 1)
        constant = Constant(field=name, cite=cite, text=choice)
        spec = MappingSpec(kind="study_design", layout="long", header_rows=1, first_data_row=2,
                           columns=(ColumnMap(column=1, role="value", field="reference"),), constants=(constant,))
        assert validate_spec(spec, grid) == (), name
        assert read_constant(name, choice) == (choice, None)


def test_other_needs_the_word():
    assert read_constant("route", "other (inhaled)") == ("other", None)
    assert read_constant("route", "inhaled") is None
    grid = RegionGrid.from_rows([["Route", "Dose (mg)"], ["inhaled", 5]])
    spec = MappingSpec(kind="study_design", layout="long", header_rows=1, first_data_row=2,
                       columns=(ColumnMap(column=2, role="value", field="dose"),),
                       constants=(Constant(field="route", cite=Cite(row=2, column=1)),))
    assert _codes(spec, grid) == [("CONSTANT_NOT_STATED", "error")]


@pytest.mark.parametrize(("name", "text", "expected"), [
    ("dose", "Study 230-23, 50 mg, fasted", (50.0, "mg")),
    ("dose", "a single dose of 0.5 g", (0.5, "g")),
    ("dose", "500 µg once", (500.0, "µg")),
    ("dose", "50 mg then 100 mg", None),
    ("lloq", "BLQ: below the lower limit of quantification (0.5 ng/mL).", (0.5, "ng/mL")),
    ("ph", "Dissolution in 900 mL pH 6.8 phosphate buffer, 50 rpm", (6.8, None)),
    ("rpm", "Dissolution in 900 mL pH 6.8 phosphate buffer, 50 rpm", (50.0, "rpm")),
    ("volume_ml", "Dissolution in 900 mL pH 6.8 phosphate buffer, 50 rpm", (900.0, "mL")),
    ("n", "All concentrations in nmol/L; n = 16 healthy volunteers.", (16.0, None)),
    ("infusion_time_min", "during and after a 30-minute infusion", (30.0, "minute")),
    ("food_state", "Study 231-24, 100 mg, fed", ("fed", None)),
    ("matrix", "Exampleamide plasma concentration (ng/mL)", ("plasma", None)),
])
def test_read_constant(name, text, expected):
    assert read_constant(name, text) == expected


def test_read_text_constant_needs_one_match():
    constant = Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"(\d{3}-\d{2})")
    assert read_text_constant(constant, "Study 230-23, 50 mg") == "230-23"
    assert read_text_constant(constant, "Studies 230-23 and 231-24") is None
    assert read_text_constant(Constant(field="batch", cite=Cite(row=1, column=1)), "  L2301 ") == "L2301"


def test_a_key_value_spec_needs_its_keys_fields_known():
    grid = RegionGrid.from_rows([["Parameter", "Value"], ["Cmax", 31.2]])
    spec = MappingSpec(kind="pk_parameters", layout="key_value", header_rows=1, first_data_row=2,
                       columns=(ColumnMap(column=1, role="parameter"), ColumnMap(column=2, role="value")),
                       keys=(KeyMap(pattern="cmax", field="pk.Cmax_max"),))
    assert _codes(spec, grid) == [("UNKNOWN_FIELD", "error")]
