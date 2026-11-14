"""PDF read once with pdfplumber (contracts §6.1): words with boxes, ruled tables with cell boxes, images, OCR need.

Per page: size, rotation, the number of characters, every word of `extract_words()` with its defaults, numbered from 1
in its order (a word span `p:<page>/w:<first>-<last>@<box>`), the ruled tables of `find_tables()` (the `lines`
strategy, its defaults) with each cell's text from `extract()` and its box (a merged cell once, with its spans), and the
images. A page with at most `NEEDS_OCR_MAX_CHARS` characters and an image needs OCR; so does a scan under a typed
running header or footer: a page with at most `NEEDS_OCR_MAX_CHARS` characters outside its top and bottom `MARGIN` and
an image covering at least `SCAN_AREA` of it (a logo is far smaller). Engines passed in add to this: a
`PdfTableEngine`'s tables after the ruled ones (one overlapping a ruled table is left out), an `OcrEngine`'s words on
a page that needs OCR. Boxes are PDF points from the page's top-left, rounded to 2 decimals.

Locate (rules, no LLM; the parameters below are reading parameters: a change is a new SOURCE_VERSION):
- Words in no table form lines (same top within `Y_TOLERANCE`), lines form paragraphs (a gap of at most `LINE_GAP`
  line heights, no table between).
- Page furniture: a page number ("3", "Page 3", "Page 3 of 12", "- 3 -", "3/12") in the top or bottom `MARGIN` of the
  page; a line repeated at the same place (top within 4 points) on most pages: in the margins, the same text once its
  page number is set aside (its other numbers kept, so running lines that differ in a dose, a cohort or an N are not
  furniture), in the body of the page, the same text holding no number (a repeated footnote with a number, such as
  the LLOQ under each cohort's table, is read where it stands); and a line that only says a table goes on ("Continued
  on next page"). A repeated line directly above a table is that table's caption, not furniture.
- A line that runs over tables side by side (a caption or a footnote of each) is cut at its wide gaps (more than
  `PIECE_GAP` line heights between two words) where the pieces stand over different tables.
- Each ruled table is a region. Its caption is the line directly above it and across its width (within `CONTEXT_GAP`
  line heights) when that line is a paragraph of its own or begins with "Table" or "Figure"; a caption wrapped over
  up to 3 lines (a paragraph that begins so) is the caption whole. The last line of a prose paragraph is no caption:
  the paragraph stays whole and the table has none. A table
  that starts a page continues the last table of the page before (the same region: `parts`, each with its own caption,
  the repeated header dropped from the grid and counted in `header_rows_repeated`) only when the earlier part is the
  last block of its page, the column count is the same, the new part repeats the first part's header row or has none
  (its first row holds a bare number), and the text between them is nothing, furniture, a line that only says the table
  goes on ("(continued)", "Continued on next page") or the first part's caption again (equal once "continued", "cont."
  or "cont'd" and their brackets, case and spacing are set aside; numbers kept). The new part's leading rows that equal
  the first part's header rows (a header of one row or more, repeated: the first part's rows above its first row whose
  first cell is a bare number) are dropped from the grid and counted; a data row is never dropped.
- Context lines: the whole paragraphs directly below a table (its last part) and across its width, at most 3 lines
  in all, within `CONTEXT_GAP` line heights; and the one-line paragraphs directly above its caption, across its width
  (at most 3). Each is an outside item naming the table (a footnote with the LLOQ). A line is the context of one table
  only.
- The other paragraphs: consecutive ones form a `prose` region (per page); a block of paragraphs whose share of words
  holding a number reaches `TABLE_LIKE_NUMERIC_SHARE` is a `table_like_text` region (an unruled table: located, not
  gridded): a paragraph of at least 2 lines, or one-line paragraphs next to each other (rows spaced wider than a
  paragraph's lines), with the one-line row of column headings directly above them; its caption is the one-line
  paragraph directly above the block.
- Each image is a `figure` region, except an image repeated at the same place on most pages (furniture).
"""

from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from modeler_intake.anchors import FigureRef, format_locator
from modeler_intake.mapping_spec import ProseParagraph
from modeler_intake.source.regions import (
    LINE_TOLERANCE,
    clip,
    lines_of_words,
    page_of,
    pdf_table_region_id,
    region_id,
    round_box,
    table_cells,
    union_box,
    word_span,
)
from modeler_intake.source_model import (
    Box,
    Figure,
    OcrEngine,
    OutsideItem,
    Page,
    PageTable,
    PdfTableEngine,
    Region,
    RegionPart,
    SourceDocument,
    TableCell,
    Word,
    has_number,
    is_numeric_text,
)

Y_TOLERANCE = LINE_TOLERANCE   # words whose tops differ by at most this are on one line (points)
LINE_GAP = 0.9             # lines a gap of at most this many line heights apart are one paragraph
CONTEXT_GAP = 3.0          # a caption or a context line stands at most this many line heights from its table
MARGIN = 0.08              # the top and bottom share of a page where a page number or a running line is furniture
SAME_PLACE = 4.0           # a repeated line or image stands within this many points of the same place
PIECE_GAP = 2.0            # a gap between two words of a line wider than this many line heights splits it into pieces
CONTEXT_LINES = 3
SCAN_AREA = 0.25           # an image covering at least this share of a page with text in its margins only is a scan

