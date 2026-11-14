"""Document role and table kind, by rule (contracts §6.1 "Role and kind"; no LLM).

Table kind: a client-data template's sheets by their name (`triage.TEMPLATE_SHEETS`; its README guide is `not_data`);
any other table by `triage.triage_sheet` on the region's own grid (its caption lines first, then its rows), mapped by
`fields.KIND_OF_CATEGORY`. `kind_evidence` is the deciding cell's locator and its words, or triage's note when nothing
(or a tie) decides it ("unknown").

Document role: a workbook built from the template is `client_template` (`client_template.is_template`); another
workbook or delimited file is a `concentration_listing` when all its tables are individual concentrations, else a
`data_workbook`. A PDF, Word or text file is read by the words of its first pages: a title phrase first (certificate of
analysis, bioanalytical report, dissolution report, product information, clinical study report, synopsis, in that
order), then what `document_reading.inventory` finds there (a design, concentration or NCA table: a study report).
`role_evidence` is the locator and the line that decided it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from modeler_intake.anchors import AnchorError, DocxSpan, SheetCell, TextSpan, format_locator, parse_locator
from modeler_intake.client_template import README, TEMPLATE_ID, is_template
from modeler_intake.document_reading import inventory
from modeler_intake.fields import KIND_OF_CATEGORY, DocumentRole, TableKind
from modeler_intake.grid import Cell, SheetGrid, cell_ref
from modeler_intake.source.regions import a1_place, as_workbook_grid, clip, parse_sheet_range, region_grid, sheet_locator
from modeler_intake.source_model import OutsideItem, Region, RegionGrid, SourceDocument
from modeler_intake.triage import TEMPLATE_SHEETS, triage_sheet

FIRST_PAGES = 3                # a PDF's first pages read for its role
FIRST_PARAGRAPHS = 60          # a Word or text file's first paragraphs (lines) read for its role
_TITLES: tuple[tuple[DocumentRole, re.Pattern[str]], ...] = (
    ("certificate_of_analysis", re.compile(r"(?i)certificate\s+of\s+analysis")),
    ("bioanalytical_report", re.compile(r"(?i)bioanalytical\s+(?:study\s+)?(?:report|method)|method\s+validation\s+report")),
    ("dissolution_report", re.compile(r"(?i)dissolution\s+(?:study\s+|test(?:ing)?\s+)?report|dissolution\s+profiles?\b")),
    ("product_information", re.compile(r"(?i)summary\s+of\s+product\s+characteristics|prescribing\s+information|"
                                       r"package\s+(?:leaflet|insert)|product\s+information")),
    ("study_report", re.compile(r"(?i)clinical\s+study\s+report|\bstudy\s+report\b")),
    ("synopsis", re.compile(r"(?i)\bsynopsis\b")),
)
_HOLDS: tuple[tuple[str, DocumentRole], ...] = (
    ("design", "study_report"), ("pk_table", "study_report"), ("nca", "study_report"), ("demographics", "study_report"),
    ("dissolution", "dissolution_report"), ("bioanalytical", "bioanalytical_report"),
    ("composition", "product_information"),
)


def classify(doc: SourceDocument) -> SourceDocument:
    """The document with each table region's kind and the document's role set."""
    template = doc.format in ("xlsx", "xlsm", "xls") and bool(doc.sheets) and is_template(as_workbook_grid(doc))
    regions = tuple(_with_kind(doc, region, template) for region in doc.regions)
    typed = doc.model_copy(update={"regions": regions})
    role, evidence = document_role(typed, template=template)
    if role == "client_template":
        typed = typed.model_copy(update={"outside": tuple(_own_text(item) for item in typed.outside)})
    return typed.model_copy(update={"role": role, "role_evidence": evidence})


def _own_text(item: OutsideItem) -> OutsideItem:
    """A README cell of a filled client template that still holds the template's own text for that cell (the id line and
    the instructions, `client_template.README`) is furniture: our words, not the client's, so its "Row 1" or "<0.5" is
    never an outside number. Any other cell of that sheet, a line the client changed or a number typed beside or below
    the instructions, stays an outside item and is counted: the sheet is never set aside as a whole."""
    try:
        place = parse_locator(item.where)
    except AnchorError:
        return item
    if not isinstance(place, SheetCell) or place.sheet != "README":
        return item
    row, column = a1_place(place.cell)
    if column == 1 and 1 <= row <= len(README) and item.text.strip() == clip(README[row - 1]).strip():
        return item.model_copy(update={"furniture": True})
    return item


def _with_kind(doc: SourceDocument, region: Region, template: bool) -> Region:
    if region.kind != "table":
        return region
    kind, evidence = table_kind(doc, region, template=template)
    return region.model_copy(update={"table_kind": kind, "kind_evidence": evidence})


def table_kind(doc: SourceDocument, region: Region, *, template: bool = False) -> tuple[TableKind, str]:
    """(kind, evidence) of one table region (see the module docstring)."""
    if template and region.where.startswith("s:"):
        sheet = parse_sheet_range(region.where)[0]
        if sheet == "README":
            return "not_data", f"{sheet_locator('README', 1, 1)}: {TEMPLATE_ID} (the template's column guide)"
        if sheet in TEMPLATE_SHEETS:
            header = next((c.text for s in doc.sheets if s.name == sheet for c in s.cells if (c.row, c.column) == (1, 1)), "")
            return KIND_OF_CATEGORY[TEMPLATE_SHEETS[sheet].value], f"{sheet_locator(sheet, 1, 1)}: {header} (template sheet)"
    grid = region_grid(doc, region.id)
    sheet, places = _triage_grid(grid)
    found = triage_sheet(sheet)
    kind = KIND_OF_CATEGORY[found.category.value]
    if kind == "unknown" or found.evidence_cell not in places:
        return kind, found.note or "no header word decides it"
    return kind, f"{places[found.evidence_cell]}: {found.evidence_quote}"


def _triage_grid(grid: RegionGrid) -> tuple[SheetGrid, dict[str, str]]:
    """The region as a SheetGrid for triage (its caption lines first), and each grid cell's ref -> its true locator."""
    name = "region"
    sheet = SheetGrid(name=name, max_row=len(grid.caption) + grid.n_rows, max_column=max(grid.n_cols, 1))
    places: dict[str, str] = {}
    for row, cell in enumerate(grid.caption, start=1):
        sheet.cells[(row, 1)] = Cell(name, row, 1, cell.value)
        places[cell_ref(name, row, 1)] = cell.locator
    offset = len(grid.caption)
    for (r, c), cell in grid.cells.items():
        sheet.cells[(r + offset, c)] = Cell(name, r + offset, c, cell.value)
        places[cell_ref(name, r + offset, c)] = cell.locator
    return sheet, places


