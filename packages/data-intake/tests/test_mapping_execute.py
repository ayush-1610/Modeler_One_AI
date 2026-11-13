"""D3: a mapping spec v2 executed by code over a region's grid (contracts §6.2, §8.5). Every truth table's approved spec,
executed on its true grid, gives exactly the truth and leaves no cell with a number unaccounted; every reading the
executor makes (BLQ, LLOQ, ULOQ, no sample, marks, decimal commas, U+2212, % formats, split cells, qualifier rows and
columns) is pinned on a small grid. Software test data (the made-up Exampleamide), never observed data."""

from __future__ import annotations

import dataclasses
import re

import pytest

from modeler_intake import synthetic
from modeler_intake.fields import field, read_choice
from modeler_intake.mapping.execute import ParsedCell, decimal_convention, execute, parse_cell, split_cell
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import Cite, ColumnMap, Constant, ExtractResult, MappingError, MappingSpec, RowRule
from modeler_intake.source_model import GridCell, RegionGrid, has_number

pytestmark = pytest.mark.req("T-47")

FILES = (synthetic.messy_workbook(), synthetic.pdf_report(), synthetic.word_report(), synthetic.delimited(),
         synthetic.template_workbook())
TABLES = [(f, t) for f in FILES for t in f.tables]
LABELS = ("study", "arm", "analyte", "matrix", "subject", "product", "batch", "vessel", "period", "occasion")
LABEL_ROLES = (*LABELS, "sequence", "other_arm", "parameter")


def _file(name: str) -> synthetic.SyntheticFile:
    return next(f for f in FILES if f.name == name)


def _table(file: synthetic.SyntheticFile, table_id: str) -> synthetic.TruthTable:
    return next(t for t in file.tables if t.id == table_id)


def _run(file_name: str, table_id: str) -> tuple[RegionGrid, ExtractResult]:
    file = _file(file_name)
    grid = synthetic.truth_grid(file, table_id)
    return grid, execute(_table(file, table_id).spec, grid)


def _number(text: str) -> float | None:
    text = text.strip().replace("\N{MINUS SIGN}", "-")
    if not text:
        return None
    return float(text.replace(",", ".")) if re.fullmatch(r"-?\d+,\d+", text) else float(text)


def _reading(text: str) -> tuple[float | None, bool, float | None, float | None]:
    """(value, censored, lloq, uloq) of a truth value as written."""
    text = text.strip().rstrip("*†‡")
    if text.upper() == "BLQ":
        return None, True, None, None
    if text.startswith("<"):
        return None, True, _number(text[1:]), None
    if text.startswith(">"):
        return None, False, None, _number(text[1:])
    try:
        return _number(text), False, None, None
    except ValueError:
        return None, False, None, None                     # a missing token ("NS")


def _truth_problems(file: synthetic.SyntheticFile, table: synthetic.TruthTable) -> list[str]:
    """Every difference between the truth of one table and what its spec, executed on its true grid, gives."""
    grid = synthetic.truth_grid(file, table.id)
    result = execute(table.spec, grid)
    truth = [v for v in file.values if v.table == table.id]
    lloqs = {v.locator: v for v in truth if v.field == "lloq"}
    texts = {c.locator: c.text for c in grid.cells.values()}
    rows = {(r.field, r.locator): r for r in result.rows}
    constants = {(c.field, c.locator): c for c in result.constants}
    problems: list[str] = []
    if len(rows) != len(result.rows) or len(constants) != len(result.constants):
        problems.append("a (field, locator) comes out twice")

    def same(what: str, got, expected) -> None:
        if got != expected:
            problems.append(f"{what}: {got!r} != {expected!r}")

    for v in truth:
        key = (v.field, v.locator)
        definition = field(v.field)
        at = dict(v.locators)
        if key in constants:
            c = constants.pop(key)
            if definition.value in ("number", "integer"):
                same(f"{key} value", c.value, _number(v.value))
                same(f"{key} unit", c.unit or "", v.unit)
            elif definition.value == "choice":
                same(f"{key} value", c.value, read_choice(v.field, v.value) or v.value)
            else:
                same(f"{key} value", c.value, v.value)
            continue
        if key not in rows:
            problems.append(f"missing {key}")
            continue
        r = rows.pop(key)
        same(f"{key} verbatim", r.verbatim, texts[v.locator])
        if definition.value in ("number", "integer"):
            number, censored, lloq, uloq = _reading(v.value)
            same(f"{key} value", r.value, number)
            same(f"{key} censored", r.censored, censored)
            same(f"{key} uloq", r.uloq, uloq)
            if censored and lloq is not None:
                same(f"{key} lloq", (r.lloq, r.lloq_unit), (lloq, v.unit or None))
            elif censored and at.get("lloq") in lloqs:
                stated = lloqs[at["lloq"]]
                same(f"{key} lloq", (r.lloq, r.lloq_unit), (_number(stated.value), stated.unit or None))
            else:
                same(f"{key} lloq", r.lloq, None)
            same(f"{key} lloq locator", r.lloq_locator, at.get("lloq"))
        else:
            same(f"{key} text", r.text_value, (read_choice(v.field, v.value) if definition.value == "choice" else None)
                 or v.value)
        same(f"{key} unit", (r.unit or "", r.unit_locator), (v.unit, at.get("unit")))
        same(f"{key} time", (r.time, r.time_unit or "", r.time_locator), (_number(v.time), v.time_unit, at.get("time")))
        same(f"{key} actual time", (r.time_actual, r.time_actual_locator), (_number(v.time_actual), at.get("time_actual")))
        same(f"{key} statistic", r.statistic or "", v.statistic)
        same(f"{key} spread", (r.spread, r.spread_kind or "", r.spread_locator),
             (_number(v.spread), v.spread_kind, at.get("spread")))
        same(f"{key} n", (r.n, r.n_locator), (int(v.n) if v.n else None, at.get("n")))
        same(f"{key} labels", {k: x for k, x in r.labels.items() if k != "parameter"},
             {role: getattr(v, role) for role in LABELS if getattr(v, role)})
        same(f"{key} label cells", r.label_locators, {role: loc for role, loc in at.items() if role in LABEL_ROLES})
        same(f"{key} conditions", (r.conditions, r.condition_locators),
             (dict(v.conditions), {name: at[name] for name, _x in v.conditions}))
    problems += [f"unexpected row {k}" for k in rows] + [f"unexpected constant {k}" for k in constants]
    return problems


