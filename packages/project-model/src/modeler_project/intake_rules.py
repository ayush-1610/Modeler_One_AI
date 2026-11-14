"""The one rules file the client-data intake judges data with, and its typed loader (contracts §4.7).

`intake_rules.yaml` holds every threshold and list that judges data (precedent: `m15_draft.yaml`,
`client_reconciliation.yaml`). It is PROVISIONAL, `UNVERIFIED` until the SME signs, and a change is a science change: a
CHANGELOG entry, a version bump and the owner's approval. Every confirmation binds its version, status and sha256, and
the store test pins the sha256 to the version, so an edit without a bump fails the suite.

The loader refuses two things: a `landing.geometric_sd_sent_as` outside `pbpk_domain.spread.ERROR_TYPES` (the error
types harvested from PK-Sim), and an `item_fields` key that `item_scope` does not list.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pbpk_domain.spread import ERROR_TYPES

FILE = "intake_rules.yaml"


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LandingRules(_B):
    blq_rule: str
    blq_rules: tuple[str, ...]
    parent_words: tuple[str, ...]
    matrix_as_plasma_with_warning: tuple[str, ...]
    sd_from: dict[str, tuple[str, ...]]                      # statistic -> the spread kinds converted to an SD
    spreads_landed: dict[str, dict[str, str]]                # statistic -> spread kind -> Series.error_kind
    geometric_sd_sent_as: str


class CoverageRules(_B):
    excluded_by_rule: dict[str, str]                         # region kind -> the reason it is excluded


class LedgerRules(_B):
    time_resolution_min: float


class TagRule(_B):
    """A tag test of `routing.by_tag` (with a template) or `routing.gaps` (with a reason)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    tag: str
    present: bool | None = None
    in_: tuple[str, ...] | None = Field(default=None, alias="in")
    not_in: tuple[str, ...] | None = None
    template: str | None = None
    reason: str | None = None


class ItemFields(_B):
    """When a requirement item counts as found (see the comment in the YAML)."""

    all: tuple[str, ...] = ()
    any: tuple[str, ...] = ()
    per: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()


class RoutingRules(_B):
    core: str
    by_tag: tuple[TagRule, ...]
    gaps: tuple[TagRule, ...]
    item_scope: dict[Literal["study", "product"], tuple[str, ...]]
    item_fields: dict[str, ItemFields]
    population_covariates: dict[str, tuple[str, ...]]


class CheckRules(_B):
    composition_sum_tolerance_percent: float
    mw_relative_tolerance: float
    dose_multiple_relative_tolerance: float
    severity: dict[Literal["fail", "warn", "info"], tuple[str, ...]]


class SpotCheckRules(_B):
    size: int
    min_per_stratum: int
    strata: tuple[str, ...]
    unit_classes: tuple[str, ...]
    always_verify_fields: tuple[str, ...]
    always_verify_methods: tuple[str, ...]
    always_verify_cross_file: tuple[str, ...]


class IntakeRules(_B):
    version: str
    status: str
    landing: LandingRules
    coverage: CoverageRules
    ledger: LedgerRules
    routing: RoutingRules
    checks: CheckRules
    spot_check: SpotCheckRules

    @model_validator(mode="after")
    def _refusals(self) -> IntakeRules:
        if self.landing.geometric_sd_sent_as not in ERROR_TYPES:
            raise ValueError(f"landing.geometric_sd_sent_as: {self.landing.geometric_sd_sent_as!r} is not one of the "
                             f"PK-Sim error types {ERROR_TYPES}")
        scoped = {item for items in self.routing.item_scope.values() for item in items}
        unscoped = sorted(set(self.routing.item_fields) - scoped)
        if unscoped:
            raise ValueError(f"routing.item_fields: {unscoped} are not listed in routing.item_scope")
        return self


def _bytes() -> bytes:
    return resources.files("modeler_project").joinpath(FILE).read_bytes()


@lru_cache(maxsize=1)
def rules() -> IntakeRules:
    """The rules file, loaded and checked once per process."""
    return IntakeRules.model_validate(yaml.safe_load(_bytes().decode("utf-8")))


RULES_VERSION: str = rules().version
RULES_STATUS: str = rules().status
RULES_SHA256: str = hashlib.sha256(_bytes()).hexdigest()
