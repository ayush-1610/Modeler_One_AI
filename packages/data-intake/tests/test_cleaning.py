"""The record of what a reading left out of a sheet and what it changed (plan 2026-11-05 §3.1 step 4: "cleaned, with a
record ... nothing silently"). A messy sheet as CROs send them (software test data, made-up numbers)."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from modeler_intake.cleaning import record
from modeler_intake.grid import read_workbook_bytes
from modeler_intake.recipe_review import RecipeProposal, review_proposal
from modeler_intake.sheet_form import SheetForm, to_proposal

pytestmark = pytest.mark.req("T-47")


def _messy() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Mean"
    for row in (["Mean plasma concentrations, Study X-01"],
                ["Time (h)", "Mean (ng/mL)", "SD", "Comments"],
                ["0", "NS", None, "pre-dose not sampled"],
                ["0,5", "12,4", "1,2", None],
                ["1", "20,1", "2,0", None],
                [None],
                ["2", "15,3", "1,8", "haemolysed"],
                ["4", "n.c.", None, None],
                ["8", "BLQ", None, None],
                [None],
                ["Values are the mean of 12 subjects"]):
        ws.append(row)
    raw = io.BytesIO()
    wb.save(raw)
    return raw.getvalue()


def test_what_a_reading_leaves_out_and_changes_is_named_cell_by_cell():
    workbook = read_workbook_bytes(_messy(), "X-01 mean.xlsx")
    form = SheetForm(sheet="Mean", header_row=2, first_data_row=3, last_data_row=9, time_column="A", value_columns=["B"],
                     sd_column="C", statistic="arithmetic_mean", decimal_comma=True, missing_tokens=["NS"],
                     below_lloq_tokens=["BLQ"], lloq=0.5, constants={"study_id": "X-01"})
    checked = review_proposal(workbook, RecipeProposal.model_validate(to_proposal(form, workbook.sheets["Mean"])), recipe_id="r")
    read = {o.source.cells["value"] for o in checked.concentrations}
    below = {o.source.cells["value"] for o in checked.concentrations if o.below_lloq}
    lines = {line.kind + ":" + line.text: line.cells for line in record(workbook.sheets["Mean"], form, read, below)}
    texts = list(lines)
    assert any(t.startswith("ignored:Above the table (row 1): “Mean plasma concentrations") for t in texts)
    assert any(t.startswith("ignored:Below the table (row 11): “Values are the mean of 12 subjects”") for t in texts)
    assert "ignored:1 empty row inside the table skipped (row 6)." in lines
    assert lines["not_read:Column D (“Comments”) not read: 2 cells beside the values."] == ("Mean!D3", "Mean!D7")
    assert lines["no_sample:1 cell marked “NS”: no sample."] == ("Mean!B3",)
    assert lines["ignored:1 value cell not read, not numbers: “n.c.”."] == ("Mean!B8",)
    assert lines["below_lloq:1 cell below the LLOQ (“BLQ”): kept as below the LLOQ, not as zero."] == ("Mean!B9",)
    assert lines["corrected:3 numbers written with a decimal comma (12,4) read as 12.4."] == ("Mean!B4", "Mean!B5", "Mean!B7")


def test_a_reading_with_no_value_columns_says_it_read_nothing():
    workbook = read_workbook_bytes(_messy(), "X-01 mean.xlsx")
    [line] = record(workbook.sheets["Mean"], SheetForm(sheet="Mean"), set())
    assert line.kind == "not_read" and "could not tell which columns" in line.text