def _cell_use_problems(grid: RegionGrid, result: ExtractResult) -> list[str]:
    problems = []
    used = [u.locator for u in result.cell_use]
    if sorted(used) != sorted(c.locator for c in grid.cells.values()) or len(set(used)) != len(used):
        problems.append("cell_use does not hold every non-empty cell exactly once")
    for u in result.cell_use:
        cell = grid.cell(u.row, u.column)
        if u.locator != cell.locator or u.numeric != (cell.merged_from is None and has_number(cell.text)):
            problems.append(f"{u.locator}: wrong locator or number flag")
        if u.use == "unaccounted" and u.numeric:
            problems.append(f"{u.locator} holds a number and is unaccounted ({cell.text!r})")
    return problems


@pytest.mark.parametrize(("file", "table"), TABLES, ids=[f"{f.name}:{t.id}" for f, t in TABLES])
def test_every_truth_spec_on_its_grid_gives_exactly_the_truth(file, table):
    """Each value with its truth locator, its labels, time, unit, statistic, spread, n, LLOQ and conditions, each
    qualifier with the locator of its own cell; no cell with a number left unaccounted."""
    assert _truth_problems(file, table) == []
    grid = synthetic.truth_grid(file, table.id)
    assert _cell_use_problems(grid, execute(table.spec, grid)) == []


def test_the_truth_covers_each_layout_and_each_format():
    assert {t.spec.layout for _f, t in TABLES} == {"long", "wide_series", "wide_times", "key_value"}
    assert {f.format for f, _t in TABLES} == {"xlsx", "pdf", "docx", "csv"}


def test_the_unruled_pdf_variant_reads_the_same_tables():
    file = synthetic.pdf_report(unruled_table=False)
    for table in file.tables:
        assert _truth_problems(file, table) == []


# --- the readings of the messy workbook ------------------------------------------------------------------------------


def _row(result: ExtractResult, cell: str):
    return next(r for r in result.rows if r.locator.endswith(f"!{cell}"))


def test_blq_lloq_uloq_no_sample_and_a_marked_value():
    _grid, result = _run("messy-delivery.xlsx", "fasting-individual")
    blq, below, above, no_sample, marked = (_row(result, c) for c in ("B4", "B6", "D7", "C8", "D6"))
    assert (blq.value, blq.censored, blq.lloq, blq.lloq_unit, blq.lloq_locator) == (None, True, 0.5, "ng/mL", "s:'Fasting'!A16")
    assert (below.value, below.censored, below.lloq, below.lloq_locator) == (None, True, 0.5, "s:'Fasting'!B6")
    assert (above.value, above.censored, above.uloq, above.verbatim) == (None, False, 1000.0, ">1000")
    assert (no_sample.value, no_sample.censored, no_sample.verbatim) == (None, False, "NS")
    uses = {u.locator: u for u in result.cell_use}
    assert (uses["s:'Fasting'!C8"].use, uses["s:'Fasting'!C8"].rule) == ("missing", "missing_token:NS")
    assert (marked.value, marked.verbatim) == (12.3, "12.3*")
    assert [(f.code, f.location, f.severity) for f in result.findings] == [("MARKED_VALUE", "s:'Fasting'!D6", "info")]
    # the LLOQ footnote and the title are cited context: they leave the outside count
    assert result.cited == ("s:'Fasting'!A1", "s:'Fasting'!A16")
    assert {(c.field, c.value, c.unit) for c in result.constants} >= {("lloq", 0.5, "ng/mL"), ("dose", 50.0, "mg")}


def test_mean_sd_and_n_rows_become_a_mean_series_with_spread_and_n_per_time():
    _grid, result = _run("messy-delivery.xlsx", "fasting-individual")
    means = sorted((r for r in result.rows if r.statistic == "arithmetic_mean"), key=lambda r: r.time)
    assert [(r.time, r.value, r.spread, r.spread_kind, r.n) for r in means] == [
        (0.0, None, None, None, 6), (0.5, 12.4037, 1.92, "SD", 5), (1.0, 30.38, 2.21, "SD", 4), (2.0, 26.03, 2.85, "SD", 6),
        (4.0, 14.47, 1.42, "SD", 6), (8.0, 4.96, 0.83, "SD", 5)]
    assert all("subject" not in r.labels for r in means)
    excluded = [u for u in result.cell_use if u.use == "excluded"]
    assert {u.rule for u in excluded} == {"row_rule:cv ?%"} and len(excluded) == 6       # the CV% row, label included


def test_a_mean_sd_cell_is_split_by_its_cell_form():
    _grid, result = _run("messy-delivery.xlsx", "summary-parameters")
    cmax = _row(result, "C3")
    assert (cmax.field, cmax.value, cmax.spread, cmax.spread_kind, cmax.spread_verbatim, cmax.verbatim) == (
        "pk.Cmax", 31.2, 4.1, "SD", "4.1", "31.2 (4.1)")
    assert (cmax.unit, cmax.labels["parameter"], cmax.label_locators["parameter"]) == ("ng/mL", "Cmax", "s:'Summary'!A3")


