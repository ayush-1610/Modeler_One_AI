#!/usr/bin/env bash
# Run the reference-model set on this machine's PK-Sim: the same tasks as the CI matrix in
# .github/workflows/reference-models.yml (read from it, so the two never drift), for when GitHub Actions cannot run.
#
#   bash deploy/reference/run_all.sh                 # every task, 4 at a time
#   bash deploy/reference/run_all.sh roundtrip -j 8  # tasks whose name contains "roundtrip", 8 at a time
#
# Engine: the server's (deploy/server/_env.sh sets MODELER_ENGINE_COMMAND to Rscript run_job.R, REFERENCE_RSCRIPT to
# its Rscript), or a Mac with Docker Desktop (export MODELER_ENGINE_COMMAND="bash $PWD/deploy/dev/docker_engine.sh" and
# REFERENCE_RSCRIPT="docker run --rm -v $PWD:$PWD -w $PWD <image> Rscript" first). Results: reports/reference/<stamp>/
# <task>/ (the task's JSON and log) and summary.md (each task's headline). Campaigns stop at the S6 signature gate.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"
PATTERN=""
JOBS=4
while [[ $# -gt 0 ]]; do
  case "$1" in
    -j) JOBS="$2"; shift 2 ;;
    *) PATTERN="$1"; shift ;;
  esac
done

if [[ -z "${MODELER_ENGINE_COMMAND:-}" && -f deploy/server/_env.sh ]]; then
  # shellcheck source=/dev/null
  source deploy/server/_env.sh
fi
: "${MODELER_ENGINE_COMMAND:?set MODELER_ENGINE_COMMAND (see the header) or run on the server}"
export REFERENCE_RSCRIPT="${REFERENCE_RSCRIPT:-Rscript}"
export MODELER_FIT_WORKERS="${MODELER_FIT_WORKERS:-8}"

OUT="$REPO/reports/reference/$(date -u +%Y%m%dT%H%MZ)"
mkdir -p "$OUT"
TASKS="$OUT/tasks.tsv"
uv run python - "$PATTERN" > "$TASKS" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(".github/workflows/reference-models.yml", encoding="utf-8"))
for row in doc["jobs"]["reference"]["strategy"]["matrix"]["include"]:
    if sys.argv[1] in row["task"]:
        print(f"{row['task']}\t{row['run']}")
PY
echo "$(wc -l < "$TASKS") task(s), $JOBS at a time -> $OUT"

run_one() {
  local task="$1" cmd="$2" dir="$OUT/$1"
  mkdir -p "$dir"
  # shellcheck disable=SC2086
  if uv run python $cmd --out "$dir" > "$dir/log.txt" 2>&1; then status=ok; else status="exit $?"; fi
  { echo "## $task ($status)"; grep -m1 -E '^### ' "$dir/log.txt" || tail -n 3 "$dir/log.txt"; echo; } >> "$OUT/summary.md"
  echo "$task: $status"
}
export -f run_one
export OUT
tr '\t\n' '\0\0' < "$TASKS" | xargs -0 -n 2 -P "$JOBS" bash -c 'run_one "$0" "$1"'
echo "summary: $OUT/summary.md"
