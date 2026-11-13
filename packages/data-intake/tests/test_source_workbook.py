"""Workbooks parsed once and located (contracts §6.1, §8.4): every table of the messy workbook is its own region with
the truth's range, each cell keeps its stored value, text and number format, the context lines are the truth's, and
the legacy grid comes from the same parse."""

from __future__ import annotations

import io
from datetime import time, timedelta
from pathlib import Path

import pytest
from openpyxl import Workbook

from modeler_intake import synthetic
from modeler_intake.anchors import anchor_text, parse_locator, same_place
from modeler_intake.grid import read_workbook_bytes
from modeler_intake.source import as_workbook_grid, parse_document, region_grid, resolve
from modeler_intake.source.regions import a1_place, parse_sheet_range
from modeler_intake.source_model import has_number, is_numeric_text

pytestmark = pytest.mark.req("T-47")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def messy():
    file = synthetic.messy_workbook()
    return file, parse_document(file.data, file.name)


@pytest.fixture(scope="module")
def template():
    file = synthetic.template_workbook()
    return file, parse_document(file.data, file.name)


def _region(doc, where):
    (found,) = [r for r in doc.regions if r.where == where]
    return found


def _workbook(build) -> bytes:
    wb = Workbook()
    build(wb.active)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def assert_located_exactly(file, doc) -> None:
    """Every truth table is a region of `doc` with the truth's range and id, its grid equals the truth's grid (cells,
    merges, context lines), and every locator of every truth value (its cell and every cell it is read with) is a cell
    of that region or of its context."""
    for table in file.tables:
        truth = synthetic.truth_grid(file, table.id)
        region = _region(doc, table.where)
        assert region.id == truth.region_id and region.kind == "table", table.id
        grid = region_grid(doc, region.id)
        assert (grid.n_rows, grid.n_cols) == (truth.n_rows, truth.n_cols) == (region.n_rows, region.n_cols), table.id
        assert set(grid.cells) == set(truth.cells), table.id
        for place, cell in truth.cells.items():
            mine = grid.cells[place]
            assert (mine.text, mine.type, mine.value, mine.number_format) == (cell.text, cell.type, cell.value,
                                                                              cell.number_format), (table.id, place)
            assert mine.locator == cell.locator and mine.merged_from == cell.merged_from, (table.id, place)
        assert [c.text for c in grid.caption] == list(table.caption), table.id
        assert [" | ".join(c.text for c in line) for line in grid.above] == list(table.above), table.id
        assert [" | ".join(c.text for c in line) for line in grid.below] == list(table.below), table.id
        places = [*grid.cells.values(), *grid.caption, *(c for line in (*grid.above, *grid.below) for c in line)]
        for value in (v for v in file.values if v.table == table.id):
            for role, locator in (("value", value.locator), *value.locators):
                assert any(same_place(parse_locator(c.locator), parse_locator(locator)) for c in places), \
                    (table.id, value.field, role, locator)


def test_every_table_of_the_messy_workbook_is_its_own_region_with_the_truths_range(messy):
    file, doc = messy
    assert doc.state == "read" and doc.parser == "workbook" and doc.parser_version.startswith("1.0+openpyxl")
    tables = [r for r in doc.regions if r.kind == "table"]
    assert sorted(r.where for r in tables) == sorted(t.where for t in file.tables)
    assert len([r for r in tables if r.where.startswith("s:'Fasting'!")]) == 2                       # two tables on one sheet
    assert {r.where for r in tables if r.where.startswith("s:'Dissolution'!")} == {"s:'Dissolution'!A3:G9",
                                                                                     "s:'Dissolution'!I3:L9"}  # side by side
    individual = _region(doc, "s:'Fasting'!A2:G14")
    assert individual.notes == ("rows 11-14 joined across empty row 10",)       # the Mean / SD / N group, joined and noted
    assert individual.caption == "Study 230-23, 50 mg, fasted" and individual.caption_locator == "s:'Fasting'!A1"
    metabolite = _region(doc, "s:'Fasting'!A21:D27")                              # a second table after a caption: not joined
    assert metabolite.caption.startswith("Table 2. Study 230-23") and metabolite.caption_locator == "s:'Fasting'!A20"
    assert metabolite.notes == ()
    two_lines = _region(doc, "s:'Dissolution'!A3:G9")
    assert two_lines.caption.split("\n") == list(file.tables[3].caption)
    assert_located_exactly(file, doc)


