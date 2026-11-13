"""Word (`.docx`) read once with python-docx (contracts §6.1): the body in order, tables as grids, images as figures.

Numbering follows python-docx: paragraphs over `Document.paragraphs` (the body's own paragraphs), tables over
`Document.tables`, both from 1. A paragraph's text is its runs in document order, wherever they stand inside it: its
own runs and hyperlinks (python-docx's `Paragraph.text`, and the same text for every plain paragraph), and also the runs
of an inline content control, a simple field, a smart tag or a tracked insertion, which python-docx leaves out (a
tracked deletion and the fallback copy of a drawing are not text; a text box is a frame of its own, below).

A table is a grid: a merged cell once, at its top-left, with its row and column spans (its covered places are copies
in the region's grid); a line break inside a cell stays in the cell ("\\n"). Every picture, chart or diagram (inline
or floating, in a paragraph, a table cell or a content control) is a figure `d:f:<n>`, numbered in document order; a
shape, a line or a text box is no figure, and the fallback copy Word keeps of a drawing (`mc:Fallback`) is not counted
twice.

Nothing is dropped in silence (G2): text the body holds that this reading does not give (a content control or other
element around whole paragraphs or rows, which `Document.paragraphs` and `Document.tables` do not number; a table inside
a cell; a text box; a footnote, an endnote or a comment) makes the document `partly_read`, its reason naming where, and each place
is listed in the warnings (`DOCX_TEXT_NOT_READ`); so do comments. Page headers and footers are page furniture: not
read as data and never counted, but each one that holds text is named with its text in the warnings
(`DOCX_FURNITURE`), so a study label or a version there is never lost in silence.

Locate: each table is a `table` region (`d:t:<n>`); its caption is the paragraph directly above it (empty paragraphs
skipped, no table between) when that paragraph is Caption-styled, begins with "Table" or "Figure", or is a short title
(at most 200 characters, not ending as a sentence ends); a prose sentence directly above a table stays prose and the
table has no caption. The short paragraphs directly below it (at most 3, each at most 200 characters, up to a heading,
a table or a longer paragraph) are its context lines below; the short paragraphs directly above its caption (at most
3, each at most 200 characters and not ending as a sentence ends, up to a heading or a sentence: an arm and dose line
such as "Part A: 50 mg, fasted") are its context lines above. Each is an outside item naming it (a footnote with the
LLOQ), and the context of one table only. The other paragraphs between tables form `prose` regions (`d:p:<a>-<b>`); a
heading starts a new one. Each figure is a `figure` region.
"""

from __future__ import annotations

import io
import re
from collections import Counter

from modeler_intake.anchors import DocxSpan, FigureRef, format_locator
from modeler_intake.source.regions import OUTSIDE_TEXT, clip, heading_style, region_id
from modeler_intake.source_model import BodyItem, Figure, OutsideItem, PageTable, Paragraph, Region, TableCell, has_number

CONTEXT_LINES = 3
MAX_NAMED = 5                  # places of unread text named in the reason (all are in the warnings)

_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
}
_NOTES = ("footnotes", "endnotes", "comments")
_FURNITURE = ("header", "footer")
_CAPTION_START = re.compile(r"(?i)(?:table|tab\.|figure|fig\.)\s*[0-9A-Z]")
_SENTENCE_END = (".", "!", "?")
_SEPARATORS = ("separator", "continuationSeparator", "continuationNotice")


def _q(name: str) -> str:
    """A prefixed name ("w:p") in Clark notation ("{namespace}p"). Elements are walked with their own methods (`iter`,
    `iterancestors`), never an XPath with prefixes: an element python-docx has no class for, such as a content
    control, has no namespace map of its own."""
    prefix, local = name.split(":")
    return "{" + _NS[prefix] + "}" + local


_FALLBACK, _DELETED, _MOVED, _TEXT_BOX = _q("mc:Fallback"), _q("w:del"), _q("w:moveFrom"), _q("w:txbxContent")
# what a body element may hold outside the text read from it, named in the order it is looked for
_HOLDERS = ((_q("w:txbxContent"), "a text box"), (_q("w:sdt"), "a content control"),
            (_q("w:customXml"), "a custom XML element"))


def _under(element, tags: tuple[str, ...]) -> bool:
    return any(ancestor.tag in tags for ancestor in element.iterancestors())


