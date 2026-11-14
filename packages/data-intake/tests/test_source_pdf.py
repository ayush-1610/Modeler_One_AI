"""PDF parsed once with pdfplumber and located (contracts §6.1, §8.4; R-a, R-b, R-d): words with boxes, ruled tables
equal to the truth, a table continued over two pages joined into one region, two tables with one header kept apart,
furniture, prose, an unruled table, a scanned page, and the engines a caller passes in."""

from __future__ import annotations

import io
from collections.abc import Sequence

import pdfplumber
import pytest
from pypdf import PdfWriter

from modeler_intake import synthetic
from modeler_intake.anchors import parse_locator, same_place
from modeler_intake.source import paragraphs, parse_document, parser_for, region_grid
from modeler_intake.source.pdf import page_lines
from modeler_intake.source_model import PageTable, TableCell, Word

pytestmark = pytest.mark.req("T-47")


@pytest.fixture(scope="module")
def report():
    file = synthetic.pdf_report()
    return file, parse_document(file.data, file.name)


def _table(doc, where):
    (found,) = [r for r in doc.regions if r.kind == "table" and r.where == where]
    return found


class StubTables:
    """A second table engine: one more table at the top of page 2, above Table 5."""

    name = "stub-tables"
    version = "0.1"

    def __init__(self) -> None:
        self.pages: list[int] = []

    def tables(self, data: bytes, page: int) -> Sequence[PageTable]:
        self.pages.append(page)
        if page != 2:
            return ()
        cells = (TableCell(row=1, column=1, text="Lot", box=(300.0, 20.0, 400.0, 35.0)),
                 TableCell(row=1, column=2, text="L2301", box=(400.0, 20.0, 500.0, 35.0)),
                 TableCell(row=2, column=1, text="Assay (%)", box=(300.0, 35.0, 400.0, 50.0)),
                 TableCell(row=2, column=2, text="99.8", box=(400.0, 35.0, 500.0, 50.0)))
        return (PageTable(index=1, box=(300.0, 20.0, 500.0, 50.0), n_rows=2, n_cols=2, cells=cells, engine="stub-tables"),)


class StubOcr:
    """An OCR engine: the words of the scanned page of `scanned_pdf`."""

    name = "stub-ocr"
    version = "0.2"

    def __init__(self) -> None:
        self.pages: list[int] = []

    def words(self, data: bytes, page: int) -> Sequence[Word]:
        self.pages.append(page)
        texts = ("Lot", "L2301:", "assay", "99.8%", "of", "label", "claim.")
        return tuple(Word(index=k, text=t, box=(56.0 + 40 * k, 100.0, 90.0 + 40 * k, 110.0)) for k, t in enumerate(texts, 1))


def test_words_carry_boxes_inside_the_page_numbered_as_extract_words_gives_them(report):
    file, doc = report
    assert doc.state == "read" and doc.parser == "pdfplumber" and doc.parser_version.startswith("1.0+pdfplumber")
    with pdfplumber.open(io.BytesIO(file.data)) as pdf:
        for page, plumber in zip(doc.pages, pdf.pages, strict=True):
            assert (page.number, page.width, page.height, page.rotation) == (plumber.page_number, 612.0, 792.0, 0)
            assert page.n_chars == len(plumber.chars) and not page.needs_ocr
            assert [w.text for w in page.words] == [w["text"] for w in plumber.extract_words()]
            assert [w.index for w in page.words] == list(range(1, len(page.words) + 1))
            for word in page.words:
                x0, top, x1, bottom = word.box
                assert 0 <= x0 <= x1 <= page.width and 0 <= top <= bottom <= page.height, (page.number, word)


def test_each_ruled_table_is_a_region_whose_cells_equal_the_truth(report):
    file, doc = report
    for table in file.tables:
        truth = synthetic.truth_grid(file, table.id)
        region = _table(doc, table.where)
        assert region.id == truth.region_id and region.caption == table.caption[0]
        grid = region_grid(doc, region.id)
        assert (grid.n_rows, grid.n_cols) == (truth.n_rows, truth.n_cols) == (len(table.rows), len(table.rows[0]))
        assert {p: (c.text, c.type) for p, c in grid.cells.items()} == {p: (c.text, c.type) for p, c in truth.cells.items()}
        for place, cell in truth.cells.items():                      # PDF places compared by identity, never by box
            assert same_place(parse_locator(grid.cells[place].locator), parse_locator(cell.locator)), (table.id, place)
        assert [c.text for c in grid.caption] == list(table.caption)
        assert [" | ".join(c.text for c in line) for line in grid.below] == list(table.below)
        places = [*grid.cells.values(), *grid.caption, *(c for line in (*grid.above, *grid.below) for c in line)]
        for value in (v for v in file.values if v.table == table.id):
            for role, locator in (("value", value.locator), *value.locators):
                assert any(same_place(parse_locator(c.locator), parse_locator(locator)) for c in places), \
                    (table.id, value.field, role, locator)


