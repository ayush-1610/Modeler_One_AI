#!/usr/bin/env bash
# Shared configuration for the single-node Modeler One deployment, sourced by the other scripts.
# Everything here must work from a bare cron environment, so PATH and every tool location are explicit.

REPO="${MODELER_REPO:-$HOME/Modeler_One_AI}"
DATA="${MODELER_DATA:-$HOME/modeler-data}"
LOGS="${MODELER_LOGS:-$HOME/modeler-logs}"
STOPPED_FLAG="$DATA/.stopped"          # set by stop_modeler.sh so the watchdog does not resurrect it
API_PORT="${MODELER_API_PORT:-8000}"
WEB_PORT="${MODELER_WEB_PORT:-3000}"

mkdir -p "$DATA/read-root" "$DATA/objstore" "$LOGS"

# --- engine (conda R + PK-Sim + .NET), as installed by T-01 under ~/modeler-engine ---
export PATH="$HOME/.local/bin:$HOME/miniforge3/bin:$HOME/modeler-engine/dotnet:/usr/local/bin:/usr/bin:/bin"
export R_LIBS_USER="$HOME/modeler-engine/rlib"
export DOTNET_ROOT="$HOME/modeler-engine/dotnet"
export LC_ALL=en_US.UTF-8
export LD_LIBRARY_PATH="$R_LIBS_USER/ospsuite/lib:$HOME/miniforge3/lib:${LD_LIBRARY_PATH:-}"

# --- application: single-node local execution against the real engine ---
export MODELER_DEV_AUTH=1
export MODELER_EXECUTION_BACKEND=local
export MODELER_READ_ROOT="$DATA/read-root"
export MODELER_OBJECT_STORE_URI="file://$DATA/objstore"
export MODELER_ENGINE_COMMAND="Rscript $REPO/services/engine-worker/r/run_job.R"
export MODELER_IMAGE_DIGEST="sha256:0000000000000000000000000000000000000000000000000000000000000000"
export MODELER_API_BASE="http://127.0.0.1:$API_PORT"

# --- agents (decision D-16): the in-house model behind LiteLLM, and Ollama's web search. Keys live OUTSIDE the
# repository, in a file only the owner can read (~/.bashrc is not read by these scripts: cron and nohup start a
# non-interactive shell). ~/.modeler-secrets.env (chmod 600), with no spaces around "=":
#   export MODELER_LLM_PROVIDER=litellm           # unset or "disabled" = agents off, manual paths only
#   export LITELLM_BASE=http://127.0.0.1:4000/v1   # the LiteLLM proxy (this server)
#   export LITELLM_KEY=...                         # the proxy's master key
#   export MODELER_LLM_MODEL=qwen-coder            # the proxy's alias (default); not the Ollama tag
#   export MODELER_LLM_TIMEOUT_S=600               # a 30B model reading a long document needs minutes per turn
#   export OLLAMA_API_KEY=...                      # web search for the agents (optional; its own key)
# Check it before starting: source ~/.modeler-secrets.env && uv run python -m modeler_agents.llm_check --search
SECRETS_FILE="${MODELER_SECRETS_FILE:-$HOME/.modeler-secrets.env}"
[ -f "$SECRETS_FILE" ] && . "$SECRETS_FILE"

# node, for `next start`
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1

# True when something is listening on a port (bash's /dev/tcp needs no extra tooling).
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }

# The stack is healthy only when both halves answer.
stack_healthy() { port_open "$API_PORT" && port_open "$WEB_PORT"; }
