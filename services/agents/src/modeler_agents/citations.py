"""Deterministic citation checks applied to every value an agent proposes."""

from __future__ import annotations

import math
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_NUMBER = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
MIN_QUOTE_CHARS = 12


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    return _WHITESPACE.sub(" ", text).strip()


def quote_appears_in(page_text: str, quote: str) -> bool:
    """True if the quote occurs verbatim (modulo whitespace, Unicode form, and line-break hyphenation)."""
    needle = normalize_for_match(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return False
    return needle in normalize_for_match(page_text)


def numbers_in(text: str) -> list[float]:
    return [float(match) for match in _NUMBER.findall(normalize_for_match(text))]


def value_stated_in_quote(value: float, quote: str) -> bool:
    """Whether the quote states the proposed value literally, or as a percentage of it.

    A False result is not a rejection (the value may be derived, e.g. from a table in other units);
    it tells the curator that the number was transformed.
    """
    return any(math.isclose(n, value, rel_tol=1e-6) or math.isclose(n, value * 100, rel_tol=1e-6) for n in numbers_in(quote))
