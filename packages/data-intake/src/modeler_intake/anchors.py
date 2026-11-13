"""Anchors: where in a client file a value was read (docs/plans/2026-11-12-intake-contracts.md §4.1).

An anchor is immutable for one `(file sha256, parser, parser version)` and is stored as text:

    anchor   = sha256 "@" parser "/" version "#" locator     ; sha256 [0-9a-f]{64}; parser [a-z0-9_]+; version [A-Za-z0-9.+_-]+
    locator  = "s:" sheet "!" a1                              ; sheet cell (a merged cell: its top-left)
             | "p:" page "/t:" n "/r:" n "/c:" n "@" box     ; PDF table cell
             | "p:" page "/w:" n "-" n "@" box               ; PDF word span (first-last word of the page)
             | "d:t:" n "/r:" n "/c:" n                      ; Word table cell (a merged cell: its top-left)
             | "d:p:" n "/ch:" k "-" k                       ; Word paragraph, characters start-end (end exclusive)
             | "x:l:" n "/ch:" k "-" k                       ; text file line, characters
             | "p:" page "/f:" n "@" box | "d:f:" n          ; figure (on a PDF page; anywhere else)
    range    = "s:" sheet "!" a1 ":" a1 | "p:" page "/t:" n | "d:t:" n | "p:" page "/w:" n "-" n | "d:p:" n "-" n
             | "x:l:" n "-" n
    sheet    = "'" text with every ' doubled "'"              ; always quoted; no control character
    box      = x0 "," top "," x1 "," bottom                   ; PDF points from the page's top-left, 2 decimals
    a1 [A-Z]{1,3}[1-9][0-9]*; n (pages, tables, rows, columns, words, paragraphs, lines, figures) [1-9][0-9]*, 1-based;
    k (character offsets) 0|[1-9][0-9]*, 0-based

Text is accepted only in its one canonical spelling (`parse_locator(t)` formats back to `t`), so two spellings never
name one place. Identity: a sheet cell is its sheet and cell; a PDF cell its page, table, row and column; a PDF span
its page and words; a Word cell or span, a text span and a figure their numbers. A PDF box is carried for the viewer
and for the anchor check after a re-parse, and is never part of the identity (`same_place`).

`canonical` and `sha256_of` live here, in L2, so that intake tests and the L3 stores hash with one canonical form.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Box = tuple[float, float, float, float]


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SheetCell(_B):
    kind: Literal["sheet_cell"] = "sheet_cell"
    sheet: str
    cell: str


class PdfCell(_B):
    kind: Literal["pdf_cell"] = "pdf_cell"
    page: int
    table: int
    row: int
    column: int
    box: Box


class PdfSpan(_B):
    kind: Literal["pdf_span"] = "pdf_span"
    page: int
    first_word: int
    last_word: int
    box: Box


class DocxCell(_B):
    kind: Literal["docx_cell"] = "docx_cell"
    table: int
    row: int
    column: int


class DocxSpan(_B):
    kind: Literal["docx_span"] = "docx_span"
    paragraph: int
    start: int
    end: int


class TextSpan(_B):
    kind: Literal["text_span"] = "text_span"
    line: int
    start: int
    end: int


class FigureRef(_B):
    kind: Literal["figure"] = "figure"
    page: int | None = None
    index: int
    box: Box | None = None


Locator = Annotated[SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef, Field(discriminator="kind")]


class Anchor(_B):
    file_sha256: str
    parser: str
    parser_version: str
    locator: Locator


class AnchorError(ValueError):
    """An anchor, locator or id that is not in the grammar, or names no place."""


# --- the grammar's parts -------------------------------------------------------------------------------------------

_SHA = r"[0-9a-f]{64}"
_PARSER = r"[a-z0-9_]+"
_VERSION = r"[A-Za-z0-9.+_-]+"
_A1 = r"[A-Z]{1,3}[1-9][0-9]*"
_N = r"[1-9][0-9]*"
_K = r"(?:0|[1-9][0-9]*)"
_SHEET = r"'((?:[^'\x00-\x1f\x7f]|'')+)'"
_NUM = r"-?(?:0|[1-9][0-9]*)\.[0-9]{2}"
_BOX = rf"({_NUM}),({_NUM}),({_NUM}),({_NUM})"

_ANCHOR = re.compile(rf"({_SHA})@({_PARSER})/({_VERSION})#(.+)", re.DOTALL)
_LOCATORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sheet_cell", re.compile(rf"s:{_SHEET}!({_A1})")),
    ("pdf_cell", re.compile(rf"p:({_N})/t:({_N})/r:({_N})/c:({_N})@{_BOX}")),
    ("pdf_span", re.compile(rf"p:({_N})/w:({_N})-({_N})@{_BOX}")),
    ("docx_cell", re.compile(rf"d:t:({_N})/r:({_N})/c:({_N})")),
    ("docx_span", re.compile(rf"d:p:({_N})/ch:({_K})-({_K})")),
    ("text_span", re.compile(rf"x:l:({_N})/ch:({_K})-({_K})")),
    ("pdf_figure", re.compile(rf"p:({_N})/f:({_N})@{_BOX}")),
    ("figure", re.compile(rf"d:f:({_N})")),
)
# The grammar's `range` (a region's `where`, a prose paragraph's locator); matched with fullmatch.
RANGE: re.Pattern[str] = re.compile(
    rf"s:{_SHEET}!{_A1}:{_A1}|p:{_N}/t:{_N}|d:t:{_N}|p:{_N}/w:{_N}-{_N}|d:p:{_N}-{_N}|x:l:{_N}-{_N}")

ID_PATTERNS: Mapping[str, re.Pattern[str]] = MappingProxyType({
    "sha256": re.compile(r"^[0-9a-f]{64}$"),
    "extract": re.compile(r"^tx-[0-9a-f]{16}$"),
    "value": re.compile(r"^tx-[0-9a-f]{16}#(0|[1-9][0-9]*)$"),
    "region": re.compile(r"^rg-[0-9a-f]{10}$"),
    "mapping": re.compile(r"^mp-[0-9a-f]{12}$"),
    "file": re.compile(r"^fl-[0-9a-f]{12}$"),
    "line": re.compile(r"^[a-z]{1,3}-[1-9][0-9]*$"),      # a store's line id: f-41, st-5, cf-3, run-7, dl-2 ...
    # the review's two hashed ids, which arrive in requests too (§4.5 Conflict.id, §4.6 CheckResult.id)
    "conflict": re.compile(r"^cx-[0-9a-f]{10}$"),
    "check": re.compile(r"^ck-[0-9a-f]{12}$"),
})


def check_id(kind: str, text: str) -> str:
    """`text` when it is an id of `kind`, else AnchorError: an id from a request is checked before it is used, and no
    path is ever built from one that is not. `kind` is a key of ID_PATTERNS (sha256, extract, value, region, mapping,
    file, line, conflict, check); any other kind is a bug in the caller, not bad input, and raises KeyError."""
    pattern = ID_PATTERNS[kind]
    if not isinstance(text, str) or pattern.fullmatch(text) is None:
        raise AnchorError(f"not a {kind} id: {text!r}")
    return text


# --- format and parse ----------------------------------------------------------------------------------------------


def _positive(*numbers: int) -> None:
    for number in numbers:
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise AnchorError(f"a page, table, row, column, word, paragraph, line or figure is a whole number from 1, "
                              f"not {number!r}")


def _offsets(start: int, end: int) -> None:
    for number in (start, end):
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise AnchorError(f"a character offset is a whole number from 0, not {number!r}")
    if start > end:
        raise AnchorError(f"a span ends before it starts ({start}-{end})")


def _box(box: Box) -> str:
    if len(box) != 4 or not all(isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in box):
        raise AnchorError(f"a box is four finite numbers, not {box!r}")
    return ",".join(f"{round(float(v), 2) + 0.0:.2f}" for v in box)


def format_locator(locator: SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef) -> str:
    """The locator's canonical text (AnchorError for a part outside its character set)."""
    if isinstance(locator, SheetCell):
        if not locator.sheet or re.search(r"[\x00-\x1f\x7f]", locator.sheet) or not re.fullmatch(_A1, locator.cell):
            raise AnchorError(f"not a sheet cell: {locator.sheet!r}!{locator.cell!r}")
        return "s:'" + locator.sheet.replace("'", "''") + "'!" + locator.cell
    if isinstance(locator, PdfCell):
        _positive(locator.page, locator.table, locator.row, locator.column)
        return f"p:{locator.page}/t:{locator.table}/r:{locator.row}/c:{locator.column}@{_box(locator.box)}"
    if isinstance(locator, PdfSpan):
        _positive(locator.page, locator.first_word, locator.last_word)
        if locator.first_word > locator.last_word:
            raise AnchorError(f"a word span ends before it starts ({locator.first_word}-{locator.last_word})")
        return f"p:{locator.page}/w:{locator.first_word}-{locator.last_word}@{_box(locator.box)}"
    if isinstance(locator, DocxCell):
        _positive(locator.table, locator.row, locator.column)
        return f"d:t:{locator.table}/r:{locator.row}/c:{locator.column}"
    if isinstance(locator, DocxSpan):
        _positive(locator.paragraph)
        _offsets(locator.start, locator.end)
        return f"d:p:{locator.paragraph}/ch:{locator.start}-{locator.end}"
    if isinstance(locator, TextSpan):
        _positive(locator.line)
        _offsets(locator.start, locator.end)
        return f"x:l:{locator.line}/ch:{locator.start}-{locator.end}"
    if isinstance(locator, FigureRef):
        _positive(locator.index)
        if locator.page is None and locator.box is None:
            return f"d:f:{locator.index}"
        if locator.page is not None and locator.box is not None:
            _positive(locator.page)
            return f"p:{locator.page}/f:{locator.index}@{_box(locator.box)}"
        raise AnchorError("a figure on a PDF page has both its page and its box; any other figure has neither")
    raise AnchorError(f"not a locator: {locator!r}")


