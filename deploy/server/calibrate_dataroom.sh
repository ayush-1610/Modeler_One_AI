#!/usr/bin/env bash
# The Data room's calibration run on this server (plan 2026-11-24 §2.3, decision D2): one run of the Data room's agents on
# the made-up Exampleamide delivery, with the key that is active in Admin → Keys, behind a hard cap; it prints the cost
# and how many of the delivery's 60 values it got right. Paid: run it only when the owner asks.
#
#   calibrate_dataroom.sh --dry                  the models, the estimate and this month's spend; no call
#   calibrate_dataroom.sh                        the "Claude demo" preset, capped at $5.50
#   calibrate_dataroom.sh --preset free          the same run on the free models ($0), to compare
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"
cd "$REPO"
exec uv run python deploy/dev/calibrate_dataroom.py "$@"
