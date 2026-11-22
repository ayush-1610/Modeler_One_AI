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

`document_text` turns a parsed document into numbered parts (a PDF page, a sheet, a Word body) of plain lines: what
the agents read, and what a quote is checked against (`find_quote`). The numbers themselves are read from the parsed
document's cells and words, never from these lines.
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


def read_delivery(uploads: Iterable[tuple[str, bytes]], *, ocr: OcrEngine | None = None) -> list[RoomFile]:
    """Every real file of the uploads (archives unpacked), read, with duplicates marked."""
    expanded: list[tuple[str, bytes]] = []
    out: list[RoomFile] = []
    for path, data in uploads:
        if is_junk(path):
            continue
        if PurePosixPath(path).suffix.lower() == ".zip":
            try:
                members = zip_members(data, path)
            except ValueError as exc:   # a damaged or protected archive is listed with its reason
                out.append(RoomFile(path=path, name=PurePosixPath(path).name, sha256=hashlib.sha256(data).hexdigest(),
                                    size_bytes=len(data), kind="archive", read_as=PurePosixPath(path).name,
                                    state="unreadable", reason=str(exc)))
                continue
            expanded.extend((f"{m}", b) for m, b in members if not is_junk(m))
        else:
            expanded.append((path, data))
    by_bytes: dict[str, str] = {}
    by_text: dict[str, str] = {}
    for path, data in expanded:
        sha = hashlib.sha256(data).hexdigest()
        if sha in by_bytes:
            first = next(f for f in out if f.path == by_bytes[sha])
            out.append(first.model_copy(update={"path": path, "name": PurePosixPath(path).name,
                                                "duplicate_of": by_bytes[sha], "document": None}))
            continue
        room = read_file(path, data, ocr=ocr)
        by_bytes[sha] = path
        if room.text_sha256 and room.state in ("read", "partly_read") and len(_normal_text_of(room)) > 40:
            if room.text_sha256 in by_text:
                room = room.model_copy(update={"same_content_as": by_text[room.text_sha256]})
            else:
                by_text[room.text_sha256] = path
        out.append(room)
    return out


def _normal_text_of(room: RoomFile) -> str:
    return "" if room.document is None else _normal("\n".join(ln for _, lines in document_text(room.document) for ln in lines))


def _normal(text: str) -> str:
    """Text for comparing contents and finding quotes: NFKC, one space, lower case, numbers as numbers (0.50 = 0.5)."""
    text = unicodedata.normalize("NFKC", text).replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"(?<![\d.])(\d+)\.(\d*?)0+(?![\d])", lambda m: m.group(1) + ("." + m.group(2) if m.group(2) else ""), text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _lines_of_words(words) -> list[str]:
    rows: list[list] = []
    for word in sorted(words, key=lambda w: (w.box[1], w.box[0])):
        if rows and abs(rows[-1][0].box[1] - word.box[1]) <= LINE_GAP_POINTS:
            rows[-1].append(word)
        else:
            rows.append([word])
    lines = []
    for row in rows:
        row.sort(key=lambda w: w.box[0])
        heights = sorted(w.box[3] - w.box[1] for w in row)
        gap = COLUMN_GAP_EM * heights[len(heights) // 2]
        line = row[0].text
        for a, b in pairwise(row):
            line += (" | " if b.box[0] - a.box[2] > gap else " ") + b.text
        lines.append(line)
    return lines


def document_text(doc: SourceDocument) -> list[tuple[str, list[str]]]:
    """The document as numbered parts of plain lines: ("p3", lines) per PDF page, ("sheet:Name", rows as
    tab-joined cells) per sheet, ("body", lines) for Word and text files."""
    parts: list[tuple[str, list[str]]] = []
    for page in doc.pages:
        parts.append((f"p{page.number}", _lines_of_words(page.words)))
    for sheet in doc.sheets:
        rows: dict[int, dict[int, str]] = {}
        for cell in sheet.cells:
            rows.setdefault(cell.row, {})[cell.column] = cell.text
        lines = []
        for r in sorted(rows):
            cols = rows[r]
            lines.append("\t".join(cols.get(c, "") for c in range(1, max(cols) + 1)))
        parts.append((f"sheet:{sheet.name}", lines))
    if doc.body:
        lines = []
        for item in doc.body:
            if item.kind == "paragraph" and item.paragraph is not None and item.paragraph.text.strip():
                lines.append(item.paragraph.text)
            elif item.kind == "table" and item.table is not None:
                grid: dict[int, dict[int, str]] = {}
                for cell in item.table.cells:
                    grid.setdefault(cell.row, {})[cell.column] = cell.text.replace("\n", " ")
                for r in sorted(grid):
                    lines.append(" | ".join(grid[r].get(c, "") for c in range(1, max(grid[r]) + 1)))
        parts.append(("body", lines))
    return parts


def find_quote(doc: SourceDocument, quote: str) -> tuple[str, int] | None:
    """Where a quote occurs in the document (part, 1-based line of its start), comparing normalised text and ignoring
    line breaks and column marks; None when it does not occur."""
    want = _normal(quote).replace(" | ", " ")
    if len(want) < 3:
        return None
    for part, lines in document_text(doc):
        normal = [_normal(ln).replace(" | ", " ") for ln in lines]
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
