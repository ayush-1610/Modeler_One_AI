#!/usr/bin/env bash
# Make the tool come back on its own, without root.
#
# This server has no sudo, so a systemd unit is not available (and a --user unit would need lingering, which
# also needs admin). The user crontab works without any privilege and survives reboots:
#
#   @reboot        start the stack (after a short delay so the network and filesystems are ready)
#   every 5 min    watchdog: start it again if it is down AND was not stopped on purpose
#
# stop_modeler.sh leaves a flag that the watchdog honours, so a deliberate stop stays stopped.
# Re-running this script is safe: entries are replaced, not duplicated.
set -euo pipefail

HERE="$(dirname "$(readlink -f "$0")")"
RUN="$HERE/run_modeler.sh"
MARKER="# modeler-one autostart"

[ -x "$RUN" ] || { echo "cannot find $RUN" >&2; exit 1; }

reboot_line="@reboot sleep 30 && $RUN --watchdog >> \$HOME/modeler-logs/autostart.log 2>&1 $MARKER"
watchdog_line="*/5 * * * * $RUN --watchdog >> \$HOME/modeler-logs/autostart.log 2>&1 $MARKER"

# Keep every unrelated crontab entry; replace only ours.
existing="$(crontab -l 2>/dev/null | grep -vF "$MARKER" || true)"
printf '%s\n%s\n%s\n' "$existing" "$reboot_line" "$watchdog_line" | sed '/^$/d' | crontab -

echo "autostart installed:"
crontab -l 2>/dev/null | grep -F "$MARKER" | sed 's/^/  /'
echo
echo "  on reboot      -> the stack starts by itself"
echo "  every 5 min    -> restarted if it died (unless stopped with stop_modeler.sh)"
echo "  to remove      -> crontab -l | grep -vF '$MARKER' | crontab -"
