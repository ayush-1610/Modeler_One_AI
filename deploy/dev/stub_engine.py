#!/usr/bin/env python3
"""A stub OSP engine for the Mac / no-engine demo (macOS cannot run PK-Sim).

The single-node runner invokes the engine as ``<command> <job.json>``. On a ``simulate`` job this reads the
built snapshot, finds every simulation in it, and writes the canonical ``profiles.json`` with a plausible
mono-exponential plasma curve per simulation — so the whole loop (evaluate → diagnose → escalate/pass) can be
exercised without a real engine. Point ``MODELER_ENGINE_COMMAND`` at ``python3 deploy/dev/stub_engine.py``.

Real runs on the Linux server use ``Rscript services/engine-worker/r/run_job.R`` instead. This is a demo aid,
not an engine: the curve is synthetic and must never be mistaken for a simulation result.
"""
import json
import math
import sys
from pathlib import Path

# Synthetic curve shape: Cmax at the first sample, terminal half-life ~2.9 h (Aciclovir-like).
TIMES_MIN = [5, 15, 30, 60, 90, 120, 180, 240, 360, 480, 600, 720]
C0 = 60.0
HALF_LIFE_MIN = 174.0


def _simulation_names(job: dict) -> list[str]:
    for item in job.get("inputs", []):
        if Path(item.get("name", "")).name != "snapshot.json":
            continue
        try:
            snap = json.loads(Path(item["path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [s.get("Name") for s in snap.get("Simulations", []) if s.get("Name")]
    return []


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text())
    out_dir = Path(job["outputs_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    if job.get("task") == "simulate":
        concs = [C0 * math.pow(0.5, t / HALF_LIFE_MIN) for t in TIMES_MIN]
        profiles = {
            name: {"times_min": TIMES_MIN, "concentrations": concs, "unit": "µmol/l"}
            for name in _simulation_names(job)
        }
        (out_dir / "profiles.json").write_text(json.dumps({"profiles": profiles}))
    (out_dir / "engine_manifest.json").write_text(json.dumps({"engine": "stub"}))
    print("PROGRESS 1.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
