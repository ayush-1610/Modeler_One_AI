"""Resolve a CPF's engine bindings against a specific engine's catalog (MS-01 §2, task T-03).

Before anything is built, every parameter that names a compound process is checked against the catalog
harvested from the engine image (T-02): the process internal name must exist, the engine parameter name
must belong to that process type, and the stored unit must be the unit the engine uses for it. A
parameter the engine cannot place raises `BindingError` (NO_ENGINE_BINDING) rather than being guessed or
silently dropped, so a CPF that binds is a CPF this engine version can build.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from pbpk_domain.catalog import Catalog
from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus


def _norm(value: str | None) -> str | None:
    return None if value is None else unicodedata.normalize("NFKC", value)


class BindingError(Exception):
    """One or more CPF parameters have no valid binding in this engine's catalog (NO_ENGINE_BINDING)."""

    code = "NO_ENGINE_BINDING"

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class ParameterBinding:
    record: ParameterRecord
    process_internal_name: str | None
    molecule: str | None
    engine_parameter: str
    catalog_verified: bool  # True when checked against a catalog process type


@dataclass(frozen=True)
class BuildPlan:
    compound: str
    bindings: tuple[ParameterBinding, ...]
    unbound: tuple[str, ...]  # parameter ids with no engine binding (derived/constraint parameters)

    def for_process(self, internal_name: str, molecule: str | None = None) -> tuple[ParameterBinding, ...]:
        return tuple(
            b for b in self.bindings
            if b.process_internal_name == internal_name and (molecule is None or b.molecule == molecule)
        )


def bind(cpf: CPF, catalog: Catalog) -> BuildPlan:
    """Resolve and validate every engine binding in `cpf` against `catalog`.

    Raises BindingError listing every unbindable parameter. Compound-process bindings are checked against
    the catalog's process types (internal name, parameter name, unit). Non-process bindings (compound
    scalars, formulation, protocol, individual) are accepted structurally — the builder's own validators
    enforce their units — and are recorded in the plan. Parameters without a binding are returned in
    `unbound` (e.g. DERIVED constraints), not treated as errors.
    """
    problems: list[str] = []
    bindings: list[ParameterBinding] = []
    unbound: list[str] = []

    for record in cpf.parameters:
        if record.status is ParameterStatus.MISSING:
            continue
        eb = record.engine_binding
        if eb is None:
            unbound.append(record.id)
            continue

        internal_name = eb.process_internal_name
        molecule = eb.molecule
        if internal_name is None:
            # Non-process binding (compound scalar, formulation, protocol, individual): accept structurally.
            bindings.append(ParameterBinding(record, None, None, eb.parameter, catalog_verified=False))
            continue

        proc = catalog.process_type(internal_name)
        if proc is None:
            known = ", ".join(sorted(p.internal_name for p in catalog.process_types)) or "(none)"
            problems.append(
                f"{record.id}: engine {catalog.engine.ospsuite} has no process type {internal_name!r} (known: {known})"
            )
            continue
        if eb.parameter not in proc.parameter_names():
            problems.append(
                f"{record.id}: process {internal_name!r} has no parameter {eb.parameter!r} "
                f"(has: {', '.join(proc.parameter_names())})"
            )
            continue
        catalog_unit = next((p.unit for p in proc.parameters if p.name == eb.parameter), None)
        if _norm(catalog_unit) != _norm(record.unit):
            problems.append(
                f"{record.id}: unit {record.unit!r} does not match the engine unit {catalog_unit!r} "
                f"for {internal_name}:{eb.parameter}"
            )
            continue
        bindings.append(ParameterBinding(record, internal_name, molecule, eb.parameter, catalog_verified=True))

    if problems:
        raise BindingError(problems)
    return BuildPlan(compound=cpf.compound, bindings=tuple(bindings), unbound=tuple(unbound))
