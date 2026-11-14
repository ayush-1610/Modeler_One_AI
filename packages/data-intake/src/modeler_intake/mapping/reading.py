"""Code's readings of cells and cited text, shared by `validate.validate_spec` and `execute.execute` (contracts §6.2).

One place reads a number from a cell (`parse_cell`, under the region's decimal convention), splits a cell that also
writes its spread, interval or unit (`split_cell`), reads a constant from cited text (`read_constant`,
`read_text_constant`), finds a unit at a cite (`unit_at`) and resolves a `Cite` to the cells it names (`cite_cells`).
`execute` re-exports the contract's names (`ParsedCell`, `decimal_convention`, `parse_cell`, `split_cell`,
`read_constant`, `read_text_constant`); this module exists so that `validate` and `execute` read with the same code
without importing each other.

Nothing here takes a number from the model: a constant's value and a value's unit are always what code reads from the
cited text, every number of a cell or a cited text under the region's decimal convention (`read_token`). Today's
`apply.parse_numeric` is not reused: it reads "1.5" as 15 under decimal commas.

A model-written pattern (a row rule's, a key's, a constant's) is matched only through `match_text`, on at most 400
characters, and only after `pattern_problem` passed it: Python's `re` has no timeout, so a pattern that can backtrack
without end is refused, never run.
"""

from __future__ import annotations

import math
import re
import re._constants as _sre
import re._parser as _sre_parse
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict

from modeler_intake import fields
from modeler_intake.apply import PRE_DOSE
from modeler_intake.document_reading import _CONC_UNIT, _DOSE_UNIT, name_key
from modeler_intake.mapping_spec import CellForm, Cite, Constant
from modeler_intake.recipe import DEFAULT_BELOW_LLOQ_TOKENS
from modeler_intake.sheet_form import _COMMA_DECIMAL, MISSING_TOKENS
from modeler_intake.sheet_form import _N as _COUNT_HEADER
from modeler_intake.source_model import GridCell, RegionGrid, is_numeric_text
from modeler_intake.validate import TIME_UNITS, canonical_unit

DecimalMark = Literal["point", "comma"]
MARKERS = "*†‡"                                           # a footnote mark after a value (MARKED_VALUE)
# the number tokens of a cited text: grouped ("1.234,5", "1,000") or with at most one decimal part, not glued to a
# letter ("d50", "B123"); each is read by `read_token` under the region's convention
NUMBER_TOKEN = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_NUMBER = re.compile(rf"(?<![\w.,])({NUMBER_TOKEN})(?![\w])")
# what joins two numbers into a range or a list of values ("10-30 mg", "10 to 30 mg", "10, 20 and 30 mg"): neither
# number is stated alone. A comma joins only inside a list that ends with "and" or "or" ("Day 1, 50 mg" is no list).
_RANGE_JOIN = re.compile(r"\s*(?:-|–|—|\bto\b)\s*", re.IGNORECASE)
_LIST_JOIN = re.compile(r"\s*,?\s*\b(?:and|or)\b\s*", re.IGNORECASE)
_LIST_COMMA = re.compile(r"\s*,\s*")
MAX_MATCH_TEXT = 400                  # a model-written pattern is matched against at most this many characters
MAX_OPEN_REPEATS = 3                  # ... and holds at most this many repeats that can match more than one character
_PERCENT = re.compile(r"\s*(%|percent\b)", re.IGNORECASE)
_WORD = re.compile(r"\s*-?\s*([A-Za-z]+)\b")
_CUE_GAP = re.compile(r"[\s=:]{0,3}")
_GAP = re.compile(r"[ \t]*-?[ \t]*")


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ParsedCell(_B):
    """One cell as code reads it. `value` None with `censored` (a below-LLOQ token or "<x", whose x is the `lloq`), with
    `uloq` (">x"), with `missing` (a no-sample token) or with a `problem` (not a number: the cell stays unaccounted)."""

    value: float | None
    censored: bool = False
    lloq: float | None = None
    uloq: float | None = None
    missing: bool = False
    marker: str = ""                    # a trailing *, † or ‡ (MARKED_VALUE)
    problem: str = ""


def nfkc(text: str) -> str:
    """NFKC with U+2212 (minus sign) read as "-": how every cell and cited text is read. The micro sign is kept (NFKC
    would make it a Greek mu), so a unit read from the text is the unit as written."""
    return "".join(c if c == "µ" else unicodedata.normalize("NFKC", c) for c in text).replace("\N{MINUS SIGN}", "-")


