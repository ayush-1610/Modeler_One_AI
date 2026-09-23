#!/usr/bin/env bash
# Put this server on the user's tailnet so it has a stable address that survives DHCP changes, reboots and
# network switches (the LAN IP has proved unreliable). Works with OR without root:
#
#   * with sudo  -> the official installer + systemd service (normal Tailscale, full networking)
#   * no sudo    -> static binaries under ~/tailscale running in USERSPACE networking mode. tailscaled then
#                   forwards inbound connections to the matching localhost port, so ssh (22), the web (3000)
#                   and the API (8000) are all reachable over the tailnet without a TUN device or root.
#
# Authentication is interactive on purpose: the script prints a login URL that YOU open in a browser and
# approve. No credentials are handled here.
#
# Usage:  bash ~/Modeler_One_AI/deploy/server/setup_tailscale.sh
set -euo pipefail

TS_DIR="$HOME/tailscale"
STATE_DIR="$HOME/.tailscale-state"

have_root() { sudo -n true 2>/dev/null; }

if have_root; then
  echo "== sudo available: installing Tailscale the normal way =="
  curl -fsSL https://tailscale.com/install.sh | sudo sh
  sudo tailscale up
  echo
  echo "Tailscale IP: $(tailscale ip -4 2>/dev/null || echo '(run: tailscale ip -4)')"
  exit 0
fi

echo "== no sudo: installing Tailscale static binaries in userspace mode =="
mkdir -p "$TS_DIR" "$STATE_DIR" "$HOME/modeler-logs"

if [ ! -x "$TS_DIR/tailscaled" ]; then
  echo "-- resolving the current stable version"
  VER="$(curl -fsSL 'https://pkgs.tailscale.com/stable/?mode=json' \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["Version"])')"
  echo "-- downloading tailscale ${VER} (amd64)"
  curl -fsSL "https://pkgs.tailscale.com/stable/tailscale_${VER}_amd64.tgz" -o "$TS_DIR/ts.tgz"
  tar -xzf "$TS_DIR/ts.tgz" -C "$TS_DIR" --strip-components=1
  rm -f "$TS_DIR/ts.tgz"
fi
"$TS_DIR/tailscaled" --version | head -1

# Start the daemon (userspace networking, no TUN, no root).
if ! pgrep -f "tailscaled.*$STATE_DIR" >/dev/null 2>&1; then
  echo "-- starting tailscaled (userspace)"
  nohup "$TS_DIR/tailscaled" \
      --tun=userspace-networking \
      --state="$STATE_DIR/tailscaled.state" \
      --socket="$STATE_DIR/tailscaled.sock" \
      > "$HOME/modeler-logs/tailscaled.log" 2>&1 &
  sleep 3
fi

echo
echo "== authenticate: open the URL printed below in any browser and approve this machine =="
"$TS_DIR/tailscale" --socket="$STATE_DIR/tailscaled.sock" up --hostname=adt-server

echo
echo "Tailscale IP: $("$TS_DIR/tailscale" --socket="$STATE_DIR/tailscaled.sock" ip -4 2>/dev/null || echo unknown)"
echo "Reachable over the tailnet: ssh (22), web (3000), API (8000)."

# Survive reboots without root, via the user crontab.
CRON_LINE="@reboot nohup $TS_DIR/tailscaled --tun=userspace-networking --state=$STATE_DIR/tailscaled.state --socket=$STATE_DIR/tailscaled.sock >> $HOME/modeler-logs/tailscaled.log 2>&1 &"
if ! crontab -l 2>/dev/null | grep -Fq "tailscaled --tun=userspace-networking"; then
  ( crontab -l 2>/dev/null; echo "$CRON_LINE" ) | crontab -
  echo "Added a @reboot entry so tailscaled restarts automatically."
fi
