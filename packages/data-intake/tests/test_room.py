"""The Data room's reader (`modeler_intake.room`) and our OCR engine's word boxes (`modeler_intake.ocr`): a delivery
unpacked with its leftovers dropped, text exports read as tables, duplicates found by bytes and by content, pages of
turned text read upright, pages of text printed as outlines read by OCR (a ruled table's cells filled from its words),
and quotes found in the plain lines the agents read.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from modeler_intake.ocr import _line_words
from modeler_intake.room import (
    document_text,
    find_quote,
    is_junk,
    numbers_in,
    page_png,
    read_delivery,
    read_file,
    reading_pdf,
    sniff_delimiter,
    upright_pdf,
)
from modeler_intake.source import parse_document
from modeler_intake.source_model import Word

pytestmark = pytest.mark.req("T-47")

W, H = 612, 792


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf(pages: list[str]) -> bytes:
    """A PDF of pages given as content streams (Helvetica as /F1)."""
    objects, kids = [], []
    for i, ops in enumerate(pages):
        page_obj, content_obj = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_obj} 0 R")
        stream = ops.encode("latin-1")
        objects.append(f"{page_obj} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj} 0 R >> endobj\n".encode())
        objects.append(f"{content_obj} 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n")
    head = [b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            f"2 0 obj << /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >> endobj\n".encode(),
            b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n"]
    body, offsets = b"%PDF-1.4\n", []
    for obj in head + objects:
        offsets.append(len(body))
        body += obj
    xref = len(body)
    body += f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    return body + f"trailer << /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


ROWS = ("Vessel 5 min 10 min 15 min", "1 81 88 90", "2 80 87 91", "Avg 81 87 90")


def _upright_page() -> str:
    return "\n".join(f"BT /F1 10 Tf 72 {700 - 16 * i} Td ({_escape(r)}) Tj ET" for i, r in enumerate(ROWS))


def _turned_page() -> str:
    """The same lines drawn turned 90° counter-clockwise (a landscape table printed on a portrait page)."""
    return "\n".join(f"BT /F1 10 Tf 0 1 -1 0 {100 + 16 * i} 72 Tm ({_escape(r)}) Tj ET" for i, r in enumerate(ROWS))


def _outlines(n: int = 240) -> str:
    """Many small filled curves and no characters: text printed as outlines."""
    return "\n".join(f"{300 + (k % 20) * 6} {200 + (k // 20) * 8} m {302 + (k % 20) * 6} {204 + (k // 20) * 8} "
                     f"{304 + (k % 20) * 6} {204 + (k // 20) * 8} {305 + (k % 20) * 6} {200 + (k // 20) * 8} c f" for k in range(n))


def _ruled_grid(x0: float, top: float, widths: tuple[float, ...], rows: int, height: float) -> str:
    ops = ["0.5 w"]
    x1 = x0 + sum(widths)
    for r in range(rows + 1):
        y = H - (top + r * height)
        ops.append(f"{x0} {y} m {x1} {y} l S")
    x = x0
    for width in (0.0, *widths):
        x += width
        ops.append(f"{x} {H - top} m {x} {H - top - rows * height} l S")
    return "\n".join(ops)


class _FakeOcr:
    """Words placed where a scan would show them: (text, box in points, top-left origin)."""

    name, version = "fake", "1"

    def __init__(self, words: list[tuple[str, tuple[float, float, float, float]]]) -> None:
        self._words = words
        self.calls: list[int] = []

    def words(self, data: bytes, page: int) -> list[Word]:
        self.calls.append(page)
        return [Word(index=k, text=t, box=b) for k, (t, b) in enumerate(self._words, start=1)]


def _zip(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


# --- OCR words ------------------------------------------------------------------------------------------------------


def test_an_ocr_line_is_cut_into_words_each_with_the_box_of_its_characters():
    text = "Avg 81.5"
    boxes = [[[10 * i, 0], [10 * i + 8, 0], [10 * i + 8, 20], [10 * i, 20]] for i in range(len(text))]
    words = _line_words(text, [[0, 0], [80, 0], [80, 20], [0, 20]], boxes, scale=2.0)
    assert [w for w, _ in words] == ["Avg", "81.5"]
    assert words[0][1] == (0.0, 0.0, 14.0, 10.0) and words[1][1] == (20.0, 0.0, 39.0, 10.0)


def test_character_boxes_that_skip_the_spaces_still_locate_each_word():
    text = "1 81"
    boxes = [[[0, 0], [8, 0], [8, 10], [0, 10]], [[20, 0], [28, 0], [28, 10], [20, 10]], [[30, 0], [38, 0], [38, 10], [30, 10]]]
    words = _line_words(text, [[0, 0], [38, 0], [38, 10], [0, 10]], boxes, scale=1.0)
    assert words == [("1", (0.0, 0.0, 8.0, 10.0)), ("81", (20.0, 0.0, 38.0, 10.0))]


def test_character_boxes_that_do_not_match_the_text_share_the_line_in_proportion():
    words = _line_words("ab cd", [[0, 0], [50, 0], [50, 10], [0, 10]], [[[0, 0], [1, 0], [1, 1], [0, 1]]], scale=1.0)
    assert [w for w, _ in words] == ["ab", "cd"]
    assert words[0][1] == (0.0, 0.0, 20.0, 10.0) and words[1][1] == (30.0, 0.0, 50.0, 10.0)


# --- turned pages -----------------------------------------------------------------------------------------------------


def test_a_page_of_turned_text_is_turned_upright_and_reads_like_the_upright_page():
    upright = document_text(parse_document(_pdf([_upright_page()]), "upright.pdf"))[0][1]
    data, angles = upright_pdf(_pdf([_upright_page(), _turned_page()]))
    assert angles == (0, 90)
    doc = parse_document(data, "turned.pdf")
    assert document_text(doc)[1][1] == upright == list(ROWS)


def test_a_pdf_with_no_turned_page_is_left_as_it_was():
    data = _pdf([_upright_page()])
    assert upright_pdf(data) == (data, (0,))


def test_the_reader_reports_the_pages_it_turned_and_reads_the_copy():
    room = read_file("Part B/Dissolution.pdf", _pdf([_turned_page()]))
    assert room.turned_pages == (1,) and room.reading_copy and room.kind == "pdf" and room.state == "read"
    assert find_quote(room.document, "Avg 81 87 90") == ("p1", 4)


def test_the_source_viewer_draws_the_page_as_it_was_read_where_each_box_falls():
    # the turned page is shown as the reader read it: upright, with its size in points the document's own, so a cell's
    # box (points, top-left origin) is highlighted on the page shown
    data = _pdf([_turned_page()])
    room = read_file("Dissolution.pdf", data)
    copy = reading_pdf("Dissolution.pdf", data)
    assert copy == upright_pdf(data)[0] and copy != data
    page = room.document.pages[0]
    png = page_png(copy, 1, scale=1.0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    assert (width, height) == (round(page.width), round(page.height)) == (H, W)
    assert reading_pdf("conc.txt", b"a\tb\tc\n1\t2\t3\n4\t5\t6\n") is None and reading_pdf("notes.docx", b"PK") is None
    with pytest.raises(IndexError):
        page_png(copy, 2)


# --- scans ------------------------------------------------------------------------------------------------------------


def test_a_page_of_text_printed_as_outlines_is_a_scan_read_by_ocr():
    ocr = _FakeOcr([("Subject", (72, 100, 110, 110)), ("Weight", (130, 100, 160, 110)), ("12", (72, 120, 82, 130)),
                    ("70.5", (130, 120, 150, 130))])
    doc = parse_document(_pdf([_outlines()]), "demographics.pdf", ocr=ocr)
    (page,) = doc.pages
    assert page.needs_ocr and ocr.calls == [1] and "+ocr-fake1" in doc.parser_version
    assert document_text(doc)[0][1] == ["Subject | Weight", "12 | 70.5"]


def test_a_few_drawn_curves_on_a_page_with_no_text_are_not_taken_for_a_scan():
    ocr = _FakeOcr([("x", (0, 0, 5, 5))])
    (page,) = parse_document(_pdf([_outlines(40)]), "logo.pdf", ocr=ocr).pages
    assert not page.needs_ocr and ocr.calls == []


def test_a_ruled_table_on_a_scan_takes_its_cells_text_from_the_ocr_words():
    grid = _ruled_grid(72, 100, (80, 80), rows=3, height=20)
    ocr = _FakeOcr([("Subject", (80, 105, 120, 115)), ("Weight", (160, 105, 190, 115)), ("(kg)", (192, 105, 210, 115)),
                    ("1", (80, 125, 85, 135)), ("70.5", (160, 125, 180, 135)),
                    ("2", (80, 145, 85, 155)), ("64.0", (160, 145, 180, 155))])
    doc = parse_document(_pdf([grid + "\n" + _outlines()]), "scan.pdf", ocr=ocr)
    (page,) = doc.pages
    (table,) = [t for t in page.tables if t.engine == "pdfplumber"]
    cells = {(c.row, c.column): c.text for c in table.cells}
    assert cells[(1, 1)] == "Subject" and cells[(1, 2)] == "Weight (kg)" and cells[(3, 2)] == "64.0"


# --- delivery ---------------------------------------------------------------------------------------------------------


CONC = "Subject\tPeriod\tTime\tConc\n1\t1\t0\tBLQ\n1\t1\t1\t12.5\n2\t1\t0\tBLQ\n2\t1\t1\t10.1\n"


def test_a_tab_export_is_read_as_a_table_with_a_cell_per_value():
    assert sniff_delimiter(CONC.encode()) == "\t"
    room = read_file("Part D/conc.dat", CONC.encode())
    assert room.kind == "delimited" and room.read_as == "conc.dat.tsv" and room.state == "read"
    assert document_text(room.document)[0][1][2] == "1 | 1 | 1 | 12.5"


def test_a_semicolon_export_is_read_as_a_table_too_and_prose_is_not():
    room = read_file("conc.txt", CONC.replace("\t", ";").encode())
    assert room.kind == "delimited" and room.read_as == "conc.txt.csv"
    assert document_text(room.document)[0][1][1] == "1 | 1 | 0 | BLQ"
    assert sniff_delimiter(b"The study was open-label.\nTwo periods, one week apart.\nTwelve subjects.\n") is None


def test_a_delivery_is_unpacked_its_leftovers_dropped_and_its_duplicates_marked():
    upload = _zip({"Client/Part D/conc.dat": CONC.encode(), "Client/Part D/conc.txt": CONC.replace("\t", ";").encode(),
                   "Client/Part D/copy/conc.dat": CONC.encode(), "__MACOSX/Client/._conc.dat": b"\x00\x05",
                   "Client/.DS_Store": b"\x00", "Client/notes.md": b"# Notes\n\nThe meal was standard.\n"})
    files = {f.path: f for f in read_delivery([("data.zip", upload)])}
    assert set(files) == {"Client/Part D/conc.dat", "Client/Part D/conc.txt", "Client/Part D/copy/conc.dat",
                          "Client/notes.md"}
    assert files["Client/Part D/copy/conc.dat"].duplicate_of == "Client/Part D/conc.dat"
    assert files["Client/Part D/copy/conc.dat"].document is None
    assert files["Client/Part D/conc.txt"].same_content_as == "Client/Part D/conc.dat"
    assert files["Client/notes.md"].same_content_as is None and files["Client/notes.md"].kind == "text"


@pytest.mark.parametrize("path", ["__MACOSX/a/b.pdf", "a/._b.pdf", "a/.DS_Store", "Thumbs.db"])
def test_operating_system_leftovers_are_junk(path):
    assert is_junk(path)


def test_a_real_file_is_not_junk():
    assert not is_junk("Client/Part A/Composition.pdf")


# --- quotes and numbers -----------------------------------------------------------------------------------------------


def test_a_quote_is_found_across_lines_whatever_its_spacing_dashes_and_trailing_zeros():
    doc = parse_document(b"Subjects fasted for 10.0 hours before dosing\nand received 240 mL of water \xe2\x80\x93 room "
                         b"temperature.\n", "protocol.txt")
    assert find_quote(doc, "fasted for 10 hours before dosing and received 240 mL of water - room") == ("body", 1)
    assert find_quote(doc, "fasted for 12 hours") is None


def test_numbers_are_read_with_thousands_separators_and_signs_but_not_from_words():
    assert numbers_in("AUC 1,234.5 ng·h/mL, change −3.2 %, batch NQ9017001-A, 0.50") == [1234.5, -3.2, 0.5]


# --- our OCR engine on a real render ----------------------------------------------------------------------------------

_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def test_the_ocr_engine_reads_a_scanned_image_and_locates_each_word_on_the_page():
    import os

    if not os.path.exists(_FONT):
        pytest.skip("no DejaVu font to render a test scan with")
    from PIL import Image, ImageDraw, ImageFont

    from modeler_intake.ocr import RapidOcr

    font = ImageFont.truetype(_FONT, 30)
    image = Image.new("RGB", (900, 160), "white")
    draw = ImageDraw.Draw(image)
    for x, header, value in ((40, "Subject", "12"), (240, "Weight (kg)", "70.5"), (520, "Height", "168")):
        draw.text((x, 30), header, fill="black", font=font)
        draw.text((x, 90), value, fill="black", font=font)
    png = io.BytesIO()
    image.save(png, format="PNG")
    room = read_file("Part D/demographics.png", png.getvalue(), ocr=RapidOcr())
    assert room.kind == "image" and room.read_as == "demographics.png.pdf" and room.ocr_pages == (1,)
    assert document_text(room.document)[0][1] == ["Subject | Weight (kg) | Height", "12 | 70.5 | 168"]
    (weight,) = [w for w in room.document.pages[0].words if w.text == "70.5"]
    x0, top, x1, bottom = weight.box   # 900 × 160 px at 2.5 px per point: the page is 360 × 64 points
    assert 90 < x0 < x1 < 130 and 30 < top < bottom < 55


def test_a_damaged_archive_is_listed_unreadable_with_its_reason():
    (room,) = read_delivery([("Client/data.zip", b"PK\x03\x04 not really a zip")])
    assert (room.kind, room.state) == ("archive", "unreadable") and "not a readable ZIP archive" in room.reason


def test_an_archive_made_without_the_utf8_flag_keeps_its_names():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        info = zipfile.ZipInfo("Part D/17-06-138 \u2013 Concentration Table.dat".encode().decode("cp437"))
        z.writestr(info, CONC.encode())   # a cp437 name, no UTF-8 flag: as macOS's archiver writes it
    (room,) = read_delivery([("data.zip", out.getvalue())])
    assert room.path == "Part D/17-06-138 \u2013 Concentration Table.dat"