def _runs(element) -> list:
    """The runs that are text: a tracked deletion, the fallback copy of a drawing and a text box's frame left out."""
    return [r for r in element.iter(_q("w:r")) if not _under(r, (_FALLBACK, _DELETED, _MOVED, _TEXT_BOX))]


def _drawings(element) -> list:
    return [d for d in element.iter(_q("w:drawing"), _q("w:pict")) if not _under(d, (_FALLBACK,))]


def read_docx(data: bytes) -> tuple[tuple[BodyItem, ...], tuple[Figure, ...], tuple[str, ...], tuple[str, ...]]:
    """(body, figures, warnings, unread) of a Word file; `unread` names each place whose text is not read (see the
    module docstring). Raises the library's exception for a file it cannot open (the caller makes it `unreadable`)."""
    import docx
    from docx.text.paragraph import Paragraph as DocxParagraph  # for its style

    document = docx.Document(io.BytesIO(data))
    body: list[BodyItem] = []
    figures: list[Figure] = []
    unread: list[str] = []
    paragraph_no = table_no = 0
    for child in document.element.body.iterchildren():
        if child.tag == _q("w:p"):
            paragraph_no += 1
            text = paragraph_text(child)
            body.append(BodyItem(kind="paragraph", paragraph=Paragraph(index=paragraph_no, text=text,
                                                                       style=_style(DocxParagraph(child, document)))))
            if _lost(child, text):
                unread.append(f"d:p:{paragraph_no}: {_what(child, 'text outside its runs')}")
        elif child.tag == _q("w:tbl"):
            table_no += 1
            table = _table(child, table_no)
            body.append(BodyItem(kind="table", table=table))
            if _lost(child, "".join(c.text for c in table.cells)):
                nested = any(t is not child for t in child.iter(_q("w:tbl")))
                unread.append(f"d:t:{table_no}: {'a table inside a cell' if nested else _what(child, 'text outside its cells')}")
        elif child.tag != _q("w:sectPr") and _held(child).strip():
            where = f"after d:p:{paragraph_no}" if paragraph_no else "before d:p:1"
            name = "a content control" if child.tag == _q("w:sdt") else f"a {child.tag.rsplit('}', 1)[-1]} element"
            unread.append(f"{where}: {name} in the body")
        figures += [_figure(drawing, len(figures) + 1 + k, document)
                    for k, drawing in enumerate(d for d in _drawings(child) if _is_figure(d))]
    unread += _notes(document)
    warnings = tuple(f"DOCX_TEXT_NOT_READ {place}" for place in unread) + _furniture(document)
    return tuple(body), tuple(figures), warnings, tuple(unread)


def unread_reason(unread: tuple[str, ...]) -> str:
    """The reason of a `partly_read` Word document: the places whose text is not read."""
    named = "; ".join(unread[:MAX_NAMED])
    more = f"; and {len(unread) - MAX_NAMED} more (see the warnings)" if len(unread) > MAX_NAMED else ""
    return f"text not read: {named}{more}"


def paragraph_text(p) -> str:
    """A paragraph's text: its runs in document order (see the module docstring)."""
    return "".join(run.text for run in _runs(p))


def _chars(text: str) -> Counter[str]:
    return Counter("".join(text.split()))


def _held(element) -> str:
    """Every text the element holds (its w:t), a tracked deletion and the fallback copy of a drawing aside."""
    return "".join(t.text or "" for t in element.iter(_q("w:t")) if not _under(t, (_FALLBACK, _DELETED, _MOVED)))


def _lost(element, read: str) -> bool:
    """Whether the element holds text that the text read from it lacks."""
    return bool(_chars(_held(element)) - _chars(read))


def _what(element, otherwise: str) -> str:
    return next((what for tag, what in _HOLDERS if next(element.iter(tag), None) is not None), otherwise)


def _notes(document) -> list[str]:
    """The footnote, endnote and comment parts that hold text (their separators aside)."""
    from docx.oxml.parser import parse_xml

    out = []
    for rel in document.part.rels.values():
        kind = rel.reltype.rsplit("/", 1)[-1]
        if rel.is_external or kind not in _NOTES:
            continue
        try:
            root = parse_xml(rel.target_part.blob)
        except Exception:  # noqa: BLE001 - a damaged notes part is named, not read
            out.append(f"{kind}: the part cannot be read")
            continue
        if any(_held(note).strip() for note in root if note.get(_q("w:type")) not in _SEPARATORS):
            out.append(f"{kind}: the document's {kind} hold text")
    return out


