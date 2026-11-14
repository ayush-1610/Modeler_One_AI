"""Anchors read back (contracts §6.1, G3): every truth value's anchor resolves to its text (PDF places compared by
identity, never by box), a wrong file, version or place is an AnchorError, `check_anchors` finds every value again
after a parser version bump and reports a moved or changed one, and `source_view` shows the value with the cells it
is read with."""

from __future__ import annotations

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import AnchorError, PdfCell, PdfSpan, anchor_text, format_locator, parse_locator, same_place
from modeler_intake.source import check_anchors, parse_document, region_grid, resolve, source_view

pytestmark = pytest.mark.req("T-47")

OLD = "0.9+old"


def _files():
    return (*synthetic.delivery(), synthetic.pdf_report(), synthetic.template_workbook(),
            synthetic.delimited(sep="\t", decimal_comma=False, encoding="utf-16"))


def _anchor(doc, locator: str, version: str | None = None) -> str:
    return anchor_text(doc.file_sha256, doc.parser, version or doc.parser_version, locator)


def _cell_text(file, value) -> str | None:
    """The truth's own text of a value's cell, when the cell is one of its table's rows."""
    from modeler_intake.source.regions import a1_place, parse_sheet_range

    (table,) = [t for t in file.tables if t.id == value.table]
    place = parse_locator(value.locator)
    if place.kind == "sheet_cell":
        _sheet, r0, c0, r1, c1 = parse_sheet_range(table.where)
        row, column = a1_place(place.cell)
        return table.rows[row - r0][column - c0] if r0 <= row <= r1 and c0 <= column <= c1 else None
    if place.kind == "docx_cell":
        return table.rows[place.row - 1][place.column - 1]
    if place.kind == "pdf_cell":
        grid = synthetic.truth_grid(file, table.id)
        return next(c.text for c in grid.cells.values() if same_place(parse_locator(c.locator), place))
    return None


def test_every_truth_values_anchor_resolves_to_its_text_and_region():
    boxes_differ = 0
    for file in _files():
        doc = parse_document(file.data, file.name)
        prose = {r.id for r in doc.regions if r.kind == "prose"}
        for value in file.values:
            found = resolve(doc, _anchor(doc, value.locator))
            assert same_place(parse_locator(found.locator), parse_locator(value.locator)), (file.name, value.locator)
            boxes_differ += found.locator != value.locator
            if value.table == "":
                assert found.text == value.value and found.region_id in prose, (file.name, value.field)
                continue
            own = _cell_text(file, value)
            assert found.text == own if own is not None else value.value in found.text, (file.name, value.locator)
            assert found.region_id == synthetic.truth_grid(file, value.table).region_id, (file.name, value.locator)
            for _role, locator in value.locators:                   # every cell a value is read with resolves too
                assert resolve(doc, _anchor(doc, locator)).region_id is not None, (file.name, locator)
            if found.page is not None:
                page = doc.pages[found.page - 1]
                assert 0 <= found.box[0] <= found.box[2] <= page.width and 0 <= found.box[1] <= found.box[3] <= page.height
    assert boxes_differ > 0          # pdfplumber's word boxes are not the truth's estimates: identity decided, not the box


def test_a_wrong_file_version_or_place_is_an_anchor_error():
    file = synthetic.messy_workbook()
    doc = parse_document(file.data, file.name)
    good = _anchor(doc, "s:'Fasting'!B4")
    assert resolve(doc, good).text == "BLQ"
    for bad in (anchor_text("f" * 64, doc.parser, doc.parser_version, "s:'Fasting'!B4"),      # another file
                _anchor(doc, "s:'Fasting'!B4", OLD),                                          # another version
                _anchor(doc, "s:'Fasting'!Z99"),                                              # no such cell
                _anchor(doc, "s:'Nowhere'!A1"),                                               # no such sheet
                good.replace("#s:", "#S:"),                                                   # not the grammar
                "not an anchor"):
        with pytest.raises(AnchorError):
            resolve(doc, bad)
    pdf = parse_document(synthetic.pdf_report().data, "study-report.pdf")
    for locator in ("p:9/t:1/r:1/c:1@0.00,0.00,1.00,1.00", "p:2/t:3/r:1/c:1@0.00,0.00,1.00,1.00",
                    "p:2/t:1/r:99/c:1@0.00,0.00,1.00,1.00", "p:1/w:900-901@0.00,0.00,1.00,1.00"):
        with pytest.raises(AnchorError):
            resolve(pdf, _anchor(pdf, locator))
    word = parse_document(synthetic.word_report().data, "design-report.docx")
    for locator in ("d:t:2/r:1/c:1", "d:t:1/r:9/c:1", "d:p:2/ch:0-999", "d:p:99/ch:0-1", "d:f:2"):
        with pytest.raises(AnchorError):
            resolve(word, _anchor(word, locator))


