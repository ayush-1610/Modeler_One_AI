"""The Data room's rules (`dataroom_rules.yaml`, plan 2026-11-21 v2 §8) and their typed loader.

PROVISIONAL: UNVERIFIED until the SME signs. A change is a science change: a CHANGELOG entry, a version bump and the
owner's approval. Every view carries `label()` (version, status, sha256), so a report says which rules made it.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

FILE = "dataroom_rules.yaml"


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AnalysisSets(_B):
    evaluable_min_quantifiable: int


class Means(_B):
    blq_predose: str
    blq_postdose_arithmetic: str
    blq_postdose_geometric: str


class BlqRule(_B):
    """Below the LLOQ before the first quantifiable sample (zero, exclude) and after it (exclude, zero, half_lloq)."""

    before: Literal["zero", "exclude"]
    after: Literal["exclude", "zero", "half_lloq"]

    def label(self) -> str:
        words = {"zero": "0", "exclude": "left out", "half_lloq": "LLOQ/2"}
        return f"below the LLOQ {words[self.before]} before the first quantifiable sample, {words[self.after]} after it"


class Reproduce(_B):
    """The client's NCA reproduced (plan 2026-11-24 §8 feature 3): the settings tried and the tiers (the literature
    review's proposal, UNVERIFIED). The first of each list is ours."""

    pass_percent: float
    investigate_percent: float
    integration: list[Literal["linear-up/log-down", "linear"]]
    time_basis: list[Literal["nominal", "actual"]]
    blq: list[BlqRule]
    lambda_z: list[Literal["best_fit"] | int]


class Nca(_B):
    method: str
    blq_leading: str
    blq_after_first: str
    tolerance_percent: float
    tmax_tolerance_h: float
    reproduce: Reproduce


class Flags(_B):
    """Exclusion flags (plan 2026-11-24 §8 feature 4): each a reason on a profile, never a deletion."""

    predose_max_percent_of_cmax: float
    auc_extrapolated_max_percent: float
    terminal_span_min_half_lives: float
    vomiting_max_tmax_multiple: float
    sample_window_percent: float
    sample_window_min_minutes: float


class Dissolution(_B):
    client_mean_tolerance_last_digit: float
    rsd_tolerance_points: float
    very_rapid_percent: float
    very_rapid_within_min: float
    plateau_below_percent: float
    bell_drop_points: float
    lag_below_percent: float
    sink_index_min: float


class Solubility(_B):
    glass_volume_ml: float
    ph_match: float


class Permeability(_B):
    reference_compounds: list[str]


class ExcipientClass(_B):
    """A functional class of excipients (plan 2026-11-24 §8 feature 9): its names and the function words that name it."""

    id: str
    label: str
    names: list[str]
    functions: list[str] = Field(default_factory=list)


class Conflicts(_B):
    relative_tolerance_percent: float


class MediumConvention(_B):
    """A medium named without its pH, and its pH by convention (D4): used only once a person confirms it."""

    names: list[str]
    ph: float


class Rules(_B):
    version: str
    status: str
    analysis_sets: AnalysisSets
    means: Means
    nca: Nca
    dissolution: Dissolution
    solubility: Solubility
    conflicts: Conflicts
    flags: Flags
    permeability: Permeability
    media_by_convention: list[MediumConvention] = []
    excipient_classes: list[ExcipientClass] = []
    sha256: str = ""

    def convention_ph(self, medium: str) -> float | None:
        """The pH a medium named without one has by convention (`media_by_convention`), or None: its names matched as
        whole words, case and punctuation aside, the longest name first ("FeSSIF-V2" before "FeSSIF")."""
        return first_named(medium, [(n, c.ph) for c in self.media_by_convention for n in c.names])

    def reference_compound(self, text: str) -> str | None:
        """The permeability reference compound a text names (`permeability.reference_compounds`), or None."""
        return first_named(text, [(n, n) for n in self.permeability.reference_compounds])

    def excipient_class(self, name: str, function: str = "") -> tuple[ExcipientClass, str] | None:
        """A component's functional class by its name, else by the function written beside it, with which of the two
        named it ("name" / "function"); None: neither names one."""
        by_name = first_named(name, [(n, c) for c in self.excipient_classes for n in c.names])
        if by_name is not None:
            return by_name, "name"
        by_function = first_named(function, [(w, c) for c in self.excipient_classes for w in c.functions])
        return (by_function, "function") if by_function is not None else None

    def label(self) -> str:
        return f"dataroom_rules {self.version} ({self.status}) sha256:{self.sha256[:12]}"


def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9./]+", " ", text.lower()).strip() + " "


def first_named[T](text: str, pairs: list[tuple[str, T]]) -> T | None:
    """The value of the first name written in `text` as whole words, case and punctuation aside, the longest name first
    ("FeSSIF-V2" before "FeSSIF", "hypromellose acetate succinate" before "hypromellose")."""
    said = _words(text)
    for name, value in sorted(pairs, key=lambda x: -len(x[0])):
        if _words(name).strip() and _words(name) in said:
            return value
    return None


@lru_cache(maxsize=1)
def load_rules() -> Rules:
    text = resources.files("modeler_project.dataroom").joinpath(FILE).read_text(encoding="utf-8")
    return Rules(**yaml.safe_load(text), sha256=hashlib.sha256(text.encode()).hexdigest())