_PAGE_NUMBER = re.compile(r"(?i)(?:page\s*)?[-–—]?\s*\d{1,4}\s*[-–—]?(?:\s*(?:of|/)\s*\d{1,4})?")
_PAGE_TOKEN = re.compile(r"(?i)\bpage\s*\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\b|\b\d{1,4}\s*(?:of|/)\s*\d{1,4}\b")
_CAPTION_START = re.compile(r"(?i)\s*(?:table|tab\.|figure|fig\.)\s*[0-9A-Z]")
_CONTINUED = re.compile(r"(?i)[(\[{]?\s*(?:continued|cont'd|cont’d|cont\.)\s*[)\]}]?")
# a line that only says a table goes on: "(continued)", "Continued on next page", "cont'd from previous page"
_CONTINUATION_NOTE = re.compile(r"(?i)[\W_]*(?:continued|cont'd|cont’d|cont\.)(?:\s+(?:on|from)\s+(?:the\s+)?"
                                r"(?:next|following|previous|preceding)\s+page)?[\W_]*")


# --- reading -------------------------------------------------------------------------------------------------------


def _password(exc: BaseException) -> bool:
    """Whether opening failed for want of a password (pdfplumber wraps pdfminer's error: its args and context)."""
    found = [exc, *exc.args, exc.__cause__, exc.__context__]
    text = " ".join(f"{type(e).__name__} {e}" for e in found if e is not None).lower()
    return "password" in text or "encrypt" in text


def read_pdf(data: bytes, file_sha256: str, *, table_engines: Sequence[PdfTableEngine] = (), ocr: OcrEngine | None = None,
             needs_ocr_max_chars: int, table_like_share: float) -> dict[str, object]:
    """The document fields of a PDF (pages, figures, regions, outside items, state and reason). An encrypted or
    corrupt file is `unreadable` with its reason; a page that fails, or that needs OCR with no engine, is listed."""
    import pdfplumber

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
        plumber_pages = list(pdf.pages)
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many types for a damaged or encrypted file
        reason = ("the PDF is encrypted: a password is needed" if _password(exc)
                  else f"the PDF could not be opened ({type(exc).__name__}: {exc})")
        return {"state": "unreadable", "reason": reason}
    pages: list[Page] = []
    figures: list[Figure] = []
    warnings: list[str] = []
    raw_boxes: dict[tuple[int, int], tuple[float, float, float, float]] = {}
    failed: list[int] = []
    try:
        for plumber_page in plumber_pages:
            number = plumber_page.page_number
            try:
                page, boxes, found = _page(plumber_page, data, table_engines, ocr, needs_ocr_max_chars, warnings)
            except Exception:  # noqa: BLE001 - one damaged page is listed, the others are read
                failed.append(number)
                page, boxes, found = Page(number=number, width=_size(plumber_page, "width"),
                                          height=_size(plumber_page, "height"), n_chars=0, words=(), tables=()), {}, []
            pages.append(page)
            figures += found
            raw_boxes.update({(number, k): b for k, b in boxes.items()})
    finally:
        pdf.close()
    layout = locate(pages, figures, file_sha256, raw_boxes=raw_boxes, table_like_share=table_like_share)
    ocr_pages = [p.number for p in pages if p.needs_ocr and not (ocr is not None and p.words)]
    reasons = []
    if failed:
        reasons.append(f"page{'s' if len(failed) > 1 else ''} {_numbers(failed)} could not be read")
    if ocr_pages:
        why = "no OCR engine is registered" if ocr is None else f"the OCR engine {ocr.name} found no words"
        reasons.append(f"page{'s' if len(ocr_pages) > 1 else ''} {_numbers(ocr_pages)} "
                       f"need{'' if len(ocr_pages) > 1 else 's'} OCR (no text layer); {why}")
    unread = set(failed) | set(ocr_pages)
    state = "read" if not unread else "unreadable" if len(unread) == len(pages) else "partly_read"
    if not pages:
        state, reasons = "unreadable", ["the PDF has no pages"]
    return {"state": state, "reason": "; ".join(reasons), "pages": tuple(pages), "warnings": tuple(warnings), **layout}


def _size(plumber_page, name: str) -> float:
    try:
        return float(getattr(plumber_page, name) or 0.0)
    except Exception:  # noqa: BLE001 - a page whose box cannot be read has no size
        return 0.0


def _numbers(numbers: Sequence[int]) -> str:
    return ", ".join(str(n) for n in numbers)