# --- the decimal convention and one cell -----------------------------------------------------------------------------


def decimal_convention(grid: RegionGrid) -> DecimalMark:
    """The region's decimal mark, decided by code with the legacy detector's rule (`sheet_form._decimal_comma`):
    "comma" when at least two text cells (cells with a str value) write a number with a decimal comma
    (`sheet_form._COMMA_DECIMAL`: "12,5", not "1,234"), else "point". Never the model's choice."""
    texts = [nfkc(c.value) for c in grid.cells.values() if c.merged_from is None and isinstance(c.value, str)]
    return "comma" if sum(bool(_COMMA_DECIMAL.match(t)) for t in texts) >= 2 else "point"


def writes_decimal(text: str, decimal: DecimalMark) -> bool:
    """Whether a cell writes a number with a decimal mark of the region's convention ("12.5" under point, "12,5" under
    comma): what `column_has_decimal` asks of the other cells of a column."""
    mark = r"\." if decimal == "point" else ","
    return re.search(rf"\d{mark}\d", nfkc(text)) is not None


def _float(sign: str, digits: str, fraction: str | None, exponent: str | None) -> float:
    return float(f"{sign}{digits}" + (f".{fraction}" if fraction else "") + (exponent or ""))


def read_number(text: str, decimal: DecimalMark, column_has_decimal: bool) -> tuple[float | None, str]:
    """A bare number written as text, read under the region's convention: (value, "") or (None, problem).

    point: "12.5" -> 12.5; "1,234.5" -> 1234.5; "1,234" -> 1234 when another cell of its column writes a decimal point,
    else ambiguous; "12,5" ambiguous; "1 234.5" (groups of three) -> 1234.5.
    comma: "12,5" -> 12.5; "1.234,5" -> 1234.5; "1.234" -> 1234 when another cell writes a decimal comma, else
    ambiguous; "12.5" and "0.125" ambiguous."""
    t = nfkc(text).strip()
    dec, grp = (".", ",") if decimal == "point" else (",", ".")
    d, g = re.escape(dec), re.escape(grp)
    spaced = re.fullmatch(rf"([-+]?)([1-9]\d{{0,2}}(?: \d{{3}})+)(?:{d}(\d+))?", t)
    if spaced:
        return _float(spaced.group(1), spaced.group(2).replace(" ", ""), spaced.group(3), None), ""
    plain = re.fullmatch(rf"([-+]?)(\d+)(?:{d}(\d+))?([eE][-+]?\d+)?", t)
    if plain:
        return _float(plain.group(1), plain.group(2), plain.group(3), plain.group(4)), ""
    bare_fraction = re.fullmatch(rf"([-+]?){d}(\d+)([eE][-+]?\d+)?", t)
    if bare_fraction:
        return _float(bare_fraction.group(1), "0", bare_fraction.group(2), bare_fraction.group(3)), ""
    grouped = re.fullmatch(rf"([-+]?)([1-9]\d{{0,2}}(?:{g}\d{{3}})+)(?:{d}(\d+))?", t)
    if grouped:
        if grouped.group(3) is not None or column_has_decimal:
            return _float(grouped.group(1), grouped.group(2).replace(grp, ""), grouped.group(3), None), ""
        return None, f"ambiguous: {t!r} may be a thousands group or a decimal ({decimal} region, no other decimal in its column)"
    if re.fullmatch(rf"[-+]?\d*{g}\d+", t):
        return None, f"ambiguous: {t!r} writes a decimal {'comma' if grp == ',' else 'point'} in a {decimal} region"
    return None, f"{t!r} is not a number"


