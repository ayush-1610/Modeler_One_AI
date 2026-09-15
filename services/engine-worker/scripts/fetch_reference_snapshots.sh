#!/usr/bin/env bash
# Download the Open Systems Pharmacology library model snapshots used as harvest and golden fixtures.
#
#   bash services/engine-worker/scripts/fetch_reference_snapshots.sh <dir>
#
# These are the published OSP qualified models (GPLv2, snapshot JSON). They are inputs to the engine
# catalog harvest (harvest_catalog.R): the platform never invents process/formulation/calculation-method
# names, it discovers them from these real snapshots. Each file is checked for a top-level "Version" key
# so a partial download (or an HTML error page) is rejected rather than silently harvested.
set -euo pipefail

DIR="${1:?usage: fetch_reference_snapshots.sh <dir>}"
mkdir -p "$DIR"
DIR="$(cd "$DIR" && pwd)"

BASE="https://raw.githubusercontent.com/Open-Systems-Pharmacology"
# repo/model name -> file is always "<Model>.json" on the master branch (verified 2026-09-15).
MODELS=(Dapagliflozin Midazolam Itraconazole Rifampicin)

for model in "${MODELS[@]}"; do
  url="${BASE}/${model}-Model/master/${model}-Model.json"
  dest="${DIR}/${model}-Model.json"
  if [ -s "$dest" ] && grep -q '"Version"' "$dest"; then
    echo "have    ${model}-Model.json"
    continue
  fi
  echo "fetch   ${url}"
  curl -fsSL "$url" -o "$dest"
  if ! grep -q '"Version"' "$dest"; then
    echo "ERROR: ${dest} has no \"Version\" key; not a snapshot (download failed?)." >&2
    rm -f "$dest"
    exit 1
  fi
done

echo
echo "Reference snapshots in $DIR:"
ls -la "$DIR"/*.json
