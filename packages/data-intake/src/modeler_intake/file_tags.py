"""File tags (docs/plans/2026-11-03-inputs-and-client-data.md §3.1; the owner, 2026-11-03).

A person tags each client file at upload with what it is, at a high level: formulation or dissolution, a clinical study
(optionally which one), bioanalytical, in vitro or physico-chemistry, or other. The tag is a hint for reading the file,
not a fact. Code pre-fills it from the file's name and, once the file is read, proposes another tag when the content says
otherwise, quoting what prompted it: a sheet's classification and its header cell, or a document's words and page. Nothing
is re-tagged silently; the person keeps one.

The name rules are mirrored for the upload forms in `apps/web/lib/fileTags.ts`; change both together.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal, get_args

from modeler_intake.triage import SheetCategory

TagKind = Literal["formulation", "clinical", "bioanalytical", "in_vitro", "other"]
TAG_KINDS: tuple[TagKind, ...] = get_args(TagKind)
LABELS: dict[TagKind, str] = {
    "formulation": "formulation or dissolution", "clinical": "clinical study", "bioanalytical": "bioanalytical",
    "in_vitro": "in vitro or physico-chemistry", "other": "other",
}

# File-name rules, first match wins: "proposal" routes the file to the brief, anything else is a client file's tag.
_NAME_RULES: tuple[tuple[Literal["proposal"] | TagKind, re.Pattern[str]], ...] = (
    ("proposal", re.compile(r"proposal|quotation|\bsow\b|statement of work")),
    ("bioanalytical", re.compile(r"bioanaly|\blc ?ms|\bbmv\b|method valid|assay valid")),
    ("in_vitro", re.compile(r"\badme\b|in ?vitro|\bcaco|\bppb\b|protein binding|microsom|hepatocyte|physchem|physico|"
                            r"solubil|permeab|\blog ?[pd]\b|\bpka\b")),
    ("formulation", re.compile(r"dissol|formulat|composition|\bbatch|\blots?\b|\bcoa\b|tablet|capsule")),
    ("clinical", re.compile(r"\bpk\b|pharmacokin|\bconc|\bcsr\b|protocol|clinical|\bstudy\b|subject|demograph|dosing|"
                            r"plasma|\bnca\b")),
)

_SHEET_TAG: dict[SheetCategory, TagKind] = {
    SheetCategory.DISSOLUTION: "formulation", SheetCategory.PRODUCT_INFO: "formulation",
    SheetCategory.PK_INDIVIDUAL: "clinical", SheetCategory.PK_SUMMARY: "clinical", SheetCategory.PK_PARAMETERS: "clinical",
    SheetCategory.STUDIES: "clinical", SheetCategory.DEMOGRAPHICS: "clinical", SheetCategory.URINE_FECES: "clinical",
    SheetCategory.BIOANALYTICAL: "bioanalytical", SheetCategory.PHYSCHEM_INVITRO: "in_vitro",
}
_SHEET_WORDS = {
    SheetCategory.DISSOLUTION: "dissolution", SheetCategory.PRODUCT_INFO: "product information",
    SheetCategory.PK_INDIVIDUAL: "individual concentrations", SheetCategory.PK_SUMMARY: "summary concentrations",
    SheetCategory.PK_PARAMETERS: "PK parameters", SheetCategory.STUDIES: "study design",
    SheetCategory.DEMOGRAPHICS: "demographics", SheetCategory.URINE_FECES: "urine or feces",
    SheetCategory.BIOANALYTICAL: "bioanalytical", SheetCategory.PHYSCHEM_INVITRO: "physico-chemistry or in vitro",
}

# Words that mark a kind of document; each distinct word found counts once.
_DOC_WORDS: dict[TagKind, tuple[str, ...]] = {
    "formulation": (r"dissolution", r"% ?dissolved", r"\bpaddle\b", r"\bapparatus\b", r"\bbatch\b", r"composition",
                    r"excipient", r"\brpm\b", r"similarity factor|\bf2\b"),
    "clinical": (r"clinical study report", r"\bprotocol\b", r"\bsubjects\b", r"pharmacokinetic", r"\bcmax\b", r"\bauc",
                 r"randomi[sz]ed", r"\bcohort", r"single dose|multiple dose|single oral dose"),
    "bioanalytical": (r"bioanalytical", r"\blloq\b", r"lc-?ms", r"calibration (?:curve|standard)", r"method validation",
                      r"quality control samples?|\bqcs?\b", r"matrix effect", r"incurred sample"),
    "in_vitro": (r"caco-?2", r"microsom", r"hepatocyte", r"protein binding|fraction unbound", r"\bpapp\b|permeability",
                 r"\bclint\b|intrinsic clearance", r"solubility", r"\blog ?[pd]\b|\bpka\b"),
}
_DOC_PAGES = 6          # the first pages say what a document is
_DOC_MIN_WORDS = 3      # distinct words before a document's kind is proposed
_QUOTE = 80


@dataclass(frozen=True)
class TagHint:
    """A tag that code read from a file's content, with what prompted it, quoted."""

    kind: TagKind
    why: str


def _normal(name: str) -> str:
    return re.sub(r"[_\-.]+", " ", name.lower())


def guess_from_name(name: str) -> Literal["proposal"] | TagKind | None:
    """What a file's name says it is, or None when it says nothing."""
    text = _normal(name)
    return next((kind for kind, rule in _NAME_RULES if rule.search(text)), None)


def default_tag(name: str) -> TagKind:
    """The tag of a client file nobody tagged: its name's, else "other"."""
    guess = guess_from_name(name)
    return guess if guess not in (None, "proposal") else "other"  # type: ignore[return-value]


def from_triage(rows: list[dict[str, Any]]) -> TagHint | None:
    """The kind most of a workbook's data sheets hold, from code's or a person's classification of each sheet. None
    for an empty workbook, or one where two kinds tie."""
    tagged = [(row, _SHEET_TAG[SheetCategory(row["category"])]) for row in rows
              if row.get("category") and SheetCategory(row["category"]) in _SHEET_TAG]
    if not tagged:
        return None
    counts = Counter(kind for _row, kind in tagged).most_common()
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return None
    kind = counts[0][0]
    row = next(r for r, k in tagged if k == kind)
    category = SheetCategory(row["category"])
    why = f"sheet “{row['sheet']}” holds {_SHEET_WORDS[category]}"
    if row.get("evidence_quote"):
        why += f" (header “{row['evidence_quote'][:_QUOTE]}”, {row['evidence_cell']})"
    share = f"{counts[0][1]} of {len(tagged)} data sheets" if len(tagged) > 1 else ""
    return TagHint(kind, f"{why}; {share}" if share else why)


def from_pages(pages: list[str]) -> TagHint | None:
    """The kind a document's first pages are about: at least three distinct words of one kind, and twice as many as of
    any other. None when the text does not say clearly (a scan has no text at all)."""
    found: dict[TagKind, list[tuple[int, str]]] = {}
    for kind, words in _DOC_WORDS.items():
        hits = []
        for pattern in words:
            for number, text in enumerate(pages[:_DOC_PAGES], start=1):
                if match := re.search(pattern, text, re.IGNORECASE):
                    hits.append((number, match.group(0)))
                    break
        found[kind] = hits
    ranked = sorted(found.items(), key=lambda kv: len(kv[1]), reverse=True)
    (kind, hits), (_other, second) = ranked[0], ranked[1]
    if len(hits) < _DOC_MIN_WORDS or len(hits) < 2 * len(second):
        return None
    quoted = ", ".join(f"“{word}” (page {page})" for page, word in hits[:4])
    return TagHint(kind, f"the text reads {quoted}")
