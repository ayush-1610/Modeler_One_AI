"""Where a process parameter of the CPF goes in PK-Sim (P4 assembly, T-49): candidates from the harvested process table.

A value for ``elim.hepatic.CYP3A4.clspec`` names a pathway and a quantity, not the PK-Sim process that carries it:
``CLspec/[Enzyme]`` exists on two harvested process types (``MetabolizationSpecific_FirstOrder``, ``rCYP450_FirstOrder``).
Which one is a model-structure choice for a person (P4, reviewed in P5), so this module lists the candidates; it never
picks one when there are several. Names and units come from the OSP import's harvested table
(`reference.osp_import.PROCESS_PARAMETERS`), the same one the importer and the builder use.
"""

from __future__ import annotations

from dataclasses import dataclass

from pbpk_domain import parameters
from pbpk_domain.cpf.models import EngineBinding
from pbpk_domain.reference.osp_import import PROCESS_FAMILY, PROCESS_PARAMETERS

# Ids whose process is fixed by the id itself (as the importer writes them).
_FIXED_PREFIX = {"elim.renal": "GlomerularFiltration", "elim.hepatic.total": "LiverClearance",
                 "elim.renal.total": "KidneyClearance"}


@dataclass(frozen=True)
class BindingCandidate:
    process: str               # PK-Sim internal process name
    parameter: str             # the engine parameter
    unit: str | None           # the unit the builder places it in
    molecule: str | None       # the enzyme / transporter / partner, from the id

    def binding(self, data_source: str) -> EngineBinding:
        process = f"{self.process}:{self.molecule}" if self.molecule else self.process
        return EngineBinding(building_block="Compound", parameter=self.parameter, process=process, data_source=data_source)


def _by_suffix(process: str, suffix: str) -> tuple[str, str | None] | None:
    return next(((name, unit) for name, (s, unit) in PROCESS_PARAMETERS[process].items() if s == suffix), None)


def binding_candidates(cpf_id: str) -> list[BindingCandidate]:
    """Every harvested process type that can carry `cpf_id` (empty: not a process parameter the builder places). An
    alias (`elim.hepatic.total_cl`) has the candidates of the id it stands for."""
    prefix, _, suffix = parameters.canonical(cpf_id).rpartition(".")
    if not prefix:
        return []
    fixed = _FIXED_PREFIX.get(prefix)
    if fixed is not None:
        hit = _by_suffix(fixed, suffix)
        return [BindingCandidate(fixed, hit[0], hit[1], None)] if hit else []
    family, _, molecule = prefix.rpartition(".")
    molecule = molecule.split("@", 1)[0]
    out = []
    for process, process_family in PROCESS_FAMILY.items():
        if process_family == family and (hit := _by_suffix(process, suffix)):
            out.append(BindingCandidate(process, hit[0], hit[1], molecule))
    return out


def is_process_id(cpf_id: str) -> bool:
    """An id of a process family (the parameter registry's `placement: process` families)."""
    return cpf_id.startswith(parameters.process_prefixes())