def test_the_template_and_the_legacy_workbook_are_located_too(template):
    file, doc = template
    assert_located_exactly(file, doc)
    legacy = (FIXTURES / "legacy-study.xls").read_bytes()
    xls = parse_document(legacy, "legacy-study.xls")
    assert xls.state == "read" and xls.parser_version.startswith("1.0+xlrd")
    pk = _region(xls, "s:'PK'!A2:C6")
    assert pk.caption == "Study EX-101 plasma concentrations" and pk.caption_locator == "s:'PK'!A1"   # a merged title, once


def test_a_merged_two_row_header_keeps_its_origin_and_its_copies_are_not_counted(messy):
    file, doc = messy
    region = _region(doc, "s:'Fasting'!A2:G14")
    grid = region_grid(doc, region.id)
    assert grid.cell(1, 1).text == "Subject" and grid.cell(1, 1).merged_from is None
    assert grid.cell(2, 1).text == "Subject" and grid.cell(2, 1).merged_from == "s:'Fasting'!A2"
    assert all(grid.cell(1, c).merged_from == "s:'Fasting'!B2" for c in range(3, 8))
    (table,) = [t for t in file.tables if t.id == "fasting-individual"]
    assert region.numeric_cells == sum(1 for row in table.rows for text in row if has_number(text))

    def merged_number(ws) -> None:                       # a merged header that holds a number: counted once, at its origin
        ws["A1"] = "Time (h)"
        ws["B1"] = "Day 1"
        ws.merge_cells("B1:D1")
        for r, row in enumerate(((0.5, 1.1, 1.2, 1.3), (1, 2.1, 2.2, 2.3)), start=2):
            for c, value in enumerate(row, start=1):
                ws.cell(r, c, value)

    small = parse_document(_workbook(merged_number), "merged.xlsx")
    (only,) = small.regions
    assert only.numeric_cells == 1 + 8
    copies = [c for s in small.sheets for c in s.cells if c.merged_from]
    assert [(c.text, c.merged_from) for c in copies] == [("Day 1", "B1"), ("Day 1", "B1")]


def test_every_truth_values_cell_has_the_truths_text(messy):
    file, doc = messy
    for value in (v for v in file.values if v.table):
        (table,) = [t for t in file.tables if t.id == value.table]
        found = resolve(doc, anchor_text(doc.file_sha256, doc.parser, doc.parser_version, value.locator))
        assert value.value in found.text, (value.table, value.field, value.locator)
        _sheet, r0, c0, r1, c1 = parse_sheet_range(table.where)
        row, column = a1_place(parse_locator(value.locator).cell)
        if r0 <= row <= r1 and c0 <= column <= c1:
            assert found.text == table.rows[row - r0][column - c0]
    mean = next(c for s in doc.sheets if s.name == "Fasting" for c in s.cells if (c.row, c.column) == (11, 3))
    assert (mean.value, mean.text, mean.type, mean.number_format) == (12.4037, "12.4037", "number", "0.00")


def test_numeric_cells_counts_cells_that_hold_a_number_without_being_one(messy):
    _file, doc = messy
    summary = _region(doc, "s:'Summary'!A2:C5")
    grid = region_grid(doc, summary.id)
    written = [grid.cell(r, 3).text for r in range(2, 5)]
    assert written == ["31.2 (4.1)", "152.4 (20.3)", "3.1 (0.6)"]
    assert not any(is_numeric_text(t) for t in written) and summary.numeric_cells == 3
    individual = region_grid(doc, _region(doc, "s:'Fasting'!A2:G14").id)
    marked = individual.cell(5, 4)
    assert marked.text == "12.3*" and marked.type == "text" and has_number(marked.text)


def test_the_context_lines_are_the_truths_and_hold_no_other_regions_cell(messy, template):
    for file, doc in (messy, template):
        tables = [r for r in doc.regions if r.kind == "table"]
        for region in tables:
            grid = region_grid(doc, region.id)
            for line in (*grid.above, *grid.below):
                for cell in line:
                    place = parse_locator(cell.locator)
                    holders = [r.id for r in tables if _in(r.where, place)]
                    assert holders == [], (region.where, cell.locator)
                    item = next(o for o in doc.outside if o.where == cell.locator)
                    assert item.region == region.id
        assert_located_exactly(file, doc)
    _file, doc = messy
    assert [(o.where, o.region) for o in doc.outside if o.region] == [
        ("s:'Fasting'!A16", _region(doc, "s:'Fasting'!A2:G14").id),
        ("s:'Fasting'!A29", _region(doc, "s:'Fasting'!A21:D27").id),
        ("s:'Fed'!A16", _region(doc, "s:'Fed'!A2:G14").id)]