def parse_cell(cell: GridCell, *, decimal: DecimalMark, column_has_decimal: bool, below_lloq_tokens: Sequence[str],
               missing_tokens: Sequence[str]) -> ParsedCell:
    """One cell as code reads it (§6.2). A number stored as a number is taken as it is (a number format ending in "%"
    reads it times 100: the caller writes the unit "%"). Text, after NFKC with U+2212 read as "-": a no-sample token
    gives `missing`; a below-LLOQ token or "<x" gives `censored` (and `lloq` x); ">x" gives `uloq` x and no value; a
    trailing *, † or ‡ is cut into `marker`; the rest is read by `read_number` under the region's convention (a trailing
    "%" is allowed). Never raises: a cell that is no number has a `problem`."""
    raw = cell.value
    if isinstance(raw, bool):
        return ParsedCell(value=None, problem=f"{cell.text!r} is a TRUE/FALSE cell, not a number")
    if isinstance(raw, int | float):
        if not math.isfinite(raw):
            return ParsedCell(value=None, problem="the stored number is not finite")
        if cell.number_format.strip().endswith("%"):
            return ParsedCell(value=float(Decimal(repr(raw)) * 100))
        return ParsedCell(value=float(raw))
    text = nfkc(cell.text).strip()
    if not text:
        return ParsedCell(value=None, problem="empty")
    marker = ""
    marked = re.fullmatch(rf"(.*?)\s*([{MARKERS}]+)", text)
    if marked and marked.group(1):
        text, marker = marked.group(1), marked.group(2)
    upper = text.upper()
    if upper in {t.strip().upper() for t in missing_tokens if t.strip()}:
        return ParsedCell(value=None, missing=True, marker=marker)
    if upper in {t.strip().upper() for t in below_lloq_tokens if t.strip()}:
        return ParsedCell(value=None, censored=True, marker=marker)
    compared = re.fullmatch(r"([<>≤≥])\s*(.+)", text)
    if compared:
        number, problem = read_number(compared.group(2).rstrip("%").strip(), decimal, column_has_decimal)
        if number is None:
            return ParsedCell(value=None, problem=problem, marker=marker)
        if compared.group(1) in "<≤":
            return ParsedCell(value=None, censored=True, lloq=number, marker=marker)
        return ParsedCell(value=None, uloq=number, marker=marker)
    number, problem = read_number(text.removesuffix("%").strip(), decimal, column_has_decimal)
    if number is None:
        return ParsedCell(value=None, problem=problem, marker=marker)
    return ParsedCell(value=number, marker=marker)


_NUM_PART = r"[<>≤≥]?\s*[-+]?(?:\d[\d.,]*|[.,]\d+)(?:[eE][-+]?\d+)?"


def split_cell(text: str, form: CellForm) -> tuple[str, str | None, str | None]:
    """A cell that also writes its spread, interval or unit, split by code: (value text, spread or low text, unit or
    high text). "12.3 (4.5)" and "12.3 ± 4.5" -> ("12.3", "4.5", None); "0.95 (0.88-1.03)" -> ("0.95", "0.88", "1.03");
    "12.3 ng/mL" -> ("12.3", None, "ng/mL"). A cell that is not of its form comes back whole: (text, None, None)."""
    t = nfkc(text).strip()
    if form == "value (spread)":
        m = re.fullmatch(r"(.*?)\s*[(\[]\s*(.*?)\s*[)\]]", t)
        return (m.group(1), m.group(2), None) if m and m.group(1) else (t, None, None)
    if form == "value ± spread":
        m = re.fullmatch(r"(.*?)\s*(?:±|\+/-|\+-)\s*(.*)", t)
        return (m.group(1), m.group(2), None) if m and m.group(1) else (t, None, None)
    if form == "value (low-high)":
        m = re.fullmatch(rf"(.*?)\s*[(\[]\s*({_NUM_PART})\s*(?:-|–|—|\bto\b|,|;)\s*({_NUM_PART})\s*[)\]]", t)
        return (m.group(1), m.group(2), m.group(3)) if m and m.group(1) else (t, None, None)
    if form == "value unit":
        m = re.fullmatch(rf"({_NUM_PART}[{MARKERS}]*)\s*(\S.*)", t)
        return (m.group(1), None, m.group(2).strip()) if m else (t, None, None)
    return t, None, None


# --- numbers and units in cited text ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class NumberRead:
    """A number code read in a cited text: its value (None: ambiguous under the convention, never guessed), the unit
    written after it (None for a class with no table, unless the field's cue follows it), the number as written, and
    where it stands in the text."""

    value: float | None
    unit: str | None
    written: str
    start: int
    end: int


def read_token(written: str, decimal: DecimalMark | None) -> float | None:
    """A number token of a cited text or a sentence, read under a decimal convention (None: ambiguous, never guessed).

    With the region's convention, as a cell is read (`read_number` with no other decimal in a column): in a comma
    region "1.000 mg" is ambiguous, never 1 mg, and "12.5" is ambiguous; in a point region "1,000" and "12,5" are.
    With no convention (`None`: prose, whose document has no region): one group of three after a mark ("1,000",
    "1.000") is ambiguous either way; two different marks read the last as the decimal ("1.234,5", "1,234.5"); any other
    single mark is a decimal ("0.500", "12,5")."""
    if decimal is not None:
        return read_number(written, decimal, column_has_decimal=False)[0]
    marks = re.findall(r"[.,]", written)
    if not marks:
        return float(written)
    if len(set(marks)) == 2:
        return read_number(written, "point" if marks[-1] == "." else "comma", column_has_decimal=False)[0]
    if len(marks) > 1 or re.fullmatch(r"[1-9]\d{0,2}[.,]\d{3}", written):
        return None                                                     # "1,000", "1.000", "1,234,567": groups or not
    return float(written.replace(",", "."))