def test_a_table_continued_over_two_pages_is_one_region_with_two_parts(report):
    _file, doc = report
    region = _table(doc, "p:2/t:1")
    first, second = region.parts
    assert (first.page, first.table, first.n_rows, first.header_rows_repeated) == (2, 1, 13, 0)
    assert (second.page, second.table, second.n_rows, second.header_rows_repeated) == (3, 1, 7, 1)
    assert first.caption == "Table 5. Study 230-25: Exampleamide plasma concentrations by subject"
    assert second.caption == first.caption + " (continued)"                              # each part with its own caption
    grid = region_grid(doc, region.id)
    assert region.n_rows == grid.n_rows == 19
    assert [r for r in range(1, grid.n_rows + 1) if grid.cell(r, 1).text == "Subject"] == [1]   # the header dropped once
    first_on_page_3 = parse_locator(grid.cell(14, 1).locator)
    assert (first_on_page_3.page, first_on_page_3.row, grid.cell(14, 1).text) == (3, 2, "203")
    assert not [r for r in doc.regions if r.where.startswith("p:3/t:")]
    assert [c.text for line in grid.below for c in line] == ["BLQ: below the lower limit of quantification (0.5 ng/mL)."]
    (lloq,) = [o for o in doc.outside if o.region == region.id]
    assert lloq.numeric and lloq.where.startswith("p:3/w:")


def test_two_tables_with_one_header_on_consecutive_pages_under_different_captions_stay_two(report):
    _file, doc = report
    six, seven = _table(doc, "p:4/t:1"), _table(doc, "p:5/t:1")
    assert six.id != seven.id and len(six.parts) == len(seven.parts) == 1
    assert "Cohort 1" in six.caption and "Cohort 2" in seven.caption
    assert region_grid(doc, six.id).cell(1, 1).text == region_grid(doc, seven.id).cell(1, 1).text == "Time (h)"


def test_a_region_id_does_not_change_when_an_engine_finds_one_more_table(report):
    file, doc = report
    engine = StubTables()
    more = parse_document(file.data, file.name, pdf_table_engines=(engine,))
    assert engine.pages == [1, 2, 3, 4, 5, 6]                                         # the engine passed in is used
    assert more.parser_version == doc.parser_version + "+stub-tables0.1"
    assert more.parser_version == parser_for(file.data, file.name, pdf_table_engines=(engine,))[1]
    before = {r.id: r.where for r in doc.regions if r.kind == "table"}
    after = {r.id: r.where for r in more.regions if r.kind == "table"}
    assert before.items() <= after.items()                                             # no region renumbered
    (extra,) = [r for r in more.regions if r.kind == "table" and r.id not in before]
    assert extra.where == "p:2/t:2" and more.pages[1].tables[1].engine == "stub-tables"
    assert region_grid(more, extra.id).cell(2, 2).text == "99.8"
    assert len(_table(more, "p:2/t:1").parts) == 2                                     # Table 5 still continues


def test_text_outside_the_tables_is_listed_by_page_and_the_page_number_is_furniture(report):
    _file, doc = report
    furniture = [o for o in doc.outside if o.furniture]
    assert [o.text for o in furniture] == [f"Page {n} of 6" for n in range(1, 7)]
    assert [parse_locator(o.where).page for o in furniture] == [1, 2, 3, 4, 5, 6]
    part_captions = {(p.page, p.caption) for r in doc.regions for p in r.parts}
    for page in doc.pages:                      # every line outside the tables: in a region, a caption, or listed
        ranges = []
        for region in doc.regions:
            if region.kind in ("prose", "table_like_text") and region.where.startswith(f"p:{page.number}/w:"):
                first, last = (int(v) for v in region.where.split(":")[-1].split("-"))
                ranges.append((first, last))
            if region.caption_locator and region.caption_locator.startswith(f"p:{page.number}/w:"):
                span = parse_locator(region.caption_locator)
                ranges.append((span.first_word, span.last_word))
        for item in doc.outside:
            span = parse_locator(item.where)
            if span.kind == "pdf_span" and span.page == page.number:
                ranges.append((span.first_word, span.last_word))
        for line in page_lines(page):
            if (page.number, line.text) in part_captions:
                continue
            for word in line.words:
                assert any(a <= word.index <= b for a, b in ranges), (page.number, word.text)


