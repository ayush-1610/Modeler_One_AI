#!/usr/bin/env bash
# Stop the tool and mark it intentionally stopped, so the watchdog leaves it alone until the next start.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"

touch "$STOPPED_FLAG"

for name in api web; do
  pidfile="$LOGS/$name.pid"
  if [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null; then
    echo "stopped $name (pid $(cat "$pidfile"))"
  else
    echo "$name not running from a pid file"
  fi
  rm -f "$pidfile"
done

# Catch anything started outside the pid files (e.g. a manual run).
pkill -f "uvicorn modeler_api.main:app --host 0.0.0.0 --port $API_PORT" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
echo "stopped (marked as intentionally down)"