def joined(text: str, spans: Sequence[tuple[int, int]]) -> list[set[int]]:
    """For each number (its (start, end) in `text`, in order), the other numbers it is joined to as a range ("10-30",
    "10 to 30") or a list ("10, 20 and 30", "10 or 30"): neither states one value alone. A comma joins two numbers only
    inside a list that goes on to "and" or "or" ("Day 1, 50 mg" joins nothing)."""
    links: list[str | None] = []
    for (_a, end), (start, _b) in pairwise(spans):
        gap = text[end:start]
        links.append("range" if _RANGE_JOIN.fullmatch(gap) else "list" if _LIST_JOIN.fullmatch(gap)
                     else "comma" if _LIST_COMMA.fullmatch(gap) else None)
    valid = [False] * len(links)
    listed = False                                     # an "and"/"or" further right in the same run of links
    for i in range(len(links) - 1, -1, -1):
        if links[i] is None:
            listed = False
            continue
        if links[i] == "list":
            listed = True
        valid[i] = links[i] != "comma" or listed
    partners: list[set[int]] = [set() for _ in spans]
    i = 0
    while i < len(spans):
        j = i
        while j < len(links) and valid[j]:
            j += 1
        members = set(range(i, j + 1))
        for m in members:
            partners[m] = members - {m}
        i = j + 1
    return partners


def unit_after(field: str, text: str, pos: int) -> str | None:
    """The unit of the field's class written directly after position `pos` (after spaces or a hyphen), or None."""
    cls = fields.unit_class(field)
    if cls == "concentration" or cls == "mass":
        pattern = _CONC_UNIT if cls == "concentration" else _DOSE_UNIT
        gap = _GAP.match(text, pos)
        found = pattern.match(text, gap.end() if gap else pos)
        return found.group(1) if found else None
    if cls == "time":
        word = _WORD.match(text, pos)
        return word.group(1) if word and canonical_unit(word.group(1), TIME_UNITS) is not None else None
    if cls == "percentage":
        found = _PERCENT.match(text, pos)
        return found.group(1) if found else None
    return None


def _has_table(field: str) -> bool:
    return fields.unit_table(fields.unit_class(field)) is not None


# a field that IS one end of a range: "collected 0-24 h" states interval_start_h 0 and interval_end_h 24, "aged 18 to
# 45 years" age_min 18 and age_max 45
RANGE_SIDE = {"interval_start_h": 0, "interval_end_h": 1, "age_min": 0, "age_max": 1}
# one field of each unit class with a table: a unit written after a number is one of theirs ("50 mg", "12 ng/mL", "2 h")
TABLE_FIELDS = ("concentration", "dose", "time", "percent_dissolved")


def numbers_of(field: str, text: str, *, decimal: DecimalMark | None = None) -> list[NumberRead]:
    """The numbers of the field's unit class a text states, each read under `decimal` (`read_token`; an ambiguous one
    is listed with value None: it is a number, never a guess). For a class with a table: each number followed by a
    unit of the class (`fields.units_in`'s units). For a class with no table: the numbers next to the field's cue ("pH
    1.2", "50 rpm", "n = 16"); when none is next to it but the cue is written, every number of the text that is not
    followed by a unit of a class with a table ("50 mg" is no n and no pH); none when the cue is not written. A number
    joined to one of these as a range or a list ("10-30 mg", "pH 1.2 to 6.8", "10, 20 and 30 mg") is one of them too,
    so the text states more than one."""
    t = nfkc(text)
    tokens = list(_NUMBER.finditer(t))
    every = [NumberRead(value=read_token(m.group(1), decimal), unit=unit_after(field, t, m.end()), written=m.group(1),
                        start=m.start(1), end=m.end(1)) for m in tokens]
    partners = joined(t, [(n.start, n.end) for n in every])
    if _has_table(field):
        chosen = {i for i, n in enumerate(every) if n.unit is not None}
    else:
        definition = fields.field(field)
        cue = definition.cue if definition is not None else ""
        cls = fields.unit_class(field)
        candidates = [i for i, n in enumerate(every)
                      if cls != "none" or not any(unit_after(name, t, n.end) for name in TABLE_FIELDS)]
        if not cue:
            chosen = set(candidates)
        else:
            cues = [c.span() for c in re.finditer(cue, t, re.IGNORECASE)]
            chosen = set()
            for i in candidates:
                n = every[i]
                for start, end in cues:
                    after = start >= n.end and _CUE_GAP.fullmatch(t[n.end:start]) is not None
                    before = n.start >= end and _CUE_GAP.fullmatch(t[end:n.start]) is not None
                    if after or before:
                        unit = t[start:end] if after and cls == "other" else None
                        every[i] = NumberRead(value=n.value, unit=unit, written=n.written, start=n.start, end=n.end)
                        chosen.add(i)
                        break
            if not chosen and cues:
                chosen = set(candidates)
    for i in list(chosen):
        chosen |= partners[i]
    found = [every[i] for i in sorted(chosen)]
    side = RANGE_SIDE.get(field)
    if side is not None and len(found) == 2 and _RANGE_JOIN.fullmatch(t[found[0].end:found[1].start]):
        return [NumberRead(value=found[side].value, unit=found[1].unit, written=found[side].written,
                           start=found[side].start, end=found[side].end)]     # "0-24 h": the interval's start or end
    return found


