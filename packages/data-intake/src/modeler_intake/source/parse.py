"""Parse once (contracts §6.1): a client file's bytes into one `SourceDocument`, located, with its role and kinds.

`parse_document` is total for content: whatever the bytes hold, it returns a document whose `state` says what was read
(`read`, `partly_read` naming what was not, `unsupported` and why, `unreadable` and why) and never raises for them; an
exception means a bug. The same bytes give the same document (`anchors.sha256_of` equal). `parser_for` names the
parser and its version without parsing: `<SOURCE_VERSION>+<library><library version>`, so a change of these reading
or locating rules (a new SOURCE_VERSION) or a library upgrade is a new version, which re-parses and checks the anchors.

| Format | Parser | Library |
|---|---|---|
| .xlsx .xlsm | workbook | openpyxl |
| .xls | workbook | xlrd |
| .csv .tsv | delimited | the standard library (`csv`) |
| .docx | docx | python-docx |
| .pdf | pdfplumber | pdfplumber (with any engine passed in, named in the version) |
| .txt .md .json | text | the standard library |
| .zip | zip | the standard library (`zipfile`) |
| .png .jpg .jpeg | image | none: unsupported, one figure |
| anything else | none | none: unsupported, "no parser for <ext>" |
"""

from __future__ import annotations

import hashlib
import re
import struct
import sys
from collections.abc import Sequence
from functools import lru_cache
from importlib import metadata
from pathlib import PurePosixPath

from modeler_intake.anchors import AnchorError, FigureRef, SheetCell, format_locator
from modeler_intake.source import archive
from modeler_intake.source.delimited import NotText, read_delimited
from modeler_intake.source.docx import locate_docx, read_docx, unread_reason
from modeler_intake.source.pdf import read_pdf
from modeler_intake.source.regions import locate_sheets, region_id
from modeler_intake.source.roles import classify
from modeler_intake.source.text import read_text
from modeler_intake.source.workbook import read_xls, read_xlsx
from modeler_intake.source.workbook import unread_reason as workbook_unread_reason
from modeler_intake.source_model import (
    ContainerRef,
    Figure,
    FileFormat,
    OcrEngine,
    PdfTableEngine,
    Region,
    SourceDocument,
)

SOURCE_VERSION = "1.0"
MAX_MEMBERS = archive.MAX_MEMBERS
MAX_MEMBER_BYTES = archive.MAX_MEMBER_BYTES          # documents.MAX_BYTES: also the limit of one file
MAX_TOTAL_BYTES = archive.MAX_TOTAL_BYTES
NEEDS_OCR_MAX_CHARS = 20               # reading parameters: a change is a new SOURCE_VERSION
TABLE_LIKE_NUMERIC_SHARE = 0.5

_FORMATS = (
    (".xlsx", "xlsx"), (".xlsm", "xlsm"), (".xls", "xls"), (".csv", "csv"), (".tsv", "tsv"), (".docx", "docx"),
    (".pdf", "pdf"), (".txt", "text"), (".text", "text"), (".md", "markdown"), (".markdown", "markdown"),
    (".json", "json"), (".zip", "zip"), (".png", "image"), (".jpg", "image"), (".jpeg", "image"),
)
_PARSERS = (("xlsx", "workbook"), ("xlsm", "workbook"), ("xls", "workbook"), ("csv", "delimited"), ("tsv", "delimited"),
            ("docx", "docx"), ("pdf", "pdfplumber"), ("text", "text"), ("markdown", "text"), ("json", "text"),
            ("zip", "zip"), ("image", "image"))
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP = b"PK\x03\x04"
_ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")      # the stream a password-protected Office file holds