def _in(where: str, place) -> bool:
    sheet, r0, c0, r1, c1 = parse_sheet_range(where)
    row, column = a1_place(place.cell)
    return sheet == place.sheet and r0 <= row <= r1 and c0 <= column <= c1


def test_numbers_outside_every_region_and_context_are_the_truths(messy, template):
    for file, doc in (messy, template):
        free = tuple(sorted(o.where for o in doc.outside if o.numeric and not o.furniture and o.region is None))
        assert free == tuple(sorted(file.outside)), file.name
    _file, doc = messy
    assert not any(o.where.startswith("s:'Fasting'!B") for o in doc.outside)       # no merged copy is ever listed


def _same_grid(mine, legacy) -> None:
    assert list(mine.sheets) == list(legacy.sheets)
    for name, sheet in legacy.sheets.items():
        ours = mine.sheets[name]
        assert (ours.max_row, ours.max_column) == (sheet.max_row, sheet.max_column), name
        assert set(ours.cells) == set(sheet.cells), name
        for place, cell in sheet.cells.items():
            assert ours.cells[place].value == cell.value and type(ours.cells[place].value) is type(cell.value), (name, place)
            assert ours.cells[place].merged_from == cell.merged_from, (name, place)


def test_values_and_merge_copies_equal_the_legacy_grid_for_the_same_bytes(messy, template):
    for file, doc in (messy, template):
        _same_grid(as_workbook_grid(doc), read_workbook_bytes(file.data, file.name))
    legacy = (FIXTURES / "legacy-study.xls").read_bytes()
    doc = parse_document(legacy, "legacy-study.xls")
    grid = as_workbook_grid(doc)
    _same_grid(grid, read_workbook_bytes(legacy, "legacy-study.xls"))
    assert grid.sheet("PK").cell(1, 3).merged_from == "PK!A1"
    dated = next(c for s in doc.sheets if s.name == "Info" for c in s.cells if c.type == "date")
    assert dated.text == "2024-03-05T00:00:00" and dated.number_format == "YYYY-MM-DD"     # a date as ISO 8601, its format kept
    with pytest.raises(ValueError):
        as_workbook_grid(parse_document(synthetic.word_report().data, "design-report.docx"))


def test_a_percent_format_is_kept_and_the_stored_number_is_read(messy):
    _file, doc = messy
    urine = next(s for s in doc.sheets if s.name == "Urine")
    fractions = [c for c in urine.cells if c.column == 4 and c.row >= 3]
    assert [(c.value, c.text, c.number_format) for c in fractions] == [
        (0.042, "0.042", "0.0%"), (0.032, "0.032", "0.0%"), (0.018, "0.018", "0.0%"), (0.014, "0.014", "0.0%")]
    grid = region_grid(doc, _region(doc, "s:'Urine'!A2:D6").id)
    assert grid.cell(2, 4).number_format == "0.0%" and grid.cell(2, 4).value == 0.042


def test_a_hidden_sheet_is_flagged_and_read(messy):
    _file, doc = messy
    notes = next(s for s in doc.sheets if s.name == "Notes")
    assert notes.hidden and not any(s.hidden for s in doc.sheets if s.name != "Notes")
    assert any(w.startswith("HIDDEN_SHEET s:'Notes'") for w in doc.warnings)
    assert [(o.where, o.numeric) for o in doc.outside if o.where.startswith("s:'Notes'")] == [("s:'Notes'!A1", False)]


def test_a_formula_with_no_cached_value_is_a_finding():
    def formula(ws) -> None:
        ws["A1"], ws["B1"] = "Time", "Conc"
        ws["A2"], ws["B2"] = 1, 2.5
        ws["A3"], ws["B3"] = 2, "=B2*2"

    doc = parse_document(_workbook(formula), "computed.xlsx")
    assert doc.state == "partly_read"                                    # a value not read is named in the state (G2)
    assert doc.reason == ("formula with no cached value, nothing to read (the workbook was not recalculated and saved "
                          "in Excel): s:'Sheet'!B3")
    assert [w for w in doc.warnings if w.startswith("FORMULA_NO_VALUE")] == [
        "FORMULA_NO_VALUE s:'Sheet'!B3: a formula with no cached value; nothing to read"]
    (table,) = [r for r in doc.regions if r.kind == "table"]
    assert region_grid(doc, table.id).cell(3, 2).type == "empty"         # nothing stands where the value would