def _page(plumber_page, data: bytes, table_engines: Sequence[PdfTableEngine], ocr: OcrEngine | None,
          needs_ocr_max_chars: int, warnings: list[str]) -> tuple[Page, dict[int, tuple[float, float, float, float]],
                                                                  list[Figure]]:
    number = plumber_page.page_number
    n_chars = len(plumber_page.chars)
    images = plumber_page.images
    n_images = len(images)
    words = tuple(Word(index=k, text=w["text"], box=round_box((w["x0"], w["top"], w["x1"], w["bottom"])))
                  for k, w in enumerate(plumber_page.extract_words(), start=1))
    tables: list[PageTable] = []
    raw: dict[int, tuple[float, float, float, float]] = {}
    for found in plumber_page.find_tables():
        index = len(tables) + 1
        tables.append(_plumber_table(found, index))
        raw[index] = tuple(float(v) for v in found.bbox)
    for engine in table_engines:
        try:
            found_by_engine = list(engine.tables(data, number))
        except Exception as exc:  # noqa: BLE001 - an engine that fails on a page leaves the page to pdfplumber, named
            warnings.append(f"TABLE_ENGINE_FAILED p:{number}: {engine.name}: {type(exc).__name__}: {exc}")
            continue
        for extra in found_by_engine:
            box = extra.box or _cells_box(extra)
            if box is not None and any(t.box is not None and _overlap(box, t.box) >= 0.5 for t in tables):
                continue
            index = len(tables) + 1
            tables.append(extra.model_copy(update={"index": index, "box": round_box(box) if box else None,
                                                   "engine": extra.engine or engine.name}))
            if box is not None:
                raw[index] = tuple(float(v) for v in box)
    needs_ocr = n_images > 0 and (n_chars <= needs_ocr_max_chars
                                  or (_body_chars(plumber_page) <= needs_ocr_max_chars and _scan_sized(plumber_page)))
    if needs_ocr and ocr is not None:
        try:
            read = [w for w in ocr.words(data, number) if w.text.strip()]
        except Exception as exc:  # noqa: BLE001 - an OCR engine that fails leaves the page needing OCR, named
            warnings.append(f"OCR_FAILED p:{number}: {ocr.name}: {type(exc).__name__}: {exc}")
            read = []
        words = tuple(Word(index=k, text=w.text, box=round_box(w.box)) for k, w in enumerate(read, start=1))
    rotation = int(getattr(plumber_page, "rotation", 0) or 0)
    page = Page(number=number, width=float(plumber_page.width), height=float(plumber_page.height), rotation=rotation,
                needs_ocr=needs_ocr, n_chars=n_chars, words=words, tables=tuple(tables), n_images=n_images)
    figures = []
    for k, image in enumerate(images, start=1):
        size = image.get("srcsize") or (0, 0)
        figures.append(Figure(index=k, page=number, box=round_box((image["x0"], image["top"], image["x1"], image["bottom"])),
                              name=str(image.get("name") or ""), width=int(size[0] or 0), height=int(size[1] or 0)))
    return page, raw, figures


def _body_chars(plumber_page) -> int:
    """The characters outside the page's top and bottom MARGIN (a running header, a footer and a page number aside)."""
    height = float(plumber_page.height)
    return sum(1 for ch in plumber_page.chars
               if MARGIN * height <= (float(ch["top"]) + float(ch["bottom"])) / 2 <= (1 - MARGIN) * height)


def _scan_sized(plumber_page) -> bool:
    """Whether one image covers at least SCAN_AREA of the page (a scan, not a logo)."""
    area = float(plumber_page.width) * float(plumber_page.height)
    for image in plumber_page.images:
        width = min(float(image["x1"]), float(plumber_page.width)) - max(float(image["x0"]), 0.0)
        height = min(float(image["bottom"]), float(plumber_page.height)) - max(float(image["top"]), 0.0)
        if area > 0 and width > 0 and height > 0 and width * height >= SCAN_AREA * area:
            return True
    return False


def _plumber_table(found, index: int) -> PageTable:
    """A ruled table: each cell's text (`extract()`) and box; a merged cell once, its spans from the grid lines."""
    rows = found.rows
    texts = found.extract()
    xs = sorted({cell[0] for row in rows for cell in row.cells if cell is not None})
    tops = sorted({cell[1] for row in rows for cell in row.cells if cell is not None})
    cells = []
    for r, row in enumerate(rows, start=1):
        for c, bbox in enumerate(row.cells, start=1):
            if bbox is None:
                continue
            col_span = max(1, sum(1 for x in xs if bbox[0] <= x < bbox[2] - 0.01))
            row_span = max(1, sum(1 for t in tops if bbox[1] <= t < bbox[3] - 0.01))
            text = texts[r - 1][c - 1] or ""
            cells.append(TableCell(row=r, column=c, text=text, box=round_box(bbox), row_span=row_span, col_span=col_span))
    n_cols = max((len(row.cells) for row in rows), default=0)
    return PageTable(index=index, box=round_box(found.bbox), n_rows=len(rows), n_cols=n_cols, cells=tuple(cells),
                     engine="pdfplumber")


def _cells_box(table: PageTable) -> Box | None:
    boxes = [c.box for c in table.cells if c.box is not None]
    return union_box(boxes) if boxes else None


def _overlap(a: Box, b: Box) -> float:
    """The share of the smaller box that the two boxes have in common."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return width * height / smaller if smaller > 0 else 0.0


def overlap(a: Box, b: Box) -> float:
    """The share of the smaller box that two boxes have in common (the anchor check's measure)."""
    return _overlap(a, b)


# --- the layout ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    page: int
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> float:
        return min(w.box[1] for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.box[3] for w in self.words)

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 1.0)

    @property
    def key(self) -> tuple[int, int]:
        return self.page, self.words[0].index

    @property
    def locator(self) -> str:
        return word_span(self.page, self.words)


