"""Code reads what an agent described (plan 2026-11-21 v2 §9 "Verification"): no number is typed by a model.

- `read_table` applies a `TableDescription` to the lines of one part of a document and returns every cell it names,
  each with its place (`Chip`). A line with fewer cells than the table's columns (an empty cell on a page has no
  words) has its cells placed under the columns by their position on the page; a line that cannot be placed is a
  problem, never guessed.
- `check_fact` finds a fact's quote in the document and the value in the quote; a fact whose quote is not in the file,
  or whose value is not in its quote, is refused with the reason.
"""

from __future__ import annotations

import hashlib
import re
import statistics
import unicodedata
from itertools import pairwise

from modeler_intake.room import Line, Part, document_parts, find_quote, numbers_in, unmarked
from modeler_intake.room_specs import Fact, TableDescription
from modeler_intake.source_model import SourceDocument
from modeler_project.dataroom.model import CheckedFact, Chip, Problem, ReadCell, ReadRow, ReadTable

_NUMBER = re.compile(r"^[<>≤≥~]?\s*[-−+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?$|^[-−+]?\.\d+$")


def parse_number(text: str) -> float | None:
    """A cell's number: "12.5", "1,234.5", "−3", "1.2e-3"; None for anything else ("<0.5", "BLQ", ".", "12 (3)")."""
    raw = unicodedata.normalize("NFKC", text).strip().replace("−", "-")
    if not raw or not _NUMBER.match(raw) or raw[0] in "<>≤≥~":
        return None
    if "," in raw and not re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        return None          # a decimal comma or a list: not guessed
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def parts_by_name(doc: SourceDocument) -> dict[str, Part]:
    return {part.name: part for part in document_parts(doc)}


def table_id(sha256: str, desc: TableDescription) -> str:
    return "tb-" + hashlib.sha256(f"{sha256}|{desc.part}|{desc.first_line}|{desc.kind}".encode()).hexdigest()[:12]


def _centre(box: tuple[float, float, float, float]) -> float:
    return (box[0] + box[2]) / 2


def _placed(line: Line, centres: list[float] | None, n: int) -> tuple[list[int | None], str]:
    """For each cell of the line, the 1-based column it stands under; a reason when they cannot be placed."""
    cells = line.cells
    on_page = all(c.box is not None for c in cells)
    if len(cells) == n or not on_page:
        # a sheet's or a Word table's cells keep their columns; a short sheet row only lacks its trailing empty cells
        return list(range(1, len(cells) + 1)), "" if len(cells) <= n else f"{len(cells)} cells, {n} expected"
    if centres is None:
        return list(range(1, len(cells) + 1)), (f"{len(cells)} cells, {n} expected, and no line of the table has every "
                                                "cell to place them by")
    if len(cells) > n:
        return list(range(1, len(cells) + 1)), f"{len(cells)} cells, {n} expected"
    placed: list[int | None] = []
    for cell in cells:
        x = _centre(cell.box)  # type: ignore[arg-type]
        placed.append(min(range(n), key=lambda i: abs(centres[i] - x)) + 1)
    if len(set(placed)) != len(placed) or placed != sorted(placed):
        return placed, "two cells fall under one column"
    return placed, ""


def _header_cells(desc: TableDescription, by_number: dict[int, Line], centres: list[float] | None, n: int) -> dict[int, list[str]]:
    """The header texts above each column: by position on a sheet or in a Word table; on a page, each header cell under
    the data column it stands over (a header written on a line of its own, as a lone "5" above a block, still counts)."""
    out: dict[int, list[str]] = {}
    for k in desc.header_lines:
        line = by_number.get(k)
        if line is None:
            continue
        if centres is None or any(c.box is None for c in line.cells):
            for i, cell in enumerate(line.cells, start=1):
                out.setdefault(i, []).append(cell.text)
            continue
        spacing = min((b - a for a, b in pairwise(centres) if b > a), default=50.0)
        for cell in line.cells:
            x = _centre(cell.box)  # type: ignore[arg-type]
            i = min(range(n), key=lambda j: abs(centres[j] - x))
            if abs(centres[i] - x) <= spacing / 2 + 1:
                out.setdefault(i + 1, []).append(cell.text)
    return out