def _xls_with_error() -> bytes:
    """fixtures/legacy-study.xls with its first RK (number) record, 'Info'!B1, made a BOOLERR record holding #DIV/0!
    (same length: xlrd reads a BOOLERR's first 8 bytes)."""
    import struct

    data = (FIXTURES / "legacy-study.xls").read_bytes()
    k = data.find(b"\x7e\x02\x0a\x00")
    row, column, xf = struct.unpack("<HHH", data[k + 4:k + 10])
    assert (row, column) == (0, 1)
    return data[:k] + b"\x05\x02\x0a\x00" + struct.pack("<HHHBBH", row, column, xf, 0x07, 1, 0) + data[k + 14:]


def test_a_cell_holding_an_error_is_its_text_in_both_formats_and_named():
    def error(ws) -> None:
        ws.title = "Info"
        ws["A1"], ws["B1"] = "Ratio", "#DIV/0!"                           # openpyxl stores it as an error cell

    for data, name in ((_xls_with_error(), "legacy.xls"), (_workbook(error), "errors.xlsx")):
        doc = parse_document(data, name)
        cell = next(c for s in doc.sheets if s.name == "Info" for c in s.cells if (c.row, c.column) == (1, 2))
        assert (cell.value, cell.text, cell.type, doc.state) == ("#DIV/0!", "#DIV/0!", "text", "read"), name
        assert "CELL_ERROR s:'Info'!B1: the cell holds the error #DIV/0!" in doc.warnings, name
        assert as_workbook_grid(doc).sheet("Info").cell(1, 2).value == "#DIV/0!", name


def test_a_corrupt_workbook_is_unreadable_with_its_reason_not_an_exception():
    for data, name in ((b"PK\x03\x04 not really a workbook", "broken.xlsx"), (b"garbage", "broken.xls"),
                       (synthetic.messy_workbook().data[:300], "cut.xlsx")):
        doc = parse_document(data, name)
        assert doc.state == "unreadable" and doc.reason and doc.sheets == () and doc.regions == (), name


def test_a_blank_row_joins_only_a_group_that_continues_the_table():
    def sheet(ws) -> None:
        rows = [("Time (h)", "A", "B"), (0.5, 1.0, 2.0), (1, 1.5, 2.5), (), ("Mean", 1.25, 2.25), (), (), ("Time (h)", "C", "D"),
                (0.5, 3.0, 4.0), (), ("Note", "", ""), (1, 3.5, 4.5)]
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row, start=1):
                if value != "":
                    ws.cell(r, c, value)

    doc = parse_document(_workbook(sheet), "groups.xlsx")
    tables = [r for r in doc.regions if r.kind == "table"]
    assert [(r.where, r.notes) for r in tables] == [
        ("s:'Sheet'!A1:C5", ("rows 5-5 joined across empty row 4",)),     # a Mean row after one blank row: joined
        ("s:'Sheet'!A8:C9", ())]                                          # two blank rows: a new table
    assert [o.where for o in doc.outside] == ["s:'Sheet'!A11", "s:'Sheet'!A12", "s:'Sheet'!B12", "s:'Sheet'!C12"]


def test_a_duration_is_typed_date_in_iso_8601_and_the_legacy_grid_gets_it_back():
    def durations(ws) -> None:
        ws["A1"], ws["B1"], ws["C1"] = "Subject", "Actual time", "Conc (ng/mL)"
        ws["A2"], ws["B2"], ws["C2"] = "001", timedelta(hours=26), 1.5
        ws["A3"], ws["B3"], ws["C3"] = "001", timedelta(minutes=30), 2.5
        ws["A4"], ws["B4"], ws["C4"] = "002", time(12, 30), 3.5

    data = _workbook(durations)
    doc = parse_document(data, "times.xlsx")
    (sheet,) = doc.sheets
    found = {c.row: (c.value, c.text, c.type) for c in sheet.cells if c.column == 2 and c.row > 1}
    assert found == {2: ("P1DT2H", "P1DT2H", "date"), 3: ("PT30M", "PT30M", "date"), 4: ("12:30:00", "12:30:00", "date")}
    assert next(c.number_format for c in sheet.cells if (c.row, c.column) == (2, 2)) == "[hh]:mm:ss"
    _same_grid(as_workbook_grid(doc), read_workbook_bytes(data, "times.xlsx"))       # a timedelta again, a time again


