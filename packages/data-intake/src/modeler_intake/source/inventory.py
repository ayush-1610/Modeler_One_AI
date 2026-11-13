"""The format inventory (plan §10, decision 5): what a set of client files holds, by format, before the adapters'
scope is frozen. Counted by rule from the bytes, nothing written.

- `files`: the files given; `by_extension`: every document read (each file, and each member of a ZIP) by its
  lower-cased extension ("(none)" without one); `zip_members`: the documents found inside ZIPs (a nested ZIP's members
  included, as `zip_members` expands them).
- `pdf_native`, `pdf_scanned`, `pdf_mixed`: PDFs whose pages all have a text layer, none has (each page needing OCR),
  or some do and some do not (a page needs OCR as `parse_document` decides it: at most `NEEDS_OCR_MAX_CHARS`
  characters and an image, or a scan-sized image under text in the page's margins only).
- `with_figures`: PDF and Word documents in which `parse_document` finds a figure region, by its own rules, so the
  inventory counts what the pipeline sees: a PDF's on a page with a text layer (a scan is no figure; a logo repeated
  at the same place on most pages is furniture), a Word body's (a logo in the page header is furniture).
- `unsupported`: documents no parser reads (an image needs OCR), by extension; a ZIP that cannot be opened or passes a
  limit is counted under its extension too.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from modeler_intake.anchors import parse_locator
from modeler_intake.source.parse import file_format, parse_document, parser_for, zip_members
from modeler_intake.source_model import SourceDocument


class FormatInventory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    files: int
    by_extension: dict[str, int]
    pdf_native: int
    pdf_scanned: int
    pdf_mixed: int
    with_figures: int
    unsupported: dict[str, int]
    zip_members: int


def _extension(name: str) -> str:
    leaf = name.replace("\\", "/").rsplit("/", 1)[-1]
    return "." + leaf.rsplit(".", 1)[1].lower() if "." in leaf.strip(".") else "(none)"


def _has_figure(doc: SourceDocument) -> bool:
    """Whether a parsed document holds a figure region on a page with a text layer (a Word body has no pages)."""
    needs = {p.number: p.needs_ocr for p in doc.pages}
    for region in doc.regions:
        if region.kind != "figure":
            continue
        page = parse_locator(region.where).page
        if page is None or not needs.get(page, False):
            return True
    return False


def inventory(files: Iterable[tuple[str, bytes]]) -> FormatInventory:
    """The format inventory of (name, bytes) pairs (see the module docstring)."""
    counts = {"files": 0, "native": 0, "scanned": 0, "mixed": 0, "figures": 0, "members": 0}
    by_extension: dict[str, int] = {}
    unsupported: dict[str, int] = {}

    def count(name: str, data: bytes, *, member: bool) -> None:
        ext = _extension(name)
        by_extension[ext] = by_extension.get(ext, 0) + 1
        counts["members"] += int(member)
        fmt = file_format(data, name)
        parser, _version = parser_for(data, name)
        if parser in ("none", "image"):
            unsupported[ext] = unsupported.get(ext, 0) + 1
        elif fmt == "pdf":
            doc = parse_document(data, name)
            if doc.pages:
                needs = [p.needs_ocr for p in doc.pages]
                key = "scanned" if all(needs) else "mixed" if any(needs) else "native"
                counts[key] += 1
                counts["figures"] += int(_has_figure(doc))
        elif fmt == "docx":
            counts["figures"] += int(_has_figure(parse_document(data, name)))
        elif fmt == "zip" and not member:
            try:
                members = zip_members(data, name)
            except ValueError:
                unsupported[ext] = unsupported.get(ext, 0) + 1
                return
            for member_name, member_data in members:
                count(member_name, member_data, member=True)

    for name, data in files:
        counts["files"] += 1
        count(name, data, member=False)
    return FormatInventory(files=counts["files"], by_extension=dict(sorted(by_extension.items())),
                           pdf_native=counts["native"], pdf_scanned=counts["scanned"], pdf_mixed=counts["mixed"],
                           with_figures=counts["figures"], unsupported=dict(sorted(unsupported.items())),
                           zip_members=counts["members"])
