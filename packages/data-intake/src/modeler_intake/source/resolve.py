"""Anchors read back (contracts §6.1): `resolve` an anchor to its text, `check_anchors` after a re-parse, and the
`source_view` the review shows beside a value.

Places are compared by identity (§4.1), never by box: a sheet cell by sheet and cell, a PDF cell by page, table, row and
column, a PDF span by page and words, a Word cell or span, a text span and a figure by their numbers. Only
`check_anchors` uses boxes, for PDF anchors read under ANOTHER parser version: the table numbering may have changed, so
a PDF cell or span is found again by its text and a box overlapping the old one by at least half (of the smaller box).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from modeler_intake.anchors import (
    Anchor,
    AnchorError,
    DocxCell,
    DocxSpan,
    FigureRef,
    PdfCell,
    PdfSpan,
    SheetCell,
    TextSpan,
    format_locator,
    parse_anchor,
    parse_locator,
)
from modeler_intake.citations import normalize_for_match
from modeler_intake.source.pdf import overlap
from modeler_intake.source.regions import (
    a1_place,
    body_paragraph,
    body_table,
    page_of,
    parse_sheet_range,
    region_grid,
    span_words,
    table_cells,
    union_box,
    word_span,
)
from modeler_intake.source_model import (
    AnchorProblem,
    GridCell,
    Region,
    RegionGrid,
    Resolved,
    SourceDocument,
    SourceView,
    ViewCell,
    has_number,
)

Locator = SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef
_RANGE_WORDS = re.compile(r"p:([0-9]+)/w:([0-9]+)-([0-9]+)")
_RANGE_LINES = re.compile(r"(d:p|x:l):([0-9]+)-([0-9]+)")


def _key(locator: Locator) -> tuple[object, ...]:
    """A locator's identity (its box set aside)."""
    found = locator.model_dump()
    found.pop("box", None)
    return tuple(sorted(found.items()))


def _anchor(doc: SourceDocument, anchor: str) -> Anchor:
    parsed = parse_anchor(anchor)
    if parsed.file_sha256 != doc.file_sha256:
        raise AnchorError(f"the anchor names another file ({parsed.file_sha256[:12]}...), not {doc.name}")
    if (parsed.parser, parsed.parser_version) != (doc.parser, doc.parser_version):
        raise AnchorError(f"the anchor was read by {parsed.parser}/{parsed.parser_version}, this document by "
                          f"{doc.parser}/{doc.parser_version}: check_anchors finds it again")
    return parsed


def resolve(doc: SourceDocument, anchor: str) -> Resolved:
    """The text an anchor names in this document (the same file and parser version), its locator here (a PDF box as
    this parse gives it), its region (the table, prose or figure region holding it, or the region it is a context
    line of) and, in a PDF, its page and box. AnchorError for another file or version, or a place not found."""
    return _find(doc, _anchor(doc, anchor).locator)