def read_table(desc: TableDescription, doc: SourceDocument, *, file: str, sha256: str) -> ReadTable:
    """Every cell the description names, line by line, each with its place."""
    tid = table_id(sha256, desc)
    part = parts_by_name(doc).get(desc.part)
    if part is None:
        return ReadTable(id=tid, description=desc, sha256=sha256, problems=(
            Problem(code="PART_NOT_FOUND", severity="error", message=f"{file} has no part {desc.part}"),))
    by_number = {line.number: line for line in part.lines}
    # a line holds as many cells as the widest header line or the furthest column described (a column may be left
    # undescribed: a ratio the client computed, a remark)
    n = max([c.index for c in desc.columns] + [len(by_number[k].cells) for k in desc.header_lines if k in by_number] or [0])
    summary_of = {line: name for name, line in desc.summary_lines.items()}
    wanted = [k for k in range(desc.first_line, desc.last_line + 1) if k not in desc.skip_lines]
    wanted += [k for k in summary_of if k not in wanted]
    problems: list[Problem] = []
    both = {t.strip().lower() for t in desc.missing_tokens} & {t.strip().lower() for t in desc.blq_tokens}
    if both:
        # "BLQ" listed as a missing sample too made every value below the LLOQ a missing sample (Nemotron on the
        # synthetic delivery, 2026-11-22): the subject sets and the AUC set changed
        problems.append(Problem(code="TOKEN_BOTH_MISSING_AND_BLQ", severity="error", message=(
            f"{', '.join(sorted(both))}: listed both as a missing sample and as below the LLOQ; a value is one or the "
            "other (below the LLOQ is a measurement, a missing sample is none)")))
    if desc.last_line < desc.first_line or not n:
        problems.append(Problem(code="EMPTY_RANGE", severity="error",
                                message=f"the table on {desc.part} of {file} names no lines or no columns"))
    # where the columns stand on a page: the median centre of each position over the lines with every cell
    full = [by_number[k] for k in wanted if k in by_number and len(by_number[k].cells) == n
            and all(c.box is not None for c in by_number[k].cells)]
    centres = ([statistics.median(_centre(line.cells[i].box) for line in full) for i in range(n)]  # type: ignore[arg-type]
               if full and part.page is not None else None)
    # a time the description gives a column must be written in that column's own header cells (code does not take the
    # agent's word, and a description shifted by one column is caught here)
    above = _header_cells(desc, by_number, centres, n)
    for spec in desc.columns:
        if spec.time is None:
            continue
        if not desc.header_lines:
            problems.append(Problem(code="TIME_NOT_CHECKED", message=(
                f"column {spec.index}: no header lines are named, so its time {spec.time:g} is not checked")))
        elif spec.time not in {x for text in above.get(spec.index, ()) for x in numbers_in(text)}:
            problems.append(Problem(code="TIME_NOT_IN_HEADER", severity="error", message=(
                f"column {spec.index}: the time {spec.time:g} is not written above it "
                f"(header lines {', '.join(map(str, desc.header_lines))})")))
    rows: list[ReadRow] = []
    for k in sorted(set(wanted)):
        line = by_number.get(k)
        if line is None:
            problems.append(Problem(code="LINE_NOT_FOUND", severity="error", message=f"{desc.part} of {file} has no line {k}"))
            continue
        if not any(c.text.strip() for c in line.cells):
            continue
        placed, why = _placed(line, centres, n)
        chip_base = {"file": file, "sha256": sha256, "part": desc.part, "line": k}
        if why:
            problems.append(Problem(code="LINE_NOT_PLACED", severity="error", message=f"line {k}: {why}; it is left out",
                                    where=Chip(**chip_base, text=line.text)))
            continue
        at = {col: cell for col, cell in zip(placed, line.cells, strict=True) if col is not None}
        cells = []
        for spec in desc.columns:
            cell = at.get(spec.index)
            text = cell.text if cell is not None else ""
            chip = Chip(**chip_base, cell=spec.index, text=text, box=cell.box if cell is not None else None,
                        ref=cell.ref if cell is not None else "")
            cells.append(ReadCell(role=spec.role, text=text, chip=chip, label=spec.label, unit=spec.unit, time=spec.time,
                                  group=spec.group))
        rows.append(ReadRow(line=k, cells=tuple(cells), summary=summary_of.get(k, "")))
    return ReadTable(id=tid, description=desc, sha256=sha256, rows=tuple(rows), problems=tuple(problems))


def _value_in_quote(value: str, quote: str) -> bool:
    """The value is written in its quote: as whole words (so "10" is not found in "100 mg"), or, for a value written
    with other spacing or punctuation, every one of its numbers is one of the quote's numbers."""
    want, text = unmarked(value), unmarked(quote)
    if want and re.search(r"(?<![\w.])" + re.escape(want) + r"(?![\w])", text):
        return True
    numbers = numbers_in(value)
    in_quote = numbers_in(quote)
    return bool(numbers) and all(x in in_quote for x in numbers)


