#!/usr/bin/env bash
# Start the whole Modeler One tool on this server: API + web + engine, reachable at one URL.
# Idempotent: if the stack is already answering it does nothing, so it is safe from cron and by hand.
#
#   run_modeler.sh              a human start — overrides an earlier deliberate stop
#   run_modeler.sh --watchdog   an automatic start (cron) — leaves a deliberate stop alone
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"

AUTOMATIC=0
[ "${1:-}" = "--watchdog" ] && AUTOMATIC=1

if stack_healthy; then
  [ "$AUTOMATIC" = 1 ] || echo "already running: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$WEB_PORT"
  exit 0
fi

# An automatic start must respect a deliberate stop, or stop_modeler.sh would be undone within minutes.
if [ "$AUTOMATIC" = 1 ] && [ -f "$STOPPED_FLAG" ]; then
  exit 0
fi
# A human start clears the flag; the stack is expected up from now on.
rm -f "$STOPPED_FLAG"

# Seed the read models on first run so the UI has the example project to open.
if [ ! -e "$MODELER_READ_ROOT/dev/projects.json" ] && [ -d "$REPO/deploy/dev/read-root/dev" ]; then
  cp -r "$REPO/deploy/dev/read-root/dev" "$MODELER_READ_ROOT/"
  echo "seeded read models from deploy/dev/read-root"
fi

cd "$REPO"

if ! port_open "$API_PORT"; then
  echo "starting API on :$API_PORT"
  nohup uv run uvicorn modeler_api.main:app --host 0.0.0.0 --port "$API_PORT" \
      > "$LOGS/api.log" 2>&1 &
  echo $! > "$LOGS/api.pid"
fi

if ! port_open "$WEB_PORT"; then
  echo "starting web on :$WEB_PORT"
  nohup npm --prefix "$REPO/apps/web" start -- -H 0.0.0.0 -p "$WEB_PORT" \
      > "$LOGS/web.log" 2>&1 &
  echo $! > "$LOGS/web.pid"
fi

# Give both a moment, then report honestly rather than assuming success.
for _ in $(seq 1 30); do
  sleep 1
  stack_healthy && break
done

if stack_healthy; then
  echo "up: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$WEB_PORT"
else
  echo "NOT fully up — check $LOGS/api.log and $LOGS/web.log" >&2
  port_open "$API_PORT" || echo "  API (:$API_PORT) is not answering" >&2
  port_open "$WEB_PORT" || echo "  web (:$WEB_PORT) is not answering" >&2
  exit 1
fi
