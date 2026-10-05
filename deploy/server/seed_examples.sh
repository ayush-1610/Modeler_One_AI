#!/usr/bin/env bash
# Load every worked example into the running tool and run its campaign on this server's PK-Sim, in the background.
#
#   bash deploy/server/seed_examples.sh            # every example, 3 campaigns at a time
#   bash deploy/server/seed_examples.sh 2          # 2 at a time
#   ONLY=rifampicin bash deploy/server/seed_examples.sh
#
# Safe to run again: examples already in the tool are skipped. Progress: tail -f ~/modeler-logs/seed.log
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"

PARALLEL="${1:-3}"
if ! stack_healthy; then
  echo "the tool is not running: start it first (bash deploy/server/run_modeler.sh)" >&2
  exit 1
fi
# every campaign writes its snapshots, results and package under $DATA; refuse to start on a nearly full disk
free_gb=$(df -Pk "$DATA" | awk 'NR==2 {print int($4/1024/1024)}')
if [ "${free_gb:-0}" -lt "${MODELER_SEED_MIN_FREE_GB:-5}" ]; then
  echo "only ${free_gb} GB free under $DATA; free space first (MODELER_SEED_MIN_FREE_GB sets the limit)" >&2
  exit 1
fi

cd "$REPO"
nohup uv run python deploy/showcase/seed_examples.py --base "$MODELER_API_BASE" --parallel "$PARALLEL" \
    --only "${ONLY:-}" --out "$DATA/showcase" > "$LOGS/seed.log" 2>&1 &
echo "seeding in the background (pid $!); progress: tail -f $LOGS/seed.log"
echo "open the tool: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$WEB_PORT"