def test_check_anchors_across_a_version_bump_finds_every_value_again():
    for file in _files():
        doc = parse_document(file.data, file.name)
        items = []
        for k, value in enumerate(file.values):
            found = resolve(doc, _anchor(doc, value.locator))
            items.append((f"tx-{k:016x}#0", _anchor(doc, found.locator, OLD), found.text))
        assert check_anchors(doc, items) == [], file.name


def test_check_anchors_finds_a_pdf_place_by_text_and_box_and_reports_a_moved_or_changed_one():
    file = synthetic.pdf_report()
    doc = parse_document(file.data, file.name)
    cell = resolve(doc, _anchor(doc, "p:2/t:1/r:3/c:3@0.00,0.00,1.00,1.00"))                # 18.2, Table 5
    x0, top, x1, bottom = cell.box
    renumbered = format_locator(PdfCell(page=2, table=2, row=7, column=1, box=(x0 + 1, top + 1, x1 + 1, bottom + 1)))
    moved = format_locator(PdfCell(page=2, table=1, row=3, column=3, box=(x0, top + 300, x1, bottom + 300)))
    word = resolve(doc, _anchor(doc, "p:1/w:24-24@0.00,0.00,1.00,1.00"))                  # "50" of the synopsis
    nudged = format_locator(PdfSpan(page=1, first_word=30, last_word=30, box=tuple(v + 0.5 for v in word.box)))
    gone = format_locator(PdfSpan(page=1, first_word=24, last_word=24, box=(500.0, 500.0, 510.0, 510.0)))
    items = [("a", _anchor(doc, renumbered, OLD), "18.2"),           # another table numbering, the same box: found
             ("b", _anchor(doc, nudged, OLD), "50"),                 # another word number, the same box: found
             ("c", _anchor(doc, cell.locator, OLD), "18.5"),         # changed: the text differs
             ("d", _anchor(doc, moved, OLD), "18.2"),                # moved: nothing there
             ("e", _anchor(doc, gone, OLD), "50"),
             ("f", anchor_text("e" * 64, "pdfplumber", OLD, cell.locator), "18.2")]          # another file
    problems = check_anchors(doc, items)
    assert [(p.id, p.problem, p.found) for p in problems] == [("c", "text_differs", "18.2"), ("d", "not_found", ""),
                                                              ("e", "not_found", ""), ("f", "not_found", "")]


def test_check_anchors_finds_a_sheet_or_word_place_by_its_locator():
    file = synthetic.messy_workbook()
    doc = parse_document(file.data, file.name)
    problems = check_anchors(doc, [("same", _anchor(doc, "s:'Fasting'!C11", OLD), "12.4037"),
                                   ("changed", _anchor(doc, "s:'Fasting'!C11", OLD), "12.40"),
                                   ("gone", _anchor(doc, "s:'Fasting'!Q40", OLD), "1.0"),
                                   ("garbled", "nonsense", "1.0")])
    assert [(p.id, p.problem, p.found) for p in problems] == [("changed", "text_differs", "12.4037"),
                                                              ("gone", "not_found", ""), ("garbled", "not_found", "")]
    word = parse_document(synthetic.word_report().data, "design-report.docx")
    problems = check_anchors(word, [("n", _anchor(word, "d:p:2/ch:68-70", OLD), "18"),
                                    ("cell", _anchor(word, "d:t:1/r:3/c:2", OLD), "8.2")])
    assert [(p.id, p.problem, p.found) for p in problems] == [("cell", "text_differs", "8.1")]


