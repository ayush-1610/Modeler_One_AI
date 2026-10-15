#!/usr/bin/env bash
# Report what is and is not running, for a quick check over ssh.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"

ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
port_open "$API_PORT" && echo "API  :$API_PORT  UP" || echo "API  :$API_PORT  DOWN"
port_open "$WEB_PORT" && echo "web  :$WEB_PORT  UP ($(web_scheme))" || echo "web  :$WEB_PORT  DOWN"
if keycloak_needed; then
  port_open "$KEYCLOAK_HTTP_PORT" && echo "keycloak :$KEYCLOAK_HTTP_PORT  UP" || echo "keycloak :$KEYCLOAK_HTTP_PORT  DOWN"
fi
echo "deployment: $MODELER_DEPLOYMENT ($( [ -n "${MODELER_DEV_AUTH:-}" ] && echo 'DEV sign-in, not Part 11' || echo 'Keycloak sign-in'))"
[ -f "$STOPPED_FLAG" ] && echo "state: intentionally stopped (watchdog will not restart it)" \
                       || echo "state: expected up (watchdog will restart it if it dies)"
stack_healthy && echo "open:  $(web_scheme)://${ip:-<server-ip>}:$WEB_PORT"
command -v tailscale >/dev/null 2>&1 && echo "tailscale: $(tailscale ip -4 2>/dev/null || echo 'not up')"
echo "logs:  $LOGS/api.log  $LOGS/web.log$(keycloak_needed && echo "  $LOGS/keycloak.log")"
