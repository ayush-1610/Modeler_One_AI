"""SAS datasets, PowerPoint decks and Apple Numbers documents (plan 2026-11-26 §7 phase 2): each read into the
structures every later step already reads (sheets, or a body as a Word file's), and a damaged one is `unreadable` with
its reason, never an exception. The fixtures are made up (the Exampleamide values of the synthetic delivery)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from modeler_intake.room import document_parts, read_file
from modeler_intake.source import parse_document
from modeler_intake.source.parse import SEND_AS

pytestmark = pytest.mark.req("T-47")
FIXTURES = Path(__file__).parent / "fixtures"


def _lines(doc) -> list[list[str]]:
    return [[c.text for c in ln.cells] for part in document_parts(doc) for ln in part.lines]


def test_a_sas_transport_file_is_one_sheet_of_names_labels_and_observations():
    data = (FIXTURES / "sas" / "pc_synthetic.xpt").read_bytes()
    doc = parse_document(data, "pc.xpt")
    assert (doc.state, doc.format, doc.parser) == ("read", "sas", "sas")
    assert doc.parser_version.split("+")[1].startswith("pyreadstat")
    assert [s.name for s in doc.sheets] == ["PC"]
    lines = _lines(doc)
    assert lines[0][:3] == ["STUDYID", "USUBJID", "PCTESTCD"]                     # the variables' names
    assert lines[1][1] == "Unique Subject Identifier"                            # their labels
    assert lines[2][:6] == ["EX-01", "EX-01-001", "EXAMPL", "PLASMA", "0", ""]    # a missing number stays empty
    assert lines[3][5] == "3.28" and lines[3][7] == "3.28" and lines[2][7] == "BLQ"
    assert any(w.startswith("SAS_LABELS") for w in doc.warnings)


def test_the_room_reads_a_sas_dataset_as_a_dataset():
    room_file = read_file("Clinical/pc.xpt", (FIXTURES / "sas" / "pc_synthetic.xpt").read_bytes())
    assert (room_file.kind, room_file.state) == ("dataset", "read")


def _deck() -> bytes:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Dissolution, pH 6.8"
    rows = [["Time (min)", "Refamide", "Exampleamide"], ["15", "62", "58"], ["30", "88", "85"]]
    table = slide.shapes.add_table(3, 3, Inches(0.5), Inches(1.5), Inches(6), Inches(1.5)).table
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            table.cell(r, c).text = text
    second = deck.slides.add_slide(deck.slide_layouts[5])
    second.shapes.title.text = "BE result"
    chart = CategoryChartData()
    chart.categories = ["Cmax", "AUC0-t"]
    chart.add_series("Test/Reference (%)", (93.0, 97.7))
    second.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1.5), Inches(6), Inches(4), chart)
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def test_a_deck_is_read_as_a_body_with_its_tables_and_its_charts_data():
    doc = parse_document(_deck(), "results.pptx")
    assert (doc.state, doc.format, doc.parser) == ("read", "pptx", "pptx")
    lines = _lines(doc)
    texts = [" | ".join(ln) for ln in lines]
    assert "Slide 1" in texts and "Dissolution, pH 6.8" in texts and "Slide 2" in texts
    assert ["Time (min)", "Refamide", "Exampleamide"] in lines and ["30", "88", "85"] in lines
    assert ["", "Cmax", "AUC0-t"] in lines and ["Test/Reference (%)", "93", "97.7"] in lines   # the chart as numbers
    assert sum(1 for r in doc.regions if r.kind == "table") == 2
    assert read_file("results.pptx", _deck()).kind == "slides"


def test_a_picture_on_a_slide_makes_the_deck_partly_read_naming_the_slide():
    from pptx import Presentation
    from pptx.util import Inches

    png = (FIXTURES.parent / "fixtures" / "sas" / "pc_synthetic.xpt").read_bytes()  # any bytes: replaced below
    del png
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes(8 * 3) for _ in range(8))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    image = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
             + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_picture(io.BytesIO(image), Inches(1), Inches(1))
    out = io.BytesIO()
    deck.save(out)
    doc = parse_document(out.getvalue(), "scan.pptx")
    assert doc.state == "partly_read" and "slide 1" in doc.reason and len(doc.figures) == 1


def _numbers() -> bytes:
    import tempfile

    from numbers_parser import Document

    document = Document()
    table = document.sheets[0].tables[0]
    for r, row in enumerate([["Subject", "Time (h)", "Conc (ng/mL)"], ["001", 0.5, 3.28], ["001", 1, 9.75]]):
        for c, value in enumerate(row):
            table.write(r, c, value)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "conc.numbers"
        document.save(str(path))
        return path.read_bytes()


def test_a_numbers_document_is_one_sheet_per_table_with_its_stored_values():
    doc = parse_document(_numbers(), "conc.numbers")
    assert (doc.state, doc.format, doc.parser) == ("read", "numbers", "numbers")
    assert len(doc.sheets) == 1
    lines = _lines(doc)
    assert lines[0] == ["Subject", "Time (h)", "Conc (ng/mL)"]
    assert lines[1] == ["001", "0.5", "3.28"] and lines[2] == ["001", "1", "9.75"]


@pytest.mark.parametrize("name", ["broken.pptx", "broken.numbers", "broken.xpt", "broken.sas7bdat"])
def test_a_damaged_file_of_a_new_format_is_unreadable_with_its_reason(name):
    doc = parse_document(b"PK\x03\x04" + b"\x00" * 64, name)
    assert doc.state == "unreadable" and doc.reason


def test_a_known_format_no_parser_reads_says_what_to_ask_for():
    doc = parse_document(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "slides.ppt")
    assert doc.state == "unsupported"
    assert doc.reason == f"no parser for .ppt: {SEND_AS['.ppt']}" and "send it as .pptx or PDF" in doc.reason