@pytest.mark.parametrize(("text", "form", "parts"), [
    ("12.3 (4.5)", "value (spread)", ("12.3", "4.5", None)),
    ("12.3 ± 4.5", "value ± spread", ("12.3", "4.5", None)),
    ("12.3 +/- 4.5", "value ± spread", ("12.3", "4.5", None)),
    ("0.95 (0.88-1.03)", "value (low-high)", ("0.95", "0.88", "1.03")),
    ("\N{MINUS SIGN}0.5 (\N{MINUS SIGN}1.2 to 0.3)", "value (low-high)", ("-0.5", "-1.2", "0.3")),
    ("12.3 ng/mL", "value unit", ("12.3", None, "ng/mL")),
    ("BLQ", "value (spread)", ("BLQ", None, None)),
    ("12.3", "value", ("12.3", None, None)),
])
def test_split_cell(text, form, parts):
    assert split_cell(text, form) == parts


# --- grids written for one reading -----------------------------------------------------------------------------------


def _spec(**changes) -> MappingSpec:
    base = dict(kind="pk_summary", layout="wide_series", header_rows=1, first_data_row=2, field="concentration",
                time_unit="h", time_unit_cite=Cite(row=1, column=1), statistic="arithmetic_mean")
    return MappingSpec(**{**base, **changes})


def test_a_second_spread_column_names_its_value_column_with_of():
    grid = RegionGrid.from_rows([["Time (h)", "Parent (ng/mL)", "SD", "Metabolite (ng/mL)", "SD"],
                                 [1, 10.1, 1.1, 2.2, 0.3], [2, 8.4, 0.9, 3.1, 0.4]])
    spec = _spec(columns=(ColumnMap(column=1, role="time"),
                          ColumnMap(column=2, role="value", unit="ng/mL", unit_cite=Cite(row=1, column=2)),
                          ColumnMap(column=3, role="spread", spread_kind="SD", of=2),
                          ColumnMap(column=4, role="value", unit="ng/mL", unit_cite=Cite(row=1, column=4)),
                          ColumnMap(column=5, role="spread", spread_kind="SD", of=4)))
    result = execute(spec, grid)
    assert [(r.locator, r.value, r.spread, r.spread_locator) for r in result.rows] == [
        ("s:'T'!B2", 10.1, 1.1, "s:'T'!C2"), ("s:'T'!D2", 2.2, 0.3, "s:'T'!E2"),
        ("s:'T'!B3", 8.4, 0.9, "s:'T'!C3"), ("s:'T'!D3", 3.1, 0.4, "s:'T'!E3")]
    assert _cell_use_problems(grid, result) == []
    with pytest.raises(MappingError, match="LAYOUT"):                    # an SD column of two value columns says which
        execute(spec.model_copy(update={"columns": (*spec.columns[:2], ColumnMap(column=3, role="spread"),
                                                     *spec.columns[3:])}), grid)


def test_an_interval_pair_with_its_level_and_a_min_max_range():
    grid = RegionGrid.from_rows([["Time (h)", "Geo mean (ng/mL)", "90% CI lower", "90% CI upper", "Min", "Max"],
                                 [1, 10.0, 8.1, 12.3, 6.0, 15.5]], caption=["Geometric mean with its 90% CI"])
    spec = _spec(statistic="geometric_mean", columns=(
        ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value", unit="ng/mL", unit_cite=Cite(row=1, column=2)),
        ColumnMap(column=3, role="interval_low", of=2, level=Cite(near="caption", line=1)),
        ColumnMap(column=4, role="interval_high", of=2, level=Cite(near="caption", line=1)),
        ColumnMap(column=5, role="ignore", reason="min and max restate the range"),
        ColumnMap(column=6, role="ignore", reason="min and max restate the range")))
    (row,) = execute(spec, grid).rows
    assert (row.interval, row.interval_kind, row.interval_level, row.interval_locators) == (
        (8.1, 12.3), "CI", 90.0, ("s:'T'!C3", "s:'T'!D3"))
    ranged = spec.model_copy(update={"columns": (spec.columns[0], spec.columns[1], ColumnMap(column=5, role="interval_low", of=2),
                                                 ColumnMap(column=6, role="interval_high", of=2),
                                                 ColumnMap(column=3, role="ignore", reason="the CI is read elsewhere"),
                                                 ColumnMap(column=4, role="ignore", reason="the CI is read elsewhere"))})
    (row,) = execute(ranged, grid).rows
    assert (row.interval, row.interval_kind, row.interval_level) == ((6.0, 15.5), "range", None)


def test_a_value_with_its_interval_in_one_cell_reads_the_level_at_its_cite():
    grid = RegionGrid.from_rows([["Parameter", "GMR (90% CI)"], ["Cmax", "0.95 (0.88-1.03)"], ["AUC_last", "1.02 (0.97-1.08)"]])
    spec = MappingSpec(kind="ddi_relation", layout="key_value", header_rows=1, first_data_row=2,
                       columns=(ColumnMap(column=1, role="parameter"),
                                ColumnMap(column=2, role="value", cell_form="value (low-high)", level=Cite(row=1, column=2))),
                       keys=(dict(pattern="cmax", field="relation.test_vs_reference.Cmax"),
                             dict(pattern="auc_last", field="relation.test_vs_reference.AUC_last")))
    result = execute(spec, grid)
    assert [(r.field, r.value, r.interval, r.interval_kind, r.interval_level) for r in result.rows] == [
        ("relation.test_vs_reference.Cmax", 0.95, (0.88, 1.03), "CI", 90.0),
        ("relation.test_vs_reference.AUC_last", 1.02, (0.97, 1.08), "CI", 90.0)]