def test_the_synopsis_is_prose_and_its_facts_lie_in_its_paragraphs(report):
    file, doc = report
    (prose,) = [r for r in doc.regions if r.kind == "prose"]
    assert prose.where.startswith("p:1/w:1-")
    found = paragraphs(doc, prose.id)
    assert [p.text for p in found] == [file.prose[0], " ".join(file.prose[1:])]
    assert found[1].heading == "Clinical Study Report Synopsis" and found[1].heading_locator.startswith("p:1/w:1-4@")
    for value in (v for v in file.values if v.table == ""):
        span = parse_locator(value.locator)
        holder = next(p for p in found if _words(p.locator)[0] <= span.first_word <= span.last_word <= _words(p.locator)[1])
        words = doc.pages[0].words[span.first_word - 1:span.last_word]
        assert " ".join(w.text for w in words) == value.value and value.value in holder.text


def _image_pdf() -> bytes:
    """A one-page PDF that is only an image (a scan with no text layer), written by hand."""
    pixels = bytes((x * 7 + y * 3) % 256 for y in range(8) for x in range(8))
    content = b"q 400 0 0 500 106 146 cm /Im1 Do Q"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im1 5 0 R >> >> "
                b"/Contents 4 0 R >>"),
               b"<< /Length %d >> stream\n" % len(content) + content + b"\nendstream",
               b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray /BitsPerComponent 8 "
               b"/Length 64 >> stream\n" + pixels + b"\nendstream"]
    body, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj " % number + obj + b" endobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return body + b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


def _words(locator: str) -> tuple[int, int]:
    first, last = locator.split("/w:")[1].split("-")
    return int(first), int(last)


def test_an_unruled_table_is_located_as_table_like_text_and_not_gridded(report):
    _file, doc = report
    (unruled,) = [r for r in doc.regions if r.kind == "table_like_text"]
    assert unruled.where.startswith("p:6/w:") and unruled.caption.startswith("Table 8.")
    assert unruled.numeric_cells == 9 and unruled.n_rows == 4
    with pytest.raises(ValueError):
        region_grid(doc, unruled.id)
    assert not [r for r in doc.regions if r.kind == "prose" and r.where.startswith("p:6/")]


def test_the_scanned_page_needs_ocr_and_the_document_is_partly_read_naming_it():
    file = synthetic.scanned_pdf()
    doc = parse_document(file.data, file.name)
    text_page, image_page = doc.pages
    assert not text_page.needs_ocr and image_page.needs_ocr and image_page.n_chars == 0 and image_page.n_images == 1
    assert doc.state == "partly_read" and doc.reason == "page 2 needs OCR (no text layer); no OCR engine is registered"
    (figure,) = doc.figures
    assert (figure.page, figure.index, figure.width, figure.height) == (2, 1, 32, 32)
    assert [r.kind for r in doc.regions] == ["prose", "figure"]
    assert doc.role == "certificate_of_analysis"


def test_a_stub_ocr_engine_passed_in_reads_the_scanned_page():
    file = synthetic.scanned_pdf()
    engine = StubOcr()
    doc = parse_document(file.data, file.name, ocr=engine)
    assert engine.pages == [2]                                                           # only the page that needs OCR
    assert doc.state == "read" and doc.parser_version.endswith("+ocr-stub-ocr0.2")
    assert [w.text for w in doc.pages[1].words][:2] == ["Lot", "L2301:"] and doc.pages[1].needs_ocr
    assert [r.kind for r in doc.regions if r.where.startswith("p:2/")] == ["prose", "figure"]


