"""What cannot be read says so (contracts §6.1, G2): a format with no parser, an image, an empty file and a file over
the size limit each get a state and a reason, never an exception; and the same bytes always give the same document
(`anchors.sha256_of`, the L2 function: this test imports nothing of `modeler_project`)."""

from __future__ import annotations

import random
import struct
import zlib

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import sha256_of
from modeler_intake.documents import MAX_BYTES
from modeler_intake.source import parse, parse_document, parser_for

pytestmark = pytest.mark.req("T-47")

OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@pytest.mark.parametrize(("name", "data"), [
    ("protocol.doc", OLE2 + b"\x00" * 64),
    ("slides.pptx", b"PK\x03\x04" + b"\x00" * 64),
    ("adpc.xpt", b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!"),
    ("study.sas7bdat", b"\x00" * 64),
    ("mail.msg", OLE2 + b"\x01" * 32),
    ("page.html", b"<html><body><table><tr><td>12.5</td></tr></table></body></html>"),
    ("data.xml", b"<?xml version='1.0'?><a>1</a>"),
    ("no-extension", b"Study 230-23"),
])
def test_a_format_with_no_parser_is_unsupported_with_its_reason(name, data):
    doc = parse_document(data, name)
    suffix = name[name.rindex("."):] if "." in name else None
    assert (doc.state, doc.parser, doc.format) == ("unsupported", "none", "other")
    assert doc.reason == (f"no parser for {suffix}" if suffix else "no parser for a file with no extension")
    assert doc.regions == () and parser_for(data, name) == ("none", "1.0")


def _png(width: int = 16, height: int = 16) -> bytes:
    """A small gray PNG, written by hand."""
    raw = b"".join(b"\x00" + bytes((x * 9 + y * 5) % 256 for x in range(width)) for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# the start of a JPEG (SOI, APP0, a baseline frame header of 30 x 20 pixels): enough to name its size
JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x11\x08\x00\x14\x00\x1e\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xd9")


def test_an_image_is_one_figure_and_unsupported():
    png = _png(24, 12)
    doc = parse_document(png, "scan.png")
    assert (doc.state, doc.parser, doc.format) == ("unsupported", "image", "image")
    assert doc.reason == "an image has no text layer; no OCR engine is registered"
    (figure,) = doc.figures
    assert (figure.index, figure.name, figure.width, figure.height) == (1, "scan.png", 24, 12)
    assert [(r.kind, r.where) for r in doc.regions] == [("figure", "d:f:1")]
    photo = parse_document(JPEG, "photo.jpg")
    assert photo.state == "unsupported" and (photo.figures[0].width, photo.figures[0].height) == (30, 20)


def test_an_empty_file_and_a_file_over_the_limit_are_unreadable(monkeypatch):
    for name in ("empty.csv", "empty.pdf", "empty.xlsx", "empty.docx", "empty.txt", "empty.zip"):
        doc = parse_document(b"", name)
        assert (doc.state, doc.reason, doc.size_bytes) == ("unreadable", "the file is empty (0 bytes)", 0), name
    assert parse.MAX_MEMBER_BYTES == MAX_BYTES                           # one file's limit: documents.MAX_BYTES (250 MB)
    monkeypatch.setattr(parse, "MAX_MEMBER_BYTES", 1000)
    file = synthetic.messy_workbook()
    doc = parse_document(file.data, file.name)
    assert doc.state == "unreadable" and doc.reason == f"the file holds {len(file.data)} bytes, over the limit of 1000"
    assert doc.sheets == () and doc.size_bytes == len(file.data)


def test_parsing_the_same_bytes_twice_gives_equal_documents():
    files = (*synthetic.delivery(), synthetic.pdf_report(), synthetic.scanned_pdf(), synthetic.template_workbook(),
             synthetic.delimited(sep="\t", decimal_comma=False, encoding="utf-16"),
             synthetic.zipped(synthetic.delimited(), synthetic.word_report()))
    for file in files:
        first, second = parse_document(file.data, file.name), parse_document(file.data, file.name)
        assert first == second and sha256_of(first) == sha256_of(second), file.name
    for name, data in (("x.doc", OLE2), ("x.png", _png()), ("x.csv", b"")):
        assert sha256_of(parse_document(data, name)) == sha256_of(parse_document(data, name))


def test_damaged_bytes_of_every_format_give_a_state_and_a_reason_never_an_exception():
    rng = random.Random(2026)
    files = (synthetic.messy_workbook(), synthetic.pdf_report(), synthetic.word_report(), synthetic.delimited(),
             synthetic.zipped(synthetic.delimited()))
    names = ("x.xlsx", "x.xls", "x.csv", "x.tsv", "x.docx", "x.pdf", "x.txt", "x.md", "x.json", "x.zip", "x.png")
    for file in files:
        for trial in range(12):
            data = bytearray(file.data)
            if trial % 3 == 0:
                data = data[:rng.randrange(1, len(data))]
            elif trial % 3 == 1:
                for _ in range(30):
                    data[rng.randrange(len(data))] = rng.randrange(256)
            else:
                data = bytearray(rng.randrange(256) for _ in range(rng.randrange(1, 300)))
            for name in (file.name, rng.choice(names)):
                doc = parse_document(bytes(data), name)
                assert doc.state in ("read", "partly_read", "unsupported", "unreadable")
                assert doc.state == "read" or doc.reason, (file.name, name, trial)


def test_a_password_protected_office_file_is_unreadable_and_named():
    locked = OLE2 + b"\x00" * 56 + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 64    # the stream it holds
    for name in ("locked.xlsx", "locked.xlsm", "locked.xls", "locked.docx"):
        doc = parse_document(locked, name)
        assert doc.state == "unreadable", name
        assert doc.reason == "the file is encrypted (a password-protected Office file): a password is needed", name
    assert parse_document(OLE2 + b"\x00" * 64, "plain.xls").reason.startswith("the xls file could not be read")