def test_per_column_units_and_lloqs():
    grid = RegionGrid.from_rows(
        [["Time (h)", "Parent (ng/mL)", "Metabolite (nmol/L)"], [0, "BLQ", "BLQ"], [1, 12.5, "<0.2"]],
        below=[["Parent LLOQ 0.5 ng/mL"], ["Metabolite LLOQ 0.2 nmol/L"]])
    spec = _spec(kind="pk_individual", statistic="individual", below_lloq_tokens=("BLQ",), columns=(
        ColumnMap(column=1, role="time"),
        ColumnMap(column=2, role="value", unit="ng/mL", unit_cite=Cite(row=1, column=2), lloq=Cite(near="below", line=1),
                  series=Cite(row=1, column=2), series_role="analyte"),
        ColumnMap(column=3, role="value", unit="nmol/L", unit_cite=Cite(row=1, column=3), lloq=Cite(near="below", line=2),
                  series=Cite(row=1, column=3), series_role="analyte")))
    result = execute(spec, grid)
    got = {r.locator: (r.unit, r.unit_locator, r.lloq, r.lloq_unit, r.lloq_locator, r.labels["analyte"]) for r in result.rows}
    assert got == {
        "s:'T'!B2": ("ng/mL", "s:'T'!B1", 0.5, "ng/mL", "s:'T'!A4", "Parent (ng/mL)"),
        "s:'T'!C2": ("nmol/L", "s:'T'!C1", 0.2, "nmol/L", "s:'T'!A5", "Metabolite (nmol/L)"),
        "s:'T'!B3": ("ng/mL", "s:'T'!B1", None, None, None, "Parent (ng/mL)"),
        "s:'T'!C3": ("nmol/L", "s:'T'!C1", 0.2, "nmol/L", "s:'T'!C3", "Metabolite (nmol/L)")}
    assert set(result.cited) == {"s:'T'!A4", "s:'T'!A5"}


def test_two_dissolution_media_are_conditions_never_two_values_of_one_thing():
    _g, vessels = _run("messy-delivery.xlsx", "dissolution-vessels")
    _g, summary = _run("messy-delivery.xlsx", "dissolution-summary")
    assert {tuple(sorted(r.conditions.items())) for r in vessels.rows} == {(("medium", "HCl buffer"), ("ph", "1.2"))}
    assert {tuple(sorted(r.conditions.items())) for r in summary.rows} == {(("medium", "phosphate buffer"), ("ph", "6.8"))}
    grid = RegionGrid.from_rows([["Medium", "Time (min)", "% dissolved"], ["pH 1.2", 15, 61.0], ["pH 6.8", 15, 44.0]])
    spec = MappingSpec(kind="dissolution", layout="long", header_rows=1, first_data_row=2, field="percent_dissolved",
                       columns=(ColumnMap(column=1, role="condition", condition="medium"), ColumnMap(column=2, role="time"),
                                ColumnMap(column=3, role="value")))
    assert [(r.time, r.value, r.conditions) for r in execute(spec, grid).rows] == [
        (15.0, 61.0, {"medium": "pH 1.2"}), (15.0, 44.0, {"medium": "pH 6.8"})]


def test_time_and_actual_time_and_a_blq_flag_column():
    _grid, result = _run("client-data-template.xlsx", "template-pk_individual")
    first, blq = _row(result, "H2"), _row(result, "H4")
    assert (first.time, first.time_actual, first.time_unit, first.time_actual_locator) == (0.5, 0.52, "h", "s:'PK_Individual'!F2")
    assert (blq.censored, blq.lloq, blq.labels["period"]) == (True, None, "1")


def test_a_statistic_column_and_a_spread_kind_column():
    _g, summary = _run("client-data-template.xlsx", "template-pk_summary")
    _g, parameters = _run("client-data-template.xlsx", "template-pk_parameters")
    assert {(r.statistic, r.spread_kind) for r in summary.rows} == {("arithmetic_mean", "SD")}
    assert {(r.field, r.statistic, r.spread_kind) for r in parameters.rows} == {
        ("pk.Cmax", "geometric_mean", "CV%"), ("pk.AUC_last", "geometric_mean", "CV%")}


# --- decimal marks, signs, formats -----------------------------------------------------------------------------------


def _cell(text, value=None, number_format: str = "") -> GridCell:
    return GridCell(text=text, value=text if value is None else value, type="text", locator="s:'T'!A1",
                    number_format=number_format)


@pytest.mark.parametrize(("text", "decimal", "column_has_decimal", "expected"), [
    ("12.5", "point", False, 12.5), ("1,234.5", "point", False, 1234.5), ("1,234", "point", True, 1234.0),
    ("1,234", "point", False, "ambiguous"), ("12,5", "point", True, "ambiguous"), ("1 234.5", "point", False, 1234.5),
    ("12,5", "comma", False, 12.5), ("1.234,5", "comma", False, 1234.5), ("1.234", "comma", True, 1234.0),
    ("1.234", "comma", False, "ambiguous"), ("12.5", "comma", True, "ambiguous"), ("0.125", "comma", True, "ambiguous"),
    ("1 234,5", "comma", False, 1234.5), ("\N{MINUS SIGN}1.5", "point", False, -1.5), ("-3e-2", "point", False, -0.03),
    (".5", "point", False, 0.5), ("55 %", "point", False, 55.0), ("15.01.2024", "point", False, "not a number"),
])
def test_parse_cell_reads_a_number_under_the_regions_convention(text, decimal, column_has_decimal, expected):
    parsed = parse_cell(_cell(text), decimal=decimal, column_has_decimal=column_has_decimal, below_lloq_tokens=(),
                        missing_tokens=())
    if isinstance(expected, float):
        assert (parsed.value, parsed.problem) == (expected, "")
    else:
        assert parsed.value is None and expected in parsed.problem