def test_a_pdf_with_no_text_layer_anywhere_or_a_password_is_unreadable():
    scanned = parse_document(_image_pdf(), "scan-only.pdf")
    assert scanned.state == "unreadable" and "page 1 needs OCR" in scanned.reason
    writer = PdfWriter(clone_from=io.BytesIO(synthetic.scanned_pdf().data))
    writer.encrypt(user_password="secret", owner_password="owner")
    locked = io.BytesIO()
    writer.write(locked)
    doc = parse_document(locked.getvalue(), "locked.pdf")
    assert doc.state == "unreadable" and doc.reason == "the PDF is encrypted: a password is needed"
    broken = parse_document(synthetic.scanned_pdf().data[:200], "cut.pdf")
    assert broken.state == "unreadable" and broken.reason


class FailingTables:
    """A second table engine that fails on every page."""

    name = "failing-tables"
    version = "1"

    def tables(self, data: bytes, page: int) -> Sequence[PageTable]:
        raise RuntimeError("model weights missing")


class FailingOcr:
    """An OCR engine that fails."""

    name = "failing-ocr"
    version = "1"

    def words(self, data: bytes, page: int) -> Sequence[Word]:
        raise ValueError("no language pack")


def test_an_engine_that_fails_is_named_and_the_page_keeps_pdfplumbers_reading(report):
    file, doc = report
    failed = parse_document(file.data, file.name, pdf_table_engines=(FailingTables(),))
    assert failed.state == "read"
    assert failed.warnings == tuple(f"TABLE_ENGINE_FAILED p:{n}: failing-tables: RuntimeError: model weights missing"
                                    for n in range(1, 7))
    assert [(r.id, r.where) for r in failed.regions] == [(r.id, r.where) for r in doc.regions]
    scanned = synthetic.scanned_pdf()
    read = parse_document(scanned.data, scanned.name, ocr=FailingOcr())
    assert read.state == "partly_read"
    assert read.reason == "page 2 needs OCR (no text layer); the OCR engine failing-ocr found no words"
    assert read.warnings == ("OCR_FAILED p:2: failing-ocr: ValueError: no language pack",)
    assert read.pages[1].needs_ocr and read.pages[1].words == ()


Texts = Sequence[tuple[float, float, str]]
Tables = Sequence[tuple[float, float, tuple[float, ...], tuple[tuple[str, ...], ...]]]