_ROLE_WORDS = ("reference", "test", "reformulat", "original", "innovator", "generic", "brand", "rld", "listed drug")


def _treatment_code_problem(fact: Fact) -> str:
    """A treatment code's meaning must say what the code is, and a product named for it must be named in the quote
    (Nemotron on the synthetic delivery, 2026-11-22: code A "meaning" A, its product claimed from a data row)."""
    meaning, code = unmarked(fact.value), unmarked(fact.subject)
    if not re.search(r"[a-z]{3,}", re.sub(r"\b" + re.escape(code) + r"\b", "", meaning) if code else meaning):
        return "a treatment code's value must say what the code is (e.g. 'reference product'), not repeat the code"
    if "|" in fact.value:
        return "a treatment code's value is what the documents say the code is, not a line of a table"
    if fact.product.strip():
        quote = unmarked(fact.quote)
        name = unmarked(fact.product)
        if name not in quote and not any(w in quote for w in _ROLE_WORDS):
            return f"the quote does not name the product {fact.product!r} or its role for this code"
    return ""


_DATA_CELL = re.compile(r"^(?:[<>≤≥]?\s*[-+]?\d[\d.,]*\s*%?|\.|-|—|na|n/a|nd|ns|blq|bql|)$", re.IGNORECASE)
_MASS = re.compile(r"(?<![a-z])(mg|g|µg|μg|ug|mcg|ng)(?![a-z])", re.IGNORECASE)


def _data_row(quote: str) -> bool:
    """A quote that is a line of a data table (five cells or more, most of them numbers or blanks), not a statement:
    an agent quoted a subject's concentration row to say the subject was excluded (2026-11-22)."""
    cells = [c.strip() for c in quote.split("|")]
    return len(cells) >= 5 and sum(bool(_DATA_CELL.match(c)) for c in cells) >= 0.6 * len(cells)


def check_fact(fact: Fact, doc: SourceDocument, *, file: str, sha256: str) -> CheckedFact:
    """The fact with its place, when its quote is in the file and its value in the quote; refused otherwise."""
    if not fact.value.strip():
        return CheckedFact(fact=fact, ok=False, problem="the fact has no value")
    if _data_row(fact.quote):
        return CheckedFact(fact=fact, ok=False, problem=(
            "the quote is a line of a data table: a table's values are read from its description (describe the table), "
            "and a fact quotes what a document states"))
    if fact.field == "study.treatment_code" and (why := _treatment_code_problem(fact)):
        return CheckedFact(fact=fact, ok=False, problem=why)
    if fact.field in ("study.dose", "product.strength") and not _MASS.search(f"{fact.value} {fact.unit}"):
        # "single oral dose of 1 tablet" gave a dose of 1 beside "1 x 90 mg" (Nemotron on the sample delivery)
        return CheckedFact(fact=fact, ok=False, problem=(
            "a dose or strength is a mass (mg): a count of tablets alone is not one; give it with the strength, e.g. "
            "1 x 90 mg"))
    found = find_quote(doc, fact.quote)
    if found is None:
        return CheckedFact(fact=fact, ok=False, problem=f"the quote is not in {file}")
    if not _value_in_quote(fact.value, fact.quote):
        return CheckedFact(fact=fact, ok=False, problem=f"the value {fact.value!r} is not in its quote")
    part, line = found
    return CheckedFact(fact=fact, ok=True, number=number_of(fact.value, fact.unit),
                       chip=Chip(file=file, sha256=sha256, part=part, line=line, text=fact.quote.strip()))


def number_of(value: str, unit: str = "") -> float | None:
    """The one number a value holds: "90" -> 90; "2 x 50 mg" -> 100; "240±2 mL" -> 240; "0.00 / 0.50 / …", "18-44" and
    "2,5" -> None (several numbers, none of them the value, or a decimal comma)."""
    text = unicodedata.normalize("NFKC", value)
    if re.search(r"\d,(?:\d{1,2}|\d{4,})(?!\d)", text):
        return None   # a decimal comma ("2,5 mg") is not guessed
    # a tolerance or spread written after the value ("240±2 mL", "30 +/- 6") is not the value
    text = re.sub(r"\s*(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?", "", text)
    times = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(\S+)?\s*", text)
    if times:   # "2 x 50 mg": two units of 50 mg
        return float(times.group(1)) * float(times.group(2))
    numbers = numbers_in(text)
    if len(numbers) == 1:
        return numbers[0]
    if unit.strip():
        hits = re.findall(r"(\d+(?:\.\d+)?)\s*" + re.escape(unit.strip()) + r"\b", text)
        if len(hits) == 1:
            return float(hits[0])
    return None

