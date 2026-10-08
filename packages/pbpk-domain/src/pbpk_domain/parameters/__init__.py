"""The CPF parameter registry (MS-01 §2.2; docs/plans/2026-10-08-parameter-registry.md, phase 4).

For every CPF id or id family: where the model takes it, the unit the CPF stores it in, the PK-Sim compound parameter it
sets, the range a reviewer is warned outside of, how a published value is obtained (ValueOrigin method), and the S0
gate. The data is ``registry.yaml`` (SME-governed, UNVERIFIED, locked); this module reads it and answers the questions
a dozen tables across the code answered separately (docs/ARCHITECTURE_BOUNDARIES.md, C1).

Phase 4b: the tables are still where they were, and tests prove the registry derives each of them exactly and answers
what docs/architecture/parameter-vocabulary.json recorded. Phases 4c/4d make those tables read from here.
"""

from __future__ import annotations

from collections.abc import Collection
from functools import lru_cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

DIMENSIONLESS = "dimensionless"
NOT_CONVERTED = "not_converted"
_FAMILY_ENDS = (".", "[")


class ParameterRule(BaseModel):
    """One registry entry: an exact id, or a family (a key ending in "." or "["). See registry.yaml for the fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    suffix: str | None = None
    placement: Literal["model", "reference", "process"] | None = None
    builder_process: bool = False
    storage: str | None = None
    reason: str | None = None
    pksim_compound: str | None = None
    builder_unit: str | None = None
    physical_bounds: tuple[float, float] | None = None
    origin: Literal["in_vivo", "in_vitro"] | None = None
    drift: str | None = None

    @property
    def is_family(self) -> bool:
        return self.key.endswith(_FAMILY_ENDS)

    @model_validator(mode="after")
    def _consistent(self) -> ParameterRule:
        problems = []
        if self.suffix is not None and (self.storage is None or self.placement or self.origin or self.pksim_compound):
            problems.append("a suffix rule only gives a storage unit")
        if (self.storage == NOT_CONVERTED) != (self.reason is not None):
            problems.append("a reason goes with storage: not_converted, and only there")
        if self.builder_process and self.placement != "process":
            problems.append("builder_process is a process family")
        if self.placement == "process" and not self.is_family:
            problems.append("a process placement names a family")
        if (self.pksim_compound or self.builder_unit) and (self.placement != "model" or self.is_family):
            problems.append("a PK-Sim compound name or builder unit belongs to one model id")
        if self.physical_bounds and (self.is_family or not self.physical_bounds[0] < self.physical_bounds[1]):
            problems.append("physical bounds are [low, high] of one id")
        if problems:
            raise ValueError(f"{self.key}{self.suffix or ''}: " + "; ".join(problems))
        return self


class S0Requirement(BaseModel):
    """One S0 requirement: met by a record of `requirement`, of one of `or_present`, or (with `any_with_prefix`) of any
    id of that family not starting with one of `excluding` (each with a value and provenance)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement: str
    message: str
    or_present: tuple[str, ...] = ()
    any_with_prefix: str | None = None
    excluding: tuple[str, ...] = ()

    def met_by(self, present: Collection[str]) -> bool:
        if self.requirement in present or any(i in present for i in self.or_present):
            return True
        prefix = self.any_with_prefix
        return prefix is not None and any(
            (i == prefix or i.startswith(prefix + ".")) and not i.startswith(self.excluding) for i in present)


class ParameterRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: str
    status: str
    parameters: tuple[ParameterRule, ...]
    s0: tuple[S0Requirement, ...]

    @model_validator(mode="after")
    def _unique(self) -> ParameterRegistry:
        seen: set[tuple[str, str | None]] = set()
        for rule in self.parameters:
            if (rule.key, rule.suffix) in seen:
                raise ValueError(f"{rule.key}{rule.suffix or ''} is listed twice")
            seen.add((rule.key, rule.suffix))
        return self


@lru_cache(maxsize=1)
def registry() -> ParameterRegistry:
    text = resources.files("pbpk_domain.parameters").joinpath("registry.yaml").read_text(encoding="utf-8")
    return ParameterRegistry.model_validate(yaml.safe_load(text))


def _rules() -> tuple[ParameterRule, ...]:
    return registry().parameters


def _family(storage: str) -> str | None | bool:
    """parameter_units' convention: None for a dimensionless value, False for one not converted by a unit change."""
    return None if storage == DIMENSIONLESS else False if storage == NOT_CONVERTED else storage


# --- storage unit (parameter_units) --------------------------------------------------------------------------------