@pytest.mark.parametrize(("cell", "expected"), [
    (_cell("<0.5"), ParsedCell(value=None, censored=True, lloq=0.5)),
    (_cell("< 0,5"), ParsedCell(value=None, censored=True, lloq=0.5)),
    (_cell(">1000"), ParsedCell(value=None, uloq=1000.0)),
    (_cell("blq"), ParsedCell(value=None, censored=True)),
    (_cell("NS"), ParsedCell(value=None, missing=True)),
    (_cell("12.3*"), ParsedCell(value=12.3, marker="*")),
    (_cell("12.3 †"), ParsedCell(value=12.3, marker="†")),
    (_cell("0.55", 0.55, "0%"), ParsedCell(value=55.0)),
    (_cell("12.4037", 12.4037, "0.00"), ParsedCell(value=12.4037)),
    (_cell("TRUE", True), ParsedCell(value=None, problem="'TRUE' is a TRUE/FALSE cell, not a number")),
])
def test_parse_cell_tokens_comparators_marks_and_stored_numbers(cell, expected):
    comma = cell.text == "< 0,5"
    got = parse_cell(cell, decimal="comma" if comma else "point", column_has_decimal=False, below_lloq_tokens=("BLQ",),
                     missing_tokens=("NS",))
    assert got == expected


def test_decimal_commas_are_decided_by_code_from_the_region():
    _grid, listing = _run("concentrations.csv", "delimited-listing")
    assert listing.decimal == "comma" and _row(listing, "C4").value == 12.5 and _row(listing, "C4").time == 0.5
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)", "Dose (mg)"], ["0,5", "12,5", "1.234"], ["1", "1.234", "2,5"],
                                 ["2", "12.5", "3,0"]])
    assert decimal_convention(grid) == "comma"
    spec = _spec(kind="pk_individual", statistic="individual", columns=(
        ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"),
        ColumnMap(column=3, role="ignore", reason="the dose is read elsewhere")))
    result = execute(spec, grid)
    # "1.234" under C2's other cells: "12,5" writes a decimal comma, so the dot groups thousands; "12.5" stays ambiguous
    assert [(r.locator, r.value) for r in result.rows] == [("s:'T'!B2", 12.5), ("s:'T'!B3", 1234.0)]
    assert [(f.code, f.location) for f in result.findings] == [("UNPARSEABLE_VALUE", "s:'T'!B4")]
    assert "ambiguous" in result.findings[0].message
    unaccounted = [u.locator for u in result.cell_use if u.use == "unaccounted"]
    assert unaccounted == ["s:'T'!B4"]                                 # counted as silent loss, never dropped
    point = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)"], ["1", "1,234"], ["2", "12.5"]])
    assert decimal_convention(point) == "point"
    assert [r.value for r in execute(spec.model_copy(update={"columns": spec.columns[:2]}), point).rows] == [1234.0, 12.5]


