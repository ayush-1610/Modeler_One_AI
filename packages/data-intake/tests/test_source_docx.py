"""Word read once with python-docx and located (contracts §6.1, §8.4; R-a): tables as grids (a merged header once, with
its span; a line break inside a cell kept), paragraphs in order, the image as a figure, captions, a footnote below a
table as its context line, prose split at headings; and text python-docx does not give (a content control, a table in a
cell, a text box, a tracked insertion, footnotes) named, the document partly read, never dropped in silence (G2)."""

from __future__ import annotations

import io
import struct
import zipfile
import zlib

import docx
import pytest
from docx.oxml.parser import parse_xml

from modeler_intake import synthetic
from modeler_intake.anchors import anchor_text, parse_locator, same_place
from modeler_intake.source import paragraphs, parse_document, region_grid, resolve
from modeler_intake.source_model import has_number

pytestmark = pytest.mark.req("T-47")


@pytest.fixture(scope="module")
def report():
    file = synthetic.word_report()
    return file, parse_document(file.data, file.name)


def test_a_table_is_a_grid_with_a_merged_header_once_and_its_spans(report):
    file, doc = report
    assert doc.state == "read" and doc.parser == "docx" and doc.parser_version.startswith("1.0+python-docx")
    (table,) = [item.table for item in doc.body if item.kind == "table"]
    assert (table.index, table.n_rows, table.n_cols, table.engine, table.box) == (1, 8, 3, "python-docx", None)
    spans = {(c.row, c.column): (c.text, c.row_span, c.col_span) for c in table.cells}
    assert spans[(1, 1)] == ("Time (h)", 2, 1) and (2, 1) not in spans                      # merged down, held once
    assert spans[(1, 2)] == ("Exampleamide plasma concentration (ng/mL)", 1, 2) and (1, 3) not in spans   # merged across
    assert spans[(2, 2)] == ("Mean\n(arithmetic)", 1, 1)                                      # a line break stays in the cell
    (truth_table,) = file.tables
    truth = synthetic.truth_grid(file, truth_table.id)
    (region,) = [r for r in doc.regions if r.kind == "table"]
    assert (region.id, region.where) == (truth.region_id, "d:t:1")
    grid = region_grid(doc, region.id)
    assert {p: (c.text, c.type, c.value, c.locator, c.merged_from) for p, c in grid.cells.items()} == \
        {p: (c.text, c.type, c.value, c.locator, c.merged_from) for p, c in truth.cells.items()}
    assert grid.cell(1, 3).merged_from == "d:t:1/r:1/c:2" and grid.cell(2, 1).merged_from == "d:t:1/r:1/c:1"
    assert region.numeric_cells == sum(1 for row in truth_table.rows for text in row if has_number(text))


def test_the_caption_is_the_paragraph_above_and_every_truth_value_is_located(report):
    file, doc = report
    (region,) = [r for r in doc.regions if r.kind == "table"]
    assert region.caption == file.tables[0].caption[0] and region.caption_locator == "d:p:4/ch:0-80"
    grid = region_grid(doc, region.id)
    places = [*grid.cells.values(), *grid.caption]
    for value in (v for v in file.values if v.table):
        for role, locator in (("value", value.locator), *value.locators):
            assert any(same_place(parse_locator(c.locator), parse_locator(locator)) for c in places), (value.field, role)


def test_paragraphs_are_kept_in_order_and_form_prose_under_their_heading(report):
    file, doc = report
    document = docx.Document(io.BytesIO(file.data))
    kept = [(item.paragraph.index, item.paragraph.text, item.paragraph.style) for item in doc.body if item.kind == "paragraph"]
    assert kept == [(k, p.text, p.style.name) for k, p in enumerate(document.paragraphs, start=1)]
    assert [item.kind for item in doc.body] == ["paragraph"] * 4 + ["table", "paragraph"]
    (prose,) = [r for r in doc.regions if r.kind == "prose"]
    assert prose.where == "d:p:1-3"
    found = paragraphs(doc, prose.id)
    assert [p.text for p in found] == list(file.prose)
    assert [p.heading for p in found] == ["", "Study design", "Study design"]
    assert found[1].heading_locator == "d:p:1/ch:0-12" and found[1].locator == "d:p:2-2"
    for value in (v for v in file.values if v.table == ""):
        span = parse_locator(value.locator)
        holder = next(p for p in found if p.index == span.paragraph)
        assert holder.text[span.start:span.end] == value.value


def test_the_image_is_listed_as_a_figure(report):
    _file, doc = report
    (figure,) = doc.figures
    assert (figure.index, figure.page, figure.box, figure.name, figure.width, figure.height) == (1, None, None, "Picture 1", 16, 16)
    (region,) = [r for r in doc.regions if r.kind == "figure"]
    assert region.where == "d:f:1"