def _furniture(document) -> tuple[str, ...]:
    """Each page header and footer part that holds text, named with its text (`DOCX_FURNITURE`): page furniture, as a
    PDF's running lines are, so listed and never counted, but never dropped in silence (a study label or a version
    there stays visible to the review). A header's or footer's picture (a logo) is no figure."""
    from docx.oxml.parser import parse_xml

    out = []
    for rel in sorted(document.part.rels.values(), key=lambda r: "" if r.is_external else str(r.target_part.partname)):
        kind = rel.reltype.rsplit("/", 1)[-1]
        if rel.is_external or kind not in _FURNITURE:
            continue
        name = str(rel.target_part.partname).rsplit("/", 1)[-1].removesuffix(".xml")
        try:
            root = parse_xml(rel.target_part.blob)
        except Exception:  # noqa: BLE001 - a damaged header part is named, not read
            out.append(f"DOCX_FURNITURE {name}: the page {kind} cannot be read")
            continue
        text = " ".join(" ".join(paragraph_text(p) for p in root.iter(_q("w:p"))).split())
        if text:
            out.append(f"DOCX_FURNITURE {name}: the page {kind} holds text, not read as data: {clip(text)}")
    return tuple(out)


def _style(para) -> str:
    try:
        return para.style.name or ""
    except (AttributeError, KeyError, ValueError):
        return ""


def _table(tbl, number: int) -> PageTable:
    """A Word table as a grid: each cell once at its top-left with its spans (gridSpan across, vMerge down)."""
    origin_at: dict[tuple[int, int], tuple[int, int]] = {}
    spans: dict[tuple[int, int], list[int]] = {}           # origin -> [last row, last column]
    texts: dict[tuple[int, int], str] = {}
    n_cols = 0
    for r, tr in enumerate(tbl.tr_lst, start=1):
        column = 1 + (tr.grid_before or 0)
        for tc in tr.tc_lst:
            span = max(1, tc.grid_span or 1)
            above = origin_at.get((r - 1, column))
            if tc.vMerge == "continue" and above is not None:
                origin = above
                spans[origin][0] = r
            else:
                origin = (r, column)
                spans[origin] = [r, column + span - 1]
                texts[origin] = "\n".join(paragraph_text(p) for p in tc.p_lst)
            for k in range(span):
                origin_at[(r, column + k)] = origin
            column += span
        n_cols = max(n_cols, column - 1)
    cells = tuple(TableCell(row=o[0], column=o[1], text=texts[o], row_span=spans[o][0] - o[0] + 1,
                            col_span=spans[o][1] - o[1] + 1) for o in sorted(texts))
    return PageTable(index=number, box=None, n_rows=len(tbl.tr_lst), n_cols=n_cols, cells=cells, engine="python-docx")


def _is_figure(drawing) -> bool:
    """A picture, a chart or a diagram; a shape, a line or a text box is not (a text box's text is reported)."""
    if next(drawing.iter(_q("a:blip"), _q("v:imagedata"), _q("c:chart")), None) is not None:
        return True
    return any(part in (g.get("uri") or "") for g in drawing.iter(_q("a:graphicData")) for part in ("/chart", "/diagram"))


def _figure(drawing, index: int, document) -> Figure:
    names = [d.get("name") for d in drawing.iter(_q("wp:docPr")) if d.get("name")]
    rids = [b.get(_q("r:embed")) for b in drawing.iter(_q("a:blip")) if b.get(_q("r:embed"))]
    return Figure(index=index, name=str(names[0]) if names else "", **_size(document, rids))


def _size(document, rids: list[str]) -> dict[str, int]:
    """The pixel size of a drawing's first image; 0 x 0 when there is none or python-docx cannot size it."""
    if not rids:
        return {"width": 0, "height": 0}
    try:
        image = document.part.related_parts[rids[0]].image
        return {"width": int(image.px_width), "height": int(image.px_height)}
    except Exception:  # noqa: BLE001 - an image part python-docx cannot size (an EMF, a broken part) keeps the figure
        return {"width": 0, "height": 0}


