"""Parameter identification: build the PI spec from the CPF (step 2) and apply estimates back (step 3).

`build_fit_spec` assembles the ``pi_spec_base.json`` structure ``run_pi.R`` reads — simulations (each a pkml),
parameters (each with its PK-Sim path from `pbpk_domain.pksim_paths`, bounds and start value), and output
mappings (each with the observed profile). `apply_fit_estimates` transfers the winning estimates back into a
new CPF version (status FITTED, provenance ParameterIdentification). Neither invents a path or a bound: an
unmappable parameter, a parameter with no bounds, or an estimate for an unknown parameter raises.

The parameter paths are the harvested candidates; the fit step must still verify each exists in the exported
pkml before running PI (a path can vary per compound). Fitting a compound-level parameter shares one path
across every simulation; the same value is identified jointly from all of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.pksim_paths import pksim_parameter_path


class FitSpecError(ValueError):
    pass


@dataclass(frozen=True)
class FitSimulation:
    """One internal study's simulation in the fit: its pkml, plasma output path and observed profile."""
    study_id: str
    pkml: str          # bare file name the engine provides (from the snapshot -> pkml conversion)
    output_path: str   # the plasma output path the observed data is compared against
    observed: dict[str, Any]  # PI observed dict (see `pi_observed`)


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


def resolve_fit_ids(cpf: CPF, target: str) -> tuple[str, ...]:
    """Expand a strategist action target to the concrete CPF ids it names.

    Targets may template ``{enzyme}`` / ``{name}`` (e.g. ``elim.hepatic.{enzyme}.clspec``); each placeholder
    matches one id segment. A plain target resolves to itself when the CPF has it. Returns () when nothing
    matches, so the caller surfaces that no fittable parameter was found."""
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
) -> dict[str, Any]:
    """Build the PI base spec fitting ``fit_ids`` against ``simulations``. Raises FitSpecError on any gap."""
    if not simulations:
        raise FitSpecError("a fit spec needs at least one simulation")
    if not fit_ids:
        raise FitSpecError("a fit spec needs at least one parameter to fit")
    override = bounds_override or {}
    sim_ids = [s.study_id for s in simulations]

    parameters: list[dict[str, Any]] = []
    for pid in fit_ids:
        record = cpf.get(pid)
        if record is None:
            raise FitSpecError(f"CPF for {cpf.compound} has no parameter {pid!r} to fit")
        path = pksim_parameter_path(record, compound=cpf.compound)  # raises for an unmapped parameter
        lo, hi = _bounds(record, override.get(pid))
        start = min(max(record.numeric_value, lo), hi)  # clamp the current value into the bounds
        entry: dict[str, Any] = {
            "name": pid, "min": lo, "max": hi, "start": start,
            "paths": [{"simulation": sid, "path": path} for sid in sim_ids],
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
            {"simulation": s.study_id, "output_path": s.output_path, "scaling": scaling, "observed": s.observed}
            for s in simulations
        ],
    }


def apply_fit_estimates(
    cpf: CPF, estimates: dict[str, float], *, stage: str, run: str | None = None, note: str | None = None,
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
        records.append(record.model_copy(update={
            "value": float(value), "status": ParameterStatus.FITTED, "fitted_at_stage": stage, "provenance": provenance,
        }))
    return cpf.replace(*records, note=note or f"applied {len(records)} fitted estimate(s) at {stage}")
