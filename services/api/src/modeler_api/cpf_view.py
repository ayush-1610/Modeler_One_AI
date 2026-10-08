"""The compound screen's projection of a CPF: parameter rows plus the S0 completeness computed from it.

Shared by the read API (`GET .../cpf`) and the write API (`PUT .../cpf` answers with the stored CPF's view); a module
of its own so neither router imports the other.
"""

from __future__ import annotations

from typing import Any

from pbpk_domain.cpf import CPF
from pbpk_domain.cpf.completeness import check_completeness

# The S0 completeness rule checks six requirement groups; completeness is the fraction satisfied.
_COMPLETENESS_TOTAL = 6


def project_cpf_view(cpf: CPF) -> dict[str, Any]:
    """Project a CPF for the compound screen: parameter rows plus the S0 completeness fraction."""
    report = check_completeness(cpf)
    completeness = round((_COMPLETENESS_TOTAL - len(report.missing_ids)) / _COMPLETENESS_TOTAL, 3)
    parameters = [
        {
            "id": p.id,
            "value": None if p.value is None else str(p.value),
            "unit": p.unit,
            "status": p.status.value.lower(),
            "source": (p.provenance.source_type if p.provenance else "unknown"),
            "reference": (p.provenance.reference if p.provenance and p.provenance.reference else ""),
            "fittableStages": list(p.fit_policy.stage) if p.fit_policy else [],
        }
        for p in cpf.parameters
    ]
    return {
        "compound": cpf.compound,
        "version": cpf.version,
        "completeness": completeness,
        "ready": report.ready,
        "missing": list(report.missing),
        "parameters": parameters,
    }
