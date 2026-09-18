#!/usr/bin/env bash
# Engine check for an Ubuntu 24.04 compute server.
#
# Installs the OSP engine (ospsuite 12.4.x + parameter identification + .NET 8 runtime) into one self-contained
# directory, then runs on this machine:
#   1. benchmark.R            model load, single runs, batch runs on 1 core and all cores, a real fitting run
#   2. golden_roundtrip.R     platform snapshot -> PK-Sim project -> snapshot; run from snapshot; PK (Linux only)
#   3. pi_smoke.R             one fitting start through run_pi.R
#   4. golden_tasks.R         population, sensitivity and batch tasks through run_job.R (T-09)
#
#   bash services/engine-worker/scripts/ubuntu_engine_check.sh /data/modeler-engine
#
# Put the engine directory on a disk with free space; the root disk of the compute servers is 93% full.
# apt steps need sudo. R packages go into <dir>/rlib, .NET into <dir>/dotnet; nothing else is installed globally.
set -euo pipefail

TARGET="${1:?usage: ubuntu_engine_check.sh <engine directory on a data disk>}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

free_gb=$(df -BG --output=avail "$TARGET" | tail -1 | tr -dc '0-9')
if [ "$free_gb" -lt 10 ]; then
  echo "Need at least 10 GB free in $TARGET (have ${free_gb} GB). Choose a directory on another disk." >&2
  exit 1
fi

echo "== system packages"
# R: accept conda R (r-base=4.6 from conda-forge) or system R >= 4.4
_need_r=0
if ! command -v Rscript >/dev/null 2>&1 || ! Rscript -e 'quit(status = as.integer(getRversion() < "4.4"))' 2>/dev/null; then
  _need_r=1
fi
# curl: may come from system or conda; only require apt curl if neither is available
_need_curl=0
command -v curl >/dev/null 2>&1 || _need_curl=1
# Locale: en_US.UTF-8 preferred; C.UTF-8 is a fully-capable UTF-8 fallback (no locale-gen needed)
_lc_all=""
if   locale -a 2>/dev/null | grep -qi "en_US.utf8\|en_US.UTF-8"; then _lc_all="en_US.UTF-8"
elif locale -a 2>/dev/null | grep -qi "C.utf8\|C.UTF-8";          then _lc_all="C.UTF-8"
fi
_need_locale=0
[ -z "$_lc_all" ] && _need_locale=1

if [ "${_need_r}" -eq 1 ] || [ "${_need_curl}" -eq 1 ] || [ "${_need_locale}" -eq 1 ]; then
  if ! sudo -n true 2>/dev/null && ! sudo -v 2>/dev/null; then
    echo "" >&2
    echo "ERROR: sudo is required but this account ($(whoami)) is not in the sudoers file." >&2
    echo "Ask a sysadmin to run the following as root, then re-run this script:" >&2
    echo "" >&2
    [ "${_need_r}"      -eq 1 ] && echo "  apt-get install -y --no-install-recommends r-base" >&2
    [ "${_need_curl}"   -eq 1 ] && echo "  apt-get install -y --no-install-recommends curl" >&2
    [ "${_need_locale}" -eq 1 ] && echo "  locale-gen en_US.UTF-8" >&2
    echo "" >&2
    exit 1
  fi
  if [ "${_need_r}" -eq 1 ]; then
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends software-properties-common dirmngr ca-certificates curl gnupg
    curl -fsSL https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc | sudo tee /etc/apt/trusted.gpg.d/cran_ubuntu_key.asc >/dev/null
    sudo add-apt-repository -y "deb https://cloud.r-project.org/bin/linux/ubuntu $(lsb_release -cs)-cran40/"
    sudo apt-get install -y --no-install-recommends r-base
  fi
  [ "${_need_curl}"   -eq 1 ] && sudo apt-get install -y --no-install-recommends curl
  if [ "${_need_locale}" -eq 1 ]; then
    sudo apt-get install -y --no-install-recommends locales
    sudo locale-gen en_US.UTF-8 >/dev/null
    _lc_all="en_US.UTF-8"
  fi
