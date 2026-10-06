"""Sheet triage (plan §10.1 step 3): what each sheet of a client workbook holds, with the header that shows it.

Code first: a template sheet is known by its name and header; any other sheet is classified by the words of its first
rows, and the cell that decided it is quoted. A sheet the words do not decide (no match, or a tie) is left OTHER for
agent A4 or a person. Nothing here reads data: triage only says where to look.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from modeler_intake.client_template import is_template
from modeler_intake.grid import SheetGrid, WorkbookGrid, as_text


class SheetCategory(StrEnum):
    PK_INDIVIDUAL = "PK_INDIVIDUAL"
    PK_SUMMARY = "PK_SUMMARY"
    PK_PARAMETERS = "PK_PARAMETERS"
    DISSOLUTION = "DISSOLUTION"
    PRODUCT_INFO = "PRODUCT_INFO"
    STUDIES = "STUDIES"
    DEMOGRAPHICS = "DEMOGRAPHICS"
    BIOANALYTICAL = "BIOANALYTICAL"
    PHYSCHEM_INVITRO = "PHYSCHEM_INVITRO"
    URINE_FECES = "URINE_FECES"
    OTHER = "OTHER"


TEMPLATE_SHEETS = {"Studies": SheetCategory.STUDIES, "PK_Individual": SheetCategory.PK_INDIVIDUAL,
                   "PK_Summary": SheetCategory.PK_SUMMARY, "PK_Parameters": SheetCategory.PK_PARAMETERS,
                   "Dissolution": SheetCategory.DISSOLUTION, "Product": SheetCategory.PRODUCT_INFO,
                   "Physchem_InVitro": SheetCategory.PHYSCHEM_INVITRO, "Urine_Feces": SheetCategory.URINE_FECES}

# Words that mark a category in a header; each match adds one point. Patterns are matched on lower-cased cell text.
_WORDS: dict[SheetCategory, tuple[str, ...]] = {
    SheetCategory.DISSOLUTION: (r"dissol", r"% ?dissolved", r"\bvessel", r"\bapparatus", r"\brpm\b", r"\bpaddle", r"\bbasket"),
    SheetCategory.PK_INDIVIDUAL: (r"\bsubject", r"\bpatient id", r"\bsubj\b", r"\bindividual"),
    SheetCategory.PK_SUMMARY: (r"\bmean\b", r"\bgeo ?mean", r"\bmedian\b", r"\bsd\b", r"\bcv ?%"),
    SheetCategory.PK_PARAMETERS: (r"\bauc", r"\bcmax", r"\btmax", r"t ?1/2|t½|half-life|thalf", r"\bcl/f", r"\bvz/f"),
    SheetCategory.PRODUCT_INFO: (r"\bbatch\b|\blot\b", r"\bstrength", r"dosage form", r"particle size|\bd50\b", r"polymorph"),
    SheetCategory.DEMOGRAPHICS: (r"\bage\b", r"\bweight\b", r"\bsex\b|\bgender", r"\bbmi\b", r"\bheight\b", r"\brace\b|ethnic"),
    SheetCategory.BIOANALYTICAL: (r"\blloq\b", r"calibration", r"\bqc\b", r"accuracy", r"precision", r"validation"),
    SheetCategory.PHYSCHEM_INVITRO: (r"\blogp\b|\blogd\b", r"\bpka\b", r"solubility", r"\bfu\b|fraction unbound", r"caco|permeab",
                                     r"\bclint\b|microsom|hepatocyte"),
    SheetCategory.URINE_FECES: (r"\burine\b", r"\bfeces\b|\bfaeces\b", r"\bae\b|amount excreted", r"\bfe\b|fraction excreted"),
}
_CONC = re.compile(r"conc|ng/ml|µg/ml|ug/ml|ng/l|nmol/l|µmol/l|plasma")
_TIME = re.compile(r"\btime\b|\bhour|\bh\)|\(h\b|\bmin\b|nominal|sampling")
HEADER_ROWS = 15


@dataclass(frozen=True)
class SheetTriage:
    sheet: str
    category: SheetCategory
    evidence_cell: str = ""       # the cell whose text decided it
    evidence_quote: str = ""      # that text, verbatim
    by: str = "code"              # code | agent:<run> | person
    note: str = ""

    def to_content(self) -> dict[str, str]:
        return {"sheet": self.sheet, "category": self.category.value, "evidence_cell": self.evidence_cell,
                "evidence_quote": self.evidence_quote, "by": self.by, "note": self.note}


def _header_cells(grid: SheetGrid) -> list[tuple[str, str]]:
    cells = []
    for row in range(1, min(grid.max_row, HEADER_ROWS) + 1):
        for column in range(1, grid.max_column + 1):
            cell = grid.cell(row, column)
            text = as_text(cell.value)
            if text and not _is_number(text):
                cells.append((cell.ref, text))
    return cells


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def triage_sheet(grid: SheetGrid) -> SheetTriage:
    """Classify one sheet by the words of its first rows; OTHER when nothing (or a tie) decides it."""
    cells = _header_cells(grid)
    scores: dict[SheetCategory, int] = {}
    first: dict[SheetCategory, tuple[str, str]] = {}
    for category, patterns in _WORDS.items():
        for pattern in patterns:
            hit = next(((ref, text) for ref, text in cells if re.search(pattern, text.lower())), None)
            if hit:
                scores[category] = scores.get(category, 0) + 1
                first.setdefault(category, hit)
    text = " ".join(t.lower() for _, t in cells)
    # a concentration-time table: individual if subjects are named, else a summary when a statistic is named
    if _CONC.search(text) and _TIME.search(text):
        for category in (SheetCategory.PK_INDIVIDUAL, SheetCategory.PK_SUMMARY):
            if category in scores:
                scores[category] += 2
    # a sheet that names its subjects holds individual data; its Mean / SD rows only summarise them (CRO layouts)
    if SheetCategory.PK_INDIVIDUAL in scores:
        scores.pop(SheetCategory.PK_SUMMARY, None)
    if not scores:
        return SheetTriage(grid.name, SheetCategory.OTHER, note="no header word decides it")
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return SheetTriage(grid.name, SheetCategory.OTHER,
                           note=f"undecided between {ranked[0][0].value} and {ranked[1][0].value}")
    best = ranked[0][0]
    ref, quote = first[best]
    return SheetTriage(grid.name, best, evidence_cell=ref, evidence_quote=quote)


def triage(workbook: WorkbookGrid) -> list[SheetTriage]:
    """Every sheet of `workbook`; the template's sheets by name, the README skipped."""
    template = is_template(workbook)
    out = []
    for name, grid in workbook.sheets.items():
        if template and name == "README":
            continue
        if template and name in TEMPLATE_SHEETS:
            if grid.max_row >= 2:
                out.append(SheetTriage(name, TEMPLATE_SHEETS[name], evidence_cell=f"{name}!A1",
                                       evidence_quote=as_text(grid.cell(1, 1).value), note="template sheet"))
            continue
        out.append(triage_sheet(grid))
    return out


def quote_in_header(workbook: WorkbookGrid, sheet: str, cell_ref: str, quote: str) -> bool:
    """Whether `quote` is (part of) the text of `cell_ref` within the first rows of `sheet` (an agent's claim)."""
    grid = workbook.sheets.get(sheet)
    if grid is None or not quote.strip():
        return False
    return any(ref == cell_ref and quote.strip().lower() in text.lower() for ref, text in _header_cells(grid))
