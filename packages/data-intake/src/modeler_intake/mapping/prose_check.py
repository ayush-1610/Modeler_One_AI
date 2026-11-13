"""The strict check a quoted prose fact passes before it is kept (contracts §6.2, plan §7.5).

A model reading a synopsis proposes a fact (a field, a value, a quote, the paragraph, and the study and arm it names);
code keeps it only when the paragraph states it, label and number in one clause, and then keeps CODE's reading, never
the model's. `check_prose_fact`, in order:
1. the quote is in the paragraph verbatim (`citations.quote_appears_in`: whitespace, Unicode form and line-break
   hyphens aside, at least 12 characters);
2. the paragraph is split into clauses (at ";", at "." followed by a space, and at " and "); the value and the
   field's `cue` (its label: "dose", "subjects", "rpm" ...) must both stand in the quoted part of one clause; a field
   with no cue (a CPF id) has no label to match;
3. a number field: that clause, whole (not only the part the quote copies: a quote cut short does not leave out the
   clause's other numbers), holds EXACTLY ONE number of the field's unit class, and it equals the value: for a
   class with a table, a number followed by a unit of the class ("50 mg", "0.5 g", "500 µg", "45 %"); for a class with
   none, any number ("230-23" is two numbers, so a study label and a count do not share a clause). A number joined to
   it as a range or a list ("10-30 mg", "10 to 30 mg", "10 and 30 mg") is a number of the class too, and a range states
   no one value (only interval_start_h and interval_end_h take one end of "0-24 h"). A number is read as the tables'
   constants are with no region: "1,000" and "1.000" are ambiguous, never 1. There is no times-100 reading: 0.45 is not
   stated by "45 %". A choice field: `fields.read_choice` on the clause gives the value. A name or text field:
   `document_reading.names_in` on the clause (a contiguous match, case, spaces and punctuation aside: "230-24" is not
   written in "230-23 and 231-24"), and a whole name: not a part of a longer one ("Cohort 1" is not written in
   "Cohort 10", "Exampleamide" not in "Exampleamide-M1");
4. the unit is parsed by code from the clause (as written), and the value kept is the one code read: the number, the
   choice, or the name as the paragraph writes it;
5. `study` and `arm`, when given, are each written (`names_in`) in the paragraph or its heading, and their spans are
   returned (`study_locator`, `arm_locator`); with no label, the ledger's rule applies (§6.3);
6. the returned `locator` is the span of the number (or the choice's word, or the name) itself.

Spans are locators of §4.1 inside the paragraph's own: a Word paragraph ("d:p:2-2") gives "d:p:2/ch:68-70", a text
line ("x:l:4-4") "x:l:4/ch:3-5", a PDF paragraph ("p:1/w:5-39", its words joined by spaces) "p:1/w:24-24@<box>". A
PDF span needs the box of its words, which a `ProseParagraph` does not carry: the caller passes `pdf_box`, the box of
a page's words first..last from the parsed document (contracts §13 report, D3).

Today's `citations.value_stated_in_quote` (any number of the quote, or 100 times it) is not reused.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from modeler_intake import fields
from modeler_intake.anchors import Box, DocxSpan, PdfSpan, TextSpan, format_locator
from modeler_intake.citations import normalize_for_match, quote_appears_in
from modeler_intake.document_reading import name_key, names_in
from modeler_intake.mapping.reading import NUMBER_TOKEN, RANGE_SIDE, joined, read_token, unit_after
from modeler_intake.mapping_spec import ProseFact, ProseParagraph

PdfBox = Callable[[int, int, int], Box]          # (page, first word, last word) -> the box of those words
# a number token of prose: digits with at most one decimal mark, not inside a word, a longer number or a unit ("CYP3A4",
# "B12", "t1/2", "mL/min/1.73 m2")
_NUMBER = re.compile(rf"(?<![\w.,/])({NUMBER_TOKEN})(?!\d)")
_CLAUSE_BREAK = re.compile(r";|\.(?= )| and ", re.IGNORECASE)
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_WORDS = re.compile(r"\S+")
_DOCX = re.compile(r"d:p:([1-9][0-9]*)(?:-([1-9][0-9]*)|/ch:(0|[1-9][0-9]*)-(0|[1-9][0-9]*))")
_TEXT = re.compile(r"x:l:([1-9][0-9]*)(?:-([1-9][0-9]*)|/ch:(0|[1-9][0-9]*)-(0|[1-9][0-9]*))")
_PDF = re.compile(r"p:([1-9][0-9]*)/w:([1-9][0-9]*)-([1-9][0-9]*)(?:@.*)?")
# the unit classes with a table, each named by one field of the class: a unit written after a number of a field with no
# table is read as written when it is one of theirs ("12.4 ng/mL" for pk.Cmax), never renamed
_TABLE_CLASSES = ("concentration", "dose", "time", "percent_dissolved")


class ProseFactError(ValueError):
    """A proposed prose fact the check refuses; the message says why (the model hears it as "REFUSED: <why>")."""


# --- the paragraph, normalized as quote_appears_in normalizes it, with the way back to its characters ----------------


@dataclass(frozen=True)
class _Mapped:
    """A text normalized as `citations.normalize_for_match` does (NFKC, line-break hyphens joined, whitespace collapsed),
    U+2212 read as "-", with `where[i]`: the index in the original text of normalized character i."""

    original: str
    text: str
    where: tuple[int, ...]

    def span(self, start: int, end: int) -> tuple[int, int]:
        """The original characters of normalized characters start..end (end exclusive)."""
        return self.where[start], self.where[end - 1] + 1

    def written(self, start: int, end: int) -> str:
        a, b = self.span(start, end)
        return self.original[a:b]


def _mapped(text: str) -> _Mapped | None:
    chars: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch):
            chars.append(c)
            where.append(i)
    joined = "".join(chars)
    keep = [True] * len(chars)
    for m in _HYPHEN_BREAK.finditer(joined):                  # "dos-\n ing" -> "dosing", as normalize_for_match does
        for k in range(m.start() + 1, m.end() - 1):
            keep[k] = False
    out: list[str] = []
    out_where: list[int] = []
    for c, w, kept in zip(chars, where, keep, strict=True):
        if not kept:
            continue
        if c.isspace():
            if not out or out[-1] == " ":
                continue
            c = " "
        out.append(c)
        out_where.append(w)
    while out and out[-1] == " ":
        out.pop()
        out_where.pop()
    normalized = "".join(out)
    if normalized != normalize_for_match(text):               # a composed sequence: no character-by-character way back
        return None
    return _Mapped(original=text, text=normalized.replace("\N{MINUS SIGN}", "-"), where=tuple(out_where))


@dataclass(frozen=True)
class _Number:
    value: float | None                       # None: "1,234", "1.000" (a thousands group or a decimal: never guessed)
    start: int                                # in the normalized text, the sign included
    end: int
    unit: str | None = None
    unit_span: tuple[int, int] | None = None
    joined: tuple[int, ...] = ()              # the other numbers of its range or list (indices into the paragraph's)


def _clauses(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """The clauses of text[start:end]: split at ";", at "." followed by a space and at " and ", spaces trimmed."""
    out = []
    cut = start
    for m in _CLAUSE_BREAK.finditer(text, start, end):
        out.append((cut, m.start()))
        cut = m.end()
    out.append((cut, end))
    trimmed = []
    for a, b in out:
        while a < b and text[a] in " ,.":
            a += 1
        while b > a and text[b - 1] in " ,.":
            b -= 1
        if a < b:
            trimmed.append((a, b))
    return trimmed


def _unit(field: str, text: str, pos: int, end: int) -> tuple[str, int, int] | None:
    """The unit written directly after a number of `field` (as written, and where in the normalized text): a unit of
    the field's class; for a class with no table, a unit of a class with one ("ng/mL", "mg", "h", "%") or the field's
    own label right after the number ("50 rpm", "900 mL", "72 kg")."""
    head = text[:end]
    if fields.unit_table(fields.unit_class(field)) is not None:
        found = unit_after(field, head, pos)
        return _unit_place(head, pos, found)
    if fields.unit_class(field) == "none":
        return None
    for name in _TABLE_CLASSES:
        found = unit_after(name, head, pos)
        if found is not None:
            return _unit_place(head, pos, found)
    definition = fields.field(field)
    if definition is not None and definition.cue:
        cue = re.compile(rf"[ \t]*(?:{definition.cue})", re.IGNORECASE).match(head, pos)
        if cue is not None:
            written = cue.group(0).strip()
            return written, cue.end() - len(written), cue.end()
    return None


def _unit_place(text: str, pos: int, found: str | None) -> tuple[str, int, int] | None:
    if found is None:
        return None
    at = text.find(found, pos)
    return (found, at, at + len(found)) if at >= 0 else None


def _numbers(field: str, text: str) -> list[_Number]:
    """Every number of the paragraph (in normalized coordinates), each with the unit written after it and the numbers
    it is joined to as a range or a list. A number glued to a letter counts only when a unit of a table follows it
    ("50mg", "12h"); "2nd", "CYP3A4" hold no number."""
    found = []
    for m in _NUMBER.finditer(text):
        written = m.group(1)
        after = m.end(1)
        if after < len(text) and text[after].isalpha() and not any(unit_after(n, text, after) for n in _TABLE_CLASSES):
            continue
        value = read_token(written, None)
        begin = m.start(1)
        if begin > 0 and text[begin - 1] == "-" and (begin - 1 == 0 or not text[begin - 2].isalnum()):
            begin -= 1                                         # a sign, not a range ("1.2-6.8") or a label ("230-23")
            value = -value if value is not None else None
        unit = _unit(field, text, after, len(text))
        found.append(_Number(value=value, start=begin, end=m.end(1), unit=unit[0] if unit else None,
                             unit_span=(unit[1], unit[2]) if unit else None))
    partners = joined(text, [(n.start, n.end) for n in found])
    return [_Number(value=n.value, start=n.start, end=n.end, unit=n.unit, unit_span=n.unit_span,
                    joined=tuple(sorted(partners[i]))) for i, n in enumerate(found)]


def _of_class(field: str, numbers: list[_Number]) -> set[int]:
    """The indices of the numbers of the field's unit class: followed by a unit of the class when the class has a
    table, else all; and every number joined to one of them as a range or a list."""
    if fields.unit_table(fields.unit_class(field)) is None:
        return set(range(len(numbers)))
    chosen = {i for i, n in enumerate(numbers) if n.unit is not None}
    for i in list(chosen):
        chosen |= set(numbers[i].joined)
    return chosen


def _number_value(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ProseFactError(f"{field} is a number: give the number the clause writes, not {value!r}")
    written = str(value).strip().replace("\N{MINUS SIGN}", "-")
    if re.fullmatch(r"[-+]?\d+,\d+", written) and not re.fullmatch(r"[-+]?\d{1,3},\d{3}", written):
        written = written.replace(",", ".")                    # "1,5" as the sentence writes it; "1,000" stays refused
    try:
        number = float(written)
    except ValueError as exc:
        raise ProseFactError(f"{field} is a number: give the number the clause writes (no unit), not {value!r}") from exc
    if not math.isfinite(number):
        raise ProseFactError(f"{field}: {value!r} is not a number")
    return number


def _joins(text: str, at: int, step: int) -> bool:
    """Whether the character at `at` continues a name's token: a letter or a digit, or a "-" or "_" with a letter or a
    digit beyond it ("Exampleamide-M1", "230-23" seen from "230-2")."""
    if not 0 <= at < len(text):
        return False
    if text[at].isalnum():
        return True
    beyond = at + step
    return text[at] in "-_" and 0 <= beyond < len(text) and text[beyond].isalnum()


def _name_span(text: str, name: str) -> tuple[int, int] | None:
    """Where `name` is written in `text` as a whole name (case, spaces and punctuation aside, as
    `document_reading.names_in` reads it: a contiguous match), as (start, end) of `text`; None when it is not. A match
    inside a longer name is no match: "Cohort 1" is not written in "Cohort 10", "230-2" not in "230-23", "Exampleamide"
    not in "Exampleamide-M1", "A" not in "Treatment"."""
    keys: list[str] = []
    where: list[int] = []
    for i, ch in enumerate(text):
        for u in ch.upper():
            if "A" <= u <= "Z" or "0" <= u <= "9":
                keys.append(u)
                where.append(i)
    wanted = name_key(name)
    joined_keys = "".join(keys)
    at = joined_keys.find(wanted) if wanted else -1
    while at >= 0:
        start, end = where[at], where[at + len(wanted) - 1] + 1
        if not _joins(text, start - 1, -1) and not _joins(text, end, 1):
            return start, end
        at = joined_keys.find(wanted, at + 1)
    return None


def _choice_span(field: str, choice: str, text: str, start: int, end: int) -> tuple[int, int]:
    """The fewest words of the clause that state the choice (`fields.read_choice`), the first such; the whole clause when
    only the whole clause does."""
    words = [(m.start(), m.end()) for m in _WORDS.finditer(text, start, end)]
    for size in range(1, len(words) + 1):
        for i in range(len(words) - size + 1):
            a, b = words[i][0], words[i + size - 1][1]
            while b > a and not text[b - 1].isalnum():
                b -= 1
            while a < b and not text[a].isalnum():
                a += 1
            if a < b and fields.read_choice(field, text[a:b]) == choice:
                return a, b
    return start, end


# --- spans as locators ---------------------------------------------------------------------------------------------


def _span_locator(locator: str | None, text: str, start: int, end: int, pdf_box: PdfBox | None, what: str) -> str:
    """The locator of characters start..end of a paragraph (or heading) whose own locator is `locator`."""
    if not locator:
        raise ProseFactError(f"the {what} has no locator: a span in it cannot be anchored")
    docx, line, pdf = _DOCX.fullmatch(locator), _TEXT.fullmatch(locator), _PDF.fullmatch(locator)
    if docx or line:
        match = docx or line
        first = int(match.group(1))
        if match.group(3) is not None:                     # a span: the text starts at that character of the paragraph
            number, offset = first, int(match.group(3))
        elif int(match.group(2)) == first:                 # one paragraph or line (a Word line break stays in it)
            number, offset = first, 0
        else:
            parts = text.split("\n")
            last = int(match.group(2))
            if last < first or len(parts) != last - first + 1:
                raise ValueError(f"the {what} {locator!r} names {last - first + 1} paragraphs or lines, its text holds "
                                 f"{len(parts)}: a span in it cannot be placed")
            before = text[:start].count("\n")
            if text[start:end].count("\n"):
                raise ProseFactError(f"the span {text[start:end]!r} runs over two paragraphs or lines")
            number, offset = first + before, -(text.rfind("\n", 0, start) + 1)
        a, b = start + offset, end + offset
        made = DocxSpan(paragraph=number, start=a, end=b) if docx else TextSpan(line=number, start=a, end=b)
        return format_locator(made)
    if pdf:
        page, first, last = int(pdf.group(1)), int(pdf.group(2)), int(pdf.group(3))
        words = [(m.start(), m.end()) for m in _WORDS.finditer(text)]
        if len(words) != last - first + 1:
            raise ValueError(f"the {what} {locator!r} names {last - first + 1} words, its text holds {len(words)}")
        covered = [k for k, (a, b) in enumerate(words) if a < end and b > start]
        if not covered:
            raise ProseFactError(f"the span {text[start:end]!r} covers no word of the {what}")
        if pdf_box is None:
            raise ValueError("a PDF span needs the box of its words: pass pdf_box (the parsed page's word boxes)")
        a, b = first + covered[0], first + covered[-1]
        return format_locator(PdfSpan(page=page, first_word=a, last_word=b, box=pdf_box(page, a, b)))
    raise ProseFactError(f"{locator!r} is not the locator of a paragraph (d:p, x:l or p:/w): tables are never read as prose")


def _label(kind: str, label: str, paragraph: ProseParagraph, pdf_box: PdfBox | None) -> tuple[str, str]:
    """(the label as written, the locator of its span) in the paragraph, else in its heading; ProseFactError when it is
    written in neither."""
    for text, locator, what in ((paragraph.text, paragraph.locator, "paragraph"),
                                (paragraph.heading, paragraph.heading_locator, "heading")):
        span = _name_span(text, label) if text and names_in(text, label) else None
        if span is not None:
            return text[span[0]:span[1]], _span_locator(locator, text, span[0], span[1], pdf_box, what)
    raise ProseFactError(f"the {kind} label {label!r} is not written in paragraph {paragraph.index} or its heading: "
                         f"name the {kind} only as the paragraph or its heading writes it, or leave it out")


# --- the check -------------------------------------------------------------------------------------------------------


def check_prose_fact(field: str, value: Any, quote: str, paragraph: ProseParagraph, *, study: str | None = None,
                     arm: str | None = None, pdf_box: PdfBox | None = None) -> ProseFact:
    """The fact as code reads it from the quoted clause of the paragraph (see the module docstring), or ProseFactError
    saying why the paragraph does not state it. `pdf_box` (page, first word, last word) -> box is needed for a PDF
    paragraph only: a ValueError without it, as for a paragraph whose text does not match its own locator."""
    definition = fields.field(field)
    if definition is None:
        raise ProseFactError(f"{field!r} is not a field of the ledger's vocabulary")
    if not isinstance(quote, str) or not quote_appears_in(paragraph.text, quote):
        raise ProseFactError(f"the quote is not in paragraph {paragraph.index} as written: copy at least 12 characters of "
                             "it exactly, the value's clause included")
    text = _mapped(paragraph.text)
    if text is None:
        raise ProseFactError(f"paragraph {paragraph.index} cannot be placed character by character")
    needle = normalize_for_match(quote).replace("\N{MINUS SIGN}", "-")
    at = text.text.find(needle)
    if at < 0:
        raise ProseFactError(f"the quote is not in paragraph {paragraph.index} as written")
    quoted = (at, at + len(needle))
    # the paragraph's clauses the quote touches, whole: a quote cut short does not leave out the clause's other numbers;
    # the label is looked for in the quoted part of the clause (`_quoted`)
    clauses = [(a, b) for a, b in _clauses(text.text, 0, len(text.text)) if a < quoted[1] and b > quoted[0]]
    cue = re.compile(definition.cue, re.IGNORECASE) if definition.cue else None
    if definition.value in ("number", "integer"):
        found, unit = _read_number(field, definition.value, value, text, clauses, cue, quoted)
    elif definition.value == "choice":
        found, unit = _read_choice(field, value, text, clauses, cue, quoted), None
    else:
        found, unit = _read_name(field, value, text, clauses, cue, quoted), None
    reading, (start, end) = found
    quote_at = text.span(at, at + len(needle))
    study_label = study_locator = arm_label = arm_locator = None
    if study is not None and str(study).strip():
        study_label, study_locator = _label("study", str(study), paragraph, pdf_box)
    if arm is not None and str(arm).strip():
        arm_label, arm_locator = _label("arm", str(arm), paragraph, pdf_box)
    a, b = text.span(start, end)
    return ProseFact(field=field, value=reading, unit=unit, quote=paragraph.text[quote_at[0]:quote_at[1]],
                     study_label=study_label, arm_label=arm_label,
                     locator=_span_locator(paragraph.locator, paragraph.text, a, b, pdf_box, "paragraph"),
                     study_locator=study_locator, arm_locator=arm_locator)


def _labelled(cue: re.Pattern[str] | None, clause: str) -> bool:
    return cue is None or cue.search(clause) is not None


def _quoted(text: str, start: int, end: int, quoted: tuple[int, int]) -> str:
    """The part of a clause the quote copies."""
    return text[max(start, quoted[0]):min(end, quoted[1])]


def _read_number(field: str, kind: str, value: Any, text: _Mapped, clauses: list[tuple[int, int]],
                 cue: re.Pattern[str] | None, quoted: tuple[int, int]) -> tuple[tuple[float, tuple[int, int]], str | None]:
    wanted = _number_value(value, field)
    unit_class = fields.unit_class(field)
    every = _numbers(field, text.text)
    of_class = _of_class(field, every)
    side = RANGE_SIDE.get(field)
    problems = []
    seen = []
    for start, end in clauses:
        clause = text.text[start:end]
        inside = [i for i in sorted(of_class) if every[i].start >= start and every[i].end <= end]
        numbers = [every[i] for i in inside]
        seen += [text.written(n.start, n.end) + (f" {text.written(*n.unit_span)}" if n.unit_span else "") for n in numbers]
        holding = [i for i in inside if every[i].value is not None and quoted[0] <= every[i].start
                   and every[i].end <= quoted[1] and math.isclose(every[i].value, wanted, rel_tol=1e-9, abs_tol=0.0)]
        if not holding:
            continue
        if not _labelled(cue, _quoted(text.text, start, end, quoted)):
            problems.append(f"the quoted clause {_quoted(text.text, start, end, quoted)!r} does not name {field} (quote "
                            "its label with the number, in the same clause)")
            continue
        number = every[holding[0]]
        partners = [every[i] for i in number.joined]
        if partners and not (side is not None and len(partners) == 1 and _is_range_end(text.text, number, partners[0], side)):
            stated = ", ".join(text.written(n.start, n.end) for n in sorted([number, *partners], key=lambda n: n.start))
            problems.append(f"the clause {clause!r} states a range or a list of {field} ({stated}), not one value")
            continue
        if len(numbers) - len(partners) != 1:
            written = ", ".join(text.written(n.start, n.end) for n in numbers)
            problems.append(f"the clause {clause!r} holds {len(numbers)} numbers of {field} ({written}): a fact's clause "
                            "states exactly one")
            continue
        if kind == "integer" and not wanted.is_integer():
            problems.append(f"{field} is a whole number; the clause writes {text.written(number.start, number.end)!r}")
            continue
        unit_of = number if number.unit_span else next((n for n in partners if n.unit_span), number)
        unit = text.written(*unit_of.unit_span) if unit_of.unit_span else None
        return (float(number.value), (number.start, number.end)), unit   # type: ignore[arg-type]
    if problems:
        raise ProseFactError(problems[0])
    stated = f"; code reads {', '.join(seen)}" if seen else ""
    table = " followed by its unit" if fields.unit_table(unit_class) is not None else ""
    raise ProseFactError(f"no clause of the quote states {field} {value!r} as a number{table}{stated} (the value is "
                         "the number as written: no unit conversion, no times 100)")


def _is_range_end(text: str, number: _Number, partner: _Number, side: int) -> bool:
    """Whether `number` is the `side` end (0 the start, 1 the end) of a two-number range with `partner` ("0-24 h")."""
    low, high = (partner, number) if partner.start < number.start else (number, partner)
    if re.fullmatch(r"\s*(?:-|–|—|to)\s*", text[low.end:high.start], re.IGNORECASE) is None:
        return False
    return (low, high)[side] is number


def _read_choice(field: str, value: Any, text: _Mapped, clauses: list[tuple[int, int]],
                 cue: re.Pattern[str] | None, quoted: tuple[int, int]) -> tuple[str, tuple[int, int]]:
    wanted = str(value).strip()
    read = []
    for whole_start, whole_end in clauses:
        start, end = max(whole_start, quoted[0]), min(whole_end, quoted[1])      # the quoted part of the clause
        clause = text.text[start:end]
        choice = fields.read_choice(field, clause)
        if choice is None:
            continue
        read.append(choice)
        if name_key(choice) == name_key(wanted) and _labelled(cue, clause):
            return choice, _choice_span(field, choice, text.text, start, end)
    stated = f"; code reads {', '.join(dict.fromkeys(read))}" if read else ""
    raise ProseFactError(f"no clause of the quote states {field} {wanted!r} (one of the choices "
                         f"{', '.join(fields.field(field).choices)}){stated}")  # type: ignore[union-attr]


def _read_name(field: str, value: Any, text: _Mapped, clauses: list[tuple[int, int]],
               cue: re.Pattern[str] | None, quoted: tuple[int, int]) -> tuple[str, tuple[int, int]]:
    if isinstance(value, bool) or not isinstance(value, str | int) or not name_key(value):
        raise ProseFactError(f"{field} is a name: give it as the paragraph writes it, not {value!r}")
    unlabelled = None
    for start, end in clauses:
        a, b = max(start, quoted[0]), min(end, quoted[1])              # the name and its label stand in the quote
        part = text.text[a:b]
        span = _name_span(part, str(value)) if names_in(part, str(value)) else None
        if span is None:
            continue
        if not _labelled(cue, part):
            unlabelled = part
            continue
        if _joins(text.text, a + span[0] - 1, -1) or _joins(text.text, a + span[1], 1):
            continue                                                 # the quote cut a longer name
        return text.written(a + span[0], a + span[1]), (a + span[0], a + span[1])
    if unlabelled is not None:
        raise ProseFactError(f"the clause {unlabelled!r} does not name {field} (its label must be in the same clause)")
    raise ProseFactError(f"no clause of the quote writes the {field} {str(value)!r} as one name (case, spaces and "
                         "punctuation aside)")