def _find(doc: SourceDocument, locator: Locator) -> Resolved:
    try:
        if isinstance(locator, SheetCell):
            sheet = next((s for s in doc.sheets if s.name == locator.sheet), None)
            place = a1_place(locator.cell)
            cell = next((c for c in sheet.cells if (c.row, c.column) == place), None) if sheet else None
            if cell is None:
                raise KeyError(locator.cell)
            return Resolved(text=cell.text, locator=format_locator(locator), region_id=_region_of(doc, locator))
        if isinstance(locator, PdfCell):
            page = page_of(doc, locator.page)
            table = page.tables[locator.table - 1] if 1 <= locator.table <= len(page.tables) else None
            if table is None or (locator.row, locator.column) not in table_cells(table):
                raise KeyError(f"t:{locator.table}/r:{locator.row}/c:{locator.column}")
            text, origin = table_cells(table)[(locator.row, locator.column)]
            at = (locator.row, locator.column) if origin is None else tuple(int(v) for v in origin.split(","))
            box = next(c.box for c in table.cells if (c.row, c.column) == at) or table.box or (0.0, 0.0, 0.0, 0.0)
            here = format_locator(PdfCell(page=page.number, table=locator.table, row=locator.row, column=locator.column,
                                          box=box))
            return Resolved(text=text, locator=here, region_id=_region_of(doc, locator), page=page.number, box=box)
        if isinstance(locator, PdfSpan):
            page = page_of(doc, locator.page)
            words = span_words(page, locator.first_word, locator.last_word)
            box = union_box(w.box for w in words)
            return Resolved(text=" ".join(w.text for w in words), locator=word_span(page.number, words),
                            region_id=_region_of(doc, locator), page=page.number, box=box)
        if isinstance(locator, DocxCell):
            cells = table_cells(body_table(doc, locator.table))
            text, _origin = cells[(locator.row, locator.column)]
            return Resolved(text=text, locator=format_locator(locator), region_id=_region_of(doc, locator))
        if isinstance(locator, DocxSpan | TextSpan):
            number = locator.paragraph if isinstance(locator, DocxSpan) else locator.line
            text = body_paragraph(doc, number)
            if locator.end > len(text):
                raise KeyError(f"characters {locator.start}-{locator.end} of a paragraph of {len(text)}")
            return Resolved(text=text[locator.start:locator.end], locator=format_locator(locator),
                            region_id=_region_of(doc, locator))
        figure = next((f for f in doc.figures if (f.page, f.index) == (locator.page, locator.index)), None)
        if figure is None:
            raise KeyError(f"figure {locator.index}")
        here = format_locator(FigureRef(page=figure.page, index=figure.index, box=figure.box)
                              if figure.page is not None and figure.box is not None else FigureRef(index=figure.index))
        return Resolved(text=figure.name, locator=here, region_id=_region_of(doc, locator), page=figure.page, box=figure.box)
    except (KeyError, IndexError, StopIteration, ValueError) as exc:
        if isinstance(exc, AnchorError):
            raise
        raise AnchorError(f"{format_locator(locator)} is not a place of {doc.name} ({exc})") from exc


def _region_of(doc: SourceDocument, locator: Locator) -> str | None:
    """The region holding a place: a table's cell or caption (or a span inside it), a prose or unruled-table range, a
    figure; else the region the place is a context line of (or a span inside it); else None (outside every region)."""
    for region in doc.regions:
        if region.caption_locator and _inside(locator, _locator_of(region.caption_locator)):
            return region.id
        if _holds(doc, region, locator):
            return region.id
    for item in doc.outside:
        if item.region and _inside(locator, _locator_of(item.where)):
            return item.region
    if isinstance(locator, SheetCell):
        for region in doc.regions:
            if region.where.startswith("s:") and region.caption_locator:
                sheet, r0, c0, _r1, c1 = parse_sheet_range(region.where)
                first = a1_place(_locator_of(region.caption_locator).cell)[0]
                row, column = a1_place(locator.cell)
                if sheet == locator.sheet and first <= row < r0 and c0 <= column <= c1:
                    return region.id
    return None


def _inside(locator: Locator, place: Locator) -> bool:
    """Whether a place is a caption's or a context line's place, or a span inside it (a dose in a caption, a word of a
    footnote): the same paragraph or line and characters within it, the same page and words within it."""
    if isinstance(locator, DocxSpan) and isinstance(place, DocxSpan):
        return locator.paragraph == place.paragraph and place.start <= locator.start and locator.end <= place.end
    if isinstance(locator, TextSpan) and isinstance(place, TextSpan):
        return locator.line == place.line and place.start <= locator.start and locator.end <= place.end
    if isinstance(locator, PdfSpan) and isinstance(place, PdfSpan):
        return locator.page == place.page and place.first_word <= locator.first_word and locator.last_word <= place.last_word
    return _key(locator) == _key(place)


def _locator_of(text: str) -> Locator:
    return parse_locator(text)