def read_constant(field: str, text: str, *, decimal: DecimalMark | None = None) -> tuple[float | str, str | None] | None:
    """The field's own reader of a cited text: (value, unit as written) when the text states it exactly once, else None.
    A number or integer: the one number of its unit class (`numbers_of`, under the region's `decimal` convention: an
    ambiguous number is not stated); a choice: `fields.read_choice`; a name or a text: the whole text. Never the
    model's reading."""
    definition = fields.field(field)
    if definition is None:
        return None
    if definition.value in ("number", "integer"):
        found = numbers_of(field, text, decimal=decimal)
        value = found[0].value if len(found) == 1 else None
        if value is None or (definition.value == "integer" and not value.is_integer()):
            return None
        return value, found[0].unit
    if definition.value == "choice":
        choice = fields.read_choice(field, text)
        return (choice, None) if choice is not None else None
    stripped = text.strip()
    return (stripped, None) if stripped else None


def read_text_constant(constant: Constant, text: str) -> str | None:
    """A name or text constant read from its cited text: the pattern's group when the pattern matches the text exactly
    once (no pattern: the whole text); a choice: `fields.read_choice`. None when it is not stated exactly once."""
    definition = fields.field(constant.field)
    if definition is None or definition.value in ("number", "integer"):
        return None
    if definition.value == "choice":
        return fields.read_choice(constant.field, text)
    if constant.pattern is None:
        return text.strip() or None
    if pattern_problem(constant.pattern) or len(text) > MAX_MATCH_TEXT:
        return None
    pattern = re.compile(constant.pattern)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        return None
    found = matches[0].group(1) if pattern.groups >= 1 else matches[0].group(0)
    if found is None:
        return None
    return found.strip() or None


def read_level(text: str, *, decimal: DecimalMark | None = None) -> float | None:
    """The confidence level a cited text writes ("90% CI" -> 90.0): its one number followed by "%", read under the
    region's convention, else None."""
    found = [m for m in re.finditer(rf"(?<![\w.,])({NUMBER_TOKEN})\s*%", nfkc(text))]
    return read_token(found[0].group(1), decimal) if len(found) == 1 else None


def unit_key(unit: str) -> str:
    return re.sub(r"\s+", "", nfkc(unit)).lower().replace("μ", "µ")


def same_unit(field: str, a: str, b: str) -> bool:
    """Whether two unit spellings name one unit of the field's class: the same canonical spelling in the class's table
    (`fields.known_unit`, `is None` meaning not known), else the same text (spaces and case aside)."""
    known_a, known_b = fields.known_unit(field, a), fields.known_unit(field, b)
    if known_a is not None and known_b is not None:
        return known_a == known_b
    return unit_key(a) == unit_key(b)


def unit_in_text(field: str, typed: str, text: str) -> str | None:
    """The unit as written in `text` that is the typed unit: for a class with a table, one of `fields.units_in` with
    the same canonical spelling; for a class with no table, the typed unit written verbatim (case aside, not glued to a
    letter or digit). None when the text does not write it."""
    if _has_table(field):
        return next((found for found in fields.units_in(field, text) if same_unit(field, typed, found)), None)
    wanted = nfkc(typed).strip()
    if not wanted:
        return None
    found = re.search(rf"(?<![A-Za-z0-9µμ]){re.escape(wanted)}(?![A-Za-z0-9µμ])", nfkc(text), re.IGNORECASE)
    return found.group(0) if found else None