def test_u2212_is_read_as_a_minus_sign():
    grid = RegionGrid.from_rows([["Time (h)", "Change from baseline"], [1, "\N{MINUS SIGN}0.4"], [2, "0.3"]])
    spec = _spec(field="pk.Cmax", time_unit=None, time_unit_cite=None, kind="pk_parameters",
                 columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")))
    assert [r.value for r in execute(spec, grid).rows] == [-0.4, 0.3]


def test_a_percent_number_format_is_read_times_100_with_unit_percent():
    grid = RegionGrid.from_rows([["Time (min)", "Released"], [15, 0.55], [30, 0.875]])
    cells = {k: dataclasses.replace(c, number_format="0.0%") if k[1] == 2 and k[0] > 1 else c for k, c in grid.cells.items()}
    grid = dataclasses.replace(grid, cells=cells)
    spec = MappingSpec(kind="dissolution", layout="wide_series", header_rows=1, first_data_row=2, field="percent_dissolved",
                       time_unit="min", time_unit_cite=Cite(row=1, column=1),
                       columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")))
    result = execute(spec, grid)
    assert [(r.value, r.unit, r.unit_locator) for r in result.rows] == [(55.0, "%", "s:'T'!B2"), (87.5, "%", "s:'T'!B3")]
    assert [(f.code, f.severity) for f in result.findings] == [("PERCENT_FORMAT", "info")]


# --- the count ---------------------------------------------------------------------------------------------------------


def test_cell_use_covers_every_non_empty_cell_and_an_unmapped_number_is_unaccounted():
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)", "Comment"], [1, 12.5, "re-assayed 2x"], [2, 8.1, "ok"]])
    spec = _spec(kind="pk_individual", statistic="individual",
                 columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")))
    result = execute(spec, grid)
    uses = {u.locator: (u.use, u.numeric) for u in result.cell_use}
    assert uses == {"s:'T'!A1": ("header", False), "s:'T'!B1": ("header", False), "s:'T'!C1": ("header", False),
                    "s:'T'!A2": ("time", True), "s:'T'!B2": ("value", True), "s:'T'!C2": ("unaccounted", True),
                    "s:'T'!A3": ("time", True), "s:'T'!B3": ("value", True), "s:'T'!C3": ("unaccounted", False)}
    assert _cell_use_problems(grid, result) == ["s:'T'!C2 holds a number and is unaccounted ('re-assayed 2x')"]


def test_a_merged_copy_is_never_a_value_nor_counted():
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)"], [1, 12.5], [2, 12.5]])
    cells = dict(grid.cells)
    cells[(3, 2)] = dataclasses.replace(cells[(3, 2)], merged_from=cells[(2, 2)].locator)
    grid = dataclasses.replace(grid, cells=cells)
    spec = _spec(kind="pk_individual", statistic="individual",
                 columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")))
    result = execute(spec, grid)
    assert [r.locator for r in result.rows] == ["s:'T'!B2"]
    copy = next(u for u in result.cell_use if u.locator == "s:'T'!B3")
    assert (copy.use, copy.numeric, copy.rule) == ("excluded", False, "merged_copy")


def test_a_non_numeric_sd_cell_is_a_finding_not_an_exception():
    grid = RegionGrid.from_rows([["Time (h)", "Mean (ng/mL)", "SD"], [1, 12.5, "NC"], [2, 8.1, "1,2.3"]])
    spec = _spec(columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"),
                          ColumnMap(column=3, role="spread", spread_kind="SD", of=2)))
    result = execute(spec, grid)
    assert [r.spread for r in result.rows] == [None, None]
    assert [(f.code, f.location) for f in result.findings] == [("UNPARSEABLE_SPREAD", "s:'T'!C2"),
                                                               ("UNPARSEABLE_SPREAD", "s:'T'!C3")]
    assert {u.locator: u.use for u in result.cell_use if u.column == 3 and u.row > 1} == {
        "s:'T'!C2": "unaccounted", "s:'T'!C3": "unaccounted"}


def test_an_invalid_spec_is_refused_before_anything_is_read():
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)"], [1, 12.5]])
    with pytest.raises(MappingError, match="UNIT_NOT_STATED"):
        execute(_spec(value_unit="µg/mL", value_unit_cite=Cite(row=1, column=2),
                      columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"))), grid)


def test_a_not_data_table_has_every_cell_excluded_and_no_value():
    _grid, result = _run("client-data-template.xlsx", "template-readme")
    assert result.rows == () and result.constants == ()
    assert {(u.use, u.rule) for u in result.cell_use} == {("excluded", "not_data")}


def test_a_row_rule_mean_row_under_long_rows_and_an_unattached_sd_row():
    grid = RegionGrid.from_rows([["Subject", "Time (h)", "Conc (ng/mL)"], ["S1", 1, 10.0], ["S2", 1, 12.0], ["SD", "", 1.4],
                                 ["Mean", 1, 11.0]])
    spec = MappingSpec(kind="pk_individual", layout="long", header_rows=1, first_data_row=2, field="concentration",
                       statistic="individual",
                       columns=(ColumnMap(column=1, role="subject"), ColumnMap(column=2, role="time"),
                                ColumnMap(column=3, role="value")),
                       row_rules=(RowRule(column=1, pattern="mean", role="arithmetic_mean"),
                                  RowRule(column=1, pattern="sd", role="spread", spread_kind="SD")))
    result = execute(spec, grid)
    mean = _row(result, "C5")
    assert (mean.statistic, mean.spread, mean.spread_locator, mean.labels) == ("arithmetic_mean", 1.4, "s:'T'!C4", {})
    assert [r.labels.get("subject") for r in result.rows] == ["S1", "S2", None]


def test_a_constant_of_a_title_and_a_naming_constant_reach_every_row():
    grid = RegionGrid.from_rows([["Time (h)", "Mean (ng/mL)"], [1, 3.2], [2, 5.8]],
                                caption=["Study EX-7, Cohort 2 (30 mg): plasma concentrations"])
    spec = _spec(columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")),
                 value_unit="ng/mL", value_unit_cite=Cite(row=1, column=2),
                 constants=(Constant(field="study_id", cite=Cite(near="caption", line=1), pattern=r"Study (\S+),"),
                            Constant(field="treatment", cite=Cite(near="caption", line=1), pattern=r", (Cohort \d+) \("),
                            Constant(field="dose", cite=Cite(near="caption", line=1)),
                            Constant(field="matrix", cite=Cite(near="caption", line=1))))
    result = execute(spec, grid)
    assert {(c.field, c.value, c.unit) for c in result.constants} == {("study_id", "EX-7", None),
                                                                      ("treatment", "Cohort 2", None), ("dose", 30.0, "mg")}
    assert {tuple(sorted(r.labels.items())) for r in result.rows} == {
        (("arm", "Cohort 2"), ("matrix", "plasma"), ("study", "EX-7"))}
    assert result.cited == ("s:'T'!A1",)


# --- never overwritten, never assumed (the review of 2026-11-13) --------------------------------------------------------


def _long_summary(rows, **changes) -> MappingSpec:
    base = dict(kind="pk_summary", layout="long", header_rows=1, first_data_row=2, field="concentration",
                columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="arm"), ColumnMap(column=3, role="value")),
                row_rules=(RowRule(column=2, pattern="mean", role="arithmetic_mean"),
                           RowRule(column=2, pattern="sd", role="spread", spread_kind="SD"),
                           RowRule(column=2, pattern="n", role="n")))
    return MappingSpec(**{**base, **changes})


