#!/usr/bin/env bash
# Push this checkout to the server and restart the tool on the new build. Run from the repository root on the Mac.
#
#   bash deploy/dev/deploy_to_server.sh            # host alias "adt-server" (see ~/.ssh/config)
#   MODELER_SERVER=user@host bash deploy/dev/deploy_to_server.sh
#
# The server copy (~/Modeler_One_AI) is an rsync target, not a git checkout. --delete keeps it an exact mirror of
# the tracked tree; data lives outside it (~/modeler-data), and the two server_e2e*.py scratch scripts are kept.
set -euo pipefail
server="${MODELER_SERVER:-adt-server}"

# What is deployed, recorded on the server for its Installation Qualification (deploy/server/qualify.sh iq, IQ-01).
# CLAUDE.md deploys only from a clean `main`; anything else is said here and fails IQ-01 there.
commit="$(git rev-parse HEAD)"
branch="$(git rev-parse --abbrev-ref HEAD)"
clean=true
[ -z "$(git status --porcelain)" ] || clean=false
if [ "$branch" != main ] || [ "$clean" != true ]; then
  echo "WARNING: deploying '$branch'$([ "$clean" = true ] || echo ' with local changes'): CLAUDE.md deploys only from a clean main" >&2
fi

rsync -az --delete --exclude='/server_e2e*.py' --exclude='.git/' --exclude='.venv/' --exclude='node_modules/' \
  --exclude='.next/' --exclude='__pycache__/' --exclude='reports/' --exclude='.pytest_cache/' \
  --exclude='.ruff_cache/' --exclude='*.pyc' --exclude='.DS_Store' ./ "$server:~/Modeler_One_AI/"
echo "synced to $server"
printf '{"commit": "%s", "branch": "%s", "clean": %s, "deployed_at": "%s", "deployed_by": "%s"}\n' \
  "$commit" "$branch" "$clean" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(whoami)@$(hostname -s)" \
  | ssh "$server" 'cat > ~/Modeler_One_AI/.deployed.json'

ssh "$server" 'set -e
  cd ~/Modeler_One_AI
  export PATH=$HOME/.local/bin:$PATH
  uv sync --all-packages -q
  export NVM_DIR=$HOME/.nvm; . "$NVM_DIR/nvm.sh" >/dev/null
  (cd apps/web && npm ci --no-audit --no-fund --silent && npm run build --silent >/dev/null)
  bash deploy/server/stop_modeler.sh >/dev/null
  bash deploy/server/run_modeler.sh
  sleep 8
  bash deploy/server/status_modeler.sh'