def _floats(groups: tuple[str, ...]) -> Box:
    x0, top, x1, bottom = (float(g) for g in groups)
    return (x0, top, x1, bottom)


def parse_locator(text: str) -> SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef:
    """The locator a text names; AnchorError for text outside the grammar or not in its canonical spelling."""
    if not isinstance(text, str):
        raise AnchorError(f"not a locator: {text!r}")
    for kind, pattern in _LOCATORS:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        g = match.groups()
        locator: SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef
        if kind == "sheet_cell":
            locator = SheetCell(sheet=g[0].replace("''", "'"), cell=g[1])
        elif kind == "pdf_cell":
            locator = PdfCell(page=int(g[0]), table=int(g[1]), row=int(g[2]), column=int(g[3]), box=_floats(g[4:]))
        elif kind == "pdf_span":
            locator = PdfSpan(page=int(g[0]), first_word=int(g[1]), last_word=int(g[2]), box=_floats(g[3:]))
        elif kind == "docx_cell":
            locator = DocxCell(table=int(g[0]), row=int(g[1]), column=int(g[2]))
        elif kind == "docx_span":
            locator = DocxSpan(paragraph=int(g[0]), start=int(g[1]), end=int(g[2]))
        elif kind == "text_span":
            locator = TextSpan(line=int(g[0]), start=int(g[1]), end=int(g[2]))
        elif kind == "pdf_figure":
            locator = FigureRef(page=int(g[0]), index=int(g[1]), box=_floats(g[2:]))
        else:
            locator = FigureRef(index=int(g[0]))
        if format_locator(locator) != text:
            raise AnchorError(f"not the canonical spelling of a locator: {text!r}")
        return locator
    raise AnchorError(f"not a locator: {text!r}")


