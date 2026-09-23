#!/usr/bin/env bash
# Report what is and is not running, for a quick check over ssh.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
port_open "$API_PORT" && echo "API  :$API_PORT  UP" || echo "API  :$API_PORT  DOWN"
port_open "$WEB_PORT" && echo "web  :$WEB_PORT  UP" || echo "web  :$WEB_PORT  DOWN"
[ -f "$STOPPED_FLAG" ] && echo "state: intentionally stopped (watchdog will not restart it)" \
                       || echo "state: expected up (watchdog will restart it if it dies)"
stack_healthy && echo "open:  http://${ip:-<server-ip>}:$WEB_PORT"
command -v tailscale >/dev/null 2>&1 && echo "tailscale: $(tailscale ip -4 2>/dev/null || echo 'not up')"
echo "logs:  $LOGS/api.log  $LOGS/web.log"