def _suffix(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower()


def file_format(data: bytes, filename: str) -> FileFormat:
    """The format by the name's extension, corrected by the content's signature where the two disagree in a way a
    reader can follow (a legacy workbook saved as .xlsx, a PDF with no extension)."""
    suffix = _suffix(filename)
    found: FileFormat = next((f for s, f in _FORMATS if s == suffix), "other")
    if found in ("xlsx", "xlsm") and data.startswith(_OLE2):
        return "xls"
    if found == "xls" and data.startswith(_ZIP):
        return "xlsx"
    if found == "other" and data.startswith(b"%PDF"):
        return "pdf"
    return found


@lru_cache(maxsize=8)
def _library(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def _tag(text: str) -> str:
    """An engine's name and version as a version part ([A-Za-z0-9.+_-] only)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", text) or "_"


def parser_for(data: bytes, filename: str, *, pdf_table_engines: Sequence[PdfTableEngine] = (),
               ocr: OcrEngine | None = None) -> tuple[str, str]:
    """(parser, parser_version) of a file, without parsing it. The engines a PDF is read with are part of its version
    (the same keywords as `parse_document`)."""
    fmt = file_format(data, filename)
    parser = next((p for f, p in _PARSERS if f == fmt), "none")
    python = f"python{sys.version_info.major}.{sys.version_info.minor}"
    library = {"xlsx": f"openpyxl{_library('openpyxl')}", "xlsm": f"openpyxl{_library('openpyxl')}",
               "xls": f"xlrd{_library('xlrd')}", "docx": f"python-docx{_library('python-docx')}",
               "pdf": f"pdfplumber{_library('pdfplumber')}"}.get(fmt, python if parser not in ("image", "none") else "")
    version = SOURCE_VERSION + (f"+{library}" if library else "")
    if fmt == "pdf":
        version += "".join(f"+{_tag(e.name)}{_tag(e.version)}" for e in pdf_table_engines)
        version += f"+ocr-{_tag(ocr.name)}{_tag(ocr.version)}" if ocr is not None else ""
    return parser, version


def zip_members(data: bytes, filename: str) -> list[tuple[str, bytes]]:
    """Every file member of a ZIP (name, bytes), one level of nested ZIP expanded (`<inner.zip>/<member>`);
    ValueError for an encrypted member, a damaged archive or a limit passed (MAX_MEMBERS, MAX_MEMBER_BYTES,
    MAX_TOTAL_BYTES)."""
    return archive.zip_members(data, filename, max_members=MAX_MEMBERS, max_member_bytes=MAX_MEMBER_BYTES,
                               max_total_bytes=MAX_TOTAL_BYTES)


def parse_document(data: bytes, filename: str, *, container: ContainerRef | None = None,
                   pdf_table_engines: Sequence[PdfTableEngine] = (), ocr: OcrEngine | None = None) -> SourceDocument:
    """One parse of a file (see the module docstring): never raises for its content."""
    sha = hashlib.sha256(data).hexdigest()
    fmt = file_format(data, filename)
    parser, version = parser_for(data, filename, pdf_table_engines=pdf_table_engines, ocr=ocr)
    base = {"file_sha256": sha, "name": filename, "size_bytes": len(data), "format": fmt, "parser": parser,
            "parser_version": version, "container": container}
    if len(data) > MAX_MEMBER_BYTES:
        return SourceDocument(**base, state="unreadable",
                              reason=f"the file holds {len(data)} bytes, over the limit of {MAX_MEMBER_BYTES}")
    if parser == "none":
        return SourceDocument(**base, state="unsupported", reason=f"no parser for {_suffix(filename) or 'a file with no extension'}")
    if not data:
        return SourceDocument(**base, state="unreadable", reason="the file is empty (0 bytes)")
    if parser == "image":
        return _image(base, data, sha)
    fields = _read(fmt, data, filename, sha, pdf_table_engines=pdf_table_engines, ocr=ocr)
    doc = SourceDocument(**base, **fields)
    if doc.state in ("unreadable", "unsupported"):
        return doc
    return classify(doc)


def _read(fmt: str, data: bytes, filename: str, sha: str, *, pdf_table_engines: Sequence[PdfTableEngine],
          ocr: OcrEngine | None) -> dict[str, object]:
    """The format reader's fields. A library's exception while it opens or reads the bytes (a damaged file) makes the
    document `unreadable` with the reason; locating what was read never catches."""
    if fmt == "pdf":
        return read_pdf(data, sha, table_engines=pdf_table_engines, ocr=ocr, needs_ocr_max_chars=NEEDS_OCR_MAX_CHARS,
                        table_like_share=TABLE_LIKE_NUMERIC_SHARE)
    if fmt in ("xlsx", "xlsm", "xls", "docx") and data.startswith(_OLE2) and _ENCRYPTED_PACKAGE in data:
        return {"state": "unreadable", "reason": "the file is encrypted (a password-protected Office file): a password is needed"}
    if fmt == "zip":
        try:
            members = zip_members(data, filename)
        except ValueError as exc:
            return {"state": "unreadable", "reason": str(exc)}
        return {"state": "read", "members": tuple(name for name, _bytes in members)}
    try:
        unread_cells: tuple[str, ...] = ()
        if fmt in ("xlsx", "xlsm"):
            sheets, warnings, unread_cells = read_xlsx(data)
            fields: dict[str, object] = {"sheets": sheets, "warnings": warnings}
        elif fmt == "xls":
            sheets, warnings, unread_cells = read_xls(data)
            fields = {"sheets": sheets, "warnings": warnings}
        elif fmt in ("csv", "tsv"):
            sheet, encoding, delimiter, warnings = read_delimited(data, filename)
            sheets = (sheet,)
            fields = {"sheets": sheets, "warnings": warnings, "encoding": encoding, "delimiter": delimiter}
        elif fmt == "docx":
            body, figures, warnings, unread = read_docx(data)
            sheets, fields = (), {"body": body, "figures": figures, "warnings": warnings}
        else:
            return read_text(data, sha, table_like_share=TABLE_LIKE_NUMERIC_SHARE)
    except NotText as exc:
        return {"state": "unreadable", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - openpyxl, xlrd, zipfile, csv and python-docx raise many types for a damaged file
        return {"state": "unreadable", "reason": f"the {fmt} file could not be read ({type(exc).__name__}: {exc})"}
    if fmt == "docx":
        regions, outside = locate_docx(fields["body"], fields["figures"], sha)
        if unread:
            return {**fields, "state": "partly_read", "reason": unread_reason(unread), "regions": regions, "outside": outside}
        return {**fields, "state": "read", "regions": regions, "outside": outside}
    named = [s for s in sheets if _anchorable(s.name)]
    regions, outside = locate_sheets(named, sha)
    reasons = [workbook_unread_reason(unread_cells)] if unread_cells else []
    if len(named) < len(sheets):
        lost = ", ".join(repr(s.name) for s in sheets if s not in named)
        reasons.append(f"sheets not located: {lost} (a name no locator can hold: empty, or with a control character)")
    if not reasons:
        return {**fields, "state": "read", "regions": regions, "outside": outside}
    return {**fields, "state": "partly_read", "regions": regions, "outside": outside, "reason": "; ".join(reasons)}


def _anchorable(sheet: str) -> bool:
    try:
        format_locator(SheetCell(sheet=sheet, cell="A1"))
    except AnchorError:
        return False
    return True


def _image(base: dict[str, object], data: bytes, sha: str) -> SourceDocument:
    width, height = image_size(data)
    figure = Figure(index=1, name=str(base["name"]), width=width, height=height)
    where = format_locator(FigureRef(index=1))
    return SourceDocument(**base, state="unsupported", reason="an image has no text layer; no OCR engine is registered",
                          figures=(figure,), regions=(Region(id=region_id(where, sha), kind="figure", where=where),))


def image_size(data: bytes) -> tuple[int, int]:
    """(width, height) in pixels of a PNG or JPEG from its header; (0, 0) when it cannot be read."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        k = 2
        while k + 9 < len(data):
            if data[k] != 0xFF:
                k += 1
                continue
            marker = data[k + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[k + 5:k + 9])
                return width, height
            k += 2 + struct.unpack(">H", data[k + 2:k + 4])[0]
    return 0, 0
