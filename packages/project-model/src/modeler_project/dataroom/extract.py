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
    if len(cells) == n or centres is None or any(c.box is None for c in cells):
        return list(range(1, len(cells) + 1)), "" if len(cells) <= n else f"{len(cells)} cells, {n} expected"
    if len(cells) > n:
        return list(range(1, len(cells) + 1)), f"{len(cells)} cells, {n} expected"
    placed: list[int | None] = []
    for cell in cells:
        x = _centre(cell.box)  # type: ignore[arg-type]
        placed.append(min(range(n), key=lambda i: abs(centres[i] - x)) + 1)
    if len(set(placed)) != len(placed) or placed != sorted(placed):
        return placed, "two cells fall under one column"
    return placed, ""


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
    if desc.last_line < desc.first_line or not n:
        problems.append(Problem(code="EMPTY_RANGE", severity="error",
                                message=f"the table on {desc.part} of {file} names no lines or no columns"))
    # where the columns stand on a page: the median centre of each position over the lines with every cell
    full = [by_number[k] for k in wanted if k in by_number and len(by_number[k].cells) == n
            and all(c.box is not None for c in by_number[k].cells)]
    centres = ([statistics.median(_centre(line.cells[i].box) for line in full) for i in range(n)]  # type: ignore[arg-type]
               if full and part.page is not None else None)
    # a time the description gives a column must be written in the header lines (code does not take the agent's word)
    header_numbers = {x for k in desc.header_lines if k in by_number for x in numbers_in(by_number[k].text)}
    for spec in desc.columns:
        if spec.time is not None and desc.header_lines and spec.time not in header_numbers:
            problems.append(Problem(code="TIME_NOT_IN_HEADER", severity="error", message=(
                f"column {spec.index}: the time {spec.time:g} is not written in header lines "
                f"{', '.join(map(str, desc.header_lines))}")))
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
    want, text = unmarked(value), unmarked(quote)
    if want and want in text:
        return True
    numbers = numbers_in(value)
    return bool(numbers) and all(x in numbers_in(quote) for x in numbers)


def check_fact(fact: Fact, doc: SourceDocument, *, file: str, sha256: str) -> CheckedFact:
    """The fact with its place, when its quote is in the file and its value in the quote; refused otherwise."""
    if not fact.value.strip():
        return CheckedFact(fact=fact, ok=False, problem="the fact has no value")
    found = find_quote(doc, fact.quote)
    if found is None:
        return CheckedFact(fact=fact, ok=False, problem=f"the quote is not in {file}")
    if not _value_in_quote(fact.value, fact.quote):
        return CheckedFact(fact=fact, ok=False, problem=f"the value {fact.value!r} is not in its quote")
    part, line = found
    return CheckedFact(fact=fact, ok=True, number=number_of(fact.value, fact.unit),
                       chip=Chip(file=file, sha256=sha256, part=part, line=line, text=fact.quote.strip()))


_UNIT_AFTER = r"\s*(?:mg|g|µg|μg|mcg|ng|ml|mL|l|L|h|hr|hrs|hours|min|kg|cm|m|%|ng/ml|ng/mL|mg/ml|mg/mL)\b"


def number_of(value: str, unit: str = "") -> float | None:
    """The one number a value holds: "90" -> 90; "1 x 90 mg" -> 90 (the number before its unit); "0.00 / 0.50 / …" or
    "18-44" -> None (several numbers, none of them the value)."""
    text = unicodedata.normalize("NFKC", value)
    # a tolerance or spread written after the value ("240±2 mL", "30 +/- 6") is not the value
    text = re.sub(r"\s*(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?", "", text)
    numbers = numbers_in(text)
    if len(numbers) == 1:
        return numbers[0]
    if unit.strip():
        hits = re.findall(r"(\d+(?:\.\d+)?)\s*" + re.escape(unit.strip()) + r"\b", text)
        if len(hits) == 1:
            return float(hits[0])
    hits = re.findall(r"(\d+(?:\.\d+)?)" + _UNIT_AFTER, text)
    if len(hits) == 1 and re.fullmatch(r"\s*\d+\s*[x×]\s*\d+(?:\.\d+)?\s*\S+\s*", text):
        return float(hits[0])   # "1 x 90 mg": one unit of 90 mg
    return None

