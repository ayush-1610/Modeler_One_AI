"""Text, Markdown and JSON files (contracts §6.1 "lines as paragraphs"): each line a paragraph with its `x:l` locator,
prose split at Markdown headings, a table written as text (a pipe table) located as `table_like_text`, the encoding
found as for a delimited file, and text anchors resolved, viewed and checked again."""

from __future__ import annotations

import pytest

from modeler_intake.anchors import AnchorError, anchor_text
from modeler_intake.source import check_anchors, paragraphs, parse_document, resolve, source_view

pytestmark = pytest.mark.req("T-47")

NOTES = ("# Results  \n"
         "Study 230-23: Cmax was 12.5 ng/mL after 50 mg.\n"
         "\n"
         "| Time (h) | Conc (ng/mL) |\n"
         "|---|---|\n"
         "| 1 | 2.5 |\n"
         "| 2 | 3.5 |\n"
         "\n"
         "## Safety\n"
         "No serious adverse event.\n")


@pytest.fixture(scope="module")
def notes():
    return parse_document(NOTES.encode("utf-8"), "notes.md")


def _anchor(doc, locator: str, version: str | None = None) -> str:
    return anchor_text(doc.file_sha256, doc.parser, version or doc.parser_version, locator)


def test_each_line_is_a_paragraph_and_headings_split_the_prose(notes):
    doc = notes
    assert (doc.state, doc.format, doc.parser, doc.encoding) == ("read", "markdown", "text", "utf-8")
    assert doc.parser_version.startswith("1.0+python3.")
    assert [(item.paragraph.index, item.paragraph.text) for item in doc.body] == \
        list(enumerate(NOTES.split("\n")[:-1], start=1))
    assert [item.paragraph.style for item in doc.body if item.paragraph.style] == ["markdown-heading"] * 2
    assert [(r.kind, r.where, r.n_rows, r.numeric_cells) for r in doc.regions] == [
        ("prose", "x:l:1-2", 2, 3), ("table_like_text", "x:l:4-7", 4, 4), ("prose", "x:l:9-10", 2, 0)]
    first = paragraphs(doc, doc.regions[0].id)
    assert [(p.index, p.locator, p.heading, p.heading_locator) for p in first] == [
        (1, "x:l:1-1", "", None), (2, "x:l:2-2", "# Results  ", "x:l:1/ch:0-11")]    # the heading as written
    heading = resolve(doc, _anchor(doc, first[1].heading_locator))
    assert heading.text == first[1].heading and heading.region_id == doc.regions[0].id
    with pytest.raises(ValueError):
        paragraphs(doc, doc.regions[1].id)                                          # an unruled table is not prose
    with pytest.raises(KeyError):
        paragraphs(doc, "rg-0000000000")


def test_a_text_span_resolves_shows_its_line_and_is_found_again(notes):
    doc = notes
    line = NOTES.split("\n")[1]
    start = line.index("12.5")
    locator = f"x:l:2/ch:{start}-{start + 4}"
    found = resolve(doc, _anchor(doc, locator))
    assert (found.text, found.locator, found.region_id, found.page, found.box) == ("12.5", locator, doc.regions[0].id,
                                                                                   None, None)
    view = source_view(doc, _anchor(doc, locator))
    assert (view.kind, view.text, view.span, view.title) == ("text", line, (start, start + 4), "Line 2")
    problems = check_anchors(doc, [("same", _anchor(doc, locator, "0.9+old"), "12.5"),
                                   ("changed", _anchor(doc, "x:l:2/ch:0-5", "0.9+old"), "Trial"),
                                   ("gone", _anchor(doc, "x:l:40/ch:0-5", "0.9+old"), "Study")])
    assert [(p.id, p.problem, p.found) for p in problems] == [("changed", "text_differs", "Study"), ("gone", "not_found", "")]
    for bad in ("x:l:2/ch:0-999", "x:l:99/ch:0-1"):
        with pytest.raises(AnchorError):
            resolve(doc, _anchor(doc, bad))


def test_text_files_are_read_in_their_encoding_and_binary_content_is_unreadable():
    latin = parse_document("Café: 12 µg/mL\r\nsecond line\r\n".encode("cp1252"), "latin.txt")
    assert (latin.state, latin.encoding, latin.format) == ("read", "cp1252", "text")
    assert latin.warnings == ("ENCODING_GUESSED: not UTF-8; read as cp1252 (Windows Western European)",)
    assert [item.paragraph.text for item in latin.body] == ["Café: 12 µg/mL", "second line"]
    wide = parse_document("Exampleamide 50 mg\n".encode("utf-16"), "wide.txt")
    assert (wide.encoding, wide.body[0].paragraph.text) == ("utf-16", "Exampleamide 50 mg")
    data = parse_document(b'{"study": "230-23",\n "dose_mg": 50}\n', "facts.json")
    assert (data.state, data.format, [r.kind for r in data.regions]) == ("read", "json", ["table_like_text"])
    #                                   half its tokens hold a number: a table written as text, located, never gridded
    binary = parse_document(b"Study\x00\x01\x02", "notes.txt")
    assert binary.state == "unreadable" and binary.reason == "binary content (NUL bytes) in a text file"