def unit_at(field: str, typed: str, cells: Sequence[GridCell]) -> tuple[str, GridCell] | None:
    """The typed unit as written at the cited cells, and the cell that writes it; None when none does."""
    for cell in cells:
        found = unit_in_text(field, typed, cell.text)
        if found is not None:
            return found, cell
    return None


def unit_of_cell(field: str, text: str) -> str | None:
    """The unit a unit column's cell writes for a value of `field`: the one unit of the class it names, else the cell's
    text as written (kept verbatim: UNIT_NOT_IN_TABLES or UNIT_NOT_CHECKED is D5's)."""
    stripped = nfkc(text).strip()
    if not stripped:
        return None
    found = fields.units_in(field, stripped) if _has_table(field) else ()
    return found[0] if len(found) == 1 else stripped


# --- what a cell writes: a value or a word ------------------------------------------------------------------------------

# a cell that stands where a number stands: below the LLOQ or no sample
TOKENS = frozenset(t.upper() for t in (*DEFAULT_BELOW_LLOQ_TOKENS, *MISSING_TOKENS))
# the letters a value cell may carry after its numbers: a unit's parts ("12.3 ng/mL", "2 h", "45 %", "50 mg/kg")
_UNIT_ATOMS = frozenset({"ng", "pg", "µg", "μg", "ug", "mcg", "mg", "g", "kg", "l", "ml", "dl", "mol", "nmol", "µmol",
                         "μmol", "umol", "pmol", "percent", *TIME_UNITS})


def value_like(text: str) -> bool:
    """Whether a cell writes a value rather than a word: a bare number, a below-LLOQ or no-sample token, or a text that
    starts with a number (after a comparator and a sign) and holds nothing but numbers, marks, brackets, separators
    and a unit ("12.3 (4.5)", "12.3 ± 4.5", "0.95 (0.88-1.03)", "5.2, 20.1", "12.3 ng/mL", "12.3*", "2 h", "45 %").
    "90% CI lower", "10 mg (n=8)", "Cohort 1" and "S01" are words."""
    t = nfkc(text).strip()
    if not t:
        return False
    if is_numeric_text(t) or t.upper() in TOKENS:
        return True
    if not re.match(r"[<>≤≥]?\s*[-+]?(?:\d|[.,]\d)", t):
        return False
    rest = re.sub(_NUM_PART, " ", t)
    return all(word.lower() in _UNIT_ATOMS for word in re.findall(r"[^\W\d_]+", rest))


# --- model-written patterns ------------------------------------------------------------------------------------------

MAX_PATTERN = 200
_REPEATS = (_sre.MAX_REPEAT, _sre.MIN_REPEAT, _sre.POSSESSIVE_REPEAT)


def _pattern_items(items) -> list:
    """The (op, argument) items of a parsed pattern, every level (groups, branches, look-arounds)."""
    out = []
    for op, av in items:
        out.append((op, av))
        if op == _sre.SUBPATTERN:
            out += _pattern_items(av[3])
        elif op in _REPEATS:
            out += _pattern_items(av[2])
        elif op == _sre.BRANCH:
            for branch in av[1]:
                out += _pattern_items(branch)
        elif op in (_sre.ASSERT, _sre.ASSERT_NOT):
            out += _pattern_items(av[1])
        elif op == _sre.ATOMIC_GROUP:
            out += _pattern_items(av)
        elif op == _sre.GROUPREF_EXISTS:
            out += _pattern_items(av[1]) + (_pattern_items(av[2]) if av[2] is not None else [])
    return out


@lru_cache(maxsize=512)
def pattern_problem(pattern: str) -> str | None:
    """Why a model-written pattern is refused (BAD_PATTERN), or None. Python's `re` has no timeout, so a pattern is run
    only when it cannot backtrack without end: at most 200 characters; no repeated group that itself holds a repeat or
    an alternation ("(\\w+\\s?)+", "(a|ab)+"); no backreference; at most 3 repeats that match more than one
    character. It is then matched against at most 400 characters (`match_text`)."""
    if len(pattern) > MAX_PATTERN:
        return f"the pattern is longer than {MAX_PATTERN} characters"
    try:
        items = _pattern_items(_sre_parse.parse(pattern))
    except (re.error, RecursionError, OverflowError):
        return "the pattern is not a valid regular expression"
    open_repeats = 0
    for op, av in items:
        if op in (_sre.GROUPREF, _sre.GROUPREF_EXISTS):
            return "the pattern refers back to a group: write the text itself"
        if op in _REPEATS and av[1] > 1 and av[1] != av[0]:
            open_repeats += 1
            if any(inner in _REPEATS or inner == _sre.BRANCH for inner, _ in _pattern_items(av[2])):
                return "a repeated group holds a repeat or an alternation, which can run without end: write it flat"
    if open_repeats > MAX_OPEN_REPEATS:
        return (f"the pattern holds {open_repeats} repeats; at most {MAX_OPEN_REPEATS} (it is matched against the whole "
                "cell, case aside: no padding is needed)")
    return None


