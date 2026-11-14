"""Delimited files (contracts §6.1, R-e): `;` with decimal commas in cp1252, tab in UTF-16 with a BOM, commas and
pipes; the encoding and the delimiter are recorded, the one sheet is named after the file stem and located as a sheet."""

from __future__ import annotations

import codecs

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import parse_locator, same_place
from modeler_intake.source import as_workbook_grid, parse_document, region_grid

pytestmark = pytest.mark.req("T-47")


def _located_exactly(file, doc) -> None:
    (table,) = file.tables
    truth = synthetic.truth_grid(file, table.id)
    (region,) = [r for r in doc.regions if r.kind == "table"]
    assert (region.where, region.id) == (table.where, truth.region_id)
    grid = region_grid(doc, region.id)
    assert {p: (c.text, c.type, c.value, c.locator) for p, c in grid.cells.items()} == \
        {p: (c.text, c.type, c.value, c.locator) for p, c in truth.cells.items()}
    assert [c.text for c in grid.caption] == list(table.caption)
    places = [*grid.cells.values(), *grid.caption]
    for value in file.values:
        for locator in (value.locator, *(at for _role, at in value.locators)):
            assert any(same_place(parse_locator(c.locator), parse_locator(locator)) for c in places), locator


@pytest.mark.parametrize(("sep", "decimal_comma", "encoding", "recorded"), [
    (";", True, "cp1252", "cp1252"),
    ("\t", False, "utf-16", "utf-16"),
    (",", True, "utf-8", "utf-8"),
    ("|", False, "utf-8", "utf-8"),
])
def test_a_delimited_file_is_read_with_its_encoding_and_delimiter(sep, decimal_comma, encoding, recorded):
    file = synthetic.delimited(sep=sep, decimal_comma=decimal_comma, encoding=encoding)
    doc = parse_document(file.data, file.name)
    assert doc.state == "read" and doc.parser == "delimited" and doc.format == ("tsv" if sep == "\t" else "csv")
    assert (doc.encoding, doc.delimiter) == (recorded, sep)
    assert [s.name for s in doc.sheets] == ["concentrations"]                    # the sheet is named after the file stem
    _located_exactly(file, doc)
    assert doc.role == "concentration_listing"
    grid = as_workbook_grid(doc)                                                  # today's grid from the same parse: 3 columns
    assert grid.sheet("concentrations").max_column == 3


def test_decimal_commas_are_kept_as_written_and_typed_as_numbers_written_as_text():
    file = synthetic.delimited(sep=";", decimal_comma=True, encoding="cp1252")
    doc = parse_document(file.data, file.name)
    (sheet,) = doc.sheets
    cell = next(c for c in sheet.cells if (c.row, c.column) == (4, 3))
    assert (cell.text, cell.value, cell.type) == ("12,5", "12,5", "number")     # a str typed number: read under the region's
    blq = next(c for c in sheet.cells if (c.row, c.column) == (3, 3))           # decimal convention by the mapping
    assert (blq.text, blq.type) == ("BLQ", "text")
    assert doc.warnings == ("ENCODING_GUESSED: not UTF-8; read as cp1252 (Windows Western European)",)
    header = next(c for c in sheet.cells if (c.row, c.column) == (2, 3))
    assert header.text == "Concentration (µg/L)"                                 # µ survives the cp1252 reading


def test_a_utf16_file_carries_its_byte_order_mark_and_no_warning():
    file = synthetic.delimited(sep="\t", decimal_comma=False, encoding="utf-16")
    assert file.data[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
    doc = parse_document(file.data, file.name)
    assert doc.encoding == "utf-16" and doc.warnings == ()


def test_a_utf8_byte_order_mark_is_named_and_not_read_as_text():
    file = synthetic.delimited(sep=",", decimal_comma=False, encoding="utf-8")
    doc = parse_document(codecs.BOM_UTF8 + file.data, file.name)
    assert doc.encoding == "utf-8-sig"
    assert next(c.text for c in doc.sheets[0].cells if (c.row, c.column) == (1, 1)).startswith("Study 230-28")


def test_binary_content_is_unreadable_with_its_reason():
    doc = parse_document(b"PK\x03\x04\x00\x00binary\x00", "listing.csv")
    assert doc.state == "unreadable" and "binary" in doc.reason and doc.encoding is None


def test_the_delimiter_is_the_one_with_the_most_consistent_columns():
    text = "Title line, with a comma\r\nSubject;Time;Conc\r\n1;0,5;1,2\r\n1;1;2,4\r\n2;0,5;1,1\r\n"
    doc = parse_document(text.encode("utf-8"), "odd name 'x'.csv")
    assert doc.delimiter == ";" and doc.sheets[0].name == "odd name 'x'"
    (region,) = [r for r in doc.regions if r.kind == "table"]
    assert region.where == "s:'odd name ''x'''!A2:C5" and region.caption == "Title line, with a comma"


@pytest.mark.parametrize(("name", "text", "first_data_row"), [
    ("kinetik.csv", "Zeit, h;Konzentration, ng/mL\n0,5;12,3\n1,0;15,1\n2,0;9,8\n4,0;5,5\n", 2),       # commas in the header
    ("headerless.csv", "0,5;12,3\n1,0;15,1\n2,0;9,8\n4,0;5,5\n", 1),                                # Sniffer alone says ","
    ("titled.csv", ("Study 230-28, Exampleamide, fasted\r\nSubject;Time (h);Conc (ng/mL)\r\n"
                    "301;0,5;12,3\r\n301;1,0;15,2\r\n301;2,0;9,8\r\n"), 3),                            # a title with commas
])
def test_a_semicolon_file_with_decimal_commas_is_never_cut_at_its_decimal_commas(name, text, first_data_row):
    doc = parse_document(text.encode("utf-8"), name)
    assert doc.delimiter == ";" and doc.state == "read" and doc.warnings == ()
    cells = {(c.row, c.column): (c.text, c.type) for c in doc.sheets[0].cells}
    width = max(c for _r, c in cells)
    assert cells[(first_data_row, width - 1)] == ("0,5", "number") and cells[(first_data_row, width)] == ("12,3", "number")
    assert not [t for t, _kind in cells.values() if ";" in t]                    # no cell holds a semicolon


def test_a_tab_file_with_decimal_commas_and_commas_in_its_header_is_read_with_tabs():
    doc = parse_document(b"Zeit, h\tKonz, ng/mL\n0,5\t12,3\n", "one row.tsv")
    assert doc.delimiter == "\t" and doc.warnings == ()
    assert [(c.text, c.type) for c in doc.sheets[0].cells if c.row == 2] == [("0,5", "number"), ("12,3", "number")]


def test_a_comma_file_with_semicolons_in_its_text_is_read_with_commas():
    doc = parse_document(b"Subject,Note,Conc\n1,fasted; morning,12.3\n2,fed; evening,15.2\n", "notes.csv")
    assert doc.delimiter == "," and doc.warnings == ()
    assert [c.text for c in doc.sheets[0].cells if c.row == 2] == ["1", "fasted; morning", "12.3"]


def test_a_tie_that_remains_is_never_read_with_commas_and_is_named():
    doc = parse_document(b"Arm A,fed;Arm B\n1,x;2\n", "tied.csv")
    assert doc.delimiter == ";" and doc.state == "read"
    assert doc.warnings == ("DELIMITER_AMBIGUOUS: ',' and ';' split the lines equally well; read with ';'",)
