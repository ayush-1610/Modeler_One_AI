#!/usr/bin/env python3
"""A stub OSP engine for the Mac / no-engine demo (macOS cannot run PK-Sim).

The single-node runner invokes the engine as ``<command> <job.json>``. On a ``simulate`` job this writes the
canonical ``profiles.json`` — the Aciclovir IV template curve keyed by the simulation name ``iv`` — so the
tier gate can pass without a real engine. Point ``MODELER_ENGINE_COMMAND`` at ``python3 deploy/dev/stub_engine.py``
for the browser demo; real runs on the Linux server use ``Rscript services/engine-worker/r/run_job.R`` instead.

This only knows the ``iv`` study of the built-in Aciclovir template; it is a demo aid, not a general engine.
"""
import json
import sys
from pathlib import Path

# The Aciclovir IV template profile the wizard uploads; echoing it makes predicted == observed so S1 passes.
PROFILE = {
    "times_min": [5, 15, 30, 60, 120, 240, 360, 480],
    "concentrations": [45.2, 33.1, 24.0, 15.2, 7.1, 2.3, 0.9, 0.35],
    "unit": "µmol/l",
}


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text())
    out_dir = Path(job["outputs_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    if job.get("task") == "simulate":
        (out_dir / "profiles.json").write_text(json.dumps({"profiles": {"iv": PROFILE}}))
    (out_dir / "engine_manifest.json").write_text(json.dumps({"engine": "stub"}))
    print("PROGRESS 1.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
