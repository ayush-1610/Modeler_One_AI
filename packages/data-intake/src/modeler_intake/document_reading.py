"""Reading a client's PDF or Word file for project data (docs/plans/2026-11-03-inputs-and-client-data.md §3.4, build I4).

What code does, with no AI:
- **the inventory:** the pages that seem to hold project data (a concentration table, NCA results, a dissolution table, the
  study design, demographics, composition, a bioanalytical method, a figure), each with the line that says so, in the
  order the file's tag asks for (a formulation file's dissolution tables first, a clinical file's design and PK first);
- **the checks** the reading agent's proposals pass before a person sees them: a study or product fact must be stated by
  its quote (the number, with its unit where it has one, or a word that says the category: "fasted", "intravenous
  infusion", "capsule"), a name must be written in its quote, and a dose is converted to mg by code.

The agent proposes, code checks, and a person confirms on Inputs (§3.3); nothing here decides a value.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from modeler_intake.citations import normalize_for_match, quote_appears_in, value_stated_in_quote

# --- the inventory -------------------------------------------------------------------------------------------------

_LINE = 160
_PER_KIND = 6
_TOTAL = 30

# What a page holds, by the words of one of its lines. Order matters only for the label of a line matching two kinds.
_HOLDS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("figure", "a figure of concentrations or dissolution (a person digitizes it)",
     re.compile(r"^\s*fig(?:ure)?\.?\s*\d+.*(?:concentration|dissol|release)", re.IGNORECASE)),
    ("pk_table", "a concentration-time table",
     re.compile(r"(?:plasma|serum|blood)?\s*concentrations?\b.*\b(?:time|h\b|hours?|min)|"
                r"^\s*table\s*\d+.*concentration", re.IGNORECASE)),
    ("nca", "NCA results (Cmax, AUC, t½)", re.compile(r"\bc\s?max\b|\bauc(?:0|inf|last|\b|_)|\bt\s?1/2\b|half[- ]life|\bt\s?max\b", re.IGNORECASE)),
    ("dissolution", "a dissolution table or method",
     re.compile(r"dissolution|%\s*(?:dissolved|released)|\bpaddle\b|\bbasket\b", re.IGNORECASE)),
    ("design", "the study design and dosing",
     re.compile(r"study design|single[- ]dose|multiple[- ]dose|randomi[sz]ed|cross-?over|\bfasted\b|\bfed\b|"
                r"administered|dose of \d", re.IGNORECASE)),
    ("demographics", "demographics", re.compile(r"demographic|\bage\b.*years|body weight|\bbmi\b", re.IGNORECASE)),
    ("composition", "composition (as reported, not used by the model)",
     re.compile(r"composition|excipient|per tablet|per capsule|mg/tablet", re.IGNORECASE)),
    ("bioanalytical", "the bioanalytical method (LLOQ)",
     re.compile(r"\blloq\b|lower limit of quantif|lc-?ms|calibration range", re.IGNORECASE)),
)
_FIRST: dict[str, tuple[str, ...]] = {   # the kinds a file's tag asks to look for first
    "clinical": ("design", "pk_table", "nca", "demographics", "bioanalytical", "figure"),
    "formulation": ("dissolution", "composition", "figure"),
    "bioanalytical": ("bioanalytical",),
}


@dataclass(frozen=True)
class InventoryItem:
    page: int
    holds: str          # pk_table, nca, dissolution, design, demographics, composition, bioanalytical, figure
    label: str
    line: str           # the page's own line that says so (a quote of the page)

    def to_content(self) -> dict[str, Any]:
        return asdict(self)


def inventory(pages: list[str], tag: str = "other") -> list[InventoryItem]:
    """The pages that seem to hold project data, each with the line that says so; the kinds the tag asks for first."""
    found: dict[str, list[InventoryItem]] = {}
    for number, text in enumerate(pages, start=1):
        seen: set[str] = set()
        for raw in text.splitlines():
            line = " ".join(raw.split())
            if len(line) < 4:
                continue
            for holds, label, pattern in _HOLDS:
                if holds in seen or not pattern.search(line):
                    continue
                seen.add(holds)
                if len(found.setdefault(holds, [])) < _PER_KIND:
                    found[holds].append(InventoryItem(number, holds, label, line[:_LINE]))
                break
    first = _FIRST.get(tag, ())
    order = [*first, *(h for h, _l, _p in _HOLDS if h not in first)]
    return [item for holds in order for item in found.get(holds, [])][:_TOTAL]


# --- the checks ----------------------------------------------------------------------------------------------------

FACT_FIELDS = ("dose", "n", "route", "food_state", "formulation", "design", "lloq",
               # the subjects' demographics (D-29): numbers for the study's individual, and hints for the person's choice
               # of its PK-Sim population and sex (a person chooses those: §3.3)
               "age_mean", "age_min", "age_max", "weight_mean", "height_mean", "females", "female_percent", "ethnicity")
DEMOGRAPHIC_FIELDS = ("age_mean", "age_min", "age_max", "weight_mean", "height_mean", "females", "female_percent", "ethnicity")
CHOICES: dict[str, tuple[str, ...]] = {
    "route": ("oral", "iv_bolus", "iv_infusion"),
    "food_state": ("fasted", "fed"),
    "formulation": ("solution", "suspension", "ir_tablet", "ir_capsule", "mr", "other"),
    "design": ("SD", "MD"),
    "role": ("TEST", "RLD", "REFERENCE", "OTHER"),
}
# The words that state a category in a quote. A reading check, not a reconciliation rule: what the person then compares
# across files is client_reconciliation.yaml's (SME-governed).
_CUES: dict[str, re.Pattern[str]] = {
    "oral": re.compile(r"\boral(?:ly)?\b|\bp\.?\s?o\.?\b|\btablets?\b|\bcapsules?\b|swallow", re.IGNORECASE),
    "iv_bolus": re.compile(r"\bbolus\b|intravenous(?:ly)? (?:injection|push)|\bi\.?v\.? (?:injection|push)", re.IGNORECASE),
    "iv_infusion": re.compile(r"infusion", re.IGNORECASE),
    # a negated fast ("non-fasted", "not fasting", "no fasting") states no fast: it reads as neither choice, never as fasted
    "fasted": re.compile(r"(?<!non[-\u2010\u2011\u2013 ])(?<!not )(?<!no )\bfast(?:ed|ing)?\b|empty stomach", re.IGNORECASE),
    "fed": re.compile(r"\bfed\b|\bmeal\b|breakfast|with food|high[- ]fat|after food", re.IGNORECASE),
    "ir_tablet": re.compile(r"\btablets?\b", re.IGNORECASE),
    "ir_capsule": re.compile(r"\bcapsules?\b", re.IGNORECASE),
    "solution": re.compile(r"\bsolution\b|\bsyrup\b", re.IGNORECASE),
    "suspension": re.compile(r"\bsuspension\b", re.IGNORECASE),
    "mr": re.compile(r"modified[- ]release|extended[- ]release|prolonged[- ]release|controlled[- ]release|"
                     r"sustained[- ]release|delayed[- ]release|\b(?:ER|XR|SR|MR|CR)\b", re.IGNORECASE),
    "other": re.compile(r"\w", re.IGNORECASE),
    "SD": re.compile(r"single[- ](?:oral )?(?:dose|administration)", re.IGNORECASE),
    "MD": re.compile(r"multiple[- ](?:oral )?dos|repeated[- ]dos|once[- ]daily|twice[- ]daily|\bq\.?d\.?\b|\bb\.?i\.?d\.?\b|"
                     r"steady[- ]state|for \d+ (?:consecutive )?days", re.IGNORECASE),
    "TEST": re.compile(r"\btest\b|\bgeneric\b|\bcandidate\b", re.IGNORECASE),
    "RLD": re.compile(r"\bRLD\b|reference listed|innovator|originator|\bbrand", re.IGNORECASE),
    "REFERENCE": re.compile(r"\breference\b|\bcomparator\b", re.IGNORECASE),
    "OTHER": re.compile(r"\w", re.IGNORECASE),
}
_MG_PER: dict[str, float] = {"mg": 1.0, "g": 1000.0, "µg": 0.001}
_DOSE_UNIT = re.compile(r"(?<![a-zµμ])(mg/kg|mg|g|µg|μg|ug|mcg)(?![a-z])", re.IGNORECASE)
_CONC_UNIT = re.compile(r"(?<![a-zµμ])((?:ng|pg|µg|μg|ug|mg|nmol|µmol|μmol|umol|pmol)\s*/\s*(?:ml|l|dl))(?![a-z])", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9µμ]+(?:\.[0-9]+)?", re.IGNORECASE)


_AGE = re.compile(r"\bage[ds]?\b|\byears?\b|\byrs?\b", re.IGNORECASE)
_FEMALE = re.compile(r"\bfemales?\b|\bwom[ae]n\b", re.IGNORECASE)


class FactError(ValueError):
    """A proposed fact its quote does not state; the message says what to fix."""


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(normalize_for_match(text))]


def name_key(name: Any) -> str:
    """A name as code compares it: case, spaces and punctuation do not make another study or product."""
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def names_in(quote: str, *names: str) -> bool:
    """Whether every name is written in the quote (case, spaces and punctuation aside)."""
    key = name_key(quote)
    return all(name_key(n) and name_key(n) in key for n in names)


def text_in(value: str, quote: str) -> bool:
    """Whether every word and number of a text value (a product, batch, medium or apparatus) is in the quote."""
    words = _tokens(value)
    have = set(_tokens(quote))
    return bool(words) and all(w in have for w in words)


def supports_choice(value: str, quote: str) -> bool:
    cue = _CUES.get(value)
    return cue is not None and cue.search(normalize_for_match(quote)) is not None


def _dose_unit(unit: str) -> str:
    u = unit.strip().lower().replace("μ", "µ")
    return "µg" if u in ("ug", "mcg") else u


def _number(value: Any, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FactError(f"{what} must be a number, not {value!r}") from exc
    if number <= 0:
        raise FactError(f"{what} must be above 0")
    return number


def check_fact(field: str, value: Any, unit: str | None, quote: str) -> dict[str, Any]:
    """The study record fields a quoted fact sets (code converts a dose to mg), or FactError saying why the quote does not
    state it. The quote's place on its page is checked by the caller."""
    if field not in FACT_FIELDS:
        raise FactError(f"unknown fact {field!r}: one of {', '.join(FACT_FIELDS)}")
    if field == "dose":
        number = _number(value, "dose")
        written = _dose_unit(unit or "")
        if written not in (*_MG_PER, "mg/kg"):
            raise FactError(f"dose unit {unit!r}: one of mg, g, µg, mcg, mg/kg")
        units = {_dose_unit(u) for u in _DOSE_UNIT.findall(normalize_for_match(quote))}
        if not value_stated_in_quote(number, quote) or written not in units:
            raise FactError(f"the quote must state the dose {number:g} {unit}")
        if written == "mg/kg":
            return {"dose_mg": number, "dose_per_kg": True}
        return {"dose_mg": round(number * _MG_PER[written], 9), "dose_per_kg": False}
    if field == "n":
        number = _number(value, "n")
        if number != int(number) or not value_stated_in_quote(number, quote):
            raise FactError(f"the quote must state the number of subjects, {value}")
        return {"n": int(number)}
    if field in ("age_mean", "age_min", "age_max"):
        number = _number(value, "age")
        if not value_stated_in_quote(number, quote) or not _AGE.search(normalize_for_match(quote)):
            raise FactError(f"the quote must state the age {number:g} (years)")
        return {field: number}
    if field in ("weight_mean", "height_mean"):
        number = _number(value, field.split("_")[0])
        unit_word = "kg" if field == "weight_mean" else "cm"
        if (unit or unit_word).strip().lower() != unit_word:
            raise FactError(f"{field.split('_')[0]} in {unit_word}, as the file states it (code converts nothing here)")
        if not value_stated_in_quote(number, quote) or not re.search(rf"\b{unit_word}\b", normalize_for_match(quote), re.IGNORECASE):
            raise FactError(f"the quote must state {number:g} {unit_word}")
        return {field: number}
    if field in ("females", "female_percent"):
        number = float(value) if isinstance(value, int | float) or str(value).replace(".", "", 1).isdigit() else -1.0
        if number < 0 or (field == "females" and number != int(number)) or (field == "female_percent" and number > 100):
            raise FactError(f"{field} must be {'a count' if field == 'females' else 'a percentage'}")
        text = normalize_for_match(quote)
        if not value_stated_in_quote(number, quote) or not _FEMALE.search(text) or (field == "female_percent" and "%" not in text):
            raise FactError(f"the quote must state {number:g}{' %' if field == 'female_percent' else ''} women or females")
        return {field: int(number) if field == "females" else number}
    if field == "ethnicity":
        written = str(value).strip()
        if not written or not text_in(written, quote):
            raise FactError(f"the quote must write the ethnicity {written!r} as the file does")
        return {"ethnicity": written}
    if field == "lloq":
        number = _number(value, "LLOQ")
        units = {re.sub(r"\s", "", u).lower() for u in _CONC_UNIT.findall(normalize_for_match(quote))}
        if not value_stated_in_quote(number, quote) or re.sub(r"\s", "", unit or "").lower() not in units:
            raise FactError(f"the quote must state the LLOQ {number:g} {unit}")
        return {"lloq": number, "lloq_unit": (unit or "").strip()}
    choice = str(value).strip()
    if choice not in CHOICES[field]:
        raise FactError(f"{field} {value!r}: one of {', '.join(CHOICES[field])}")
    if not supports_choice(choice, quote):
        raise FactError(f"the quote does not say {field} is {choice}")
    return {field: choice}


def check_quote(page_text: str | None, quote: str) -> str | None:
    """None when the quote is on the page verbatim, else what is wrong."""
    if page_text is None:
        return "no such page in this file"
    if not quote_appears_in(page_text, quote):
        return "the quote is not on that page verbatim"
    return None


def check_component(name: str, amount: Any, unit: str, quote: str) -> dict[str, Any]:
    """One line of a product's composition as the file reports it (§3.6: shown, not used by the model): the quote
    writes the component and states its amount with its unit."""
    written = str(name).strip()
    number = _number(amount, "amount")
    if not written or not text_in(written, quote):
        raise FactError(f"the quote must write the component {written!r}")
    if not value_stated_in_quote(number, quote) or re.sub(r"\s", "", unit or "").lower() not in re.sub(r"\s", "", normalize_for_match(quote)).lower():
        raise FactError(f"the quote must state {number:g} {unit}")
    return {"name": written, "amount": number, "unit": str(unit).strip()}
