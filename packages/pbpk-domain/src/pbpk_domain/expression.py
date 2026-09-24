"""Expression profiles for the proteins a compound's processes act through (MS-01 §S0).

A metabolising enzyme, transporter or binding partner acts in PK-Sim only where it is expressed. The profiles
come from `data/expression_library.json`, harvested verbatim from the OSP reference model snapshots by
`scripts/harvest_expression_library.py` — never invented. A molecule that is not in the library cannot be
placed, and S0 reports it, because a process without its protein silently eliminates nothing.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources

from pbpk_domain.snapshot.builder import ExpressionSpec

# The category the campaign's individuals reference ("<molecule>|Human|Healthy").
DEFAULT_CATEGORY = "Healthy"


@cache
def expression_library() -> dict[str, dict]:
    """molecule -> {"source": {model, category}, "alternatives": [...], "profile": <snapshot profile>}."""
    text = resources.files("pbpk_domain.data").joinpath("expression_library.json").read_text(encoding="utf-8")
    return json.loads(text)["molecules"]


def library_expression(molecule: str, *, category: str = DEFAULT_CATEGORY, species: str = "Human") -> ExpressionSpec | None:
    """The harvested expression profile for ``molecule`` as a builder spec, or None when it is not harvested."""
    entry = expression_library().get(molecule)
    if entry is None:
        return None
    profile = entry["profile"]
    return ExpressionSpec(type=profile["Type"], molecule=molecule, species=species, category=category, harvested=profile)


def expression_source(molecule: str) -> str | None:
    """Where the library's profile for ``molecule`` came from, for the record ("Dapagliflozin model, Healthy")."""
    entry = expression_library().get(molecule)
    if entry is None:
        return None
    return f"OSP {entry['source']['model']} model ({entry['source']['category']})"