def is_caption(para: Paragraph) -> bool:
    """Whether a paragraph directly above a table is its caption: Caption-styled, beginning with "Table" or "Figure",
    or a short title (at most OUTSIDE_TEXT characters, not ending as a sentence ends). A prose sentence directly above
    a table with no caption stays prose."""
    text = para.text.strip()
    if re.match(r"(?i)caption\b", para.style) or _CAPTION_START.match(text):
        return True
    return len(text) <= OUTSIDE_TEXT and not text.endswith(_SENTENCE_END)


def locate_docx(body: tuple[BodyItem, ...], figures: tuple[Figure, ...],
                file_sha256: str) -> tuple[tuple[Region, ...], tuple[OutsideItem, ...]]:
    """Tables, their captions and context lines, prose runs and figures (see the module docstring)."""
    items = list(body)
    captions: dict[int, int] = {}                 # table position in body -> caption paragraph position
    for pos, item in enumerate(items):
        if item.kind != "table":
            continue
        k = pos - 1
        while k >= 0 and items[k].kind == "paragraph" and not items[k].paragraph.text.strip():
            k -= 1
        if k >= 0 and items[k].kind == "paragraph" and k not in captions.values() and is_caption(items[k].paragraph):
            captions[pos] = k
    caption_positions = set(captions.values())
    below: dict[int, list[int]] = {}
    for pos, item in enumerate(items):
        if item.kind != "table":
            continue
        k, taken = pos + 1, []
        while k < len(items) and len(taken) < CONTEXT_LINES:
            nxt = items[k]
            if nxt.kind != "paragraph":
                break
            text = nxt.paragraph.text
            if not text.strip():
                k += 1
                continue
            if k in caption_positions or heading_style(nxt.paragraph.style) or len(text) > OUTSIDE_TEXT:
                break
            taken.append(k)
            k += 1
        below[pos] = taken
    above: dict[int, list[int]] = {}
    assigned = caption_positions | {k for ks in below.values() for k in ks}
    for pos, item in enumerate(items):
        if item.kind != "table":
            continue
        k, taken = captions.get(pos, pos) - 1, []
        while k >= 0 and len(taken) < CONTEXT_LINES and items[k].kind == "paragraph":
            para = items[k].paragraph
            if not para.text.strip():
                k -= 1
                continue
            if k in assigned or heading_style(para.style) or len(para.text) > OUTSIDE_TEXT \
                    or para.text.rstrip().endswith(_SENTENCE_END):
                break
            taken.append(k)
            k -= 1
        above[pos] = taken
        assigned |= set(taken)
    context = {k: pos for found in (below, above) for pos, ks in found.items() for k in ks}
    regions: list[Region] = []
    outside: list[OutsideItem] = []
    run: list[Paragraph] = []

    def close() -> None:
        if run:
            where = f"d:p:{run[0].index}-{run[-1].index}"
            regions.append(Region(id=region_id(where, file_sha256), kind="prose", where=where, n_rows=len(run),
                                  numeric_cells=sum(1 for p in run for t in p.text.split() if has_number(t))))
            run.clear()

    table_ids: dict[int, str] = {}
    for pos, item in enumerate(items):
        if item.kind == "table" and item.table is not None:
            table_ids[pos] = region_id(f"d:t:{item.table.index}", file_sha256)
    for pos, item in enumerate(items):
        if item.kind == "table" and item.table is not None:
            close()
            table = item.table
            caption = items[captions[pos]].paragraph if pos in captions else None
            regions.append(Region(
                id=table_ids[pos], kind="table", where=f"d:t:{table.index}", caption=caption.text if caption else "",
                caption_locator=format_locator(DocxSpan(paragraph=caption.index, start=0, end=len(caption.text)))
                if caption else None, n_rows=table.n_rows, n_cols=table.n_cols,
                numeric_cells=sum(1 for c in table.cells if has_number(c.text))))
            continue
        para = item.paragraph
        if para is None or not para.text.strip() or pos in caption_positions:
            continue
        if pos in context:
            close()
            outside.append(OutsideItem(where=format_locator(DocxSpan(paragraph=para.index, start=0, end=len(para.text))),
                                       text=clip(para.text), numeric=has_number(para.text), region=table_ids[context[pos]]))
            continue
        if heading_style(para.style):
            close()
        run.append(para)
    close()
    for figure in figures:
        where = format_locator(FigureRef(index=figure.index))
        regions.append(Region(id=region_id(where, file_sha256), kind="figure", where=where))
    return tuple(regions), tuple(outside)
