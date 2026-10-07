"""T-47: a client sheet is described by a form a person can fill in; the page's first filling is read from the sheet."""

from __future__ import annotations

import pytest
from openpyxl import Workbook

from modeler_intake.apply import apply_recipe
from modeler_intake.grid import read_workbook_bytes
from modeler_intake.recipe import ColumnMapping, MappingRecipe, TableMapping
from modeler_intake.sheet_form import SheetForm, preview_rows, suggest, to_proposal
from modeler_intake.triage import SheetCategory, triage_sheet
from modeler_intake.validate import validate_concentrations, validate_dissolution

pytestmark = pytest.mark.req("T-47")
TIMES = ["Pre-dose", "0.50", "1.00", "2.00", "4.00", "8.00", "12.00", "24.00", "48.00", "72.00"]


def _grid(build, name: str = "client.xlsx"):
    import io

    wb = Workbook()
    build(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return read_workbook_bytes(buf.getvalue(), name)


def _be(wb):
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Study 230-23: plasma concentrations of desvenlafaxine (ng/mL) after a single 50 mg dose"])
    ws.append([])
    ws.append(["Time (hr)"])
    ws.append(["Subject No.", "Period", *TIMES])
    ws.append(["001", "I", "BLQ", 12.1, 40.5, 80.2, 95.0, 60.1, 41.0, 12.3, 2.1, "BLQ"])
    ws.append(["002", "II", "BLQ", 10.0, 35.0, 70.4, 88.8, 55.5, 39.9, 10.8, "NS", "BLQ"])
    ws.append(["003", "I", "BLQ", 9.1, 30.2, 66.0, 81.0, 50.0, 35.5, 9.9, 1.5, "BLQ"])
    ws.append(["Mean", None, None, 10.4, 35.2, 72.2, 88.3, 55.2, 38.8, 11.0, 1.8, None])
    ws.append(["SD", None, None, 1.5, 5.2, 7.2, 7.0, 5.0, 2.9, 1.2, 0.4, None])
    ws.append([])
    ws.append(["BLQ = below the lower limit of quantification (1.00 ng/mL); NS = no sample"])


def _recipe(proposal: dict) -> MappingRecipe:
    tables = []
    for t in proposal["tables"]:
        constants = {c["key"]: float(c["value"]) if c["key"] in ("dose", "ph", "rpm", "n", "strength_mg", "volume_ml")
                     else c["value"] for c in t["constants"]}
        tables.append(TableMapping(**{**{k: v for k, v in t.items() if k not in ("constants", "evidence")},
                                      "columns": [ColumnMapping(**c) for c in t["columns"]], "constants": constants}))
    return MappingRecipe(recipe_id="r", tables=tables)


def _quotes_hold(grid, proposal: dict) -> bool:
    sheet = grid.sheets[proposal["tables"][0]["sheet"]]
    for e in proposal["tables"][0]["evidence"]:
        ref = e["cell"].split("!")[1]
        column = "".join(ch for ch in ref if ch.isalpha())
        row = int("".join(ch for ch in ref if ch.isdigit()))
        if e["quote"] not in str(sheet.cell(row, column).value):
            return False
    return True


def test_a_be_study_with_times_across_the_top_is_suggested_and_read():
    grid = _grid(_be, "230-23 Fasting Reference.xlsx")
    form, notes = suggest(grid.sheets["Sheet1"], filename="230-23 Fasting Reference.xlsx", drug="desvenlafaxine")
    assert form.layout == "times_across" and form.header_row == 4 and form.first_data_row == 5
    assert form.subject_column == "A" and form.group_column == "B" and form.value_columns[0] == "C" and len(form.value_columns) == 10
    assert form.last_data_row == 7 and any("Mean" in n and "not read" in n for n in notes)
    assert form.value_unit == "ng/mL" and form.time_unit == "h" and form.lloq == 1.0
    assert form.constants == {"study_id": "230-23-REF", "analyte": "desvenlafaxine", "matrix": "plasma", "dose": "50",
                              "dose_unit": "mg", "route": "oral", "food_state": "fasted"}
    assert form.below_lloq_tokens == ["BLQ"] and any("'NS'" in n for n in notes)
    # named subjects make it individual data, whatever the Mean / SD rows under them say
    assert triage_sheet(grid.sheets["Sheet1"]).category is SheetCategory.PK_INDIVIDUAL

    # the person marks NS as "no sample"; the recipe reads every subject, quoting the cells that state units and dose
    assert form.mean_row == 8 and form.mean_statistic == "arithmetic_mean" and any("mean profile" in n for n in notes)
    form = form.model_copy(update={"missing_tokens": ["NS"], "mean_n": 3})
    proposal = to_proposal(form, grid.sheets["Sheet1"])
    assert proposal["tables"][0]["time_row"] == 4 and _quotes_hold(grid, proposal)
    assert {e["supports"] for e in proposal["tables"][0]["evidence"]} >= {"value unit ng/mL", "time unit h", "LLOQ 1", "dose 50"}
    result = apply_recipe(grid, _recipe(proposal))
    assert result.issues == [] and validate_concentrations(result.concentrations) == []
    # the subjects, and the sheet's own Mean row as one more series (the profile the campaign judges)
    assert {r.series for r in result.concentrations} == {"001 / I", "002 / II", "003 / I", "Mean"}
    means = [r for r in result.concentrations if r.series == "Mean"]
    assert len(result.concentrations) == 29 + 8 and {r.statistic for r in means} == {"arithmetic_mean"} and means[0].n == 3

    # a unit the person changes drops the quote that supported the old one
    changed = to_proposal(form.model_copy(update={"value_unit": "µg/l"}), grid.sheets["Sheet1"])
    assert not any(e["supports"].startswith("value unit") for e in changed["tables"][0]["evidence"])


def _dissolution(wb):
    ws = wb.active
    ws.title = "pH 6.8"
    ws.append([("Dissolution of Desvenlafaxine ER Tablets 50 mg (Test), Batch No. B2301, USP II (paddle), 50 rpm, 900 mL "
                "phosphate buffer pH 6.8")])
    ws.append(["Time (hr)", *(f"Vessel {i}" for i in range(1, 13)), "Mean", "SD", "%CV"])
    for t, base in ((1, 18.0), (2, 30.0), (4, 48.0), (8, 72.0), (12, 88.0), (16, 96.0), (20, 99.0)):
        ws.append([t, *(base + d for d in (-1.5, -1, -0.5, 0, 0.5, 1, 1.5, -1, 1, 0, 0.5, -0.5)), base, 0.9, 1.0])


def test_a_dissolution_sheet_gets_its_conditions_and_the_brief_product_name():
    grid = _grid(_dissolution, "Dissolution Test.xlsx")
    form, _notes = suggest(grid.sheets["pH 6.8"], filename="Dissolution Test.xlsx",
                          products=[{"name": "Desvenlafaxine succinate ER Tablets", "role": "TEST"}])
    assert form.kind == "dissolution" and form.layout == "times_down" and form.time_column == "A"
    assert form.value_columns == [chr(ord("B") + i) for i in range(12)] and form.value_unit == "%" and form.time_unit == "h"
    assert form.constants == {"role": "TEST", "product": "Desvenlafaxine succinate ER Tablets", "ph": "6.8", "rpm": "50",
                              "volume_ml": "900", "batch": "B2301", "strength_mg": "50", "medium": "phosphate",
                              "apparatus": "USP II"}
    proposal = to_proposal(form, grid.sheets["pH 6.8"])
    assert _quotes_hold(grid, proposal)
    records = apply_recipe(grid, _recipe(proposal)).dissolution
    assert len(records) == 84 and validate_dissolution(records) == []
    assert {(r.product, r.role, r.ph, r.rpm, r.volume_ml) for r in records} == {
        ("Desvenlafaxine succinate ER Tablets", "TEST", 6.8, 50.0, 900.0)}
    assert {r.vessel for r in records} == {f"Vessel {i}" for i in range(1, 13)}


def _iv_summary(wb):
    ws = wb.active
    ws.title = "Fig 1"
    ws.append(["Time (h)", "Mean concentration (ng/mL)", "SD", "N"])
    for t, v in ((0.5, 120.0), (2, 310.0), (5, 420.0), (8, 250.0), (24, 60.0)):
        ws.append([t, v, v / 5, 14])


def test_published_mean_data_get_their_statistic_sd_and_n_and_the_route_from_the_file_name():
    grid = _grid(_iv_summary, "Nichols2012 IV 50 mg 5 h infusion.xlsx")
    form, notes = suggest(grid.sheets["Fig 1"], filename="Nichols2012 IV 50 mg 5 h infusion.xlsx", drug="desvenlafaxine")
    assert form.layout == "times_down" and (form.time_column, form.value_columns, form.sd_column, form.n_column) == ("A", ["B"], "C", "D")
    assert form.statistic == "arithmetic_mean" and form.value_unit == "ng/mL"
    assert form.constants["route"] == "iv_infusion" and form.constants["formulation"] == "solution"
    assert form.constants["study_id"] == "Nichols2012-IV" and form.constants["dose"] == "50"
    assert form.study == {"infusion_time_min": "300"}
    assert any("dose '50' is taken from the file name" in n for n in notes)
    result = apply_recipe(grid, _recipe(to_proposal(form, grid.sheets["Fig 1"])))
    assert result.issues == [] and [r.n for r in result.concentrations] == [14] * 5


def test_a_sheet_without_numbers_says_so_and_the_preview_is_the_sheet_as_text():
    def notes_only(wb):
        wb.active.title = "Notes"
        wb.active.append(["Shipped with the courier on 1 September"])

    grid = _grid(notes_only)
    form, notes = suggest(grid.sheets["Notes"])
    assert form == SheetForm(sheet="Notes") and "may not hold data" in notes[0]
    assert preview_rows(grid.sheets["Notes"]) == [["Shipped with the courier on 1 September"]]


def _cro_wide(wb, title="Sheet1"):
    """Times down, one column per subject, then the CRO's summary columns (Mean, SD, CV %, Geo Mean)."""
    ws = wb.active
    ws.title = title
    ws.append(["Time (hr)", *(f"{i:02d}" for i in range(1, 7)), "Mean", "SD", "CV%", "Geo Mean"])
    for t, base in ((0, None), (1, 30.0), (2, 70.0), (4, 90.0), (8, 55.0), (24, 12.0)):
        subjects = ["BLQ"] * 6 if base is None else [base + d for d in (-3, -2, -1, 1, 2, 3)]
        ws.append([t, *subjects, base, 2.0 if base else None, 4.0 if base else None, base])


@pytest.mark.parametrize(("filename", "study_id", "food", "route"), [
    ("230-23_Fasting_Reference.Data.Desvenlafaxine.xlsx", "230-23-REF", "fasted", "oral"),
    ("231-23_Fed_Test.Data.Desvenlafaxine.xlsx", "231-23-TEST", "fed", "oral"),
    ("093-26_Fasting_Reference-P.xlsx", "093-26-REF", "fasted", "oral"),
    ("Nichols2012_Oral_Desvenlafaxine_100 mg.Sheet1.Desvenlafaxine.xlsx", "Nichols2012", None, "oral"),
    ("Nichols2012_IV_Desvenlafaxine_50 mg_1h Infusion.Sheet1.Desvenlafaxine.xlsx", "Nichols2012-IV", None, "iv_infusion"),
])
def test_file_names_with_underscores_give_each_arm_and_route_its_own_study(filename, study_id, food, route):
    sheet = filename[:27]            # Excel keeps 31 characters of a sheet name; the CRO's export names it after the file
    grid = _grid(lambda wb: _cro_wide(wb, sheet), filename)
    form, notes = suggest(grid.sheets[sheet], filename=filename, drug="desvenlafaxine")
    assert form.constants["study_id"] == study_id and form.constants.get("food_state") == food
    assert form.constants["route"] == route
    if route == "iv_infusion":
        assert form.study == {"infusion_time_min": "60"} and form.constants["dose"] == "50"
    # the subjects are read, as individuals; the CRO's summary columns are left out and said so
    assert form.value_columns == ["B", "C", "D", "E", "F", "G"] and form.statistic == "individual"
    assert any("summarise the subjects" in n for n in notes)
    # the CRO's Mean column is the study's mean profile (with its SD), read next to the subjects
    assert (form.mean_column, form.mean_statistic, form.mean_sd_column) == ("H", "arithmetic_mean", "I")
    proposal = to_proposal(form.model_copy(update={"mean_n": 6, "lloq": 0.5}), grid.sheets[sheet])
    result = apply_recipe(grid, _recipe(proposal))
    assert {r.series for r in result.concentrations if r.statistic == "arithmetic_mean"} == {"Mean"}