def test_a_footnote_below_a_table_is_its_context_line_and_a_heading_starts_new_prose():
    document = docx.Document()
    document.add_heading("Pharmacokinetics", level=1)
    document.add_paragraph("Plasma was sampled for 24 hours.")
    document.add_paragraph("Table 3. Exampleamide concentrations (ng/mL)")
    table = document.add_table(rows=3, cols=2)
    for r, row in enumerate((("Time (h)", "Mean"), ("1", "10.5"), ("2", "8.25"))):
        for c, text in enumerate(row):
            table.cell(r, c).text = text
    document.add_paragraph("LLOQ = 0.5 ng/mL")
    document.add_heading("Safety", level=1)
    document.add_paragraph("No serious adverse event in 24 subjects.")
    buffer = io.BytesIO()
    document.save(buffer)
    doc = parse_document(buffer.getvalue(), "pk.docx")
    assert [(r.kind, r.where) for r in doc.regions] == [("prose", "d:p:1-2"), ("table", "d:t:1"), ("prose", "d:p:5-6")]
    table_region = doc.regions[1]
    assert table_region.caption == "Table 3. Exampleamide concentrations (ng/mL)"
    grid = region_grid(doc, table_region.id)
    assert [[c.text for c in line] for line in grid.below] == [["LLOQ = 0.5 ng/mL"]] and grid.above == ()
    assert [(o.where, o.numeric, o.region) for o in doc.outside] == [("d:p:4/ch:0-16", True, table_region.id)]
    assert paragraphs(doc, doc.regions[2].id)[1].heading == "Safety"


def test_a_damaged_word_file_is_unreadable_with_its_reason():
    data = synthetic.word_report().data
    for broken in (data[:400], b"PK\x03\x04 nothing", b"not a zip at all"):
        doc = parse_document(broken, "broken.docx")
        assert doc.state == "unreadable" and doc.reason.startswith("the docx file could not be read")


