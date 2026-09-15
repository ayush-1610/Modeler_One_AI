#!/usr/bin/env bash
# Run the engine catalog harvest (T-02) on a compute server, reusing the engine that
# ubuntu_engine_check.sh installed into <engine dir> (.NET in <dir>/dotnet, R packages in <dir>/rlib).
#
#   bash services/engine-worker/scripts/harvest_catalog.sh <engine dir> [out dir]
#
# Downloads the OSP reference snapshots, harvests the catalog into <out dir>/catalog.json, and copies the
# reference snapshots into services/engine-worker/golden/fixtures/ so they can be committed as golden fixtures.
set -euo pipefail

TARGET="${1:?usage: harvest_catalog.sh <engine dir> [out dir]}"
TARGET="$(cd "$TARGET" && pwd)"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT="${2:-$TARGET/catalog}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
FIXTURES="$REPO/services/engine-worker/golden/fixtures"
mkdir -p "$FIXTURES"

# Same engine environment as ubuntu_engine_check.sh.
export DOTNET_ROOT="$TARGET/dotnet"
export PATH="$TARGET/dotnet:$PATH"
export R_LIBS_USER="$TARGET/rlib"
if   locale -a 2>/dev/null | grep -qi "en_US.utf8\|en_US.UTF-8"; then export LC_ALL=en_US.UTF-8
elif locale -a 2>/dev/null | grep -qi "C.utf8\|C.UTF-8";          then export LC_ALL=C.UTF-8
fi
_r_prefix="$(Rscript -e 'cat(normalizePath(file.path(R.home(), "..", ".."), mustWork=FALSE))' 2>/dev/null || true)"
if [ -n "$_r_prefix" ] && [ -d "$_r_prefix/lib" ]; then
  export LD_LIBRARY_PATH="$_r_prefix/lib:${R_LIBS_USER}/ospsuite/lib:${LD_LIBRARY_PATH:-}"
else
  export LD_LIBRARY_PATH="${R_LIBS_USER}/ospsuite/lib:${LD_LIBRARY_PATH:-}"
fi

echo "== fetch reference snapshots"
bash "$REPO/services/engine-worker/scripts/fetch_reference_snapshots.sh" "$OUT/reference"

echo "== harvest"
Rscript "$REPO/services/engine-worker/r/harvest_catalog.R" "$OUT/catalog.json" "$OUT/reference"

echo "== copy reference snapshots into golden fixtures"
cp -f "$OUT"/reference/*.json "$FIXTURES/"

echo
echo "catalog.json:  $OUT/catalog.json"
echo "fixtures:      $FIXTURES (commit these)"