def test_an_sd_row_qualifies_the_mean_of_its_own_time_grouped_or_interleaved():
    grouped = RegionGrid.from_rows([["Time (h)", "Statistic", "Conc (ng/mL)"], [0.5, "Mean", 12.3], [1, "Mean", 15.1],
                                    [2, "Mean", 9.8], [2, "SD", 2.1], [0.5, "SD", 4.5], [1, "SD", 3.2]])
    result = execute(_long_summary(grouped), grouped)
    assert [(r.time, r.value, r.spread, r.spread_locator) for r in result.rows] == [
        (0.5, 12.3, 4.5, "s:'T'!C6"), (1.0, 15.1, 3.2, "s:'T'!C7"), (2.0, 9.8, 2.1, "s:'T'!C5")]
    interleaved = RegionGrid.from_rows([["Time (h)", "Statistic", "Conc (ng/mL)"], [0.5, "Mean", 12.3], [0.5, "SD", 4.5],
                                        [0.5, "N", 12], [1, "Mean", 15.1], [1, "SD", 3.2], [1, "N", 11]])
    result = execute(_long_summary(interleaved), interleaved)
    assert [(r.time, r.value, r.spread, r.n) for r in result.rows] == [(0.5, 12.3, 4.5, 12), (1.0, 15.1, 3.2, 11)]
    for grid, outcome in ((grouped, execute(_long_summary(grouped), grouped)), (interleaved, result)):
        assert _cell_use_problems(grid, outcome) == []                 # the SD and N rows' own times are read
        assert outcome.findings == ()


def test_a_qualifier_row_of_a_time_with_no_mean_is_a_finding_and_stays_unaccounted():
    grid = RegionGrid.from_rows([["Time (h)", "Statistic", "Conc (ng/mL)"], [0.5, "Mean", 12.3], [3, "SD", 4.5]])
    result = execute(_long_summary(grid), grid)
    assert [(r.value, r.spread) for r in result.rows] == [(12.3, None)]
    assert [(f.code, f.location) for f in result.findings] == [("QUALIFIER_WITHOUT_VALUE", "s:'T'!C3")]
    assert next(u for u in result.cell_use if u.locator == "s:'T'!C3").use == "unaccounted"


def test_a_second_spread_or_n_is_never_written_over_the_first():
    grid = RegionGrid.from_rows([["Time (h)", "Statistic", "Conc (ng/mL)", "SD"], [1, "Mean", 12.3, 3.1], [1, "SD", 4.2, ""]])
    spec = _long_summary(grid, columns=(*_long_summary(grid).columns, ColumnMap(column=4, role="spread", spread_kind="SD",
                                                                                  of=3)))
    result = execute(spec, grid)
    (row,) = result.rows
    assert (row.spread, row.spread_locator) == (3.1, "s:'T'!D2")
    assert [(f.code, f.location, f.severity) for f in result.findings] == [("QUALIFIER_TWICE", "s:'T'!C3", "warn")]
    assert next((u.use, u.rule) for u in result.cell_use if u.locator == "s:'T'!C3") == ("unaccounted", "qualifier_twice")
    # two spread columns of one value, or two spread row rules that match rows, are refused before anything is read
    wide = RegionGrid.from_rows([["", 0.5, 1], ["Mean", 12.3, 20.1], ["SD", 3.1, 4.2], ["CV%", 25.2, 20.9]])
    rows = MappingSpec(kind="pk_summary", layout="wide_times", header_rows=1, first_data_row=2, time_row=1,
                       field="concentration", columns=(ColumnMap(column=1, role="arm"), ColumnMap(column=2, role="value"),
                                                       ColumnMap(column=3, role="value")),
                       row_rules=(RowRule(column=1, pattern="mean", role="arithmetic_mean"),
                                  RowRule(column=1, pattern="sd", role="spread", spread_kind="SD"),
                                  RowRule(column=1, pattern="cv%", role="spread", spread_kind="CV%")))
    with pytest.raises(MappingError, match="two spread row rules"):
        execute(rows, wide)
    excluded = rows.model_copy(update={"row_rules": (*rows.row_rules[:2], RowRule(column=1, pattern="cv%", role="exclude",
                                                                                  reason="restates the SD"))})
    assert [(r.value, r.spread, r.spread_kind) for r in execute(excluded, wide).rows] == [(12.3, 3.1, "SD"), (20.1, 4.2, "SD")]
    columns = RegionGrid.from_rows([["Time (h)", "Mean (ng/mL)", "SD", "CV%"], [1, 12.3, 3.1, 25.2]])
    two = _spec(columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"),
                         ColumnMap(column=3, role="spread", spread_kind="SD", of=2),
                         ColumnMap(column=4, role="spread", spread_kind="CV%", of=2)))
    with pytest.raises(MappingError, match="two spreads for the values of column 2"):
        execute(two, columns)


def test_a_time_cell_that_writes_its_own_unit_keeps_it():
    grid = RegionGrid.from_rows([["Time", "Conc (ng/mL)"], ["15 min", 3.1], ["30 min", 8.2], ["1 h", 12.0]],
                                caption=["Times in h"])
    spec = _spec(layout="long", time_unit="h", time_unit_cite=Cite(near="caption", line=1),
                 columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")))
    result = execute(spec, grid)
    assert [(r.time, r.time_unit) for r in result.rows] == [(15.0, "min"), (30.0, "min"), (1.0, "h")]
    assert [(f.code, f.location, f.severity) for f in result.findings] == [
        ("TIME_UNIT_CONFLICT", "s:'T'!A3", "warn"), ("TIME_UNIT_CONFLICT", "s:'T'!A4", "warn")]
    actual = RegionGrid.from_rows([["Time (h)", "Actual", "Conc (ng/mL)"], [0.5, "35 min", 3.1], [1, 1.1, 8.2]])
    spec = _spec(layout="long", kind="pk_individual", statistic="individual",
                 columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="time_actual"),
                          ColumnMap(column=3, role="value")))
    result = execute(spec, actual)
    assert [(r.time, r.time_unit, r.time_actual) for r in result.rows] == [(0.5, "h", None), (1.0, "h", 1.1)]
    assert [(f.code, f.location) for f in result.findings] == [("TIME_UNIT_CONFLICT", "s:'T'!B2")]