def storage_targets() -> tuple[tuple[str, str | None], ...]:
    """(key, family) of the plain storage rules, in order: `parameter_units._TARGETS`."""
    return tuple((r.key, _family(r.storage)) for r in _rules() if r.storage and r.suffix is None)


def storage_family(cpf_id: str) -> str | None | bool:
    """The storage family of a CPF id (None: dimensionless); False when no unit change converts it."""
    for r in _rules():
        if r.suffix and r.storage and cpf_id.startswith(r.key) and cpf_id.endswith(r.suffix):
            return _family(r.storage)
    for key, family in storage_targets():
        if cpf_id == key or cpf_id.startswith(key + ".") or (key.endswith(".") and cpf_id.startswith(key)):
            return family
    return False


def not_converted_reason(cpf_id: str) -> str | None:
    """Why a value under this id waits for a scientific step rather than a unit change (CLint → CLspec)."""
    return next((r.reason for r in _rules() if r.storage == NOT_CONVERTED and r.suffix
                 and cpf_id.startswith(r.key) and cpf_id.endswith(r.suffix)), None)


# --- placement (modeler_project.inputs, cpf.build, cpf.process_bindings) -------------------------------------------


def _keys(placement: str, *, family: bool) -> tuple[str, ...]:
    return tuple(r.key for r in _rules() if r.placement == placement and r.is_family == family and r.suffix is None)


def model_ids() -> frozenset[str]:
    return frozenset(_keys("model", family=False))


def model_prefixes() -> tuple[str, ...]:
    return _keys("model", family=True)


def reference_ids() -> frozenset[str]:
    return frozenset(_keys("reference", family=False))


def reference_prefixes() -> tuple[str, ...]:
    return _keys("reference", family=True)


def process_prefixes() -> tuple[str, ...]:
    """The families whose ids are process parameters (`cpf.process_bindings.is_process_id`)."""
    return _keys("process", family=True)


def builder_process_prefixes() -> tuple[str, ...]:
    """The process families the builder must place or report (`cpf.build._PROCESS_FAMILIES`)."""
    return tuple(r.key for r in _rules() if r.builder_process)


def reference_elimination() -> tuple[str, ...]:
    """Clinical elimination fractions kept for checks, never a pathway (`cpf.build.REFERENCE_ELIMINATION`)."""
    return tuple(r.key for r in _rules() if r.placement == "reference" and r.key.startswith("elim."))


def placement(cpf_id: str) -> str | None:
    """"model", "process" (a process parameter the harvested table places), "reference", or None: not a parameter the
    model uses. An alternative (`<id>@<name>`) is placed as its id."""
    from pbpk_domain.cpf.process_bindings import binding_candidates

    base = cpf_id.partition("@")[0]
    if base in model_ids() or base.startswith(model_prefixes()):
        return "model"
    if base in reference_ids() or base.startswith(reference_prefixes()):
        return "reference"
    if base.startswith(process_prefixes()):
        return "process" if binding_candidates(base) else None
    return None


# --- PK-Sim compound parameters, builder units, review bounds, ValueOrigin -----------------------------------------


def compound_parameters() -> dict[str, str]:
    """CPF id -> harvested PK-Sim compound parameter (`pksim_paths._COMPOUND_PARAM`)."""
    return {r.key: r.pksim_compound for r in _rules() if r.pksim_compound}


def builder_units() -> dict[str, str]:
    return {r.key: r.builder_unit for r in _rules() if r.builder_unit}


def physical_bounds() -> dict[str, tuple[float, float]]:
    return {r.key: r.physical_bounds for r in _rules() if r.physical_bounds}


def origin_prefixes(origin: Literal["in_vivo", "in_vitro"]) -> tuple[str, ...]:
    return tuple(r.key for r in _rules() if r.origin == origin)


def origin(cpf_id: str) -> Literal["in_vivo", "in_vitro"] | None:
    """How a published value of this id is obtained; in vivo wins where both families match."""
    if cpf_id.startswith(origin_prefixes("in_vivo")):
        return "in_vivo"
    if cpf_id.startswith(origin_prefixes("in_vitro")):
        return "in_vitro"
    return None


# --- the S0 gate (cpf.completeness) ---------------------------------------------------------------------------------


def s0_requirements() -> tuple[S0Requirement, ...]:
    return registry().s0


def unmet_s0(present: Collection[str]) -> tuple[S0Requirement, ...]:
    """The S0 requirements the ids present (each with a value and provenance) leave unmet, in reporting order."""
    return tuple(req for req in s0_requirements() if not req.met_by(present))
