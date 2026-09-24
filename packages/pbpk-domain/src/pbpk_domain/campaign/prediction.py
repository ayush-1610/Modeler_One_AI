"""S6 — prediction: sensitivity and uncertainty of the validated model (MS-01 §4 S6).

S6 runs only after S4 and S5 are signed. For each reference simulation (the internal studies, from the final CPF):

- **Local sensitivity** of the PK parameters (AUC, Cmax) to every FITTED and PREDICTED CPF parameter the engine
  can locate, by the engine's `sensitivity` task (±10 % variation). The ranking says which assumptions the
  predictions rest on.
- **Uncertainty propagation**: the fitted parameters are sampled from their identification uncertainty (SD from
  the Hessian CI; log-normal for log-scaled parameters, normal otherwise, both truncated to the fit policy
  bounds), n = 200 [SME], run as one engine `batch`, and reduced to 5 / 50 / 95 % prediction intervals of AUC and
  Cmax. With no fitted parameter carrying an SD there is nothing to propagate, and S6 says so.

The application templates the question of interest may need (DDI, paediatric, organ impairment, VBE) are the next
phase (T-31); S6 here characterises the validated model itself.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus
from pbpk_domain.nca import nca

UNCERTAINTY_SAMPLES = 200         # MS-01 §4 S6, n = 200 [SME]
SENSITIVITY_VARIATION = 0.1       # ±10 %, the engine default
PREDICTION_PERCENTILES = (5.0, 50.0, 95.0)
# The PK parameters S6 reports, as the engine names them in sensitivity results.
SENSITIVITY_PK = ("AUC_inf", "AUC_tEnd", "C_max")


@dataclass(frozen=True)
class SensitivityRow:
    parameter: str       # the engine parameter path
    pk_parameter: str
    value: float         # relative change of the PK parameter per relative change of the parameter


def _numeric(record: ParameterRecord) -> bool:
    return isinstance(record.value, int | float) and not isinstance(record.value, bool)


def sensitivity_candidates(cpf: CPF) -> tuple[ParameterRecord, ...]:
    """FITTED and PREDICTED numeric parameters — the ones the prediction rests on (MS-01 S6)."""
    return tuple(p for p in cpf.parameters
                 if p.status in (ParameterStatus.FITTED, ParameterStatus.PREDICTED) and _numeric(p))


def uncertain_parameters(cpf: CPF) -> tuple[ParameterRecord, ...]:
    """FITTED parameters whose identification produced an SD — the ones uncertainty is propagated from."""
    return tuple(p for p in cpf.parameters
                 if p.status is ParameterStatus.FITTED and _numeric(p) and p.uncertainty is not None
                 and p.uncertainty.sd is not None and p.uncertainty.sd > 0)


def _bounds(record: ParameterRecord) -> tuple[float, float]:
    if record.fit_policy is not None:
        return record.fit_policy.lower, record.fit_policy.upper
    if record.plausibility is not None:
        return record.plausibility.lower, record.plausibility.upper
    return -math.inf, math.inf


def sample_parameters(records: Sequence[ParameterRecord], n: int = UNCERTAINTY_SAMPLES, seed: int = 1) -> list[dict[str, float]]:
    """n joint draws (independent; the correlation matrix is not propagated yet) in the CPF's units.

    A log-scaled parameter is drawn log-normally with the CV implied by its SD; any other normally. Draws are
    truncated to the parameter's fit policy (or plausibility) bounds by resampling, never clipped to the bound."""
    rng = np.random.default_rng(seed)
    draws: list[dict[str, float]] = [{} for _ in range(n)]
    for record in records:
        mean, sd = record.numeric_value, float(record.uncertainty.sd)
        lo, hi = _bounds(record)
        log_scale = record.fit_policy is not None and record.fit_policy.scale.value == "log" and mean > 0
        values: list[float] = []
        while len(values) < n:
            if log_scale:
                sigma = math.sqrt(math.log(1.0 + (sd / mean) ** 2))
                batch = mean * np.exp(rng.normal(-0.5 * sigma**2, sigma, size=n))
            else:
                batch = rng.normal(mean, sd, size=n)
            values.extend(float(v) for v in batch if lo <= v <= hi)
        for i in range(n):
            draws[i][record.id] = values[i]
    return draws


def prediction_interval(values: Sequence[float]) -> dict[str, float]:
    """5 / 50 / 95 % of a sample (NaN-free)."""
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if not clean:
        return {}
    p5, p50, p95 = np.percentile(clean, PREDICTION_PERCENTILES)
    return {"p5": float(p5), "p50": float(p50), "p95": float(p95), "n": len(clean)}


def results_csv_pk(data: bytes, *, t_last_min: float | None = None) -> dict[str, float] | None:
    """AUC (to the last time, or to ``t_last_min``) and Cmax of the plasma column of one engine results CSV."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    if len(rows) < 3:
        return None
    header = rows[0]
    t_col = next((i for i, h in enumerate(header) if h.lower().startswith("time")), None)
    c_col = next((i for i, h in enumerate(header) if "Plasma (Peripheral Venous Blood)" in h), None)
    if t_col is None or c_col is None:
        return None
    pairs = [(float(r[t_col]), float(r[c_col])) for r in rows[1:] if len(r) > max(t_col, c_col) and r[c_col] != ""]
    if t_last_min is not None:
        pairs = [(t, c) for t, c in pairs if t <= t_last_min] or pairs
    if len(pairs) < 2:
        return None
    result = nca([t for t, _ in pairs], [c for _, c in pairs])
    return {"auc": result.auc_last, "cmax": result.c_max}


def parse_sensitivity(data: bytes) -> list[SensitivityRow]:
    """The engine's sensitivity CSV, reduced to (parameter, PK parameter, value) for the plasma output."""
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    out: list[SensitivityRow] = []
    for row in rows:
        keys = {k.lower(): k for k in row}
        quantity = row.get(keys.get("quantitypath", ""), "")
        if quantity and "Plasma (Peripheral Venous Blood)" not in quantity:
            continue
        pk = row.get(keys.get("pkparameter", ""), "")
        param = row.get(keys.get("parameterpath", keys.get("parameter", "")), "")
        try:
            value = float(row.get(keys.get("value", ""), ""))
        except ValueError:
            continue
        if pk in SENSITIVITY_PK and math.isfinite(value):
            out.append(SensitivityRow(parameter=param, pk_parameter=pk, value=value))
    return out
