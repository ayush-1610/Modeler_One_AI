"""Reading a client's delivery for the Data room (plan 2026-11-21 v2 §5 stage 1, §9 "Inventory", "Tables"): no AI.

`read_delivery` takes the uploaded files (a zip, many files, or both) and returns one `RoomFile` per real file:
- archives unpacked (one nested level); the operating system's leftovers (`__MACOSX/`, `._*`, `.DS_Store`) dropped;
- text exports that are tables (`.txt`, `.dat`, `.prn`, `.asc`, `.tab`, `.out` with a consistent tab, comma or
  semicolon layout) read as delimited tables, so every value has its cell;
- images (a screenshot of an email, a photographed table) read as a one-page scan;
- PDFs read with our OCR engine for pages that have no text layer (a scan, or text printed as outlines), and pages
  whose text is drawn turned (a landscape table on a portrait page) first turned upright (`upright_pdf`): read as
  printed they come out backwards and transposed;
- duplicates found twice: the same bytes, and the same content in another format (a `.txt` and a `.dat` of one table).

`document_parts` turns a parsed document into numbered parts (a PDF page, a sheet, a Word body) of lines of located
cells: what the agents read, what a table description points into (part, line, cell), and what a quote is checked
against (`find_quote`). Every cell keeps where it came from (its words' box on a page, its A1 address on a sheet), so
a value read from it is shown at its place.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections.abc import Iterable
from itertools import pairwise
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

from modeler_intake.ocr import image_to_pdf
from modeler_intake.source import parse_document, zip_members
from modeler_intake.source_model import OcrEngine, SourceDocument

TABLE_TEXT_SUFFIXES = (".txt", ".dat", ".prn", ".asc", ".tab", ".out", ".lst")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp")
_JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
LINE_GAP_POINTS = 3.0       # words whose tops differ by at most this many points share a line
COLUMN_GAP_EM = 0.8         # a gap between two words of a line wider than this many text heights is a column
                            # break, written as " | " (a word space is about 0.3; a scan's columns are 1 and more)


def _orientation(page) -> int:
    """The angle (0, 90, 180, 270) most of a page's characters are drawn at; 0 when no angle holds 60 % of them."""
    votes: dict[int, int] = {}
    for char in page.chars:
        a, b, _c, _d = char["matrix"][:4]
        angle = (90 if b > 0 else 270) if abs(b) > abs(a) else (180 if a < 0 else 0)
        votes[angle] = votes.get(angle, 0) + 1
    if not votes:
        return 0
    angle, n = max(votes.items(), key=lambda kv: kv[1])
    return angle if n >= 0.6 * sum(votes.values()) else 0


def upright_pdf(data: bytes) -> tuple[bytes, tuple[int, ...]]:
    """The PDF with every page whose text is drawn turned rotated so the text reads left to right, and the angle of each
    page (0 for a page left as it was); the same bytes when no page is turned."""
    import pdfplumber
    from pypdf import PdfWriter, Transformation
    from pypdf.generic import RectangleObject

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            angles = tuple(_orientation(p) for p in pdf.pages)
    except Exception:  # noqa: BLE001 - a PDF pdfplumber cannot open is left to the reader, which reports it
        return data, ()
    if not any(angles):
        return data, angles
    writer = PdfWriter(clone_from=io.BytesIO(data))
    for page, angle in zip(writer.pages, angles, strict=False):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        x0, y0 = float(page.mediabox.left), float(page.mediabox.bottom)
        if angle == 90:
            page.add_transformation(Transformation().translate(-x0, -y0).rotate(-90).translate(0, width))
            page.mediabox = RectangleObject([0, 0, height, width])
        elif angle == 270:
            page.add_transformation(Transformation().translate(-x0, -y0).rotate(90).translate(height, 0))
            page.mediabox = RectangleObject([0, 0, height, width])
        elif angle == 180:
            page.add_transformation(Transformation().translate(-x0, -y0).rotate(180).translate(width, height))
            page.mediabox = RectangleObject([0, 0, width, height])
        if angle:
            page.cropbox = page.mediabox
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), angles


class RoomFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str                          # as delivered, inside the archive (Part D/Synopsis.pdf)
    name: str                          # the file's own name
    sha256: str
    size_bytes: int
    kind: str                          # pdf, docx, workbook, delimited, text, image, archive, other
    read_as: str                       # the name the reader was given (a .dat read as .tsv)
    state: str                         # read, partly_read, unsupported, unreadable
    reason: str = ""
    pages: int = 0
    ocr_pages: tuple[int, ...] = ()    # pages read by OCR
    duplicate_of: str | None = None    # path of the first file with the same bytes
    same_content_as: str | None = None # path of the first file with the same content in another format
    text_sha256: str = ""              # of the normalised text (for duplicates and caching)
    turned_pages: tuple[int, ...] = () # pages turned upright before reading (their text was drawn rotated)
    reading_copy: bool = False         # the document was read from a copy (turned pages, an image as a PDF, a
                                       # delimited export as .tsv): the source viewer shows the copy
    document: SourceDocument | None = None


def is_junk(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    base = parts[-1] if parts else path
    return "__MACOSX" in parts or base.startswith("._") or base.lower() in _JUNK_NAMES


def _decode(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def sniff_delimiter(data: bytes) -> str | None:
    """The delimiter of a text export that is a table (most lines split into the same number of fields, at least 3),
    else None."""
    text = _decode(data[:200_000])
    if text is None or "\x00" in text:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip()][:200]
    if len(lines) < 3:
        return None
    for delimiter in ("\t", ";", ",", "|"):
        widths = [len(next(csv.reader([ln], delimiter=delimiter))) for ln in lines]
        common = max(set(widths), key=widths.count)
        if common >= 3 and widths.count(common) >= 0.8 * len(widths):
            return delimiter
    return None


def _kind(doc: SourceDocument | None, suffix: str, delimited: bool) -> str:
    if delimited:
        return "delimited"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if doc is None:
        return "other"
    return {"xlsx": "workbook", "xlsm": "workbook", "xls": "workbook", "csv": "delimited", "tsv": "delimited",
            "docx": "docx", "pdf": "pdf", "text": "text", "markdown": "text", "json": "text", "zip": "archive"}.get(
        str(doc.format), "other")


def read_file(path: str, data: bytes, *, ocr: OcrEngine | None = None) -> RoomFile:
    """One delivered file, read by the right reader (see the module docstring)."""
    name = PurePosixPath(path.replace("\\", "/")).name
    suffix = PurePosixPath(name).suffix.lower()
    read_as, payload, delimited, turned = name, data, False, ()
    if suffix in TABLE_TEXT_SUFFIXES:
        delimiter = sniff_delimiter(data)
        if delimiter is not None:
            delimited = True
            read_as = f"{name}.{'tsv' if delimiter == chr(9) else 'csv'}"
            if delimiter not in ("\t", ","):
                text = _decode(data) or ""
                out = io.StringIO()
                csv.writer(out).writerows(csv.reader(io.StringIO(text), delimiter=delimiter))
                payload = out.getvalue().encode("utf-8")
    elif suffix == ".pdf" or data[:5] == b"%PDF-":
        payload, angles = upright_pdf(data)
        turned = tuple(i + 1 for i, a in enumerate(angles) if a)
    elif suffix in IMAGE_SUFFIXES:
        try:
            payload, read_as = image_to_pdf(data), f"{name}.pdf"
        except Exception as exc:  # noqa: BLE001 - a damaged image is reported, not raised
            sha = hashlib.sha256(data).hexdigest()
            return RoomFile(path=path, name=name, sha256=sha, size_bytes=len(data), kind="image", read_as=name,
                            state="unreadable", reason=f"the image could not be opened: {exc}")
    doc = parse_document(payload, read_as, ocr=ocr)
    sha = hashlib.sha256(data).hexdigest()
    ocr_pages = tuple(p.number for p in doc.pages if p.needs_ocr and p.words)
    text = "\n".join(line for part in document_text(doc) for line in part[1])
    return RoomFile(path=path, name=name, sha256=sha, size_bytes=len(data), kind=_kind(doc, suffix, delimited),
                    read_as=read_as, state=str(doc.state), reason=doc.reason, pages=len(doc.pages),
                    ocr_pages=ocr_pages, text_sha256=hashlib.sha256(_normal(text).encode()).hexdigest(),
                    turned_pages=turned, reading_copy=payload is not data, document=doc)


def reading_pdf(name: str, data: bytes) -> bytes | None:
    """The PDF whose pages `read_file` read, made again from the file's bytes exactly as it made it (a PDF turned upright,
    an image as a one-page scan), so a cell's box (points, top-left origin) falls on the same place of the page shown;
    None for a file read as sheets or a body (a delimited export, a workbook, a Word or text file)."""
    suffix = PurePosixPath(name.replace("\\", "/")).suffix.lower()
    if suffix in TABLE_TEXT_SUFFIXES:
        return None
    if suffix == ".pdf" or data[:5] == b"%PDF-":
        return upright_pdf(data)[0]
    if suffix in IMAGE_SUFFIXES:
        return image_to_pdf(data)
    return None


def page_png(pdf: bytes, page: int, *, scale: float = 1.5) -> bytes:
    """One page (1-based) of a PDF drawn as a PNG at `scale` × 72 dpi (pdfium, as the OCR engine draws it); IndexError
    for a page the PDF does not have."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf)
    try:
        if not 1 <= page <= len(document):
            raise IndexError(f"the file has {len(document)} pages, not page {page}")
        image = document[page - 1].render(scale=scale).to_pil()
    finally:
        document.close()
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def expand_uploads(uploads: Iterable[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[RoomFile]]:
    """The real files of the uploads (archives unpacked, leftovers dropped), and the archives that could not be opened."""
    expanded: list[tuple[str, bytes]] = []
    unreadable: list[RoomFile] = []
    for path, data in uploads:
        if is_junk(path):
            continue
        if PurePosixPath(path).suffix.lower() == ".zip":
            try:
                members = zip_members(data, path)
            except ValueError as exc:   # a damaged or protected archive is listed with its reason
                unreadable.append(RoomFile(path=path, name=PurePosixPath(path).name, sha256=hashlib.sha256(data).hexdigest(),
                                           size_bytes=len(data), kind="archive", read_as=PurePosixPath(path).name,
                                           state="unreadable", reason=str(exc)))
                continue
            expanded.extend((_utf8_name(m), b) for m, b in members if not is_junk(m))
        else:
            expanded.append((path, data))
    return expanded, unreadable


_COPY_NAME = re.compile(r"(?i)(?:[\s_-]*-?\s*copy(?:\s*\(\d+\))?|\s*\(\d+\)|[\s_-]+(?:dup|duplicate))(?=\.[^.]+$)|^copy of ")


def _copy_named(name: str) -> bool:
    """A file name that marks a copy: "x - Copy.xlsx", "x (1).pdf", "Copy of x.docx", "x_duplicate.csv"."""
    return bool(_COPY_NAME.search(name))


def mark_duplicates(files: list[tuple[str, bytes, RoomFile | None]]) -> list[RoomFile]:
    """The files in order, each read once: a later file with the same bytes is a duplicate of the first (no document),
    one with the same content in another format names the first (`same_content_as`). `files` holds (path, bytes, the
    file read), the read file None for a repeat of earlier bytes."""
    out: list[RoomFile] = []
    by_bytes: dict[str, int] = {}                  # bytes -> the primary's place in `out`
    by_text: dict[str, str] = {}
    for path, data, room in files:
        sha = hashlib.sha256(data).hexdigest()
        if sha in by_bytes:
            i = by_bytes[sha]
            first = out[i]
            if _copy_named(first.name) and not _copy_named(PurePosixPath(path).name):
                # the original's name wins over "… - Copy.xlsx" or "…(1).pdf", whichever the archive listed first (a new
                # delivery, 2026-11-24: the copy became the primary and the original its duplicate)
                out[i] = first.model_copy(update={"path": path, "name": PurePosixPath(path).name})
                out.append(first.model_copy(update={"duplicate_of": path, "same_content_as": None, "document": None}))
                by_text = {k: (path if v == first.path else v) for k, v in by_text.items()}
                continue
            out.append(first.model_copy(update={"path": path, "name": PurePosixPath(path).name, "duplicate_of": first.path,
                                                "same_content_as": None, "document": None}))
            continue
        assert room is not None
        by_bytes[sha] = len(out)
        if room.text_sha256 and room.state in ("read", "partly_read") and len(_normal_text_of(room)) > 40:
            if room.text_sha256 in by_text:
                room = room.model_copy(update={"same_content_as": by_text[room.text_sha256]})
            else:
                by_text[room.text_sha256] = path
        out.append(room)
    return out


def read_delivery(uploads: Iterable[tuple[str, bytes]], *, ocr: OcrEngine | None = None) -> list[RoomFile]:
    """Every real file of the uploads (archives unpacked), read, with duplicates marked."""
    expanded, unreadable = expand_uploads(uploads)
    seen: set[str] = set()
    read: list[tuple[str, bytes, RoomFile | None]] = []
    for path, data in expanded:
        sha = hashlib.sha256(data).hexdigest()
        read.append((path, data, None if sha in seen else read_file(path, data, ocr=ocr)))
        seen.add(sha)
    return unreadable + mark_duplicates(read)


def _utf8_name(name: str) -> str:
    """A member name as its maker wrote it: an archive made without the UTF-8 flag (macOS's own) has its UTF-8 names
    read as cp437 ("17-06-138 ΓÇô Cinacalcet" for "17-06-138 – Cinacalcet"); a name that is not such a misreading is kept."""
    try:
        fixed = name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    return fixed if fixed != name else name


def _normal_text_of(room: RoomFile) -> str:
    return "" if room.document is None else _normal("\n".join(ln for _, lines in document_text(room.document) for ln in lines))


def _normal(text: str) -> str:
    """Text for comparing contents and finding quotes: NFKC, one space, lower case, numbers as numbers (0.50 = 0.5)."""
    text = unicodedata.normalize("NFKC", text).replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"(?<![\d.])(\d+)\.(\d*?)0+(?![\d])", lambda m: m.group(1) + ("." + m.group(2) if m.group(2) else ""), text)
    return re.sub(r"\s+", " ", text).strip().lower()


class LineCell(BaseModel):
    """One cell of a line: a run of words between column gaps (a page), a sheet cell, a Word table cell, a paragraph."""

    model_config = ConfigDict(frozen=True)

    text: str
    box: tuple[float, float, float, float] | None = None   # a page cell: its words' box, points, top-left origin
    ref: str = ""                                           # a sheet cell: its A1 address; a Word cell: t<table>/r<row>/c<col>


class Line(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int                       # 1-based within its part
    cells: tuple[LineCell, ...]

    @property
    def text(self) -> str:
        """The line as the agents read it: cells joined by " | " (an empty sheet cell stays as an empty place)."""
        return " | ".join(c.text for c in self.cells)


class Part(BaseModel):
    """A numbered part of a document: a PDF page (p3), a sheet (sheet:Name) or a Word/text body (body)."""

    model_config = ConfigDict(frozen=True)

    name: str
    page: int | None = None
    width: float | None = None
    height: float | None = None
    lines: tuple[Line, ...] = ()


def _page_lines(words) -> list[Line]:
    rows: list[list] = []
    for word in sorted(words, key=lambda w: (w.box[1], w.box[0])):
        if rows and abs(rows[-1][0].box[1] - word.box[1]) <= LINE_GAP_POINTS:
            rows[-1].append(word)
        else:
            rows.append([word])
    lines = []
    for number, row in enumerate(rows, start=1):
        row.sort(key=lambda w: w.box[0])
        heights = sorted(w.box[3] - w.box[1] for w in row)
        gap = COLUMN_GAP_EM * heights[len(heights) // 2]
        groups: list[list] = [[row[0]]]
        for a, b in pairwise(row):
            if b.box[0] - a.box[2] > gap:
                groups.append([b])
            else:
                groups[-1].append(b)
        cells = tuple(LineCell(text=" ".join(w.text for w in g),
                               box=(min(w.box[0] for w in g), min(w.box[1] for w in g), max(w.box[2] for w in g),
                                    max(w.box[3] for w in g))) for g in groups)
        lines.append(Line(number=number, cells=cells))
    return lines


def _a1(row: int, column: int) -> str:
    letters = ""
    while column:
        column, rest = divmod(column - 1, 26)
        letters = chr(65 + rest) + letters
    return f"{letters}{row}"


def _title_once(row: int, cols: dict[int, str], origins: dict[int, str]) -> None:
    """A sheet row whose only text is one merged cell (a title merged across the table) keeps that text once, in its
    first cell (the new deliveries, 2026-11-24: a listing's three title lines read as 17 copies each, wherever an agent
    or a column label looked). A merged cell beside other text (a group header over its columns, "Subject" merged down
    two header rows) keeps its copies: each labels its own column or row. A row of copies only (a title merged down as
    well) keeps one empty place, so every line keeps its number."""
    filled = {origins[c] for c, text in cols.items() if text.strip()}
    copies = [c for c, text in cols.items() if text.strip() and origins[c] != _a1(row, c)]
    if len(filled) != 1 or not copies:
        return
    (origin,) = filled
    text = cols[copies[0]]
    here = [c for c in cols if origins[c] == origin == _a1(row, c)]
    first = min(cols)
    cols.clear()
    if here:
        cols[here[0]] = text
    else:
        cols[first] = ""


def document_parts(doc: SourceDocument) -> list[Part]:
    """The document as numbered parts of lines of located cells: one part per PDF page, per sheet, and the Word or text
    body. What the agents read, what a table description points into, and what a quote is checked against."""
    parts: list[Part] = []
    for page in doc.pages:
        parts.append(Part(name=f"p{page.number}", page=page.number, width=page.width, height=page.height,
                          lines=tuple(_page_lines(page.words))))
    for sheet in doc.sheets:
        rows: dict[int, dict[int, str]] = {}
        origins: dict[int, dict[int, str]] = {}
        for cell in sheet.cells:
            rows.setdefault(cell.row, {})[cell.column] = cell.text
            origins.setdefault(cell.row, {})[cell.column] = cell.merged_from or _a1(cell.row, cell.column)
        for r, cols in rows.items():
            _title_once(r, cols, origins[r])
        lines = []
        for number, r in enumerate(sorted(rows), start=1):
            cols = rows[r]
            lines.append(Line(number=number, cells=tuple(LineCell(text=cols.get(c, ""), ref=_a1(r, c))
                                                        for c in range(1, max(cols) + 1))))
        parts.append(Part(name=f"sheet:{sheet.name}", lines=tuple(lines)))
    if doc.body:
        lines = []
        for item in doc.body:
            if item.kind == "paragraph" and item.paragraph is not None and item.paragraph.text.strip():
                for text in item.paragraph.text.splitlines() or [item.paragraph.text]:
                    if text.strip():
                        lines.append(Line(number=len(lines) + 1, cells=(LineCell(text=text, ref=f"para{item.paragraph.index}"),)))
            elif item.kind == "table" and item.table is not None:
                grid: dict[int, dict[int, str]] = {}
                for cell in item.table.cells:
                    grid.setdefault(cell.row, {})[cell.column] = cell.text.replace("\n", " ")
                for r in sorted(grid):
                    cells = tuple(LineCell(text=grid[r].get(c, ""), ref=f"t{item.table.index}/r{r}/c{c}")
                                  for c in range(1, max(grid[r]) + 1))
                    lines.append(Line(number=len(lines) + 1, cells=cells))
        parts.append(Part(name="body", lines=tuple(lines)))
    return parts


def document_text(doc: SourceDocument) -> list[tuple[str, list[str]]]:
    """The document's parts as plain lines (`document_parts`, each line's cells joined by " | ")."""
    return [(part.name, [line.text for line in part.lines]) for part in document_parts(doc)]


def unmarked(text: str) -> str:
    """Normalised text with the column marks taken out (a quote is written without them)."""
    return re.sub(r"\s+", " ", re.sub(r"\s*\|\s*", " ", _normal(text))).strip()


def find_quote(doc: SourceDocument, quote: str) -> tuple[str, int] | None:
    """Where a quote occurs in the document (part, 1-based line of its start), comparing normalised text and ignoring
    line breaks and column marks; None when it does not occur."""
    want = unmarked(quote)
    if len(want) < 3:
        return None
    for part, lines in document_text(doc):
        normal = [unmarked(ln) for ln in lines]
        joined, starts, pos = "", [], 0
        for ln in normal:
            starts.append(pos)
            joined += ln + " "
            pos = len(joined)
        at = joined.find(want)
        if at >= 0:
            line = max(i for i, s in enumerate(starts) if s <= at) + 1
            return part, line
    return None


def numbers_in(text: str) -> list[float]:
    """The numbers written in a text (1,234.5 and 1.234,5 are not guessed: a comma is a thousands separator only
    between groups of three digits)."""
    out = []
    for m in re.finditer(r"(?<![\w.])[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-−]?\d+(?:\.\d+)?", unicodedata.normalize("NFKC", text)):
        token = m.group(0).replace("−", "-").replace(",", "")
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out
