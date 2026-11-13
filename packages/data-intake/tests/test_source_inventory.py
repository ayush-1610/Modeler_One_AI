"""The format inventory (plan §10 decision 5; contracts §6.1): counts by extension, native against scanned PDFs,
documents with figures, unsupported formats, ZIP members."""

from __future__ import annotations

import struct
import zlib

import pytest

from modeler_intake import synthetic
from modeler_intake.source import FormatInventory, inventory

pytestmark = pytest.mark.req("T-47")


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


def _png(width: int = 16, height: int = 16) -> bytes:
    """A small gray PNG, written by hand."""
    raw = b"".join(b"\x00" + bytes((x * 9 + y * 5) % 256 for x in range(width)) for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def test_the_inventory_counts_formats_scans_figures_and_what_no_parser_reads():
    files = [(f.name, f.data) for f in synthetic.delivery()]
    files += [("scanned.pdf", synthetic.scanned_pdf().data), ("scan-only.pdf", _image_pdf()), ("photo.PNG", _png()),
              ("protocol.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16), ("README", b"notes"),
              ("batch.zip", synthetic.zipped(synthetic.delimited(), synthetic.word_report()).data),
              ("locked.zip", b"not a zip")]
    found = inventory(files)
    assert found == FormatInventory(
        files=11,
        by_extension={"(none)": 1, ".csv": 2, ".doc": 1, ".docx": 2, ".pdf": 3, ".png": 1, ".xlsx": 1, ".zip": 2},
        pdf_native=1, pdf_scanned=1, pdf_mixed=1,          # the report; a scan only; a text page then a scanned page
        with_figures=2,                                    # the Word report and its copy in the ZIP; a scan is no figure
        unsupported={"(none)": 1, ".doc": 1, ".png": 1, ".zip": 1}, zip_members=2)


def test_an_empty_inventory_counts_nothing():
    assert inventory([]) == FormatInventory(files=0, by_extension={}, pdf_native=0, pdf_scanned=0, pdf_mixed=0,
                                            with_figures=0, unsupported={}, zip_members=0)


def _logo_pdf(pages: int = 2) -> bytes:
    """A PDF whose pages each hold a line of text and the same small logo at the same place, written by hand."""
    pixels = bytes((x * 7 + y * 3) % 256 for y in range(8) for x in range(8))
    kids = " ".join(f"{4 + 2 * k} 0 R" for k in range(pages)).encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, pages),
               b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray /BitsPerComponent 8 "
               b"/Length 64 >> stream\n" + pixels + b"\nendstream"]
    font = 4 + 2 * pages
    for k in range(pages):
        content = b"q 40 0 0 20 500 750 cm /Im1 Do Q BT /F1 10 Tf 56 700 Td (Exampleamide clinical study report, page %d) Tj ET" % (k + 1)
        objects += [b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im1 3 0 R >> "
                    b"/Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (font, 5 + 2 * k),
                    b"<< /Length %d >> stream\n" % len(content) + content + b"\nendstream"]
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    body, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj " % number + obj + b" endobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return body + b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


def _header_logo_docx() -> bytes:
    import io

    import docx

    document = docx.Document()
    header = document.sections[0].header.paragraphs[0]
    header.text = "Exampleamide Study 230-23 Report, Version 2.0"
    header.add_run().add_picture(io.BytesIO(_png()))
    document.add_paragraph("No figure in the body.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_a_logo_in_a_page_header_or_repeated_on_every_page_is_no_figure_as_parse_document_decides():
    from modeler_intake.source import parse_document

    files = [("logo.pdf", _logo_pdf()), ("header logo.docx", _header_logo_docx())]
    for name, data in files:
        doc = parse_document(data, name)
        assert not [r for r in doc.regions if r.kind == "figure"], name           # furniture, not a figure
    found = inventory(files)
    assert (found.pdf_native, found.with_figures) == (1, 0)