_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
       'xmlns:v="urn:schemas-microsoft-com:vml" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def _png() -> bytes:
    """A small gray PNG, written by hand."""
    raw = b"".join(b"\x00" + bytes((x * 9 + y * 5) % 256 for x in range(8)) for y in range(8))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _saved(document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _text_box(text: str) -> str:
    """A run holding a floating text box as Word writes it: the drawing, and its VML copy as the fallback."""
    box = f"<w:txbxContent><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:txbxContent>"
    return (f"<w:r {_NS}><mc:AlternateContent><mc:Choice Requires=\"wps\"><w:drawing><wp:anchor><wp:docPr id=\"9\" "
            f"name=\"Text Box 9\"/><a:graphic><a:graphicData uri=\"http://schemas.microsoft.com/office/word/2010/"
            f"wordprocessingShape\"><wps:wsp><wps:txbx>{box}</wps:txbx></wps:wsp></a:graphicData></a:graphic>"
            f"</wp:anchor></w:drawing></mc:Choice><mc:Fallback><w:pict><v:shape><v:textbox>{box}</v:textbox></v:shape>"
            f"</w:pict></mc:Fallback></mc:AlternateContent></w:r>")


def test_inline_runs_python_docx_leaves_out_are_read_in_their_paragraph():
    document = docx.Document()
    dose = document.add_paragraph("Dose ")
    dose._p.append(parse_xml(f'<w:ins {_NS} w:id="1" w:author="reviewer"><w:r><w:t>50 mg</w:t></w:r></w:ins>'))
    dose._p.append(parse_xml(f'<w:del {_NS} w:id="2" w:author="reviewer"><w:r><w:delText> 40 mg</w:delText></w:r></w:del>'))
    dose._p.append(parse_xml(f"<w:sdt {_NS}><w:sdtContent><w:r><w:t>, study EXA-101</w:t></w:r></w:sdtContent></w:sdt>"))
    caption = document.add_paragraph("Table ")
    caption._p.append(parse_xml(f'<w:fldSimple {_NS} w:instr=" SEQ Table "><w:r><w:t>4</w:t></w:r></w:fldSimple>'))
    caption.add_run(". Exampleamide plasma concentrations")
    doc = parse_document(_saved(document), "inline.docx")
    assert (doc.state, doc.warnings) == ("read", ())
    texts = [item.paragraph.text for item in doc.body if item.kind == "paragraph"]
    assert texts == ["Dose 50 mg, study EXA-101", "Table 4. Exampleamide plasma concentrations"]
    assert [p.text for p in docx.Document(io.BytesIO(_saved(document))).paragraphs] == \
        ["Dose ", "Table . Exampleamide plasma concentrations"]                 # what python-docx alone would give
    found = resolve(doc, anchor_text(doc.file_sha256, doc.parser, doc.parser_version, "d:p:1/ch:5-10"))
    assert found.text == "50 mg"


def test_text_the_reading_does_not_give_is_named_and_the_document_is_partly_read():
    document = docx.Document()
    document.add_heading("Pharmacokinetics", level=1)
    document.add_paragraph("Dose 50 mg")
    boxed = document.add_paragraph("Plasma was sampled for 24 hours.")
    boxed._p.append(parse_xml(_text_box("Cmax 12.5 ng/mL")))
    document.add_paragraph("Table 1. Exampleamide concentrations (ng/mL)")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Time (h)", "Conc"
    table.cell(1, 1).text = "9.9"
    inner = table.cell(1, 0).add_table(rows=1, cols=2)
    inner.cell(0, 0).text, inner.cell(0, 1).text = "1", "12.5"
    control = parse_xml(f"<w:sdt {_NS}><w:sdtContent><w:p><w:r><w:t>Protocol EXA-101</w:t></w:r></w:p></w:sdtContent></w:sdt>")
    document.element.body.insert(0, control)
    doc = parse_document(_saved(document), "controls.docx")
    unread = ["before d:p:1: a content control in the body", "d:p:3: a text box", "d:t:1: a table inside a cell"]
    assert doc.state == "partly_read" and doc.reason == "text not read: " + "; ".join(unread)
    assert doc.warnings == tuple(f"DOCX_TEXT_NOT_READ {place}" for place in unread)
    texts = [item.paragraph.text for item in doc.body if item.kind == "paragraph"]
    assert texts == [p.text for p in docx.Document(io.BytesIO(_saved(document))).paragraphs]   # numbered as python-docx
    assert texts[2] == "Plasma was sampled for 24 hours."                       # the text box is not in its paragraph
    assert [(r.kind, r.where) for r in doc.regions] == [("prose", "d:p:1-3"), ("table", "d:t:1")]   # the rest is read
    assert doc.figures == ()                                              # a text box is no figure, its copy neither
    grid = region_grid(doc, doc.regions[1].id)
    assert grid.cell(2, 2).text == "9.9" and (2, 1) not in grid.cells     # the cell holding the inner table: no text
    many = docx.Document()
    for k in range(7):
        many.element.body.append(parse_xml(f"<w:sdt {_NS}><w:sdtContent><w:p><w:r><w:t>Field {k}</w:t></w:r></w:p>"
                                           "</w:sdtContent></w:sdt>"))
    crowded = parse_document(_saved(many), "crowded.docx")
    assert crowded.reason.endswith("; and 2 more (see the warnings)") and len(crowded.warnings) == 7


def test_a_picture_in_a_content_control_or_with_a_fallback_copy_is_one_figure():
    document = docx.Document()
    document.add_paragraph("Figure 1. Mean Exampleamide plasma concentrations")
    document.add_picture(io.BytesIO(_png()))
    wrapped = document.paragraphs[-1]._p
    control = parse_xml(f"<w:sdt {_NS}><w:sdtContent/></w:sdt>")
    wrapped.addprevious(control)
    control[0].append(wrapped)                                            # the picture inside a content control
    document.add_picture(io.BytesIO(_png()))
    run = document.paragraphs[-1].runs[0]._r
    drawing = run[-1]
    rid = drawing.xpath(".//a:blip/@r:embed")[0]
    alternate = parse_xml(f'<mc:AlternateContent {_NS}><mc:Choice Requires="wps"/><mc:Fallback><w:pict><v:shape>'
                          f'<v:imagedata r:id="{rid}"/></v:shape></w:pict></mc:Fallback></mc:AlternateContent>')
    run.remove(drawing)
    alternate[0].append(drawing)
    run.append(alternate)                                                 # the drawing, and its VML copy as fallback
    doc = parse_document(_saved(document), "pictures.docx")
    assert doc.state == "read" and doc.warnings == ()
    assert [(f.index, f.width, f.height) for f in doc.figures] == [(1, 8, 8), (2, 8, 8)]
    assert [r.where for r in doc.regions if r.kind == "figure"] == ["d:f:1", "d:f:2"]


_FOOTNOTES = ('<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
              '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p>'
              '</w:footnote>{note}</w:footnotes>')


def _with_footnotes(data: bytes, note: str) -> bytes:
    """The Word file with a footnotes part (its separators, and `note`)."""
    source, out = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            body = source.read(info.filename)
            if info.filename == "[Content_Types].xml":
                body = body.replace(b"</Types>", b'<Override PartName="/word/footnotes.xml" ContentType="application/'
                                    b'vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>')
            elif info.filename == "word/_rels/document.xml.rels":
                body = body.replace(b"</Relationships>", b'<Relationship Id="rIdNotes" Type="http://schemas.openxml'
                                    b'formats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>'
                                    b"</Relationships>")
            target.writestr(info, body)
        target.writestr("word/footnotes.xml", _FOOTNOTES.format(note=note))
    return out.getvalue()


def test_footnotes_with_text_are_named_and_separators_alone_are_not():
    data = synthetic.word_report().data
    note = '<w:footnote w:id="1"><w:p><w:r><w:t>LLOQ 0.5 ng/mL</w:t></w:r></w:p></w:footnote>'
    doc = parse_document(_with_footnotes(data, note), "noted.docx")
    assert doc.state == "partly_read" and doc.reason == "text not read: footnotes: the document's footnotes hold text"
    assert len([r for r in doc.regions if r.kind == "table"]) == 1                 # the body is read as before
    plain = parse_document(_with_footnotes(data, ""), "separators.docx")
    assert plain.state == "read" and plain.warnings == ()


def _docx(build) -> bytes:
    document = docx.Document()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _three_rows(document) -> None:
    table = document.add_table(rows=3, cols=2)
    for r, row in enumerate((("Time (h)", "Conc"), ("1", "2.5"), ("2", "3.5"))):
        for c, text in enumerate(row):
            table.cell(r, c).text = text


def test_a_prose_sentence_directly_above_a_table_is_no_caption_and_stays_prose():
    sentence = ("Eighteen subjects received 20 mg of Exampleamide fasted; the mean Cmax was 17.9 ng/mL at 2 h and the "
                "terminal half-life was 4.1 h (see below).")

    def build(document) -> None:
        document.add_heading("Results", level=1)
        document.add_paragraph(sentence)
        _three_rows(document)

    doc = parse_document(_docx(build), "sentence above.docx")
    prose, table = doc.regions
    assert (prose.kind, prose.where, table.kind, table.caption, table.caption_locator) == ("prose", "d:p:1-2", "table", "", None)
    assert [p.text for p in paragraphs(doc, prose.id)] == ["Results", sentence]


def test_an_arm_and_dose_line_above_the_caption_is_the_tables_context_above():
    def build(document) -> None:
        document.add_heading("Part A", level=1)
        document.add_paragraph("Part A: 50 mg, fasted")
        document.add_paragraph("Table 2. Exampleamide plasma concentrations (ng/mL)")
        _three_rows(document)
        document.add_paragraph("LLOQ 0.5 ng/mL")

    doc = parse_document(_docx(build), "context above.docx")
    (table,) = [r for r in doc.regions if r.kind == "table"]
    grid = region_grid(doc, table.id)
    assert [[(c.text, c.locator) for c in line] for line in grid.above] == [[("Part A: 50 mg, fasted", "d:p:2/ch:0-21")]]
    assert [[c.text for c in line] for line in grid.below] == [["LLOQ 0.5 ng/mL"]]
    assert [(o.where, o.numeric, o.region) for o in doc.outside] == [("d:p:2/ch:0-21", True, table.id),
                                                                     ("d:p:4/ch:0-14", True, table.id)]


def test_a_page_header_and_footer_with_text_are_named_with_their_text_and_a_logo_there_is_no_figure():
    def build(document) -> None:
        header = document.sections[0].header.paragraphs[0]
        header.text = "Exampleamide Study 230-23 Report, Version 2.0"
        header.add_run().add_picture(io.BytesIO(_png()))
        document.sections[0].footer.paragraphs[0].text = "Confidential"
        document.add_paragraph("Results are below.")
        _three_rows(document)

    doc = parse_document(_docx(build), "with header.docx")
    assert doc.state == "read" and doc.figures == ()                      # furniture: listed, not counted
    assert doc.warnings == (
        "DOCX_FURNITURE footer1: the page footer holds text, not read as data: Confidential",
        "DOCX_FURNITURE header1: the page header holds text, not read as data: Exampleamide Study 230-23 Report, Version 2.0")


def test_a_comment_with_text_is_named_and_the_document_is_partly_read():
    def build(document) -> None:
        paragraph = document.add_paragraph("Cmax was 17.9 ng/mL.")
        document.add_comment(paragraph.runs, text="Corrected from 19.7 after the QC audit", author="QA")

    doc = parse_document(_docx(build), "commented.docx")
    assert doc.state == "partly_read" and doc.reason == "text not read: comments: the document's comments hold text"
    assert doc.warnings == ("DOCX_TEXT_NOT_READ comments: the document's comments hold text",)
