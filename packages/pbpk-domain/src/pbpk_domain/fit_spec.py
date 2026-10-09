"""Parameter identification: build the PI spec from the CPF (step 2) and apply estimates back (step 3).

`build_fit_spec` assembles the ``pi_spec_base.json`` structure ``run_pi.R`` reads — simulations (each a pkml),
parameters (each with its PK-Sim path from `pbpk_domain.pksim_paths`, bounds and start value), and output
mappings (each with the observed profile). `apply_fit_estimates` transfers the winning estimates back into a
new CPF version (status FITTED, provenance ParameterIdentification). Neither invents a path or a bound: an
unmappable parameter, a parameter with no bounds, or an estimate for an unknown parameter raises.

The parameter paths are the harvested candidates; the fit step must still verify each exists in the exported
pkml before running PI (a path can vary per compound). Fitting a compound-level parameter shares one path
across every simulation; the same value is identified jointly from all of them.

In a model system (`pbpk_domain.system`, multi-compound phase 2, D-25) a fit can move another compound's parameter:
a metabolite's clearance, a co-parent enantiomer's. Its fit id is qualified, ``<compound>::<CPF id>``
(`qualify`, `split_fit_id`); the fitted compound's own ids stay bare, so every single-compound target, rule and fit
spec is unchanged. Each CPF stays the record of its own parameters: the estimates go back to the compound they name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus, Provenance, Uncertainty
from pbpk_domain.pksim_paths import pksim_parameter_path

if TYPE_CHECKING:
    from pbpk_domain.system import ModelSystem

QUALIFIER = "::"


class FitSpecError(ValueError):
    pass


def split_fit_id(fit_id: str) -> tuple[str | None, str]:
    """(compound, CPF id) of a fit id; the compound is None for a bare id (the fitted compound's own parameter)."""
    compound, sep, pid = fit_id.partition(QUALIFIER)
    return (compound, pid) if sep else (None, fit_id)


def qualify(compound: str, pid: str, fitted: str) -> str:
    """The fit id of `compound`'s parameter `pid` in a fit of `fitted`: bare for the fitted compound's own."""
    return pid if compound == fitted else f"{compound}{QUALIFIER}{pid}"


def fit_owner(cpf: CPF, fit_id: str, system: ModelSystem | None = None) -> tuple[CPF, str]:
    """(the CPF that holds the parameter, its id there). Raises FitSpecError for a compound the fit cannot reach: a
    qualified id outside a model system, or naming a compound the system does not have."""
    compound, pid = split_fit_id(fit_id)
    if compound is None or compound == cpf.compound:
        return cpf, pid
    if system is None or compound not in system.roles:
        raise FitSpecError(f"{fit_id!r}: {compound!r} is not a compound of this fit's model system")
    return system.cpf(compound), pid


def by_compound[V](values: dict[str, V], fitted: str) -> dict[str, dict[str, V]]:
    """Split a mapping keyed by fit id into one per compound, keyed by that compound's own CPF ids."""
    out: dict[str, dict[str, V]] = {}
    for fit_id, value in values.items():
        compound, pid = split_fit_id(fit_id)
        out.setdefault(compound or fitted, {})[pid] = value
    return out


@dataclass(frozen=True)
class FitSimulation:
    """One internal study's simulation in the fit: its pkml, plasma output path and observed profile."""
    study_id: str
    pkml: str          # bare file name the engine provides (from the snapshot -> pkml conversion)
    output_path: str   # the plasma output path the observed data is compared against
    observed: dict[str, Any]  # PI observed dict (see `pi_observed`)
    protocol: str | None = None     # the simulation's protocol name (formulation parameters live under it)
    formulation: str | None = None  # the CPF formulation the simulation uses (None for IV / solution)


def pi_observed(
    name: str, times: list[float], values: list[float], *, time_unit: str, unit: str, mol_weight: float,
    dimension: str = "Concentration (mass)", sd: list[float] | None = None, lloq: float | None = None,
) -> dict[str, Any]:
    """The observed block run_pi.R's build_dataset expects for one output mapping.

    ``dimension`` is the OSP quantity dimension of the values — "Concentration (mass)" (default) or
    "Concentration (molar)" when the series is in molar units (e.g. µmol/l, matching the simulated plasma)."""
    observed: dict[str, Any] = {
        "name": name, "time": list(times), "time_unit": time_unit,
        "values": list(values), "unit": unit, "dimension": dimension, "mol_weight": mol_weight,
    }
    observed["sd"] = list(sd) if sd else []
    if lloq is not None:
        observed["lloq"] = lloq
    return observed


def resolve_fit_ids(cpf: CPF, target: str, system: ModelSystem | None = None) -> tuple[str, ...]:
    """Expand a strategist action target to the concrete CPF ids it names.

    Targets may template ``{enzyme}`` / ``{name}`` (e.g. ``elim.hepatic.{enzyme}.clspec``); each placeholder
    matches one id segment. A plain target resolves to itself when the CPF has it. Returns () when nothing
    matches, so the caller surfaces that no fittable parameter was found. A qualified target
    (``<compound>::<target>``) resolves against that compound's CPF in `system` and stays qualified; it matches
    nothing outside a model system or for a compound the system does not have."""
    compound, part = split_fit_id(target)
    if compound is not None:
        if compound == cpf.compound:
            return resolve_fit_ids(cpf, part)
        if system is None or compound not in system.roles:
            return ()
        return tuple(qualify(compound, pid, cpf.compound) for pid in resolve_fit_ids(system.cpf(compound), part))
    if "{" not in target:
        return (target,) if cpf.get(target) is not None else ()
    pattern = "^" + re.escape(target).replace(r"\{enzyme\}", "[^.]+").replace(r"\{name\}", "[^.]+") + "$"
    rx = re.compile(pattern)
    return tuple(p.id for p in cpf.parameters if rx.match(p.id))


def _bounds(record: ParameterRecord, override: tuple[float, float] | None) -> tuple[float, float]:
    if override is not None:
        lo, hi = override
    elif record.fit_policy is not None:
        lo, hi = record.fit_policy.lower, record.fit_policy.upper
    elif record.plausibility is not None:
        lo, hi = record.plausibility.lower, record.plausibility.upper
    else:
        raise FitSpecError(f"{record.id!r}: no bounds to fit (needs a fit policy, a plausibility range, or an override)")
    if not lo < hi:
        raise FitSpecError(f"{record.id!r}: fit bounds {lo}..{hi} are not increasing")
    return float(lo), float(hi)


def _paths(record: ParameterRecord, compound: str, simulations: list[FitSimulation], *,
           fitted: bool = True) -> list[dict[str, str]]:
    """Where the parameter lives in each simulation. A formulation parameter lives under each simulation's own
    protocol and exists only in the simulations using that formulation; everything else has one path in all.
    Formulations are the fitted compound's (its products'); another compound's formulation is not fitted here."""
    from pbpk_domain.cpf.formulations import weibull_parameter_path

    parts = record.id.split(".")
    if parts[0] == "form" and not fitted:
        raise FitSpecError(f"{compound}::{record.id}: a formulation is fitted on the fitted compound only")
    if parts[0] == "form":
        paths = [
            {"simulation": s.study_id, "path": weibull_parameter_path(record.id, protocol=s.protocol)}
            for s in simulations if s.formulation == parts[1] and s.protocol
        ]
        if not paths or any(p["path"] is None for p in paths):
            raise FitSpecError(f"{record.id!r}: no simulation in this fit uses formulation {parts[1]!r}")
        return paths
    path = pksim_parameter_path(record, compound=compound)  # raises for an unmapped parameter
    return [{"simulation": s.study_id, "path": path} for s in simulations]


def study_weights(simulations: list[FitSimulation]) -> dict[str, float]:
    """Each study's residual weight when every study contributes equally (MS-01 v1.1 SJ, D-04, UNVERIFIED).

    The engine's parameter identification multiplies each residual by its weight before squaring
    (ospsuite.parameteridentification >= 2.1, `PIOutputMapping$addObservedDataSets(weights =)`), so a study of n points
    adds about w^2 * n to the weighted sum of squares. w = sqrt(N / (k * n)) for N points over k studies makes that the
    same N / k for every study, and keeps the mean squared weight at 1 (the objective's scale is unchanged)."""
    counts = {s.study_id: sum(v is not None for v in s.observed["values"]) for s in simulations}
    counted = {sid: n for sid, n in counts.items() if n > 0}
    if not counted:
        return {}
    total, k = sum(counted.values()), len(counted)
    return {sid: (total / (k * n)) ** 0.5 for sid, n in counted.items()}


def build_fit_spec(
    cpf: CPF,
    fit_ids: list[str],
    simulations: list[FitSimulation],
    *,
    bounds_override: dict[str, tuple[float, float]] | None = None,
    algorithm: str = "BOBYQA",
    max_evaluations: int = 200,
    seed: int = 1,
    scaling: str = "log",
    equal_study_weights: bool = False,
    system: ModelSystem | None = None,
) -> dict[str, Any]:
    """Build the PI base spec fitting ``fit_ids`` against ``simulations``. Raises FitSpecError on any gap.

    ``equal_study_weights`` (the joint refinement, SJ) gives every study the same say however many points it has
    (`study_weights`); otherwise every point weighs the same, as the stage fits always have. A qualified fit id
    (``<compound>::<id>``) is read from that compound's CPF in ``system`` and placed at its own PK-Sim path; the
    PI parameter keeps the fit id as its name, so the estimate returns to the compound it belongs to."""
    if not simulations:
        raise FitSpecError("a fit spec needs at least one simulation")
    if not fit_ids:
        raise FitSpecError("a fit spec needs at least one parameter to fit")
    override = bounds_override or {}
    weights = study_weights(simulations) if equal_study_weights else {}

    parameters: list[dict[str, Any]] = []
    for fit_id in fit_ids:
        owner, pid = fit_owner(cpf, fit_id, system)
        record = owner.get(pid)
        if record is None:
            raise FitSpecError(f"CPF for {owner.compound} has no parameter {pid!r} to fit")
        lo, hi = _bounds(record, override.get(fit_id))
        start = min(max(record.numeric_value, lo), hi)  # clamp the current value into the bounds
        entry: dict[str, Any] = {
            "name": fit_id, "min": lo, "max": hi, "start": start,
            "paths": _paths(record, owner.compound, simulations, fitted=owner is cpf),
        }
        # A dimensionless parameter (e.g. GFR fraction) carries no unit key at all: a JSON null does not survive
        # run_job.R's re-serialisation (R writes it back as {}), and ospsuite then rejects the empty "unit".
        if record.unit:
            entry["unit"] = record.unit
        parameters.append(entry)

    return {
        "algorithm": algorithm,
        "max_evaluations": max_evaluations,
        "seed": seed,
        "simulations": [{"id": s.study_id, "pkml": s.pkml} for s in simulations],
        "parameters": parameters,
        "output_mappings": [
            {"simulation": s.study_id, "output_path": s.output_path, "scaling": scaling,
             "observed": {**s.observed, "weight": weights[s.study_id]} if s.study_id in weights else s.observed}
            for s in simulations
        ],
    }


def apply_fit_estimates(
    cpf: CPF, estimates: dict[str, float], *, stage: str, run: str | None = None, note: str | None = None,
    uncertainty: dict[str, dict] | None = None,
) -> CPF:
    """Return a new CPF version with each estimated parameter set to its fitted value.

    Each updated record becomes FITTED with ParameterIdentification provenance that records the CPF version
    it superseded. Raises FitSpecError for an estimate whose parameter the CPF does not have."""
    records: list[ParameterRecord] = []
    for pid, value in estimates.items():
        record = cpf.get(pid)
        if record is None:
            raise FitSpecError(f"cannot apply estimate for {pid!r}: CPF for {cpf.compound} has no such parameter")
        provenance = Provenance(
            source_type="ParameterIdentification", reference=note, run=run,
            supersedes=f"{cpf.compound}@{cpf.version}:{pid}",
        )
        spread = (uncertainty or {}).get(pid) or {}
        precision = Uncertainty(sd=spread.get("sd"), cv_percent=spread.get("cv"), ci95_lower=spread.get("ci_lower"),
                                ci95_upper=spread.get("ci_upper")) if spread else None
        records.append(record.model_copy(update={
            "value": float(value), "status": ParameterStatus.FITTED, "fitted_at_stage": stage, "provenance": provenance,
            "uncertainty": precision,
        }))
    return cpf.replace(*records, note=note or f"applied {len(records)} fitted estimate(s) at {stage}")