def _put_rows(ws, top: int, left: int, rows) -> None:
    for r, row in enumerate(rows, start=top):
        for c, value in enumerate(row, start=left):
            ws.cell(r, c, value)


_PROFILE = (("Time (min)", "Mean", "SD"), (5, 12.4, 2.1), (15, 44.9, 3.9), (30, 86.5, 3.1))


def test_a_title_merged_across_tables_side_by_side_leaves_them_two_regions_each_with_the_title():
    def sheet(ws) -> None:
        ws.title = "Dissolution"
        ws["A1"] = "Exampleamide IR tablet, batch L2301: % dissolved"
        ws.merge_cells("A1:G1")
        ws["A2"], ws["E2"] = "pH 1.2", "pH 6.8"
        _put_rows(ws, 3, 1, _PROFILE)
        _put_rows(ws, 3, 5, _PROFILE)                                  # column D empty between them

    doc = parse_document(_workbook(sheet), "dissolution.xlsx")
    left, right = [r for r in doc.regions if r.kind == "table"]
    assert (left.where, right.where) == ("s:'Dissolution'!A3:C6", "s:'Dissolution'!E3:G6")
    assert (left.numeric_cells, right.numeric_cells) == (9, 9)
    title = "Exampleamide IR tablet, batch L2301: % dissolved"
    assert (left.caption, right.caption) == (f"{title}\npH 1.2", f"{title}\npH 6.8")
    assert (left.caption_locator, right.caption_locator) == ("s:'Dissolution'!A1", "s:'Dissolution'!E1")
    caption = region_grid(doc, right.id).caption                      # the title over the right table: its copy there
    assert [(c.locator, c.merged_from, c.text) for c in caption] == [
        ("s:'Dissolution'!E1", "s:'Dissolution'!A1", title), ("s:'Dissolution'!E2", None, "pH 6.8")]
    for region in (left, right):
        anchor = anchor_text(doc.file_sha256, doc.parser, doc.parser_version, region.caption_locator)
        assert resolve(doc, anchor).region_id == region.id
    assert doc.outside == ()


def test_a_title_merged_wider_than_its_table_does_not_widen_it_over_a_note_beside_it():
    def sheet(ws) -> None:
        ws["A1"] = "Exampleamide: % dissolved"
        ws.merge_cells("A1:H1")
        _put_rows(ws, 2, 1, _PROFILE[:3])
        ws["F3"] = "Note: values from 2 runs"

    doc = parse_document(_workbook(sheet), "wide title.xlsx")
    (table,) = [r for r in doc.regions if r.kind == "table"]
    assert (table.where, table.n_cols, table.caption) == ("s:'Sheet'!A2:C4", 3, "Exampleamide: % dissolved")
    assert [(o.where, o.numeric, o.region) for o in doc.outside] == [("s:'Sheet'!F3", True, None)]   # listed and counted


def test_a_title_over_the_empty_column_between_tables_side_by_side_joins_neither():
    def sheet(ws) -> None:
        ws["D1"] = "Exampleamide dissolution, batch L2301"
        _put_rows(ws, 2, 1, _PROFILE)
        _put_rows(ws, 2, 5, _PROFILE)

    doc = parse_document(_workbook(sheet), "centred title.xlsx")
    assert [r.where for r in doc.regions if r.kind == "table"] == ["s:'Sheet'!A2:C5", "s:'Sheet'!E2:G5"]
    assert [(o.where, o.region) for o in doc.outside] == [("s:'Sheet'!D1", None)]


def test_a_merged_header_over_a_spacer_column_keeps_its_table_whole():
    def sheet(ws) -> None:
        ws["A1"] = "Table 1. Exampleamide concentrations"
        ws["A2"], ws["B2"] = "Subject", "Concentration (ng/mL)"
        ws.merge_cells("B2:D2")
        ws["B3"], ws["D3"] = "Day 1", "Day 8"
        _put_rows(ws, 4, 1, ((101, 12.5, None, 14.1), (102, 11.9, None, 13.0)))

    doc = parse_document(_workbook(sheet), "spacer.xlsx")
    (table,) = [r for r in doc.regions if r.kind == "table"]
    assert (table.where, table.caption, table.numeric_cells) == ("s:'Sheet'!A2:D5", "Table 1. Exampleamide concentrations", 8)