def _holds(doc: SourceDocument, region: Region, locator: Locator) -> bool:
    where = region.where
    if isinstance(locator, SheetCell) and where.startswith("s:"):
        sheet, r0, c0, r1, c1 = parse_sheet_range(where)
        row, column = a1_place(locator.cell)
        return sheet == locator.sheet and r0 <= row <= r1 and c0 <= column <= c1
    if isinstance(locator, PdfCell) and region.kind == "table":
        return any((p.page, p.table) == (locator.page, locator.table) and locator.row > p.header_rows_repeated
                   for p in region.parts)
    if isinstance(locator, PdfSpan):
        match = _RANGE_WORDS.fullmatch(where)
        return bool(match) and int(match.group(1)) == locator.page \
            and int(match.group(2)) <= locator.first_word and locator.last_word <= int(match.group(3))
    if isinstance(locator, DocxCell):
        return where == f"d:t:{locator.table}"
    if isinstance(locator, DocxSpan | TextSpan):
        match = _RANGE_LINES.fullmatch(where)
        prefix = "d:p" if isinstance(locator, DocxSpan) else "x:l"
        number = locator.paragraph if isinstance(locator, DocxSpan) else locator.line
        return bool(match) and match.group(1) == prefix and int(match.group(2)) <= number <= int(match.group(3))
    if isinstance(locator, FigureRef) and region.kind == "figure":
        return _key(_locator_of(where)) == _key(locator)
    return False


# --- after a re-parse ------------------------------------------------------------------------------------------------


def check_anchors(doc: SourceDocument, items: Iterable[tuple[str, str, str]]) -> list[AnchorProblem]:
    """Each (id, anchor text, verbatim) of a value read under ANOTHER parser version found again in `doc` with the same
    text: a sheet or Word cell, a Word or text span and a figure by their locator; a PDF cell or span by its text and a
    box overlapping the old one by at least half. One problem per value that is not found (`not_found`: moved, or
    gone) or holds another text (`text_differs`, with the text found).

    A prose fact's anchor is the span of the value itself and its verbatim the quote that holds it (the ledger's
    `record_prose`). Such a value is found when the quote lies over the span: the span's text stands in the quote, with
    the quote's words before and after it standing before and after the span in the document (`_quote_covers`). A
    span that now holds another number of the same quote is a problem: the place is checked, not only the text."""
    problems = []
    for value_id, anchor, verbatim in items:
        try:
            parsed = parse_anchor(anchor)
        except AnchorError:
            problems.append(AnchorProblem(id=value_id, anchor=anchor, problem="not_found"))
            continue
        if parsed.file_sha256 != doc.file_sha256:
            problems.append(AnchorProblem(id=value_id, anchor=anchor, problem="not_found"))
            continue
        locator = parsed.locator
        if isinstance(locator, PdfCell | PdfSpan):
            found, text = _again_in_pdf(doc, locator, verbatim)
        else:
            try:
                text = _find(doc, locator).text
                found = True
            except AnchorError:
                found, text = False, ""
            if found and text != verbatim and isinstance(locator, DocxSpan | TextSpan):
                paragraph = body_paragraph(doc, locator.paragraph if isinstance(locator, DocxSpan) else locator.line)
                if _quote_covers(paragraph[:locator.start], text, paragraph[locator.end:], verbatim):
                    text = verbatim
        if not found:
            problems.append(AnchorProblem(id=value_id, anchor=anchor, problem="not_found"))
        elif text != verbatim:
            problems.append(AnchorProblem(id=value_id, anchor=anchor, problem="text_differs", found=text))
    return problems


_SPACE = re.compile(r"\s+")
_JOINS = str.maketrans("", "", "-\N{HYPHEN}\N{NON-BREAKING HYPHEN}\N{SOFT HYPHEN}\N{MINUS SIGN}")


def _squeezed(text: str) -> str:
    """A text with no white space, in the form a quote is matched in (`citations.normalize_for_match`)."""
    return _SPACE.sub("", normalize_for_match(text)).replace("\N{MINUS SIGN}", "-")