def _view_roles(view) -> dict[tuple[int, int], tuple[str, str | None]]:
    return {(c.row, c.column): (c.text, c.role) for c in view.cells if c.highlighted}


def test_source_view_highlights_the_value_and_the_cells_it_is_read_with():
    file = synthetic.messy_workbook()
    doc = parse_document(file.data, file.name)
    value = next(v for v in file.values if v.table == "fasting-individual" and v.locator == "s:'Fasting'!B4")
    also = {role: _anchor(doc, locator) for role, locator in value.locators}
    also["foreign"] = anchor_text("e" * 64, doc.parser, doc.parser_version, "s:'Fasting'!A1")    # another file: left out
    view = source_view(doc, _anchor(doc, value.locator), also=also)
    assert (view.kind, view.title, view.n_rows, view.n_cols) == ("grid", "Study 230-23, 50 mg, fasted", 13, 7)
    assert view.region_id == synthetic.truth_grid(file, "fasting-individual").region_id
    assert _view_roles(view) == {(3, 2): ("BLQ", "value"), (2, 2): ("0", "time"), (3, 1): ("001", "subject"),
                                 (1, 2): ("Exampleamide plasma concentration (ng/mL) by time after dose (h)",
                                          "unit, analyte, matrix"),
                                 (-1, 1): ("Study 230-23, 50 mg, fasted", "study"), (14, 1): ("LLOQ = 0.5 ng/mL", "lloq")}
    assert view.page is None and view.box is None and view.text == ""
    in_region = [c for c in view.cells if 1 <= c.row <= 13]                       # every non-empty cell of the region,
    assert len(in_region) == len(region_grid(doc, view.region_id).cells)          # merged copies included
    assert ("Subject", "s:'Fasting'!A3") in {(c.text, c.locator) for c in in_region}


def test_source_view_gives_the_page_its_size_and_the_box_for_a_pdf():
    file = synthetic.pdf_report()
    doc = parse_document(file.data, file.name)
    value = next(v for v in file.values if v.table == "report-table6" and v.time == "2")
    anchor = _anchor(doc, value.locator)
    view = source_view(doc, anchor, also={role: _anchor(doc, at) for role, at in value.locators})
    assert (view.kind, view.page, view.page_size) == ("grid", 4, (612.0, 792.0))
    assert view.box == resolve(doc, anchor).box and view.title.startswith("Table 6.")
    roles = _view_roles(view)
    assert roles[(4, 2)] == ("7.1", "value") and roles[(4, 1)] == ("2", "time") and roles[(4, 3)][1] == "spread"
    assert roles[(4, 4)][1] == "n" and roles[(1, 2)][1] == "unit" and roles[(-1, 1)][1] == "study, arm, analyte, matrix"
    prose = next(v for v in file.values if v.table == "" and v.field == "dose")
    text = source_view(doc, _anchor(doc, prose.locator))
    assert (text.kind, text.page, text.page_size) == ("text", 1, (612.0, 792.0))
    assert text.text[text.span[0]:text.span[1]] == "50" and text.box == resolve(doc, _anchor(doc, prose.locator)).box
    word = parse_document(synthetic.word_report().data, "design-report.docx")
    n = source_view(word, _anchor(word, "d:p:2/ch:68-70"))
    assert (n.kind, n.text[n.span[0]:n.span[1]], n.page, n.box) == ("text", "18", None, None)
    with pytest.raises(AnchorError):
        source_view(doc, _anchor(doc, value.locator, OLD))


def _inner(locator: str) -> str:
    """A span inside a caption's or a context line's span: its second and third word (PDF), characters 1 to 9 (Word)."""
    place = parse_locator(locator)
    if isinstance(place, PdfSpan):
        last = min(place.first_word + 2, place.last_word)
        first = min(place.first_word + 1, last)
        return format_locator(PdfSpan(page=place.page, first_word=first, last_word=last, box=place.box))
    return format_locator(place.model_copy(update={"start": 1, "end": min(9, place.end)}))