def _ruled_pdf(*pages: tuple[Texts, Tables]) -> bytes:
    """A PDF written by hand, one page per (texts, tables): lines of text (x, top, text; Helvetica 10) and ruled tables
    (x, top, column widths, rows; Helvetica 9, rows 16 points high), on 612 x 792 pages."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % (4 + 2 * k) for k in range(len(pages))),
                                                           len(pages)),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for k, (texts, tables) in enumerate(pages):
        ops = []
        for x, top, widths, rows in tables:
            right, bottom = x + sum(widths), top + 16 * len(rows)
            ops += [f"{x:.2f} {792 - top - 16 * r:.2f} m {right:.2f} {792 - top - 16 * r:.2f} l S"
                    for r in range(len(rows) + 1)]
            edges = [x + sum(widths[:c]) for c in range(len(widths) + 1)]
            ops += [f"{e:.2f} {792 - top:.2f} m {e:.2f} {792 - bottom:.2f} l S" for e in edges]
            for r, row in enumerate(rows):
                ops += [f"BT /F1 9 Tf {edges[c] + 4:.2f} {792 - top - 16 * r - 10.7:.2f} Td ({text}) Tj ET"
                        for c, text in enumerate(row) if text]
        ops += [f"BT /F1 10 Tf {x:.2f} {792 - top - 8:.2f} Td ({text}) Tj ET" for x, top, text in texts]
        stream = "\n".join(ops).encode("latin-1")
        objects += [b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                    b"/Contents %d 0 R >>" % (5 + 2 * k),
                    b"<< /Length %d >> stream\n" % len(stream) + stream + b"\nendstream"]
    body, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj " % number + obj + b" endobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return body + b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


def test_tables_side_by_side_each_have_their_own_caption_and_footnote():
    rows = (("Time (h)", "Conc"), ("1", "2.5"), ("2", "3.5"))
    data = _ruled_pdf(([(56, 60, "Table 1. Exampleamide, Cohort 1"), (320, 60, "Table 2. Exampleamide, Cohort 2"),
                        (56, 150, "LLOQ 0.5 ng/mL"), (320, 150, "LLOQ 0.2 ng/mL")],
                       [(56, 90, (60.0, 60.0), rows), (320, 90, (60.0, 60.0), rows)]))
    doc = parse_document(data, "side-by-side.pdf")
    with pdfplumber.open(io.BytesIO(data)) as pdf:                  # one line each in pdfplumber's words
        (page,) = pdf.pages
        assert len({round(w["top"]) for w in page.extract_words() if w["text"] == "Table"}) == 1
    left, right = [r for r in doc.regions if r.kind == "table"]
    assert (left.where, right.where) == ("p:1/t:1", "p:1/t:2")
    assert (left.caption, right.caption) == ("Table 1. Exampleamide, Cohort 1", "Table 2. Exampleamide, Cohort 2")
    assert [[c.text for c in line] for line in region_grid(doc, left.id).below] == [["LLOQ 0.5 ng/mL"]]
    assert [[c.text for c in line] for line in region_grid(doc, right.id).below] == [["LLOQ 0.2 ng/mL"]]
    assert [(o.text, o.region) for o in doc.outside] == [("LLOQ 0.5 ng/mL", left.id), ("LLOQ 0.2 ng/mL", right.id)]
    assert [r.kind for r in doc.regions] == ["table", "table"]       # nothing else on the page: no prose left over


def test_a_header_of_two_rows_repeated_and_a_continuation_note_keep_one_region():
    header = (("Subject", "Exampleamide (ng/mL)", ""), ("", "Day 1", "Day 8"))
    first = (*header, ("101", "12.5", "14.1"), ("102", "11.9", "13.0"))
    second = (*header, ("103", "13.2", "15.4"), ("104", "10.8", "12.2"))
    widths = (80.0, 100.0, 100.0)
    data = _ruled_pdf(([(56, 60, "Table 9. Study 230-29: trough concentrations"), (56, 170, "Continued on next page")],
                       [(56, 90, widths, first)]),
                      ([(56, 60, "(continued)")], [(56, 90, widths, second)]))
    doc = parse_document(data, "continued.pdf")
    (region,) = [r for r in doc.regions if r.kind == "table"]
    assert [(p.page, p.n_rows, p.header_rows_repeated, p.caption) for p in region.parts] == [
        (1, 4, 0, "Table 9. Study 230-29: trough concentrations"), (2, 4, 2, "(continued)")]
    grid = region_grid(doc, region.id)
    assert grid.n_rows == region.n_rows == 6
    assert [grid.cell(r, 1).text for r in range(1, 7)] == ["Subject", "", "101", "102", "103", "104"]
    assert region.numeric_cells == 2 + 6 + 6                              # the repeated header ("Day 1") counted once
    assert [(o.text, o.furniture, o.region) for o in doc.outside] == [("Continued on next page", True, None)]
    assert [r.kind for r in doc.regions] == ["table"]                     # the note is furniture, not prose


_ROWS = (("Time (h)", "Conc"), ("1", "2.5"), ("2", "3.5"))


def test_the_same_lloq_footnote_under_a_table_on_each_page_is_each_tables_context_not_furniture():
    footnote = "LLOQ = 0.5 ng/mL; BLQ values set to zero"
    data = _ruled_pdf(([(56, 60, "Table 6. Cohort 1 (10 mg)"), (56, 150, footnote)], [(56, 90, (60.0, 60.0), _ROWS)]),
                      ([(56, 60, "Table 7. Cohort 2 (30 mg)"), (56, 150, footnote)], [(56, 90, (60.0, 60.0), _ROWS)]))
    doc = parse_document(data, "cohorts.pdf")
    first, second = [r for r in doc.regions if r.kind == "table"]
    for region in (first, second):
        assert [[c.text for c in line] for line in region_grid(doc, region.id).below] == [[footnote]]
    assert [(o.text, o.numeric, o.furniture, o.region) for o in doc.outside] == [
        (footnote, True, False, first.id), (footnote, True, False, second.id)]


def test_running_lines_that_differ_in_their_numbers_are_not_furniture_and_the_page_number_is():
    pages = []
    for k, (dose, n, cmax) in enumerate(((10, 8, 7.4), (30, 12, 22.3), (60, 12, 41.0)), start=1):
        pages.append(([(56, 30, f"Exampleamide Study 230-2{k} Cohort {k} ({dose} mg)"), (56, 60, f"Table {k}. Cohort {k}"),
                       (56, 740, f"Cohort {k}: {dose} mg, N = {n} subjects, Cmax {cmax} ng/mL"), (300, 760, f"Page {k} of 3")],
                      [(56, 90, (60.0, 60.0), _ROWS)]))
    doc = parse_document(_ruled_pdf(*pages), "cohort headers.pdf")
    furniture = [o.text for o in doc.outside if o.furniture]
    assert furniture == ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"]
    tables = [r for r in doc.regions if r.kind == "table"]
    for k, region in enumerate(tables, start=1):                     # the running header: the context above its table
        assert [[c.text for c in line] for line in region_grid(doc, region.id).above] == [
            [f"Exampleamide Study 230-2{k} Cohort {k} ({(10, 30, 60)[k - 1]} mg)"]]
    footers = [r for r in doc.regions if r.kind == "prose"]          # the running footers: read as prose, page by page
    assert [r.where.split("/")[0] for r in footers] == ["p:1", "p:2", "p:3"] and all(r.numeric_cells == 4 for r in footers)


def test_a_data_row_that_equals_the_first_parts_after_the_repeated_header_is_kept():
    first = (("Time (h)", "Conc (ng/mL)"), ("0", "BLQ"), ("1", "12.5"), ("2", "20.1"))
    second = (("Time (h)", "Conc (ng/mL)"), ("0", "BLQ"), ("1", "13.0"), ("2", "19.4"))
    data = _ruled_pdf(([(56, 60, "Table 3. Exampleamide, periods 1 and 2")], [(56, 90, (80.0, 80.0), first)]),
                      ([(56, 60, "Table 3. Exampleamide, periods 1 and 2 (continued)")], [(56, 90, (80.0, 80.0), second)]))
    doc = parse_document(data, "periods.pdf")
    (region,) = [r for r in doc.regions if r.kind == "table"]
    assert [(p.page, p.n_rows, p.header_rows_repeated) for p in region.parts] == [(1, 4, 0), (2, 4, 1)]
    grid = region_grid(doc, region.id)
    assert [grid.cell(r, 1).text for r in range(1, grid.n_rows + 1)] == ["Time (h)", "0", "1", "2", "0", "1", "2"]
    assert grid.cell(5, 2).locator.startswith("p:2/t:1/r:2/c:2@") and region.numeric_cells == 10


def test_a_header_of_times_across_repeated_on_the_next_page_is_dropped_once():
    header = (("Subject", "0.5", "1", "2"),)
    first = (*header, ("101", "12.5", "14.1", "9.0"), ("102", "11.9", "13.0", "8.4"))
    second = (*header, ("103", "13.2", "15.4", "9.9"))
    widths = (70.0, 60.0, 60.0, 60.0)
    data = _ruled_pdf(([(56, 60, "Table 4. Exampleamide plasma concentrations (ng/mL) by time (h)")], [(56, 90, widths, first)]),
                      ([(56, 60, "Table 4. Exampleamide plasma concentrations (ng/mL) by time (h) (continued)")],
                       [(56, 90, widths, second)]))
    doc = parse_document(data, "times across.pdf")
    (region,) = [r for r in doc.regions if r.kind == "table"]
    assert [p.header_rows_repeated for p in region.parts] == [0, 1]
    grid = region_grid(doc, region.id)
    assert [grid.cell(r, 1).text for r in range(1, grid.n_rows + 1)] == ["Subject", "101", "102", "103"]


@pytest.mark.parametrize("pitch", [14, 22, 30])
def test_an_unruled_table_is_table_like_text_however_wide_its_rows_are_spaced(pitch):
    rows = (("Time (h)", "Mean", "SD"), ("0.5", "4.1", "1.2"), ("1", "9.8", "2.0"), ("2", "17.9", "3.1"), ("4", "12.0", "2.2"))
    texts = [(56, 100, "Table 5. Exampleamide plasma concentrations (ng/mL), mean and SD")]
    texts += [(56 + 100 * c, 130 + pitch * r, text) for r, row in enumerate(rows) for c, text in enumerate(row)]
    doc = parse_document(_ruled_pdf((texts, [])), "unruled.pdf")
    (region,) = doc.regions                                              # one row per paragraph at 22 and 30 points
    assert (region.kind, region.where) == ("table_like_text", "p:1/w:10-25")
    assert region.caption == "Table 5. Exampleamide plasma concentrations (ng/mL), mean and SD"
    assert (region.n_rows, region.numeric_cells) == (5, 12)              # its header row with it


def test_the_last_line_of_a_prose_paragraph_is_no_caption_and_the_paragraph_stays_whole():
    texts = [(56, 60, "Eighteen subjects received 20 mg of Exampleamide in the fasted state;"),
             (56, 72, "the mean Cmax was 17.9 ng/mL at 2 h and the"),
             (56, 84, "terminal half-life was 4.1 h (Table 1 gives the profile).")]
    doc = parse_document(_ruled_pdf((texts, [(56, 100, (60.0, 60.0), _ROWS)])), "prose above.pdf")
    prose, table = doc.regions
    assert (prose.kind, prose.where, prose.numeric_cells) == ("prose", "p:1/w:1-32", 5)
    assert (table.kind, table.caption, table.caption_locator) == ("table", "", None)
    (paragraph,) = paragraphs(doc, prose.id)
    assert paragraph.text.endswith("and the terminal half-life was 4.1 h (Table 1 gives the profile).")


def test_a_caption_wrapped_over_two_lines_is_the_caption_whole_one_grid_cell_per_line():
    first, second = "Table 2. Exampleamide plasma concentrations after 20 mg in the fasted state,", "Study 230-27, mean (SD)"
    texts = [(56, 60, "A sentence of prose that ends here."), (56, 90, first), (56, 102, second)]
    doc = parse_document(_ruled_pdf((texts, [(56, 120, (60.0, 60.0), _ROWS)])), "wrapped caption.pdf")
    (table,) = [r for r in doc.regions if r.kind == "table"]
    assert table.caption == f"{first}\n{second}" and table.caption_locator.startswith("p:1/w:8-23@")
    grid = region_grid(doc, table.id)
    assert [c.text for c in grid.caption] == [first, second]
    assert [c.locator.split("@")[0] for c in grid.caption] == ["p:1/w:8-19", "p:1/w:20-23"]
    assert [[c.text for c in line] for line in grid.above] == [["A sentence of prose that ends here."]]


def _scan_under_running_lines(image: tuple[int, int, int, int]) -> bytes:
    """A two-page PDF written by hand: a page of text, then a page with an image (x, y, width, height in PDF points)
    under a typed running header and footer (34 characters, all in the page's margins)."""
    pixels = bytes((x * 7 + y * 3) % 256 for y in range(8) for x in range(8))
    x, y, width, height = image
    text1 = b"BT /F1 10 Tf 56 700 Td (Certificate of analysis, Exampleamide batch L2301) Tj ET"
    text2 = (b"q %d 0 0 %d %d %d cm /Im1 Do Q " % (width, height, x, y)
             + b"BT /F1 10 Tf 56 770 Td (Exampleamide CSR 230-23) Tj ET BT /F1 10 Tf 280 20 Td (Page 2 of 2) Tj ET")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
               b"<< /Length %d >> stream\n" % len(text1) + text1 + b"\nendstream",
               (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> "
                b"/XObject << /Im1 8 0 R >> >> /Contents 6 0 R >>"),
               b"<< /Length %d >> stream\n" % len(text2) + text2 + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray /BitsPerComponent 8 "
               b"/Length 64 >> stream\n" + pixels + b"\nendstream"]
    body, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj " % number + obj + b" endobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return body + b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


def test_a_scan_under_a_typed_running_header_and_footer_needs_ocr_and_a_logo_does_not():
    from modeler_intake.source import inventory

    scan = _scan_under_running_lines((106, 146, 400, 500))
    doc = parse_document(scan, "scan with header.pdf")
    assert doc.pages[1].n_chars == 34 and doc.pages[1].needs_ocr and not doc.pages[0].needs_ocr
    assert doc.state == "partly_read" and doc.reason == "page 2 needs OCR (no text layer); no OCR engine is registered"
    assert (inventory([("scan.pdf", scan)]).pdf_mixed, inventory([("scan.pdf", scan)]).with_figures) == (1, 0)
    logo = parse_document(_scan_under_running_lines((500, 700, 60, 40)), "logo with header.pdf")
    assert not logo.pages[1].needs_ocr and logo.state == "read"
