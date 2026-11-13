"""D3: what the table mapper is shown of a table (contracts §4.4, §6.2, §8.5). No digit of a body cell reaches the
payload, on the band `header_band` actually chooses, nor through a REJECTED answer that quotes a body cell; header words
and context lines are verbatim. Software test data (the made-up Exampleamide)."""

from __future__ import annotations

import re

import pytest

from modeler_intake import synthetic
from modeler_intake.mapping.fingerprint import header_band
from modeler_intake.mapping.reading import value_like
from modeler_intake.mapping.redact import redact, redact_cell, redact_findings
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import Cite, Constant
from modeler_intake.source_model import Finding, Region, RegionGrid, has_number

pytestmark = pytest.mark.req("T-47")

FILES = (synthetic.messy_workbook(), synthetic.pdf_report(), synthetic.word_report(), synthetic.delimited(),
         synthetic.template_workbook())
TABLES = [(f, t) for f in FILES for t in f.tables]


def _redacted(file: synthetic.SyntheticFile, table: synthetic.TruthTable):
    grid = synthetic.truth_grid(file, table.id)
    region = Region(id=grid.region_id, kind="table", where=table.where, table_kind=table.kind)
    return grid, redact(grid, region, file_name=file.name, document_role="data_workbook")


@pytest.mark.parametrize(("text", "redacted"), [
    ("12.5", "#.#"), ("12,5", "#,#"), ("1.234,5", "#.#,#"), ("<0.5", "<#.#"), ("S01", "S#"), ("2 h", "# h"), ("BLQ", "BLQ"),
    ("１２.5", "#.#"), ("x" * 50, "x" * 40),
])
def test_redact_cell(text, redacted):
    assert redact_cell(text) == redacted


@pytest.mark.parametrize(("file", "table"), TABLES, ids=[f"{f.name}:{t.id}" for f, t in TABLES])
def test_no_digit_of_a_body_cell_is_in_the_payload(file, table):
    grid, shown = _redacted(file, table)
    band = header_band(grid)
    assert shown.header_rows == band
    for row in shown.body:
        assert not any(re.search(r"\d", text) for text in row)
    for column in shown.profile:
        assert not any(re.search(r"\d", text) for text in column.distinct_texts)
    for r, row in enumerate(shown.header, start=1):
        for c, text in enumerate(row, start=1):
            written = grid.cell(r, c).text
            assert text == (redact_cell(written) if value_like(written) else written)   # header words verbatim
    payload = shown.model_copy(update={"context": ()}).model_dump_json()
    for (row, _c), cell in grid.cells.items():
        if row > band and has_number(cell.text) and re.search(r"[.,]\d|\d{3}", cell.text):
            assert cell.text not in payload, cell.text


def test_the_context_lines_are_verbatim_and_the_text_heavy_product_table_sends_one_header_row():
    messy = FILES[0]
    _grid, fasting = _redacted(messy, next(t for t in messy.tables if t.id == "fasting-individual"))
    assert [(c.near, c.line, c.text) for c in fasting.context] == [("caption", 1, "Study 230-23, 50 mg, fasted"),
                                                                  ("below", 1, "LLOQ = 0.5 ng/mL")]
    assert fasting.header == (("Subject", *["Exampleamide plasma concentration (ng/mL) by time after dose (h)"] * 6),)
    assert fasting.body_rows == (2, 3, 4, 5, 6, 10, 11, 12, 13)[:5] + (11, 12, 13)
    assert fasting.body[0] == ("Subject", "#", "#.#", "#", "#", "#", "#")                  # the time row, redacted
    _grid, product = _redacted(messy, next(t for t in messy.tables if t.id == "product-batches"))
    assert product.header_rows == 1 and product.body[0][4] == "L#"
    assert product.body[0][0] == "Exampleamide IR tablet"


