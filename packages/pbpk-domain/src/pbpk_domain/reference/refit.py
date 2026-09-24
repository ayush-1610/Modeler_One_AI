"""The refit test of a published model (plan Phase 4, test 2): can the pipeline fit it back from a wrong start?

The parameters the published model itself identified (status FITTED: its value origin names a parameter
identification) are freed within the families the user approved, started from shifted values, and bounded as the
user approved on 2026-09-24: 0.1× to 10× of the published value for clearances, permeabilities and solubility, and
±1.5 log units for lipophilicity. The campaign then fits them against the real clinical data; the test compares
its fitted model's fold errors with the published model's on the same studies (the as-is campaign), not the
recovered parameter values. From plasma data alone the split of clearance between enzymes and kidney is not
identifiable (the published model also used urine and mass-balance data, task T-11), so equally good fits with
different splits are expected and are reported as such.
"""

from __future__ import annotations

from dataclasses import dataclass

from pbpk_domain.cpf.models import CPF, FitPolicy, ParameterRecord, ParameterStatus, Plausibility, Provenance, Scale

APPROVAL = "user-approved refit bounds, 2026-09-24"


@dataclass(frozen=True)
class FreedParameter:
    stages: tuple[str, ...]  # MS-01 stages allowed to fit it
    shift: float             # the start = published × shift (or + shift for a log-unit quantity)
    additive: bool = False   # logP is bounded ±1.5 log units, not by a factor


def _rule(param_id: str) -> FreedParameter | None:
    """Which published values the refit frees, where they may be fitted, and how their start is shifted."""
    if param_id == "phys.logp":
        return FreedParameter(("S1", "S2"), 0.5, additive=True)
    if param_id.startswith("elim.hepatic.") and param_id.endswith(".clspec"):
        return FreedParameter(("S1",), 2.0)
    if param_id.startswith(("elim.hepatic.", "transp.")) and param_id.endswith(".kcat"):
        return FreedParameter(("S1", "S2"), 2.0)  # a Michaelis-Menten metabolism / transport rate (clearance family)
    if param_id == "elim.renal.gfr_fraction":
        return FreedParameter(("S1",), 2.0)
    if param_id == "perm.cellular":
        return FreedParameter(("S1", "S2"), 2.0)
    if param_id == "perm.intestinal":
        return FreedParameter(("S2",), 1 / 3)
    if param_id == "phys.solubility.ref":
        return FreedParameter(("S2", "S3"), 0.5)
    return None


def refit_cpf(published: CPF) -> tuple[CPF, dict[str, dict[str, float]]]:
    """The published CPF with the identified parameters freed and shifted. Returns it and, per freed parameter,
    the published value, the start and the bounds (for the report)."""
    records: list[ParameterRecord] = []
    freed: dict[str, dict[str, float]] = {}
    for record in published.parameters:
        rule = _rule(record.id)
        identified = record.status is ParameterStatus.FITTED
        if rule is None or not identified or not isinstance(record.value, int | float):
            records.append(record)
            continue
        value = float(record.value)
        if rule.additive:
            lower, upper, start, scale = value - 1.5, value + 1.5, value + rule.shift, Scale.LINEAR
        else:
            lower, upper, start, scale = value * 0.1, value * 10.0, value * rule.shift, Scale.LOG
        policy = FitPolicy(stage=rule.stages, lower=lower, upper=upper, scale=scale)
        records.append(record.model_copy(update={
            "value": start,
            "status": ParameterStatus.PREDICTED,
            "fit_policy": policy,
            "plausibility": Plausibility(lower=lower, upper=upper, source=APPROVAL),
            "provenance": Provenance(source_type="assumed",
                                     reference=f"refit test start: published {value:g} shifted "
                                               f"{'+' if rule.additive else '×'}{rule.shift:g}",
                                     supersedes=record.provenance.reference if record.provenance else None),
        }))
        freed[record.id] = {"published": value, "start": start, "lower": lower, "upper": upper}
    cpf = CPF(compound=published.compound, parameters=tuple(records),
              note=f"Refit test of the published model ({APPROVAL})")
    return cpf, freed
