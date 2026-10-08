"""The S0 readiness gate (MS-01 §2.2 completeness rule).

A campaign may not start unless the CPF has, with provenance and a value: molecular weight, lipophilicity,
pKa (or a documented statement that the compound is neutral), fraction unbound, reference solubility, and
at least one elimination pathway. Anything missing is reported so it can be routed to the literature agent
and the client; nothing here runs the engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from pbpk_domain import parameters
from pbpk_domain.cpf.models import CPF, ParameterStatus


@dataclass(frozen=True)
class CompletenessReport:
    ready: bool
    missing: tuple[str, ...]      # human-readable descriptions of what is missing
    missing_ids: tuple[str, ...]  # the canonical ids (or prefixes) that were not satisfied

    def __bool__(self) -> bool:
        return self.ready


def _present_ids(cpf: CPF) -> set[str]:
    """The ids with a value and provenance (a record marked missing, with no value or no source, is not a statement)."""
    return {p.id for p in cpf.parameters
            if p.status is not ParameterStatus.MISSING and p.value is not None and p.provenance is not None}


def check_completeness(cpf: CPF) -> CompletenessReport:
    # The requirements are the parameter registry's (pbpk_domain/parameters/registry.yaml): the four compound values
    # (a measured pH-solubility table stands for the reference solubility), any pKa or a documented "neutral", and any
    # elimination pathway; the clinical fractions (fe in urine, fm per pathway) describe elimination but are not a
    # pathway the model has.
    unmet = parameters.unmet_s0(_present_ids(cpf))
    return CompletenessReport(ready=not unmet, missing=tuple(r.message for r in unmet),
                              missing_ids=tuple(r.requirement for r in unmet))
