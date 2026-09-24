"""The S0 readiness gate (MS-01 §2.2 completeness rule).

A campaign may not start unless the CPF has, with provenance and a value: molecular weight, lipophilicity,
pKa (or a documented statement that the compound is neutral), fraction unbound, reference solubility, and
at least one elimination pathway. Anything missing is reported so it can be routed to the literature agent
and the client; nothing here runs the engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from pbpk_domain.cpf.models import CPF, ParameterStatus


@dataclass(frozen=True)
class CompletenessReport:
    ready: bool
    missing: tuple[str, ...]      # human-readable descriptions of what is missing
    missing_ids: tuple[str, ...]  # the canonical ids (or prefixes) that were not satisfied

    def __bool__(self) -> bool:
        return self.ready


def _present(cpf: CPF, param_id: str) -> bool:
    record = cpf.get(param_id)
    return (
        record is not None
        and record.status is not ParameterStatus.MISSING
        and record.value is not None
        and record.provenance is not None
    )


def _any_with_prefix(cpf: CPF, prefix: str) -> bool:
    return any(
        p.status is not ParameterStatus.MISSING and p.value is not None and p.provenance is not None
        for p in cpf.with_prefix(prefix)
    )


def check_completeness(cpf: CPF) -> CompletenessReport:
    missing: list[str] = []
    missing_ids: list[str] = []

    for param_id, label in (
        ("phys.mw", "molecular weight"),
        ("phys.logp", "lipophilicity (logP/logD)"),
        ("bind.fu", "fraction unbound in plasma"),
        ("phys.solubility.ref", "reference aqueous solubility"),
    ):
        if param_id == "phys.solubility.ref" and _present(cpf, "phys.solubility.table"):
            continue  # a measured pH-solubility table (OSP Raltegravir, Voriconazole) is the reference solubility
        if not _present(cpf, param_id):
            missing.append(f"{label} ({param_id})")
            missing_ids.append(param_id)

    # pKa is satisfied by any pKa record, or by an explicit "neutral" declaration.
    if not _any_with_prefix(cpf, "phys.pka") and cpf.get("phys.pka.neutral") is None:
        missing.append("pKa values, or a documented statement that the compound is neutral (phys.pka.* or phys.pka.neutral)")
        missing_ids.append("phys.pka")

    # At least one elimination pathway (any elim.* with provenance, e.g. an enzyme clearance or total CL).
    if not _any_with_prefix(cpf, "elim"):
        missing.append("at least one elimination pathway (elim.* or elim.hepatic.total_cl)")
        missing_ids.append("elim")

    return CompletenessReport(ready=not missing, missing=tuple(missing), missing_ids=tuple(missing_ids))