def test_an_lloq_column_qualifies_every_row_with_its_own_unit():
    grid = RegionGrid.from_rows([["Subject", "Time (h)", "Conc (ng/mL)", "LLOQ (pg/mL)"], ["S01", 0.5, "BLQ", 50],
                                 ["S01", 1, 12.3, 50], ["S01", 2, 3.3, "n/a"]])
    spec = MappingSpec(kind="pk_individual", layout="long", header_rows=1, first_data_row=2, field="concentration",
                       below_lloq_tokens=("BLQ",), columns=(
                           ColumnMap(column=1, role="subject"), ColumnMap(column=2, role="time"),
                           ColumnMap(column=3, role="value", unit="ng/mL", unit_cite=Cite(row=1, column=3)),
                           ColumnMap(column=4, role="lloq")))
    result = execute(spec, grid)
    assert [(r.value, r.unit, r.lloq, r.lloq_unit, r.lloq_locator) for r in result.rows] == [
        (None, "ng/mL", 50.0, "pg/mL", "s:'T'!D2"), (12.3, "ng/mL", 50.0, "pg/mL", "s:'T'!D3"),
        (3.3, "ng/mL", None, None, None)]
    assert [(f.code, f.location) for f in result.findings] == [("UNPARSEABLE_LLOQ", "s:'T'!D4")]
    assert _cell_use_problems(grid, result) == []
    # a typed and cited unit on the LLOQ column; a header that writes none leaves the LLOQ's unit unstated
    typed = spec.model_copy(update={"columns": (*spec.columns[:3], ColumnMap(column=4, role="lloq", unit="pg/mL",
                                                                                unit_cite=Cite(row=1, column=4)))})
    assert validate_spec(typed, grid) == () and execute(typed, grid).rows[0].lloq_unit == "pg/mL"
    bare = RegionGrid.from_rows([["Subject", "Time (h)", "Conc (ng/mL)", "LLOQ"], ["S01", 0.5, "BLQ", 50]])
    assert execute(spec, bare).rows[0].lloq_unit is None


def test_a_percent_written_in_a_text_value_cell_is_its_unit():
    grid = RegionGrid.from_rows([["Time (min)", "Dissolved"], [15, "45 %"], [30, "80%"]])
    spec = MappingSpec(kind="dissolution", layout="long", header_rows=1, first_data_row=2, field="percent_dissolved",
                       columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")))
    assert [(r.value, r.unit, r.unit_locator) for r in execute(spec, grid).rows] == [
        (45.0, "%", "s:'T'!B2"), (80.0, "%", "s:'T'!B3")]
    conc = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)"], [1, "12.5%"]])
    result = execute(_spec(value_unit="ng/mL", value_unit_cite=Cite(row=1, column=2),
                           columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value"))), conc)
    assert (result.rows[0].unit, [(f.code, f.severity) for f in result.findings]) == ("%", [("UNIT_CONFLICT", "warn")])


def test_an_unparseable_spread_is_a_warning_wherever_it_is_written():
    grid = RegionGrid.from_rows([["Time (h)", "Mean (SD) ng/mL"], [1, "12.3 (NC)"], [2, "9.1 (1.2)"]])
    spec = _spec(columns=(ColumnMap(column=1, role="time"),
                          ColumnMap(column=2, role="value", cell_form="value (spread)", spread_kind="SD")))
    result = execute(spec, grid)
    assert [(r.value, r.spread) for r in result.rows] == [(12.3, None), (9.1, 1.2)]
    assert [(f.code, f.severity) for f in result.findings] == [("UNPARSEABLE_SPREAD", "warn")]
    assert next((u.use, u.rule) for u in result.cell_use if u.locator == "s:'T'!B2") == ("value", "spread_unparsed")


def test_a_constant_is_read_under_the_regions_decimal_mark():
    grid = RegionGrid.from_rows([["Zeit (h)", "Konz (ng/mL)"], ["0,5", "12,5"], ["1", "14,25"], ["2", "1.234,5"]],
                                caption=["Exampleamide Dosis 1.000 mg"], below=[["Dosis 2,5 mg; LLOQ 0,5 ng/mL"]])
    spec = _spec(layout="long", time_unit="h", time_unit_cite=Cite(row=1, column=1),
                 columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")),
                 constants=(Constant(field="dose", cite=Cite(near="below", line=1)),), lloq=Cite(near="below", line=1))
    result = execute(spec, grid)
    assert result.decimal == "comma" and [r.value for r in result.rows] == [12.5, 14.25, 1234.5]
    assert {(c.field, c.value, c.unit) for c in result.constants} == {("dose", 2.5, "mg"), ("lloq", 0.5, "ng/mL")}
    with pytest.raises(MappingError, match="'1.000' as ambiguous in this comma-decimal region"):
        execute(spec.model_copy(update={"constants": (Constant(field="dose", cite=Cite(near="caption", line=1)),)}), grid)


def test_a_pattern_that_could_run_without_end_is_refused_before_it_is_run():
    footnote = "Values below the LLOQ were set to zero for the mean."            # 52 characters: (\w+\s?)+ never ends
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/mL)"], [0.5, 1.2], [footnote, None]])
    spec = _spec(layout="long", columns=(ColumnMap(column=1, role="time"), ColumnMap(column=2, role="value")),
                 row_rules=(RowRule(column=1, pattern=r"(\w+\s?)+", role="exclude", reason="a footnote"),))
    with pytest.raises(MappingError, match="BAD_PATTERN"):
        execute(spec, grid)
    flat = spec.model_copy(update={"row_rules": (RowRule(column=1, pattern=r"values below.*", role="exclude",
                                                         reason="a footnote"),)})
    assert [u.use for u in execute(flat, grid).cell_use if u.row == 3] == ["excluded"]