def _quote_covers(before: str, span: str, after: str, quote: str) -> bool:
    """Whether a quote lies over a span of the document: some occurrence of the span's text in the quote has the
    quote's text before it at the end of `before` (the document's text up to the span) and the quote's text after it
    at the start of `after`. White space aside everywhere; a hyphen aside in the text around the span only (a word cut
    at a line's end), never in the span itself, where it may be a minus sign."""
    inner, whole = _squeezed(span), _squeezed(quote)
    if not inner or len(whole) <= len(inner):
        return False
    lead, tail = _squeezed(before).translate(_JOINS), _squeezed(after).translate(_JOINS)
    at = whole.find(inner)
    while at >= 0:
        if lead.endswith(whole[:at].translate(_JOINS)) and tail.startswith(whole[at + len(inner):].translate(_JOINS)):
            return True
        at = whole.find(inner, at + 1)
    return False


def _again_in_pdf(doc: SourceDocument, locator: PdfCell | PdfSpan, verbatim: str) -> tuple[bool, str]:
    """(found at the place, the text there): the same text first, else the text that overlaps most."""
    try:
        page = page_of(doc, locator.page)
    except KeyError:
        return False, ""
    candidates: list[tuple[float, str]] = []
    if isinstance(locator, PdfCell):
        for table in page.tables:
            for cell in table.cells:
                if cell.box is not None and (share := overlap(cell.box, locator.box)) >= 0.5:
                    candidates.append((share, cell.text))
    else:
        # the span's own length first (a prose fact's verbatim is the quote around the span, longer than the span), then
        # the verbatim's, should a new version cut the same text into another number of words
        own = locator.last_word - locator.first_word + 1
        for size in dict.fromkeys((own, max(1, len(verbatim.split())))):
            for word in page.words:
                if overlap(word.box, locator.box) <= 0:
                    continue
                words = page.words[word.index - 1:word.index - 1 + size]
                if len(words) != size or (share := overlap(union_box(w.box for w in words), locator.box)) < 0.5:
                    continue
                text = " ".join(w.text for w in words)
                candidates.append((share, text))
                if size == own and text != verbatim and _quote_covers(
                        " ".join(w.text for w in page.words[:word.index - 1]), text,
                        " ".join(w.text for w in page.words[word.index - 1 + size:]), verbatim):
                    return True, verbatim
    if any(text == verbatim for _share, text in candidates):
        return True, verbatim
    if candidates:
        return True, max(candidates)[1]
    return False, ""


# --- what the review shows -------------------------------------------------------------------------------------------


def source_view(doc: SourceDocument, anchor: str, *, also: Mapping[str, str] | None = None) -> SourceView:
    """What the review shows beside a value: the table region around a cell (its cells, its caption and context lines
    at negative rows above and rows past `n_rows` below), the value's cell highlighted as "value" and each anchor of
    `also` (role -> anchor text: its time, unit, labels, spread, n, LLOQ) highlighted with its role; or the paragraph or
    line around a span, the span marked. A PDF view gives the page, its size and the box to draw. AnchorError when the
    anchor does not resolve in this document; an `also` anchor that names no place of the view is left out."""
    parsed = _anchor(doc, anchor)
    resolved = _find(doc, parsed.locator)
    roles: dict[tuple[object, ...], list[str]] = {_key(parsed.locator): ["value"]}
    for role, other in (also or {}).items():
        try:
            other_anchor = parse_anchor(other)
        except AnchorError:
            continue
        if other_anchor.file_sha256 == doc.file_sha256:
            roles.setdefault(_key(other_anchor.locator), []).append(role)
    region = next((r for r in doc.regions if r.id == resolved.region_id), None)
    page_size = None
    if resolved.page is not None:
        page = page_of(doc, resolved.page)
        page_size = (page.width, page.height)
    if region is not None and region.kind == "table":
        grid = region_grid(doc, region.id)
        cells = _view_cells(region, grid, roles)
        return SourceView(kind="grid", title=_title(doc, region), region_id=region.id, n_rows=grid.n_rows, n_cols=grid.n_cols,
                          cells=tuple(cells), page=resolved.page, page_size=page_size, box=resolved.box)
    if isinstance(parsed.locator, SheetCell):
        cell = ViewCell(row=1, column=1, text=resolved.text, numeric=has_number(resolved.text), locator=resolved.locator,
                        highlighted=True, role="value")
        return SourceView(kind="grid", title=f"{parsed.locator.sheet} {parsed.locator.cell}", region_id=resolved.region_id,
                          n_rows=1, n_cols=1, cells=(cell,))
    text, span = _text_around(doc, parsed.locator, region)
    title = region.caption if region is not None and region.caption else _place_title(parsed.locator)
    return SourceView(kind="text", title=title, region_id=resolved.region_id, text=text, span=span, page=resolved.page,
                      page_size=page_size, box=resolved.box)


