#!/usr/bin/env bash
# Installation Qualification of this server (GAMP 5 IQ; validation pack V1): what is installed, checked against what the
# repository says should be. Read-only; it never prints a secret. The checks are in deploy/server/qualify.py.
#
#   qualify.sh iq                 writes $MODELER_DATA/qualification/iq-<UTC time>.json and prints each check
#   qualify.sh iq --out FILE      writes FILE instead
#
# Exit 1 when a check fails. The record goes into the validation pack:
#   uv run python -m pbpk_domain.report.validation_pack --trace-matrix … --iq FILE [--pq pq.json] --out pack.md
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"

MODELER_REPO="$REPO" MODELER_DATA="$DATA" MODELER_API_PORT="$API_PORT" MODELER_WEB_PORT="$WEB_PORT" \
  MODELER_WEB_TLS="${MODELER_WEB_TLS:-}" exec python3 "$REPO/deploy/server/qualify.py" "$@"