def _parts(file_sha256: str, parser: str, parser_version: str) -> None:
    if not isinstance(file_sha256, str) or not re.fullmatch(_SHA, file_sha256):
        raise AnchorError(f"not a sha256: {file_sha256!r}")
    if not isinstance(parser, str) or not re.fullmatch(_PARSER, parser):
        raise AnchorError(f"not a parser name: {parser!r}")
    if not isinstance(parser_version, str) or not re.fullmatch(_VERSION, parser_version):
        raise AnchorError(f"not a parser version: {parser_version!r}")


def format_anchor(anchor: Anchor) -> str:
    _parts(anchor.file_sha256, anchor.parser, anchor.parser_version)
    return f"{anchor.file_sha256}@{anchor.parser}/{anchor.parser_version}#{format_locator(anchor.locator)}"


def parse_anchor(text: str) -> Anchor:
    """The anchor a text names; AnchorError for text outside the grammar, also for a part outside its character set."""
    match = _ANCHOR.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        raise AnchorError(f"not an anchor: {text!r}")
    sha, parser, version, locator = match.groups()
    return Anchor(file_sha256=sha, parser=parser, parser_version=version, locator=parse_locator(locator))


def anchor_text(file_sha256: str, parser: str, parser_version: str, locator: str) -> str:
    """The anchor text of a locator text read from that file under that parser version (every part is checked)."""
    _parts(file_sha256, parser, parser_version)
    parse_locator(locator)
    return f"{file_sha256}@{parser}/{parser_version}#{locator}"


def _identity(locator: SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef) -> tuple[Any, ...]:
    if isinstance(locator, SheetCell):
        return (locator.kind, locator.sheet, locator.cell)
    if isinstance(locator, PdfCell):
        return (locator.kind, locator.page, locator.table, locator.row, locator.column)
    if isinstance(locator, PdfSpan):
        return (locator.kind, locator.page, locator.first_word, locator.last_word)
    if isinstance(locator, DocxCell):
        return (locator.kind, locator.table, locator.row, locator.column)
    if isinstance(locator, DocxSpan):
        return (locator.kind, locator.paragraph, locator.start, locator.end)
    if isinstance(locator, TextSpan):
        return (locator.kind, locator.line, locator.start, locator.end)
    return (locator.kind, locator.page, locator.index)


def same_place(a: SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef,
               b: SheetCell | PdfCell | PdfSpan | DocxCell | DocxSpan | TextSpan | FigureRef) -> bool:
    """Whether two locators name one place: equal identity; the box is never compared."""
    return _identity(a) == _identity(b)


# --- one canonical form for hashing --------------------------------------------------------------------------------


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def canonical(value: Any) -> str:
    """json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False); a pydantic model (also one nested
    in a dict or a list) is dumped first with model_dump(mode="json", by_alias=True), so `schema`, not `schema_id`.
    A non-finite number (NaN, an infinity) has no JSON form: ValueError, so that nothing is hashed that cannot be
    stored and read back as it was hashed."""
    return json.dumps(_dump(value) if isinstance(value, BaseModel) else value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False, default=_dump)


def sha256_of(value: Any) -> str:
    """The sha256 of `canonical(value)` (UTF-8), hex."""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()