def match_text(pattern: str, text: str) -> bool:
    """Whether a model-written pattern matches the whole text, case aside: never for a refused pattern, nor for a text
    longer than 400 characters (a footnote that long is no row label)."""
    if pattern_problem(pattern) is not None or len(text) > MAX_MATCH_TEXT:
        return False
    return re.fullmatch(pattern, text, re.IGNORECASE) is not None


# --- statistics and spread kinds as a header or a label writes them -----------------------------------------------

_STATISTIC_WORDS = (("geometric_mean", r"\bgeo"), ("median", r"\bmedian\b"),
                    ("arithmetic_mean", r"\bmean\b|\baverage\b|\bavg\b|\barith"), ("individual", r"\bindividual\b"))
_SPREAD_WORDS = (("geoCV%", r"\bgeo\w*\.?\s*(?:%\s*)?cv\b|\bgcv\b"), ("geoSD", r"\bgeo\w*\.?\s*sd\b|\bgsd\b"),
                 ("CV%", r"\bcv\b|%\s*cv|coefficient of variation"), ("SE", r"\bsem?\b|standard error"),
                 ("SD", r"\bs\.?d\.?\b|\bstd\b|standard deviation"))


def read_statistic(text: str) -> str | None:
    """The statistic a header or a label names ("Geo mean" -> geometric_mean, "Median"), else None."""
    t = nfkc(text).strip().lower()
    if t in ("individual", "arithmetic_mean", "geometric_mean", "median"):
        return t
    found = [name for name, pattern in _STATISTIC_WORDS if re.search(pattern, t)]
    return found[0] if found else None


def read_spread_kind(text: str) -> str | None:
    """The spread kind a header or a label names ("SEM" -> SE, "%CV" -> CV%), else None."""
    t = nfkc(text).strip()
    if t in ("SD", "SE", "CV%", "geoSD", "geoCV%"):
        return t
    found = [name for name, pattern in _SPREAD_WORDS if re.search(pattern, t, re.IGNORECASE)]
    return found[0] if found else None


def spread_only(text: str) -> str | None:
    """The spread kind of a header that names a spread and nothing else ("SD", "SE (ng/mL)", "SEM", "%CV", "Geo CV%",
    "Std. Dev."), else None. A header that names a statistic with its spread ("Mean (SD)", "Mean ± SD", "Geometric mean
    (geo CV%)") heads a value column whose cells write both (a `cell_form` splits them): None. So does a label that
    only starts like a spread ("SE-101", "SD 03": a subject's or a site's code, with its number): None."""
    t = nfkc(text).strip()
    kind = read_spread_kind(t)
    if kind is None:
        return None
    rest = t
    for _name, pattern in _SPREAD_WORDS:
        rest = re.sub(pattern, " ", rest, flags=re.IGNORECASE)        # "Geo CV%": its "geo" is the spread's, no mean
    if read_statistic(rest) is not None or re.search(r"\d", re.sub(r"\([^)]*\)", " ", rest)):
        return None
    return kind


def count_only(text: str) -> bool:
    """Whether a header names a count and nothing else ("n", "N", "N (subjects)", "No. of subjects"): today's reader
    of an N column (`sheet_form._N`)."""
    return _COUNT_HEADER.match(nfkc(text)) is not None


def statistic_agrees(typed: str, text: str) -> bool:
    """Whether a typed statistic agrees with the words of a header or a label: they name none, or the same one. A bare
    "mean" (no "arith") names a mean of either kind; "geo" names the geometric mean only, "median" the median."""
    read = read_statistic(text)
    if read is None or read == typed:
        return True
    bare_mean = read == "arithmetic_mean" and not re.search(r"\barith", nfkc(text), re.IGNORECASE)
    return bare_mean and typed == "geometric_mean"


def spread_kind_agrees(typed: str, text: str) -> bool:
    """Whether a typed spread kind agrees with the words of a header or a label: they name none, or the same kind; a
    "CV%" or "SD" with no "geo" may be a geometric one's (geoCV%, geoSD)."""
    read = read_spread_kind(text)
    return read is None or read == typed or typed == f"geo{read}"