def document_role(doc: SourceDocument, *, template: bool = False) -> tuple[DocumentRole, str]:
    """(role, evidence) of a document (see the module docstring)."""
    if doc.format in ("xlsx", "xlsm", "xls", "csv", "tsv"):
        if template:
            readme = next((s for s in doc.sheets if s.name == "README"), None)
            if readme is not None and any((c.row, c.column) == (1, 1) and c.text.strip() == TEMPLATE_ID for c in readme.cells):
                return "client_template", f"{sheet_locator('README', 1, 1)}: {TEMPLATE_ID}"      # as is_template reads it
            first = next((s for s in doc.sheets if s.name in TEMPLATE_SHEETS), None)
            if first is not None:
                return "client_template", f"{sheet_locator(first.name, 1, 1)}: the template's header"
            return "client_template", "client_template.is_template"
        tables = [r for r in doc.regions if r.kind == "table"]
        if tables and all(r.table_kind == "pk_individual" for r in tables):
            return "concentration_listing", tables[0].kind_evidence
        if tables:
            return "data_workbook", f"{len(tables)} table region{'s' if len(tables) > 1 else ''}: {tables[0].where}"
        return "other", ""
    pages = _first_lines(doc)
    for role, pattern in _TITLES:
        for _page, locator, text in pages:
            if pattern.search(text):
                return role, f"{locator}: {text[:160]}"
    texts: dict[int, list[str]] = {}
    for page, _locator, text in pages:
        texts.setdefault(page, []).append(text)
    numbers = sorted(texts)
    items = inventory(["\n".join(texts[n]) for n in numbers])
    for holds, role in _HOLDS:
        item = next((i for i in items if i.holds == holds), None)
        if item is None:
            continue
        page = numbers[item.page - 1]
        locator = next((loc for p, loc, text in pages if p == page and " ".join(text.split())[:160] == item.line), "")
        return role, f"{locator}: {item.line}" if locator else f"page {page}: {item.line}"
    return "other", ""


def _first_lines(doc: SourceDocument) -> list[tuple[int, str, str]]:
    """(page, locator, text) of the lines of the document's first pages: a PDF's lines (tables aside), a Word file's
    or text file's paragraphs (one page)."""
    out: list[tuple[int, str, str]] = []
    if doc.format == "pdf":
        from modeler_intake.source.pdf import page_lines

        for page in doc.pages[:FIRST_PAGES]:
            out += [(page.number, line.locator, line.text) for line in page_lines(page)]
        return out
    for item in doc.body:
        para = item.paragraph
        if item.kind != "paragraph" or para is None or not para.text.strip():
            continue
        span = (DocxSpan(paragraph=para.index, start=0, end=len(para.text)) if doc.format == "docx"
                else TextSpan(line=para.index, start=0, end=len(para.text)))
        out.append((1, format_locator(span), para.text))
        if len(out) >= FIRST_PARAGRAPHS:
            break
    return out


def kinds(doc: SourceDocument) -> Sequence[tuple[str, TableKind]]:
    """(region id, kind) of each table region (for reports and tests)."""
    return [(r.id, r.table_kind) for r in doc.regions if r.kind == "table"]
