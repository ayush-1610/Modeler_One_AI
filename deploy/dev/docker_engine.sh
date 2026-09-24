#!/usr/bin/env bash
# Run one engine job in the Linux engine image on this machine (the Mac fallback when the server is away).
#
# PK-Sim cannot run snapshots on macOS, so the job runs in the linux/amd64 engine image under Docker. The job's
# working directory (where EngineRunner stages inputs and collects outputs) is mounted at the SAME path inside
# the container, so every path in job.json resolves unchanged and EngineRunner needs no special case. Use it as
#
#   MODELER_ENGINE_COMMAND="bash $PWD/deploy/dev/docker_engine.sh"   (absolute: the engine starts in the job dir)
#
# Build the image once:  docker build --platform linux/amd64 -f services/engine-worker/Dockerfile \
#                          -t modeler-engine:ospsuite-12.4.4 .
# This is a development fallback: results are real PK-Sim results, but the image is not the qualified,
# digest-pinned production image (T-12) — record which engine produced any evidence.
set -euo pipefail

job="${1:?usage: docker_engine.sh <job.json>}"
job="$(cd "$(dirname "$job")" && pwd)/$(basename "$job")"
workdir="$(dirname "$job")"
image="${MODELER_ENGINE_IMAGE:-modeler-engine:ospsuite-12.4.4}"

# Also mount any input that lives outside the workdir (EngineRunner stages inputs inside it, but a direct call
# may point elsewhere), read-only, at its own path.
extra=()
while IFS= read -r path; do
  [ -n "$path" ] && [ -e "$path" ] && case "$path" in "$workdir"/*) ;; *) extra+=(-v "$path:$path:ro") ;; esac
done < <(python3 - "$job" <<'PY'
import json, sys
job = json.load(open(sys.argv[1]))
for item in job.get("inputs", []):
    print(item.get("path", ""))
PY
)

exec docker run --rm -i --init --platform linux/amd64 \
  -v "$workdir:$workdir" ${extra[@]+"${extra[@]}"} -w "$workdir" \
  -e LC_ALL=en_US.UTF-8 \
  "$image" Rscript /engine/run_job.R "$job"