# --- times ------------------------------------------------------------------------------------------------------------

_TIME_TEXT = re.compile(r"(.+?)\s*([A-Za-z]+)?\.?")


def read_time(cell: GridCell, decimal: DecimalMark, column_has_decimal: bool) -> tuple[float | None, str | None, str]:
    """A sampling time a cell states: (time, the unit the cell writes or None, problem). A stored number as it is; a
    pre-dose word (`apply.PRE_DOSE`) is time 0; "2 h", "30 min" carry their unit."""
    raw = cell.value
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return (float(raw), None, "") if math.isfinite(raw) else (None, None, "the stored number is not finite")
    text = nfkc(cell.text).strip()
    if not text:
        return None, None, "empty"
    if text.lower() in PRE_DOSE:
        return 0.0, None, ""
    match = _TIME_TEXT.fullmatch(text)
    if match is None:
        return None, None, f"{text!r} is not a time"
    unit = match.group(2)
    if unit is not None and canonical_unit(unit, TIME_UNITS) is None:
        return None, None, f"{text!r} is not a time"
    number, problem = read_number(match.group(1), decimal, column_has_decimal)
    return (number, unit, "") if number is not None else (None, None, problem)


# --- cites -------------------------------------------------------------------------------------------------------------


def cite_exists(grid: RegionGrid, cite: Cite) -> bool:
    """Whether a cite names a place of the region: a cell inside it, or a context line it has."""
    if cite.near is not None:
        return bool(grid.context(cite.near, cite.line))
    return cite.row is not None and cite.column is not None and 1 <= cite.row <= grid.n_rows and 1 <= cite.column <= grid.n_cols


def cite_cells(grid: RegionGrid, cite: Cite) -> tuple[GridCell, ...]:
    """The cells a cite names: a context line's cells, or one cell of the region (a merged copy stands for its origin,
    whose locator it takes); () for a place that is empty or does not exist."""
    if cite.near is not None:
        return grid.context(cite.near, cite.line)
    if cite.row is None or cite.column is None:
        return ()
    cell = grid.cell(cite.row, cite.column)
    if not cell.locator:
        return ()
    if cell.merged_from is not None:
        return (GridCell(text=cell.text, value=cell.value, type=cell.type, locator=cell.merged_from,
                         number_format=cell.number_format),)
    return (cell,)


def is_context(grid: RegionGrid, cell: GridCell) -> bool:
    """Whether a cited cell is a context line's (it leaves the outside count when read: `ExtractResult.cited`)."""
    return any(c.locator == cell.locator for c in (*grid.caption, *(x for line in (*grid.above, *grid.below) for x in line)))


@dataclass(frozen=True)
class Reading:
    """A constant read from its cite: the value (None: an ambiguous number), its unit, the number or name as written,
    and the cell it stands in."""

    value: float | str | None
    unit: str | None
    written: str
    cell: GridCell


def read_cited(constant: Constant, cells: Sequence[GridCell], *, decimal: DecimalMark | None = None) -> list[Reading]:
    """Every reading of a constant over its cited cells (one per cell that states it), numbers under the region's
    `decimal` convention. Exactly one reading with a value is a statement; none, several, or one ambiguous number
    (value None: "1.000 mg" in a comma region) are not (CONSTANT_NOT_STATED)."""
    definition = fields.field(constant.field)
    if definition is None:
        return []
    found: list[Reading] = []
    for cell in cells:
        if definition.value in ("number", "integer"):
            numbers = numbers_of(constant.field, cell.text, decimal=decimal)
            if definition.value == "integer":
                numbers = [n for n in numbers if n.value is None or n.value.is_integer()]
            found += [Reading(value=n.value, unit=n.unit, written=n.written, cell=cell) for n in numbers]
            continue
        if definition.value != "choice" and constant.pattern is None and len(cells) > 1:
            continue                                         # a whole line of several cells names nothing by itself
        value = read_text_constant(constant, cell.text)
        if value is not None:
            found.append(Reading(value=value, unit=None, written=value, cell=cell))
    if definition.value == "choice" and len({r.value for r in found}) == 1 and found:
        return found[:1]                                     # the same choice stated in two cells of one line
    return found


def same_name(a: str, b: str) -> bool:
    """Whether two readings of a name are one name (case, spaces and punctuation aside: `document_reading.name_key`)."""
    return bool(name_key(a)) and name_key(a) == name_key(b)
