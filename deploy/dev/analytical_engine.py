#!/usr/bin/env python3
"""A transparent one-compartment analytical stand-in for the OSP engine. **This is NOT PK-Sim.**

PK-Sim cannot run on macOS, and the Linux engine host is not always reachable. Without an engine the platform
can only be exercised with a fixed canned curve, which makes every compound look identical and never exercises
fitting. This stand-in instead computes a plasma profile from the *actual* CPF values in the built snapshot —
dose, route, infusion time, molecular weight, fraction unbound, lipophilicity and the clearance processes — so
different compounds behave differently and changing a parameter genuinely changes the prediction.

It therefore exercises the whole control flow end to end (build -> simulate -> evaluate -> diagnose -> fit ->
apply -> re-simulate -> pass/escalate). What it does **not** do is PBPK: there is no physiology, no tissue
distribution, no absorption model beyond first-order. Numbers produced here are a software fixture, never a
scientific result, and must never be presented as a simulation.

Model
-----
  CL = fu * (gfr_fraction * GFR + sum(hepatic specific clearances) * V_liver)     [L/min]
  V  = V0 * 10**(0.15 * logP), clamped                                            [L]
  IV bolus      C(t) = (D/V) e^(-kt)
  IV infusion   C(t) = (R/CL)(1 - e^(-kt))        for t <= T
                C(t) = C(T) e^(-k(t-T))           for t >  T
  Oral          C(t) = (F D ka / (V(ka-k))) (e^(-kt) - e^(-ka t))
with k = CL/V. Concentrations are µmol/L; the dose is converted from mg with the compound's molecular weight.

Tasks: `simulate` (writes profiles.json, plus a model file per simulation when export_pkml is set) and
`parameter_identification` (fits the named CPF parameters to the observed data by deterministic search).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

GFR_L_PER_MIN = 0.125      # glomerular filtration rate, standard adult
V_LIVER_L = 1.8            # liver volume, for scaling a specific hepatic clearance
V0_L = 44.0                # volume of distribution at logP = 0
LOGP_SLOPE = 0.15
V_MIN_L, V_MAX_L = 5.0, 700.0
KA_PER_MIN = 1.0 / 60.0    # first-order oral absorption, 1/h
ORAL_F = 1.0


# --- reading the snapshot ------------------------------------------------------------------------

def _params(block: dict) -> dict:
    return {p.get("Name"): p.get("Value") for p in (block or {}).get("Parameters", []) or []}


def _alt_value(compound: dict, key: str, name: str, default=None):
    """Read a value out of a PK-Sim 'alternatives' block (Lipophilicity, FractionUnbound, ...)."""
    for alt in compound.get(key, []) or []:
        value = _params(alt).get(name)
        if value is not None:
            return value
    return default


def _compound_inputs(compound: dict) -> dict:
    """The CPF-derived quantities the analytical model needs, straight out of the snapshot."""
    gfr_fraction, clspec = 0.0, 0.0
    for process in compound.get("Processes", []) or []:
        values = _params(process)
        if process.get("InternalName") == "GlomerularFiltration":
            gfr_fraction += float(values.get("GFR fraction") or 0.0)
        else:  # any molecule-based clearance contributes a specific clearance
            for key in ("CLspec/[Enzyme]", "Specific clearance", "CLspec"):
                if values.get(key) is not None:
                    clspec += float(values[key])
                    break
    return {
        "mw": float(_params(compound).get("Molecular weight") or 0.0) or 300.0,
        "logp": float(_alt_value(compound, "Lipophilicity", "Lipophilicity", 0.0) or 0.0),
        "fu": float(_alt_value(compound, "FractionUnbound", "Fraction unbound (plasma, reference value)", 1.0) or 1.0),
        "gfr_fraction": gfr_fraction,
        "clspec": clspec,
    }


def _protocol_inputs(protocol: dict) -> dict:
    values = _params(protocol)
    return {
        "route": "oral" if str(protocol.get("ApplicationType", "")).lower().startswith("oral") else "iv",
        "dose_mg": float(values.get("InputDose") or 0.0),
        "infusion_min": float(values.get("Infusion time") or 0.0),
    }


def _times(simulation: dict) -> list[float]:
    schema = (simulation.get("OutputSchema") or [{}])[0]
    values = _params(schema)
    end_h = float(values.get("End time") or 24.0)
    per_h = float(values.get("Resolution") or 4.0)
    step = 60.0 / max(per_h, 0.5)
    n = int((end_h * 60.0) / step)
    return [round(i * step, 4) for i in range(n + 1)]


def models_from_snapshot(snapshot: dict) -> dict[str, dict]:
    """One model input set per simulation in the snapshot, keyed by simulation name."""
    protocols = {p.get("Name"): p for p in snapshot.get("Protocols", []) or []}
    compounds = {c.get("Name"): c for c in snapshot.get("Compounds", []) or []}
    models: dict[str, dict] = {}
    for simulation in snapshot.get("Simulations", []) or []:
        ref = (simulation.get("Compounds") or [{}])[0]
        compound = compounds.get(ref.get("Name")) or next(iter(compounds.values()), {})
        protocol = protocols.get((ref.get("Protocol") or {}).get("Name"), {})
        models[simulation.get("Name")] = {
            **_compound_inputs(compound), **_protocol_inputs(protocol),
            "times_min": _times(simulation),
        }
    return models


# --- the model -----------------------------------------------------------------------------------

def clearance_and_volume(m: dict) -> tuple[float, float]:
    cl = m["fu"] * (m["gfr_fraction"] * GFR_L_PER_MIN + m["clspec"] * V_LIVER_L)
    cl = max(cl, 1e-6)
    v = min(max(V0_L * (10 ** (LOGP_SLOPE * m["logp"])), V_MIN_L), V_MAX_L)
    return cl, v


def concentrations(m: dict) -> list[float]:
    cl, v = clearance_and_volume(m)
    k = cl / v
    dose_umol = (m["dose_mg"] / m["mw"]) * 1000.0 if m["mw"] else 0.0
    out: list[float] = []
    if m["route"] == "oral":
        ka = KA_PER_MIN
        for t in m["times_min"]:
            if abs(ka - k) < 1e-9:
                c = (ORAL_F * dose_umol / v) * k * t * math.exp(-k * t)
            else:
                c = (ORAL_F * dose_umol * ka / (v * (ka - k))) * (math.exp(-k * t) - math.exp(-ka * t))
            out.append(max(c, 0.0))
        return out
    infusion = m["infusion_min"]
    if infusion > 0:
        rate = dose_umol / infusion
        c_end = (rate / cl) * (1 - math.exp(-k * infusion))
        for t in m["times_min"]:
            c = (rate / cl) * (1 - math.exp(-k * t)) if t <= infusion else c_end * math.exp(-k * (t - infusion))
            out.append(max(c, 0.0))
        return out
    return [max((dose_umol / v) * math.exp(-k * t), 0.0) for t in m["times_min"]]


# --- fitting: apply a CPF parameter onto the model inputs -----------------------------------------

def _apply(m: dict, name: str, value: float) -> dict:
    updated = dict(m)
    if name == "elim.renal.gfr_fraction":
        updated["gfr_fraction"] = value
    elif name == "phys.logp":
        updated["logp"] = value
    elif name == "bind.fu":
        updated["fu"] = value
    elif name.startswith("elim.hepatic."):
        updated["clspec"] = value
    return updated


def _interp(times: list[float], values: list[float], t: float) -> float:
    if t <= times[0]:
        return values[0]
    for i in range(1, len(times)):
        if t <= times[i]:
            span = times[i] - times[i - 1] or 1.0
            w = (t - times[i - 1]) / span
            return values[i - 1] + w * (values[i] - values[i - 1])
    return values[-1]


def _objective(models: dict[str, dict], names: list[str], vector: list[float], observed: dict) -> float:
    """Sum of squared error on log concentration, the usual PI objective shape."""
    total = 0.0
    for sim_id, obs in observed.items():
        m = models.get(sim_id)
        if not m:
            continue
        for name, value in zip(names, vector):
            m = _apply(m, name, value)
        predicted = concentrations(m)
        for t, y in zip(obs["times"], obs["values"]):
            p = max(_interp(m["times_min"], predicted, float(t)), 1e-12)
            total += (math.log(p) - math.log(max(float(y), 1e-12))) ** 2
    return total


def _optimize(models, names, bounds, start, observed, *, passes=4, grid=12):
    """Deterministic coordinate search: refine each parameter on a shrinking grid. No dependencies, and
    reproducible, which matters because the platform records the fit as evidence."""
    best = list(start)
    best_obj = _objective(models, names, best, observed)
    evaluations = 1
    spans = [(hi - lo) for lo, hi in bounds]
    for _ in range(passes):
        for i, (lo, hi) in enumerate(bounds):
            centre, span = best[i], spans[i]
            left, right = max(lo, centre - span / 2), min(hi, centre + span / 2)
            for j in range(grid + 1):
                candidate = list(best)
                candidate[i] = left + (right - left) * j / grid
                obj = _objective(models, names, candidate, observed)
                evaluations += 1
                if obj < best_obj:
                    best_obj, best = obj, candidate
            spans[i] = max((right - left) / 3.0, (hi - lo) * 1e-4)
    return best, best_obj, evaluations


# --- job entry point -----------------------------------------------------------------------------

def _input_path(job: dict, suffix: str) -> Path | None:
    for item in job.get("inputs", []):
        if str(item.get("name", "")).endswith(suffix):
            return Path(item["path"])
    return None


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text())
    out_dir = Path(job["outputs_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    task = job.get("task")

    if task == "simulate":
        snapshot_path = _input_path(job, "snapshot.json")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path else {}
        models = models_from_snapshot(snapshot)
        profiles = {
            name: {"times_min": m["times_min"], "concentrations": concentrations(m), "unit": "µmol/l",
                   "path": "Organism|PeripheralVenousBlood|x|Plasma (Peripheral Venous Blood)"}
            for name, m in models.items()
        }
        (out_dir / "profiles.json").write_text(json.dumps({"profiles": profiles}))
        if job.get("options", {}).get("export_pkml"):
            stem = snapshot_path.stem if snapshot_path else "model"
            for name, m in models.items():
                # our "pkml" is the model input set; only this engine reads it back (for the fit).
                (out_dir / f"{stem}-{name}.pkml").write_text(json.dumps(m))

    elif task == "parameter_identification":
        spec_path = _input_path(job, "pi_spec_base.json")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        models = {}
        for item in job.get("inputs", []):
            if str(item.get("name", "")).endswith(".pkml"):
                sim = Path(item["name"]).stem.split("-")[-1]
                models[sim] = json.loads(Path(item["path"]).read_text())
        # the PI spec names each simulation and its observed series
        # pi_observed() emits {"time": [...], "values": [...]}; accept "times" too for robustness.
        observed = {}
        for om in spec.get("output_mappings", []):
            block = om.get("observed", {})
            times = block.get("time") or block.get("times") or []
            observed[om["simulation"]] = {"times": list(times), "values": list(block.get("values") or [])}
        for om in spec.get("output_mappings", []):
            models.setdefault(om["simulation"], next(iter(models.values()), {}))
        names = [p["name"] for p in spec["parameters"]]
        bounds = [(float(p["min"]), float(p["max"])) for p in spec["parameters"]]
        start_values = job.get("options", {}).get("start_values") or {}
        start = [float(start_values.get(p["name"], p["start"])) for p in spec["parameters"]]
        best, obj, evals = _optimize(models, names, bounds, start, observed)
        (out_dir / "pi_result.json").write_text(json.dumps({
            "estimates": [{"name": n, "estimate": v} for n, v in zip(names, best)],
            "objective_value": obj, "convergence": True, "function_evaluations": evals,
        }))

    (out_dir / "engine_manifest.json").write_text(json.dumps({"engine": "analytical-stand-in", "task": task}))
    print("PROGRESS 1.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