def _view_cells(region: Region, grid: RegionGrid, roles: Mapping[tuple[object, ...], list[str]]) -> list[ViewCell]:
    c0 = parse_sheet_range(region.where)[2] if region.where.startswith("s:") else 1

    def view(row: int, column: int, cell: GridCell) -> ViewCell:
        found = roles.get(_key(_locator_of(cell.locator)), [])
        return ViewCell(row=row, column=column, text=cell.text, numeric=has_number(cell.text), locator=cell.locator,
                        highlighted=bool(found), role=", ".join(found) if found else None)

    def column_of(cell: GridCell) -> int:
        locator = _locator_of(cell.locator)
        return a1_place(locator.cell)[1] - c0 + 1 if isinstance(locator, SheetCell) else 1

    out = [view(r, c, cell) for (r, c), cell in sorted(grid.cells.items())]
    row = -1
    for cell in reversed(grid.caption):
        out.append(view(row, column_of(cell), cell))
        row -= 1
    for line in grid.above:
        out += [view(row, column_of(cell), cell) for cell in line]
        row -= 1
    for k, line in enumerate(grid.below, start=1):
        out += [view(grid.n_rows + k, column_of(cell), cell) for cell in line]
    return out


def _title(doc: SourceDocument, region: Region) -> str:
    if region.caption:
        return region.caption.split("\n")[0]
    if region.where.startswith("s:"):
        return f"{parse_sheet_range(region.where)[0]} {region.where.rsplit('!', 1)[1]}"
    if region.where.startswith("p:"):
        page, table = re.fullmatch(r"p:([0-9]+)/t:([0-9]+)", region.where).groups()
        return f"Page {page}, table {table}"
    return f"{doc.name}: table {region.where.removeprefix('d:t:')}"


def _place_title(locator: Locator) -> str:
    if isinstance(locator, PdfSpan):
        return f"Page {locator.page}"
    if isinstance(locator, DocxSpan):
        return f"Paragraph {locator.paragraph}"
    if isinstance(locator, TextSpan):
        return f"Line {locator.line}"
    if isinstance(locator, FigureRef):
        return f"Figure {locator.index}" + (f", page {locator.page}" if locator.page else "")
    return format_locator(locator)


def _text_around(doc: SourceDocument, locator: Locator, region: Region | None) -> tuple[str, tuple[int, int] | None]:
    """The paragraph (or line) holding a span, and the span's character offsets in it."""
    if isinstance(locator, DocxSpan | TextSpan):
        number = locator.paragraph if isinstance(locator, DocxSpan) else locator.line
        return body_paragraph(doc, number), (locator.start, locator.end)
    if isinstance(locator, PdfSpan):
        page = page_of(doc, locator.page)
        first, last = locator.first_word, locator.last_word
        if region is not None and region.kind == "prose":
            from modeler_intake.source.pdf import region_paragraphs

            for para in region_paragraphs(doc, region):
                a, b = (int(v) for v in _RANGE_WORDS.fullmatch(para.locator).groups()[1:])
                if a <= first and last <= b:
                    first, last = a, b
                    break
        else:
            from modeler_intake.source.pdf import page_lines

            for line in page_lines(page):
                if line.words[0].index <= locator.first_word and locator.last_word <= line.words[-1].index:
                    first, last = line.words[0].index, line.words[-1].index
                    break
        words = span_words(page, first, last)
        start = sum(len(w.text) + 1 for w in words if w.index < locator.first_word)
        end = start + len(" ".join(w.text for w in words if locator.first_word <= w.index <= locator.last_word))
        return " ".join(w.text for w in words), (start, end)
    if isinstance(locator, FigureRef):
        figure = next(f for f in doc.figures if (f.page, f.index) == (locator.page, locator.index))
        return figure.name, None
    return "", None
