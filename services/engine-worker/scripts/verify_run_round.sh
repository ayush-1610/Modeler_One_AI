#!/usr/bin/env bash
# Verify the campaign round's engine path on the Linux OSP engine (F-405): run task=simulate on a real
# multi-simulation snapshot and confirm run_job.R emits the canonical profiles.json the campaign reads.
#
# Run on the engine host (needs ospsuite 12.4.4 + .NET 8; runSimulationsFromSnapshot is Linux/Windows only):
#   LC_ALL=en_US.UTF-8 services/engine-worker/scripts/verify_run_round.sh
#
# It prints the OSP result files PK-Sim wrote (revealing its CSV naming) and the profiles.json summary.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"          # services/engine-worker
snapshot="${1:-$here/golden/example_snapshot.json}"
work="${2:-$(mktemp -d)}"
out="$work/outputs"
mkdir -p "$out"

sha="$( { sha256sum "$snapshot" 2>/dev/null || shasum -a 256 "$snapshot"; } | awk '{print $1}')"

python3 - "$snapshot" "$sha" "$out" > "$work/job.json" <<'PY'
import json, sys
snapshot, sha, out = sys.argv[1:4]
json.dump({
    "job_id": "verify-run-round",
    "task": "simulate",
    "inputs": [{"name": "snapshot.json", "path": snapshot, "sha256": sha}],
    "options": {},
    "outputs_dir": out,
}, sys.stdout, indent=2)
PY

echo "== running task=simulate =="
Rscript "$here/r/run_job.R" "$work/job.json"

echo
echo "== result files PK-Sim wrote (note the CSV naming) =="
ls -1 "$out"

echo
echo "== profiles.json =="
test -f "$out/profiles.json" || { echo "FAIL: profiles.json not written"; exit 1; }
python3 - "$out/profiles.json" <<'PY'
import json, sys
b = json.load(open(sys.argv[1]))
profiles = b.get("profiles", {})
assert profiles, "FAIL: profiles is empty"
for name, p in profiles.items():
    t, c = p.get("times_min", []), p.get("concentrations", [])
    assert len(t) == len(c) and len(t) > 1, f"FAIL: {name} has no series"
    print(f"  {name}: {len(t)} points, Cmax={max(c):.4g} {p.get('unit')}, path={p.get('path')}")
print("OK: profiles.json has a plasma series per simulation")
PY
echo
echo "work dir: $work"
