"""Checks across a delivery that no one table or fact holds (plan 2026-11-26 §7 phase 3; the corpus audit's R03 and
R07, and two cases its projects met). Each is said with its evidence, never acted on: the modeler decides.

- **Concentrations that look simulated** (R03: "reject an observed dataset whose time grid equals a simulator output
  grid, or whose provenance is a simulation export"; P25 used simulated curves as observed, P29 another project's
  simulated subjects as targets): a concentration table whose times are a dense, equally spaced grid (`GRID_MIN_TIMES`
  or more), whose values are mostly unrounded (6 significant figures or more, as no assay reports), or whose file names
  a simulator.
- **Lot conflicts** (R07: "dose, strength, lot and batch in each observed dataset must match the protocol/CSR"; P04 had
  lot CA1021001 against …002): one lot number given for two products, or one product's lot numbers in two files that
  differ by a character or two (one lot written two ways, or two lots?).
- **A file about another drug:** a used document (a PDF, a Word file, a text) that never names the project's drug.
- **Personal data:** a subject listing with identifying columns (name, initials, date of birth, address, phone,
  e-mail, a national or medical record number), or a date of birth in a document's text. A client delivery should
  hold pseudonymised subjects only.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise

from modeler_intake.room import document_parts
from modeler_intake.source_model import SourceDocument
from modeler_project.dataroom.clinical import samples_from
from modeler_project.dataroom.model import CheckedFact, Chip, FileView, Problem, ReadTable

GRID_MIN_TIMES = 40          # a dense grid: this many equally spaced sampling times or more
UNROUNDED_DIGITS = 6         # an assay reports 2 to 4 significant figures; a simulator writes 6 or more
UNROUNDED_SHARE = 0.9        # of the table's measured values
_SIMULATOR = re.compile(r"\bSimcyp\b|\bGastroPlus\b|\bPK-?Sim\b|\bMoBi\b|\bDDDPlus\b|\bPhoenix\s+NLME\b|\bSimulat(?:ed|ion)\s+"
                        r"(?:plasma\s+)?(?:concentration|profile|result|output)s?\b|\bvirtual\s+(?:subject|population|trial)s?\b",
                        re.IGNORECASE)
_LISTING = re.compile(r"(?i)\b(?:subject|subj|patient|volunteer|screening|randomi[sz]ation)\b|\bsex\b|\bgender\b|\bage\b")
_PERSONAL_COLUMN = re.compile(
    r"(?i)^\s*(?:(?:subject|patient|volunteer|full|first|last|family|given)\s*)?name\s*$|^\s*initials?\s*$|"
    r"\bdate\s+of\s+birth\b|^\s*d\.?o\.?b\.?\s*$|\bbirth\s*date\b|^\s*(?:home\s+)?address\s*$|^\s*e-?mail\s*$|"
    r"\b(?:tele)?phone\b|\bmobile\b|\bsocial\s+security\b|\bnational\s+id|\bpassport\b|\bmedical\s+record\b|"
    r"^\s*mrn\s*$|\bnhs\s+number\b|\baadhaa?r\b")
_BIRTH_IN_TEXT = re.compile(r"(?i)\b(?:date\s+of\s+birth|d\.o\.b\.?|dob)\s*[:=]?\s*\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}")
_TEXT_KINDS = ("pdf", "docx", "text", "pptx")


def _significant(text: str) -> int:
    digits = re.sub(r"^[-+]?0*\.?0*", "", re.sub(r"[eE].*$", "", text.strip()).replace(",", ""))
    return len(re.sub(r"\D", "", digits))


def _chip(table: ReadTable) -> Chip:
    d = table.description
    return Chip(file=d.file, sha256=table.sha256, part=d.part, line=d.first_line)


def simulated_concentrations(tables: Sequence[ReadTable], docs: Mapping[str, SourceDocument]) -> list[Problem]:
    out: list[Problem] = []
    for table in tables:
        samples, _p, _u = samples_from(table)
        if not samples:
            continue
        where = f"the concentration table on {table.description.part} of {table.description.file}"
        said: list[str] = []
        times = sorted({s.time_h for s in samples if s.time_h > 0})
        steps = {round(b - a, 6) for a, b in pairwise(times)}
        if len(times) >= GRID_MIN_TIMES and len(steps) == 1:
            said.append(f"{len(times)} sampling times every {steps.pop():g} h, a simulator's output grid")
        measured = [s.text for s in samples if s.value is not None]
        if len(measured) >= 20 and sum(1 for t in measured if _significant(t) >= UNROUNDED_DIGITS) >= UNROUNDED_SHARE * len(measured):
            said.append(f"its values unrounded ({UNROUNDED_DIGITS} significant figures or more, as no assay reports)")
        doc = docs.get(table.sha256)
        if doc is not None:
            text = " ".join(ln.text for part in document_parts(doc) for ln in part.lines[:400])
            if m := _SIMULATOR.search(text) or _SIMULATOR.search(table.description.file):
                said.append(f"its file names {m.group(0)!r}")
        if said:
            out.append(Problem(code="LOOKS_SIMULATED", where=_chip(table), message=(
                f"{where} looks like a simulation, not observed data: {'; '.join(said)}. Confirm with the client that "
                "these are measured concentrations before they are used (R03)")))
    return out


def _distance(a: str, b: str) -> int:
    """The edit distance of two short codes."""
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, start=1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def lot_conflicts(facts: Iterable[CheckedFact]) -> list[Problem]:
    batches = [f for f in facts if f.ok and f.fact.field == "product.batch" and f.fact.value.strip()]
    by_lot: dict[str, dict[str, CheckedFact]] = defaultdict(dict)
    by_product: dict[str, dict[str, CheckedFact]] = defaultdict(dict)
    for f in batches:
        lot = re.sub(r"[\s_]", "", f.fact.value.upper())
        product = (f.fact.product or f.fact.subject).strip()
        if product:
            by_lot[lot].setdefault(product.lower(), f)
            by_product[product.lower()].setdefault(lot, f)
    out: list[Problem] = []
    for lot, products in sorted(by_lot.items()):
        if len(products) > 1:
            named = sorted(f.fact.product or f.fact.subject for f in products.values())
            out.append(Problem(code="LOT_TWO_PRODUCTS", where=next(iter(products.values())).chip, message=(
                f"lot {lot} is given for {' and for '.join(named)} (R07): one lot is one product; which is it?")))
    for lots in by_product.values():
        items = sorted(lots.items())
        for i, (a, fa) in enumerate(items):
            for b, fb in items[i + 1:]:
                if fa.fact.file != fb.fact.file and len(a) >= 5 and 0 < _distance(a, b) <= 2:
                    product = fa.fact.product or fa.fact.subject
                    out.append(Problem(code="LOT_CONFLICT", where=fb.chip, message=(
                        f"{product}: lot {a} in {fa.fact.file}, {b} in {fb.fact.file} (R07): one lot written two ways, "
                        "or two lots? The dose, strength and lot of each dataset must match the protocol and the CSR")))
    return out


def not_the_drug(files: Sequence[FileView], docs: Mapping[str, SourceDocument], names: Sequence[str]) -> list[Problem]:
    words = sorted({w for n in names for w in re.findall(r"[A-Za-z][A-Za-z-]{4,}", n)
                    if not re.fullmatch(r"(?i)tablets?|capsules?|reference|test|product|solution|suspension|"
                                        r"reformulated|original|generic|brand|film-coated|extended|release", w)},
                   key=str.lower)
    if not words:
        return []
    pattern = re.compile(r"(?i)\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")
    out: list[Problem] = []
    for f in files:
        doc = docs.get(f.sha256)
        if doc is None or f.duplicate_of or (f.triage is not None and f.triage.purpose != "used") or doc.format not in _TEXT_KINDS:
            continue
        parts = document_parts(doc)
        text = "\n".join(ln.text for part in parts for ln in part.lines)
        if len(text) >= 300 and not pattern.search(text) and not pattern.search(f.path):
            # the file's first line, so the page shows the check on the file it concerns (plan §9, slice 5d)
            first = next(((part, ln) for part in parts for ln in part.lines if ln.text.strip()), None)
            where = Chip(file=f.path, sha256=f.sha256, part=first[0].name, line=first[1].number,
                         text=first[1].text[:200]) if first else None
            out.append(Problem(code="FILE_NAMES_NOT_THE_DRUG", severity="info", where=where, message=(
                f"{f.path} never names {', '.join(words[:3])}: is it about this project's drug? (a corpus delivery held a "
                "document about another drug)")))
    return out


def personal_data(files: Sequence[FileView], docs: Mapping[str, SourceDocument]) -> list[Problem]:
    out: list[Problem] = []
    for f in files:
        doc = docs.get(f.sha256)
        if doc is None or f.duplicate_of:
            continue
        found: list[str] = []
        where: Chip | None = None                    # the first line it was found on (plan §9, slice 5d)
        for part in document_parts(doc):
            for line in part.lines[:5] if part.name.startswith("sheet:") else ():
                cells = [c.text.strip() for c in line.cells]
                if sum(1 for c in cells if _LISTING.search(c)) >= 1 and len(cells) >= 3:
                    named = [f"column {c!r} on {part.name}" for c in cells if c and _PERSONAL_COLUMN.search(c)]
                    if named and where is None:
                        where = Chip(file=f.path, sha256=f.sha256, part=part.name, line=line.number, text=line.text[:200])
                    found += named
            if not part.name.startswith("sheet:") and _BIRTH_IN_TEXT.search("\n".join(ln.text for ln in part.lines)):
                found.append(f"a date of birth on {part.name}")
                # its line (the part's first when the words run across two lines)
                hit = next((ln for ln in part.lines if _BIRTH_IN_TEXT.search(ln.text)), part.lines[0] if part.lines else None)
                if where is None and hit is not None:
                    where = Chip(file=f.path, sha256=f.sha256, part=part.name, line=hit.number, text=hit.text[:200])
        if found:
            found = list(dict.fromkeys(found))
            out.append(Problem(code="PERSONAL_DATA", where=where, message=(
                f"{f.path} holds personal data: {'; '.join(found[:4])}{' …' if len(found) > 4 else ''}. A client delivery "
                "should hold pseudonymised subjects only: ask for it without them, or confirm it may be held")))
    return out


def detect(*, files: Sequence[FileView], docs: Mapping[str, SourceDocument], tables: Sequence[ReadTable],
           facts: Sequence[CheckedFact], drug_names: Sequence[str]) -> list[Problem]:
    """Every check of this module over a delivery."""
    concentrations = [t for t in tables if t.description.kind == "concentrations"]
    return (simulated_concentrations(concentrations, docs) + lot_conflicts(facts) + not_the_drug(files, docs, drug_names)
            + personal_data(files, docs))


__all__ = ["GRID_MIN_TIMES", "UNROUNDED_DIGITS", "detect", "lot_conflicts", "not_the_drug", "personal_data",
           "simulated_concentrations"]
