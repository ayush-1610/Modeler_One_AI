"""The Data room's rules (`dataroom_rules.yaml`, plan 2026-11-21 v2 §8) and their typed loader.

PROVISIONAL: UNVERIFIED until the SME signs. A change is a science change: a CHANGELOG entry, a version bump and the
owner's approval. Every view carries `label()` (version, status, sha256), so a report says which rules made it.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib import resources

import yaml
from pydantic import BaseModel, ConfigDict

FILE = "dataroom_rules.yaml"


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AnalysisSets(_B):
    evaluable_min_quantifiable: int


class Means(_B):
    blq_predose: str
    blq_postdose_arithmetic: str
    blq_postdose_geometric: str


class Nca(_B):
    method: str
    blq_leading: str
    blq_after_first: str
    tolerance_percent: float
    tmax_tolerance_h: float


class Dissolution(_B):
    client_mean_tolerance_last_digit: float
    rsd_tolerance_points: float
    very_rapid_percent: float
    very_rapid_within_min: float
    plateau_below_percent: float


class Solubility(_B):
    glass_volume_ml: float


class Conflicts(_B):
    relative_tolerance_percent: float


class Rules(_B):
    version: str
    status: str
    analysis_sets: AnalysisSets
    means: Means
    nca: Nca
    dissolution: Dissolution
    solubility: Solubility
    conflicts: Conflicts
    sha256: str = ""

    def label(self) -> str:
        return f"dataroom_rules {self.version} ({self.status}) sha256:{self.sha256[:12]}"


@lru_cache(maxsize=1)
def load_rules() -> Rules:
    text = resources.files("modeler_project.dataroom").joinpath(FILE).read_text(encoding="utf-8")
    return Rules(**yaml.safe_load(text), sha256=hashlib.sha256(text.encode()).hexdigest())
