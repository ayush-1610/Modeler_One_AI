"""The evidence register (plan §8): every value or dataset that may enter a model, with its source and grade.

An `EvidenceItem` is PROPOSED (by an agent or a person) and then ACCEPTED or REJECTED by a person; each decision is a
new version of the EVIDENCE artifact, so the history of a value is its chain of versions. Code, not the agent, does
the arithmetic (unit conversion to the PK-Sim storage unit), the confidence grade (§8.4) and the flags (value not in
the quote, missing conditions, physically impossible values, conflicts with other evidence). Conflicting values are
shown side by side, never averaged.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pbpk_domain.parameter_units import ConversionError, to_storage_unit


class SourceType(StrEnum):
    CLIENT_REPORT = "CLIENT_REPORT"
    CLIENT_FILE = "CLIENT_FILE"
    REGULATORY_REVIEW = "REGULATORY_REVIEW"
    PUBLICATION = "PUBLICATION"
    DATABASE = "DATABASE"
    OSP_LIBRARY = "OSP_LIBRARY"
    PROPOSAL = "PROPOSAL"
    PREDICTED = "PREDICTED"
    ASSUMPTION = "ASSUMPTION"


class Extraction(StrEnum):
    TEXT = "TEXT"
    TABLE = "TABLE"
    FIGURE_DIGITIZED = "FIGURE_DIGITIZED"
    CELL = "CELL"
    COMPUTED = "COMPUTED"
    MANUAL = "MANUAL"


class EvidenceState(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


PRIMARY = {SourceType.REGULATORY_REVIEW, SourceType.PUBLICATION, SourceType.CLIENT_REPORT, SourceType.CLIENT_FILE}


class SourceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_sha256: str | None = None   # a stored document (uploaded, fetched full text, retrieved record)
    page: int | None = None
    locator: str = ""               # Table 2, Figure 3, Sheet!B4
    title: str = ""
    authors: str = ""
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    req_id: str | None = None
    target: str                     # concrete CPF id, e.g. bind.fu, elim.hepatic.UGT1A9.clspec
    value: float | str | None = None
    unit: str | None = None         # as stated in the source
    value_pksim: float | None = None
    unit_pksim: str | None = None
    conversion: str = ""
    source_type: SourceType
    source: SourceRef = Field(default_factory=SourceRef)
    quote: str = ""
    extraction: Extraction = Extraction.TEXT
    conditions: dict[str, str] = Field(default_factory=dict)
    confidence: Literal["A", "B", "C", "D"] = "D"
    flags: tuple[str, ...] = ()
    purpose: str = "model_building"
    provider: Literal["CLIENT", "LITERATURE"] = "LITERATURE"
    state: EvidenceState = EvidenceState.PROPOSED
    proposed_by: str = ""
    proposed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str = ""
    note: str = ""

    def to_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_content(cls, content: dict[str, Any]) -> EvidenceItem:
        return cls.model_validate(content)


def new_id() -> str:
    return f"ev-{uuid.uuid4().hex[:10]}"


# Physical validity only (not SME plausibility): a value outside these cannot be right whatever the source.
_PHYSICAL = {"bind.fu": (0.0, 1.0), "phys.mw": (10.0, 1e6), "phys.logp": (-10.0, 15.0), "dist.bp_ratio": (0.0, 20.0),
             "elim.renal.gfr_fraction": (0.0, 10.0)}


_STOP = {"or", "and", "of", "the", "per", "vs", "a", "an"}


def _missing_conditions(required: tuple[str, ...], given: dict[str, str]) -> list[str]:
    """Required conditions none of whose words appear among the recorded conditions (a flag, not a rejection)."""
    text = " ".join(f"{k} {v}" for k, v in given.items()).lower()
    missing = []
    for label in required:
        words = [w for w in re.findall(r"[a-z0-9,.]+", label.lower().replace(",", " ")) if len(w) > 1 and w not in _STOP]
        if words and not any(w in text for w in words):
            missing.append(label)
    return missing


def assess(item: EvidenceItem, *, required_conditions: tuple[str, ...] = (), value_in_quote: bool | None = None) -> EvidenceItem:
    """Convert to the storage unit, grade (plan §8.4) and flag. Returns the item with these fields set."""
    flags: list[str] = [f for f in item.flags if f.startswith("conflict")]
    value_pksim, unit_pksim, how = item.value_pksim, item.unit_pksim, item.conversion
    if isinstance(item.value, int | float) and value_pksim is None:
        try:
            converted = to_storage_unit(item.target, float(item.value), item.unit)
            value_pksim, unit_pksim, how = converted.value, converted.unit, converted.how
        except ConversionError as exc:
            flags.append(f"needs_conversion: {exc}")
    if value_in_quote is False:
        flags.append("value_not_in_quote")
    missing = _missing_conditions(required_conditions, item.conditions)
    flags.extend(f"condition_missing: {c}" for c in missing)
    species = item.conditions.get("species", "").strip().lower()
    if species and species not in ("human", "humans", "man", "healthy volunteers"):
        flags.append(f"species_mismatch: {species}")
    bounds = _PHYSICAL.get(item.target)
    if bounds and value_pksim is not None and not bounds[0] < value_pksim <= bounds[1]:
        flags.append(f"outside_physical_range {bounds[0]:g}–{bounds[1]:g}")

    if item.source_type is SourceType.ASSUMPTION:
        grade = "D"
    elif item.source_type is SourceType.PREDICTED or item.extraction in (Extraction.FIGURE_DIGITIZED, Extraction.COMPUTED):
        grade = "C"
    elif item.source_type in PRIMARY and not missing and value_in_quote is not False and not species.startswith(("rat", "dog", "mouse", "monkey")):
        grade = "A"
    else:
        grade = "B"
    return item.model_copy(update={"value_pksim": value_pksim, "unit_pksim": unit_pksim, "conversion": how,
                                   "confidence": grade, "flags": tuple(dict.fromkeys(flags))})


def flag_conflicts(items: list[EvidenceItem], *, fold: float = 2.0) -> list[EvidenceItem]:
    """Mark items of the same target whose converted values differ by more than `fold` (rejected items excluded)."""
    by_target: dict[str, list[EvidenceItem]] = defaultdict(list)
    for item in items:
        if item.state is not EvidenceState.REJECTED and item.value_pksim not in (None, 0):
            by_target[item.target].append(item)
    out = []
    for item in items:
        peers = [p for p in by_target.get(item.target, []) if p.id != item.id and p.unit_pksim == item.unit_pksim]
        base = [f for f in item.flags if not f.startswith("conflict")]
        if item.value_pksim not in (None, 0) and item.state is not EvidenceState.REJECTED:
            far = [p for p in peers if max(abs(p.value_pksim), abs(item.value_pksim)) /
                   max(min(abs(p.value_pksim), abs(item.value_pksim)), 1e-300) > fold]
            if far:
                base.append(f"conflict >{fold:g}-fold with {', '.join(p.id for p in far)}")
        out.append(item.model_copy(update={"flags": tuple(base)}))
    return out