def test_distinct_texts_show_blq_and_ns():
    messy = FILES[0]
    _grid, fasting = _redacted(messy, next(t for t in messy.tables if t.id == "fasting-individual"))
    by_column = {p.column: p for p in fasting.profile}
    assert by_column[2].distinct_texts == ("BLQ",)                     # "<0.5" is a bare number: counted, never shown
    assert (by_column[2].numbers, by_column[2].texts, by_column[2].empty) == (3, 6, 3)
    assert "NS" in by_column[3].distinct_texts and "#.#*" in by_column[4].distinct_texts
    assert by_column[1].distinct_texts == ("Subject", "Mean", "SD", "N", "CV%")         # the ids 001-006 are numbers


def test_a_rejected_answer_that_quotes_a_body_cell_carries_none_of_its_digits():
    messy = FILES[0]
    table = next(t for t in messy.tables if t.id == "fasting-individual")
    grid = synthetic.truth_grid(messy, table.id)
    wrong = table.spec.model_copy(update={"constants": (Constant(field="dose", cite=Cite(row=3, column=4)),
                                                        Constant(field="study_id", cite=Cite(row=4, column=1),
                                                                 pattern=r"Study (\S+)"))})
    findings = validate_spec(wrong, grid)
    assert any("30.4" in f.message for f in findings) and any("002" in f.message for f in findings)
    answer = redact_findings(findings)
    assert answer.startswith("REJECTED: ") and "30.4" not in answer and "002" not in answer and "'#.#'" in answer


def test_a_message_is_redacted_but_still_says_what_to_fix():
    answer = redact_findings([Finding(code="UNIT_NOT_STATED", location="value_unit",
                                      message="the cited text does not write the unit 'µg/mL': 'Concentration (ng/mL) at 12.5 h, "
                                              "a long header that goes on well past forty characters'")])
    assert "UNIT_NOT_STATED at value_unit" in answer and "#.# h" in answer and "forty characters" in answer


@pytest.mark.parametrize(("rows", "band"), [
    ([["Statistic", "N", "Cmax (ng/mL)", "AUC"], ["Mean (SD)", 24, "12.3 (4.5)", "120 (30)"],
      ["Geo mean (CV%)", 24, "11.8 (35)", "115 (28)"], ["Median", 24, 11.0, 118]], 1),
    ([["Cmax (ng/mL)", "123.4 (12.1)", "98.7 (10.2)"], ["AUC0-inf (ng·h/mL)", "1520 (210)", "1302 (190)"],
      ["Tmax (h)", "1.5 (0.5-3.0)", "2.0 (1.0-4.0)"]], 0),
    ([["Parameter", "Test"], ["Cmax", "12.3*"], ["Note", "values with * were re-assayed"], ["AUC", "120 ng·h/mL"]], 1),
])
def test_no_digit_of_a_value_written_with_its_spread_or_mark_reaches_the_mapper(rows, band):
    """Values written with their spread, interval, mark or unit are no header: the band ends above them (a headerless
    key-value table has none), and a band cell that writes a value is redacted."""
    grid = RegionGrid.from_rows(rows)
    shown = redact(grid, Region(id=grid.region_id, kind="table", where="s:'T'!A1:D4", table_kind="pk_summary"),
                   file_name="summary.docx", document_role="study_report")
    assert shown.header_rows == header_band(grid) == band
    for r, row in enumerate(shown.header, start=1):
        for c, text in enumerate(row, start=1):
            assert text == (redact_cell(grid.cell(r, c).text) if value_like(grid.cell(r, c).text) else grid.cell(r, c).text)
    assert not any(re.search(r"\d", text) for row in shown.body for text in row)
    payload = shown.model_copy(update={"context": ()}).model_dump_json()
    for cell in grid.cells.values():
        if value_like(cell.text) and re.search(r"[.,(]", cell.text):
            assert cell.text not in payload and not re.search(re.escape(cell.text.split(" ")[0]), payload), cell.text
