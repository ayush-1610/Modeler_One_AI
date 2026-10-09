"""Datasets of published OSP models left out of the import, each a recorded human decision (MS-01 D5; exclusions.yaml).

The importer itself (`osp_import`, locked) is unchanged: an excluded dataset is taken out of the snapshot before it
runs, and named among the import's skipped datasets with its reason, so a reviewer sees what was left out and why.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

EXCLUSIONS = Path(__file__).with_name("exclusions.yaml")


@dataclass(frozen=True)
class Exclusion:
    model: str
    dataset: str
    reason: str
    decided_by: str
    decided_at: str

    def skipped(self) -> str:
        return f"{self.dataset}: excluded ({self.decided_by}, {self.decided_at}, D5): {self.reason}"


@cache
def exclusions() -> tuple[Exclusion, ...]:
    data = yaml.safe_load(EXCLUSIONS.read_text(encoding="utf-8"))
    return tuple(Exclusion(**{k: str(v).strip() for k, v in row.items()}) for row in data.get("exclusions", []))


def without_excluded(snapshot: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """The snapshot without its excluded datasets (a copy; the original is untouched), and a skipped line for each."""
    names = {e.dataset: e for e in exclusions()}
    hit = [names[d["Name"]] for d in snapshot.get("ObservedData", []) if d.get("Name") in names]
    if not hit:
        return snapshot, ()
    kept = copy.copy(snapshot)
    kept["ObservedData"] = [d for d in snapshot["ObservedData"] if d.get("Name") not in names]
    return kept, tuple(e.skipped() for e in hit)