@dataclass
class _Para:
    lines: list[Line]
    assigned: str | None = None           # "context" (of a table), "caption"

    @property
    def page(self) -> int:
        return self.lines[0].page

    @property
    def top(self) -> float:
        return self.lines[0].top

    @property
    def bottom(self) -> float:
        return self.lines[-1].bottom

    @property
    def words(self) -> list[Word]:
        return [w for line in self.lines for w in line.words]

    def share(self) -> float:
        words = self.words
        return sum(1 for w in words if has_number(w.text)) / len(words) if words else 0.0


def _in_box(word: Word, box: Box | None) -> bool:
    if box is None:
        return False
    cx, cy = (word.box[0] + word.box[2]) / 2, (word.box[1] + word.box[3]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def page_lines(page: Page, *, skip: frozenset[int] = frozenset()) -> list[Line]:
    """The lines of the words in no table of a page (and not in `skip`), in reading order; a line is a run of
    consecutive words, so its span locator names exactly its words."""
    boxes = [t.box for t in page.tables if t.box is not None]
    lines: list[Line] = []
    current: list[Word] = []
    for word in page.words:
        if word.index in skip or any(_in_box(word, b) for b in boxes):
            if current:
                lines.append(Line(page.number, tuple(current)))
                current = []
            continue
        if current and abs(word.box[1] - current[0].box[1]) > Y_TOLERANCE:
            lines.append(Line(page.number, tuple(current)))
            current = []
        current.append(word)
    if current:
        lines.append(Line(page.number, tuple(current)))
    return lines


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def caption_key(text: str) -> str:
    """A caption with "continued" and its kin set aside (brackets, case and spacing too); numbers are kept."""
    found = _CONTINUED.sub(" ", unicodedata.normalize("NFKC", text))
    return " ".join(found.casefold().split()).rstrip(" -–—:;,.")


def _between(page: Page, upper: float, lower: float) -> bool:
    """Whether a table of the page lies between two heights."""
    return any(t.box is not None and t.box[1] >= upper - 1 and t.box[3] <= lower + 1 for t in page.tables)


def _furniture(pages: Sequence[Page], lines: dict[int, list[Line]]) -> set[tuple[int, int]]:
    marks: set[tuple[int, int]] = set()
    with_text = [p for p in pages if lines.get(p.number)]
    for page in pages:
        for line in lines.get(page.number, ()):
            if _in_margin(line, page) and _PAGE_NUMBER.fullmatch(line.text.strip()):
                marks.add(line.key)
    if len(with_text) < 2:
        return marks
    groups: dict[str, list[Line]] = {}
    for page in pages:
        for line in lines.get(page.number, ()):
            margin = _in_margin(line, page)
            if margin or not has_number(line.text):
                groups.setdefault(_norm(line.text), []).append(line)
            if margin:
                groups.setdefault("#margin#" + _margin_key(line.text, page.number), []).append(line)
    for group in groups.values():
        if len(group) < 2:
            continue
        for line in group:
            pages_here = {other.page for other in group if abs(other.top - line.top) <= SAME_PLACE}
            if len(pages_here) >= 2 and 2 * len(pages_here) > len(with_text):
                marks.add(line.key)
    return marks


def _in_margin(line: Line, page: Page) -> bool:
    return line.top < MARGIN * page.height or line.bottom > (1 - MARGIN) * page.height


def _margin_key(text: str, page: int) -> str:
    """A margin line with its page number set aside ("Page 3", "Page 3 of 12", "3/12", "3 of 12", or a number equal to
    the page number at either end): its other numbers are kept, so lines that differ in them are not one line."""
    words = _PAGE_TOKEN.sub(" # ", _norm(text)).split()
    for k in (0, len(words) - 1):
        if words and words[k].strip("-–—()[]") == str(page):
            words[k] = "#"
    return " ".join(words)


def _pieces(line: Line) -> list[Line]:
    """A line cut at its wide gaps (more than PIECE_GAP line heights between two words)."""
    out, current = [], [line.words[0]]
    for word in line.words[1:]:
        if word.box[0] - current[-1].box[2] > PIECE_GAP * line.height:
            out.append(Line(line.page, tuple(current)))
            current = []
        current.append(word)
    out.append(Line(line.page, tuple(current)))
    return out


def _across(words: Sequence[Word], box: Box) -> bool:
    """Whether words stand over (or under) a box: their horizontal extent overlaps the box's."""
    return min(w.box[0] for w in words) < box[2] and max(w.box[2] for w in words) > box[0]


def _cut_beside(page: Page, lines: list[Line]) -> list[Line]:
    """The page's lines, each line that runs over tables side by side cut where its pieces stand over different
    tables (the captions or footnotes of each)."""
    boxes = [t.box for t in page.tables if t.box is not None]
    if len(boxes) < 2:
        return lines
    out = []
    for line in lines:
        pieces = _pieces(line)
        current = list(pieces[0].words)
        for before, piece in pairwise(pieces):
            over_before = {k for k, box in enumerate(boxes) if _across(before.words, box)}
            over = {k for k, box in enumerate(boxes) if _across(piece.words, box)}
            if over_before and over and over_before.isdisjoint(over):
                out.append(Line(line.page, tuple(current)))
                current = []
            current += piece.words
        out.append(Line(line.page, tuple(current)))
    return out


def _caption_line(page: Page, table: PageTable, lines: list[Line],
                  taken: set[tuple[int, int]]) -> tuple[Line, tuple[Line, ...]] | None:
    """(the caption directly above a table, the lines it is made of), or None. The candidate is the nearest line above
    the table and across its width, no table between, within CONTEXT_GAP line heights. It is the caption when it is a
    paragraph of its own, or when it begins with "Table" or "Figure"; when it ends a paragraph of at most CONTEXT_LINES
    lines that begins so (a caption wrapped over lines), the caption is that paragraph. The last line of a prose
    paragraph is no caption: the paragraph stays whole."""
    if table.box is None:
        return None
    above = sorted((ln for ln in lines if ln.bottom <= table.box[1] + 1 and ln.key not in taken and _across(ln.words, table.box)),
                   key=lambda ln: (ln.bottom, ln.words[0].index))
    if not above:
        return None
    line = above[-1]
    if table.box[1] - line.bottom > CONTEXT_GAP * line.height or _between(page, line.bottom, table.box[1]):
        return None
    para = [line]
    for prev in reversed(above[:-1]):
        gap = para[0].top - prev.bottom
        if not -Y_TOLERANCE <= gap <= LINE_GAP * max(prev.height, para[0].height) or _between(page, prev.bottom, para[0].top):
            break
        para.insert(0, prev)
    if len(para) == 1:
        return line, (line,)
    if _CAPTION_START.match(para[0].text) and len(para) <= CONTEXT_LINES:
        words = tuple(w for ln in para for w in ln.words)
        if all(b.index == a.index + 1 for a, b in pairwise(words)):
            return Line(page.number, words), tuple(para)
    if _CAPTION_START.match(line.text):
        return line, (line,)
    return None


def _row_texts(table: PageTable, row: int) -> list[str]:
    cells = table_cells(table)
    return [" ".join(cells[(row, c)][0].split()) for c in range(1, table.n_cols + 1) if (row, c) in cells]


def _header_like(texts: Sequence[str]) -> bool:
    return any(texts) and not any(is_numeric_text(t) for t in texts if t)


@dataclass
class _Group:
    """A table region being built: its parts (page, table) with their captions and repeated header rows."""

    parts: list[tuple[Page, PageTable, int, Line | None]] = field(default_factory=list)


def locate(pages: Sequence[Page], figures: Sequence[Figure], file_sha256: str, *, raw_boxes: dict[tuple[int, int], tuple[float, float, float, float]],
           table_like_share: float) -> dict[str, object]:
    """Regions, outside items and figures of the pages (see the module docstring)."""
    all_lines = {p.number: _cut_beside(p, page_lines(p)) for p in pages}
    by_number = {p.number: p for p in pages}
    # captions first: a repeated line directly above a table is its caption, never furniture
    captions: dict[tuple[int, int], Line] = {}
    caption_keys: set[tuple[int, int]] = set()                  # every line a caption is made of
    for page in pages:
        taken: set[tuple[int, int]] = set()
        for table in sorted(page.tables, key=lambda t: (t.box[1] if t.box else 0.0, t.index)):
            found = _caption_line(page, table, all_lines[page.number], taken)
            if found is not None:
                captions[(page.number, table.index)] = found[0]
                taken |= {ln.key for ln in found[1]}
        caption_keys |= taken
    furniture = (_furniture(pages, all_lines) | {ln.key for found in all_lines.values() for ln in found if _goes_on(ln)}) \
        - caption_keys
    for key, line in list(captions.items()):
        if line.key in furniture:
            del captions[key]
    lines = {n: [ln for ln in found if ln.key not in furniture and ln.key not in caption_keys]
             for n, found in all_lines.items()}
    groups = _join(pages, captions, lines)
    paras = {p.number: _paragraphs(p, lines[p.number]) for p in pages}
    regions: list[Region] = []
    outside: list[OutsideItem] = []
    contexts: list[tuple[str, Line]] = []
    for group in groups:
        rid = _group_region_id(group, file_sha256, raw_boxes)
        last_page, last_table, _rep, _cap = group.parts[-1]
        for para in _below(last_page, last_table, paras[last_page.number]):
            para.assigned = "context"
            contexts += [(rid, line) for line in para.lines]
        first_page, first_table, _rep, first_caption = group.parts[0]
        for para in _above(first_page, first_table, first_caption, paras[first_page.number]):
            para.assigned = "context"
            contexts += [(rid, line) for line in para.lines]
        regions.append(_table_region(group, rid))
    for rid, line in contexts:
        outside.append(OutsideItem(where=line.locator, text=clip(line.text), numeric=has_number(line.text), region=rid))
    for page in pages:
        regions += _text_regions(page, paras[page.number], file_sha256, table_like_share)
        for line in all_lines[page.number]:
            if line.key in furniture:
                outside.append(OutsideItem(where=line.locator, text=clip(line.text), numeric=has_number(line.text),
                                           furniture=True))
    figure_regions, figure_furniture = _figure_regions(pages, figures, file_sha256)
    order = {p.number: k for k, p in enumerate(pages)}
    regions += figure_regions
    outside += figure_furniture
    regions.sort(key=lambda r: (order.get(_first_page(r), 0), _region_top(r, by_number)))
    outside.sort(key=lambda o: (order.get(_page_of_locator(o.where), 0), _top_of_locator(o.where)))
    return {"figures": tuple(figures), "regions": tuple(regions), "outside": tuple(outside)}


def _first_page(region: Region) -> int:
    return int(re.match(r"p:([0-9]+)", region.where).group(1))


def _page_of_locator(where: str) -> int:
    return int(re.match(r"p:([0-9]+)", where).group(1))


def _top_of_locator(where: str) -> float:
    match = re.search(r"@(-?[0-9.]+),(-?[0-9.]+),", where)
    return float(match.group(2)) if match else 0.0


def _region_top(region: Region, pages: dict[int, Page]) -> float:
    page = pages.get(_first_page(region))
    if page is None:
        return 0.0
    if region.kind == "table" and region.parts:
        box = page.tables[region.parts[0].table - 1].box
        return box[1] if box else 0.0
    match = re.fullmatch(r"p:[0-9]+/w:([0-9]+)-[0-9]+", region.where)
    if match:
        return page.words[int(match.group(1)) - 1].box[1]
    return _top_of_locator(region.where)


def _join(pages: Sequence[Page], captions: dict[tuple[int, int], Line], lines: dict[int, list[Line]]) -> list[_Group]:
    """The table regions: each ruled table, a table continued from the page before joined to its region."""
    groups: list[_Group] = []
    last_group: dict[int, _Group] = {}           # page -> the group of its last table
    for page in pages:
        ordered = sorted(page.tables, key=lambda t: (t.box[1] if t.box else 0.0, t.index))
        for k, table in enumerate(ordered):
            caption = captions.get((page.number, table.index))
            target = None
            if k == 0 and page.number - 1 in last_group:
                target = _continues(page, table, caption, last_group[page.number - 1], lines)
            if target is None:
                target = _Group()
                groups.append(target)
                repeated = 0
            else:
                repeated = _repeated_rows(target.parts[0][1], table)
            target.parts.append((page, table, repeated, caption))
        if ordered:
            last_group[page.number] = next(g for g in groups if g.parts[-1][1] is ordered[-1]
                                           and g.parts[-1][0].number == page.number)
    return groups


def _header_band(table: PageTable) -> int:
    """The leading rows of a table that may be its header: those above its first row whose first cell is a bare number
    (a time, a subject number: a data row). A header of times across ("", "0.5", "1") is in the band."""
    cells = table_cells(table)
    band = 0
    while band < table.n_rows and not is_numeric_text(cells.get((band + 1, 1), ("", None))[0]):
        band += 1
    return band


def _repeated_rows(first: PageTable, table: PageTable) -> int:
    """How many leading rows of a continued part repeat the first part's header rows (its header band). A data row
    that happens to equal the first part's (a pre-dose "0 | BLQ" in each period) is never dropped."""
    count, band = 0, min(_header_band(first), table.n_rows)
    while count < band and _row_texts(first, count + 1) == _row_texts(table, count + 1):
        count += 1
    return count


def _goes_on(line: Line) -> bool:
    """A line that only says the table goes on."""
    return _CONTINUATION_NOTE.fullmatch(unicodedata.normalize("NFKC", line.text).strip()) is not None


def _continues(page: Page, table: PageTable, caption: Line | None, earlier: _Group,
               lines: dict[int, list[Line]]) -> _Group | None:
    prev_page, prev_table, _rep, _cap = earlier.parts[-1]
    first_table, first_caption = earlier.parts[0][1], earlier.parts[0][3]
    if prev_table.box is None or table.box is None or table.n_cols != first_table.n_cols:
        return None
    if any(ln.top >= prev_table.box[3] - 1 and not _goes_on(ln) for ln in lines[prev_page.number]):
        return None                                                    # the earlier part is not the last block
    if any(ln.bottom <= table.box[1] + 1 and not _goes_on(ln) for ln in lines[page.number]):
        return None                                                    # text other than its caption stands above it
    if caption is not None and _goes_on(caption):
        caption = None                                                 # "(continued)" alone: no caption of its own
    if caption is not None and (first_caption is None or caption_key(caption.text) != caption_key(first_caption.text)):
        return None
    header, first_row = _row_texts(first_table, 1), _row_texts(table, 1)
    if header != first_row and _header_like(first_row):
        return None                                                    # another header: another table
    return earlier


def _group_region_id(group: _Group, file_sha256: str, raw_boxes: dict[tuple[int, int], tuple[float, float, float, float]]) -> str:
    page, table, _rep, _cap = group.parts[0]
    box = raw_boxes.get((page.number, table.index)) or table.box
    first_row = [c.text for c in sorted((c for c in table.cells if c.row == 1), key=lambda c: c.column)]
    if box is None:
        return region_id(f"p:{page.number}/t:{table.index}", file_sha256)
    return pdf_table_region_id(page.number, box, first_row, file_sha256)


def _table_region(group: _Group, rid: str) -> Region:
    parts, numeric, n_rows = [], 0, 0
    for page, table, repeated, caption in group.parts:
        parts.append(RegionPart(page=page.number, table=table.index, n_rows=table.n_rows, header_rows_repeated=repeated,
                                caption=_caption_text(caption)))
        numeric += sum(1 for c in table.cells if c.row > repeated and has_number(c.text))
        n_rows += table.n_rows - repeated
    first_page, first_table, _rep, caption = group.parts[0]
    return Region(id=rid, kind="table", where=f"p:{first_page.number}/t:{first_table.index}", parts=tuple(parts),
                  caption=_caption_text(caption), caption_locator=caption.locator if caption else None,
                  n_rows=n_rows, n_cols=first_table.n_cols, numeric_cells=numeric)


def _caption_text(caption: Line | None) -> str:
    """A caption's text: its lines (one, or a caption wrapped over lines) joined by a line break, as a sheet's."""
    if caption is None:
        return ""
    return "\n".join(" ".join(w.text for w in line) for line in lines_of_words(caption.words))


def _paragraphs(page: Page, lines: list[Line]) -> list[_Para]:
    out: list[_Para] = []
    for line in lines:
        if out:
            prev = out[-1].lines[-1]
            gap = line.top - prev.bottom
            if -Y_TOLERANCE <= gap <= LINE_GAP * max(prev.height, line.height) and not _between(page, prev.bottom, line.top):
                out[-1].lines.append(line)
                continue
        out.append(_Para([line]))
    return out


def _below(page: Page, table: PageTable, paras: list[_Para]) -> list[_Para]:
    if table.box is None:
        return []
    taken, edge, count = [], table.box[3], 0
    for para in sorted((p for p in paras if p.top >= table.box[3] - 1), key=lambda p: p.top):
        if not _across(para.words, table.box):
            continue                                            # beside the table (under its neighbour)
        if para.assigned or _between(page, edge, para.top) or para.top - edge > CONTEXT_GAP * para.lines[0].height:
            break
        if count + len(para.lines) > CONTEXT_LINES:
            break
        taken.append(para)
        count += len(para.lines)
        edge = para.bottom
    return taken


def _above(page: Page, table: PageTable, caption: Line | None, paras: list[_Para]) -> list[_Para]:
    if table.box is None:
        return []
    edge = caption.top if caption is not None else table.box[1]
    taken = []
    for para in sorted((p for p in paras if p.bottom <= edge + 1), key=lambda p: -p.bottom):
        if not _across(para.words, table.box):
            continue
        if (para.assigned or len(para.lines) != 1 or len(taken) == CONTEXT_LINES or _between(page, para.bottom, edge)
                or edge - para.bottom > CONTEXT_GAP * para.lines[0].height):
            break
        taken.append(para)
        edge = para.top
    return taken


def _text_regions(page: Page, paras: list[_Para], file_sha256: str, share: float) -> list[Region]:
    """Prose and unruled-table regions of a page's paragraphs that are no table's context, run by run (a table or a
    context line ends a run)."""
    tops = sorted((t.box[1], t.box[3]) for t in page.tables if t.box is not None)
    items: list[tuple[float, str, _Para | None]] = [(top, "table", None) for top, _bottom in tops]
    items += [(p.top, "para", p) for p in paras]
    items.sort(key=lambda i: (i[0], 0 if i[1] == "table" else 1))
    regions: list[Region] = []
    run: list[_Para] = []
    for _top, kind, para in items:
        if kind == "table" or para is None or para.assigned:
            regions += _run_regions(page, run, file_sha256, share)
            run = []
            continue
        run.append(para)
    regions += _run_regions(page, run, file_sha256, share)
    return regions


def _near(upper: _Para, lower: _Para) -> bool:
    return lower.top - upper.bottom <= CONTEXT_GAP * upper.lines[-1].height


def _words_of(found: Sequence[_Para]) -> list[Word]:
    return [w for p in found for w in p.words]


def _share_of(found: Sequence[_Para]) -> float:
    words = _words_of(found)
    return sum(1 for w in words if has_number(w.text)) / len(words) if words else 0.0


def _table_like(paras: Sequence[_Para], share: float) -> list[bool]:
    """Which paragraphs of a run are an unruled table. A paragraph whose share of words holding a number reaches the
    threshold is one when it has at least 2 lines or stands next to another such paragraph (rows spaced wider than a
    paragraph's lines); a one-line paragraph of columns (cut into pieces by wide gaps, no "Table" or "Figure" at its
    start) directly above is its header row, while the block's share still reaches the threshold."""
    numeric = [p.share() >= share for p in paras]
    near = [_near(a, b) for a, b in pairwise(paras)]
    flags = [numeric[k] and (len(paras[k].lines) >= 2 or (k > 0 and numeric[k - 1] and near[k - 1])
                             or (k + 1 < len(paras) and numeric[k + 1] and near[k])) for k in range(len(paras))]
    for k in range(len(paras) - 2, -1, -1):
        if flags[k] or not flags[k + 1] or not near[k] or len(paras[k].lines) != 1:
            continue
        line = paras[k].lines[0]
        if len(_pieces(line)) < 2 or _CAPTION_START.match(line.text):
            continue
        end = k + 1
        while end < len(paras) and flags[end]:
            end += 1
        if _share_of(paras[k:end]) >= share:
            flags[k] = True
    return flags


def _run_regions(page: Page, paras: list[_Para], file_sha256: str, share: float) -> list[Region]:
    """A run of paragraphs as regions: each block of unruled-table paragraphs a `table_like_text` region (its caption
    the one-line paragraph directly above it), the paragraphs between them `prose` regions."""
    flags = _table_like(paras, share)
    regions: list[Region] = []
    k = 0
    prose: list[_Para] = []

    def where(found: Sequence[_Para]) -> str:
        words = _words_of(found)
        return f"p:{page.number}/w:{words[0].index}-{words[-1].index}"

    def close_prose() -> None:
        if prose:
            at = where(prose)
            regions.append(Region(id=region_id(at, file_sha256), kind="prose", where=at, n_rows=sum(len(p.lines) for p in prose),
                                  numeric_cells=sum(1 for w in _words_of(prose) if has_number(w.text))))
            prose.clear()

    while k < len(paras):
        if not flags[k]:
            prose.append(paras[k])
            k += 1
            continue
        end = k
        while end < len(paras) and flags[end]:
            end += 1
        block = paras[k:end]
        caption = None
        if prose and len(prose[-1].lines) == 1 and _near(prose[-1], block[0]):
            caption = prose.pop().lines[0]
        close_prose()
        at = where(block)
        regions.append(Region(id=region_id(at, file_sha256), kind="table_like_text", where=at,
                              caption=caption.text if caption else "", caption_locator=caption.locator if caption else None,
                              n_rows=sum(len(p.lines) for p in block),
                              numeric_cells=sum(1 for w in _words_of(block) if has_number(w.text))))
        k = end
    close_prose()
    return regions


def _figure_regions(pages: Sequence[Page], figures: Sequence[Figure],
                    file_sha256: str) -> tuple[list[Region], list[OutsideItem]]:
    """An image at the same place and of the same size on most pages (a logo) is furniture; every other image is a
    figure region."""
    regions, outside = [], []
    for figure in figures:
        where = figure_locator(figure)
        same = {other.page for other in figures if (other.width, other.height) == (figure.width, figure.height)
                and other.box is not None and figure.box is not None
                and all(abs(a - b) <= SAME_PLACE for a, b in zip(other.box, figure.box, strict=True))}
        if len(pages) >= 2 and len(same) >= 2 and 2 * len(same) > len(pages):
            outside.append(OutsideItem(where=where, text=clip(f"image {figure.name}".strip()), numeric=False, furniture=True))
        else:
            regions.append(Region(id=region_id(where, file_sha256), kind="figure", where=where))
    return regions, outside


# --- prose paragraphs of a stored document ---------------------------------------------------------------------------


def region_paragraphs(doc: SourceDocument, region: Region) -> list[ProseParagraph]:
    match = re.fullmatch(r"p:([0-9]+)/w:([0-9]+)-([0-9]+)", region.where)
    if match is None:
        raise ValueError(f"not a word range: {region.where!r}")
    page = page_of(doc, int(match.group(1)))
    first, last = int(match.group(2)), int(match.group(3))
    skip = set()
    for item in doc.outside:
        span = re.fullmatch(r"p:([0-9]+)/w:([0-9]+)-([0-9]+)@.*", item.where)
        if span and int(span.group(1)) == page.number:
            skip |= set(range(int(span.group(2)), int(span.group(3)) + 1))
    for other in doc.regions:
        if other.caption_locator and other.caption_locator.startswith(f"p:{page.number}/w:"):
            span = re.fullmatch(r"p:[0-9]+/w:([0-9]+)-([0-9]+)@.*", other.caption_locator)
            if span:
                skip |= set(range(int(span.group(1)), int(span.group(2)) + 1))
    skip |= {w.index for w in page.words if not first <= w.index <= last}
    paras = _paragraphs(page, page_lines(page, skip=frozenset(skip)))
    heights = sorted(line.height for p in paras for line in p.lines)
    body = heights[len(heights) // 2] if heights else 0.0
    out: list[ProseParagraph] = []
    heading, heading_at = "", None
    for k, para in enumerate(paras, start=1):
        words = para.words
        text = " ".join(w.text for w in words)
        is_heading = len(para.lines) == 1 and (para.lines[0].height > body + 0.5
                                                or (len(text) <= 80 and not text.rstrip().endswith((".", ":", ";", ","))))
        out.append(ProseParagraph(index=k, text=text, locator=f"p:{page.number}/w:{words[0].index}-{words[-1].index}",
                                  heading="" if is_heading else heading, heading_locator=None if is_heading else heading_at))
        if is_heading:
            heading, heading_at = text, para.lines[0].locator
    return out


def figure_locator(figure: Figure) -> str:
    return format_locator(FigureRef(page=figure.page, index=figure.index, box=figure.box))