def test_a_span_inside_a_caption_or_a_context_line_resolves_to_its_table_and_its_grid():
    checked = 0
    for file in (synthetic.pdf_report(), synthetic.word_report()):
        doc = parse_document(file.data, file.name)
        places = [(r.caption_locator, r.id) for r in doc.regions if r.kind == "table" and r.caption_locator]
        places += [(o.where, o.region) for o in doc.outside if o.region]
        for locator, region in places:
            inner = _inner(locator)
            assert resolve(doc, _anchor(doc, inner)).region_id == region, (file.name, inner)
            view = source_view(doc, _anchor(doc, inner))
            assert (view.kind, view.region_id) == ("grid", region)
            checked += 1
    assert checked >= 5


def test_check_anchors_finds_a_prose_value_inside_its_quote():
    """A prose fact's anchor is the span of the value itself and its verbatim the quote that holds it: an unchanged
    document gives no problem, in Word, in a text file and in a PDF (a word number may have moved; the last words of a
    page included)."""
    from modeler_intake.source.regions import body_paragraph, page_of

    word = parse_document(synthetic.word_report().data, "design-report.docx")
    second, third = body_paragraph(word, 2), body_paragraph(word, 3)
    assert (second[68:70], third[44:46]) == ("18", "20")
    assert check_anchors(word, [("n", _anchor(word, "d:p:2/ch:68-70", OLD), second),
                                ("dose", _anchor(word, "d:p:3/ch:44-46", OLD), third[30:]),        # a quote cut short
                                ("spaced", _anchor(word, "d:p:2/ch:68-70", OLD), "  ".join(second.split()))]) == []
    text = parse_document(b"Study notes\nA single dose of 18 mg and later 24 mg were given.\n", "notes.txt")
    line = "A single dose of 18 mg and later 24 mg were given."
    assert check_anchors(text, [("dose", _anchor(text, "x:l:2/ch:17-19", OLD), line)]) == []
    file = synthetic.pdf_report()
    pdf = parse_document(file.data, file.name)
    words = page_of(pdf, 1).words
    items = []
    for value in (v for v in file.values if v.table == ""):
        span = parse_locator(value.locator)
        quote = " ".join(w.text for w in words[max(0, span.first_word - 6):span.last_word + 4])
        moved = format_locator(PdfSpan(page=1, first_word=span.first_word + 5, last_word=span.last_word + 5,
                                       box=tuple(v + 0.5 for v in span.box)))
        items += [(f"{value.field}", _anchor(pdf, value.locator, OLD), quote),
                  (f"{value.field}-renumbered", _anchor(pdf, moved, OLD), quote)]
    assert len(items) == 6 and check_anchors(pdf, items) == []


def test_check_anchors_reports_a_span_that_no_longer_stands_where_its_quote_puts_it():
    """The place is checked, not only the text: a span that holds another number of the same quote, a quote of another
    sentence and a quote that is no longer in the document are problems, each with the text now at the span."""
    text = parse_document(b"Study notes\nA single dose of 24 mg and later 18 mg were given.\n", "notes.txt")
    was = "A single dose of 18 mg and later 24 mg were given."           # the span held 18; it now holds the quote's 24
    problems = check_anchors(text, [("slid", _anchor(text, "x:l:2/ch:17-19", OLD), was),
                                    ("elsewhere", _anchor(text, "x:l:2/ch:17-19", OLD), "at most 24 mg per day"),
                                    ("gone", _anchor(text, "x:l:2/ch:17-19", OLD), "The dose was 30 mg."),
                                    ("past", _anchor(text, "x:l:2/ch:90-92", OLD), was)])
    assert [(p.id, p.problem, p.found) for p in problems] == [("slid", "text_differs", "24"), ("elsewhere", "text_differs", "24"),
                                                              ("gone", "text_differs", "24"), ("past", "not_found", "")]
    file = synthetic.pdf_report()
    pdf = parse_document(file.data, file.name)
    (dose,) = [v for v in file.values if v.table == "" and v.field == "dose"]
    problems = check_anchors(pdf, [("other", _anchor(pdf, dose.locator, OLD), "a dose of 50 mg was never given here")])
    assert [(p.id, p.problem) for p in problems] == [("other", "text_differs")]