else
  echo "  all system prerequisites already satisfied; skipping apt"
fi

echo "== .NET 8 runtime"
if [ ! -x "$TARGET/dotnet/dotnet" ]; then
  curl -fsSL https://dot.net/v1/dotnet-install.sh -o "$TARGET/dotnet-install.sh"
  bash "$TARGET/dotnet-install.sh" --runtime dotnet --channel 8.0 --install-dir "$TARGET/dotnet"
fi

export LC_ALL="${_lc_all:-en_US.UTF-8}"
export DOTNET_ROOT="$TARGET/dotnet"
export PATH="$TARGET/dotnet:$PATH"
export R_LIBS_USER="$TARGET/rlib"
mkdir -p "$R_LIBS_USER"

# If R comes from conda, add its prefix lib dir to LD_LIBRARY_PATH so rSharp finds ICU and other shared libs
_r_prefix="$(Rscript -e 'cat(normalizePath(file.path(R.home(), "..", ".."), mustWork=FALSE))' 2>/dev/null || true)"
if [ -n "$_r_prefix" ] && [ -d "$_r_prefix/lib" ]; then
  export LD_LIBRARY_PATH="$_r_prefix/lib:${LD_LIBRARY_PATH:-}"
fi

echo "== OSP R packages"
Rscript -e '
minor_num <- strsplit(R.version$minor, ".", fixed = TRUE)[[1L]][1L]
minor <- paste(R.version$major, minor_num, sep = ".")
osp_url <- paste0("https://open-systems-pharmacology.r-universe.dev/bin/linux/noble-x86_64/", minor)
options(
  repos = c(osp = osp_url, CRAN = "https://packagemanager.posit.co/cran/__linux__/noble/latest"),
  HTTPUserAgent = paste0("R/", getRversion(), " R (", paste(getRversion(), R.version[["platform"]], R.version[["arch"]], R.version[["os"]]), ")"),
  timeout = 1800
)
lib <- Sys.getenv("R_LIBS_USER")
needed <- c("ospsuite", "ospsuite.parameteridentification", "jsonlite", "digest")
missing_pkgs <- needed[!vapply(needed, requireNamespace, logical(1L), lib.loc = lib, quietly = TRUE)]
if (length(missing_pkgs) > 0L) install.packages(missing_pkgs, lib = lib)
for (p in c(needed, "rSharp")) cat(p, as.character(packageVersion(p, lib.loc = lib)), "\n")
'
export LD_LIBRARY_PATH="$R_LIBS_USER/ospsuite/lib:${LD_LIBRARY_PATH:-}"

OUT="$TARGET/check-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
{ lscpu; echo; free -g; echo; df -h "$TARGET" /; echo; cat /etc/os-release; } > "$OUT/host.txt"

status=0
echo "== benchmark"
Rscript "$REPO/services/engine-worker/r/benchmark.R" "" "" 400 "$OUT/benchmark.json" > "$OUT/benchmark.log" 2>&1 || status=1
echo "== golden round trip"
Rscript "$REPO/services/engine-worker/golden/golden_roundtrip.R" "$REPO/services/engine-worker/golden/example_snapshot.json" "$OUT/golden" > "$OUT/golden.log" 2>&1 || status=1
echo "== fitting smoke test"
Rscript "$REPO/services/engine-worker/golden/pi_smoke.R" "$OUT/pi_smoke" > "$OUT/pi_smoke.log" 2>&1 || status=1
echo "== engine tasks (population, sensitivity, batch)"
( cd "$REPO" && Rscript "$REPO/services/engine-worker/golden/golden_tasks.R" ) > "$OUT/golden_tasks.log" 2>&1 || status=1

tail -n 5 "$OUT/golden.log" "$OUT/pi_smoke.log" "$OUT/golden_tasks.log"
echo
echo "Results in $OUT (benchmark.json, golden/golden_report.json, pi_smoke/out/pi_result.json, host.txt)."
exit "$status"
