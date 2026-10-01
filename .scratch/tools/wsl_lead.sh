#!/usr/bin/env bash
# Lead's checks on the integration worktree, run inside WSL:
#   wsl_lead.sh client            regenerate frontend/lib/api
#   wsl_lead.sh static            ruff format --check, ruff check, pyright
#   wsl_lead.sh test <pytest args>
#   wsl_lead.sh frontend          lint, typecheck, unit tests
set -uo pipefail
cd /mnt/c/Users/ekenh/worktrees/atlas/oval-tide/atlas || exit 1
export PATH="/home/linuxbrew/.linuxbrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/atlas-oval-tide"
case "$1" in
  client)
    uv sync --frozen 2>&1 | tail -1
    if [ ! -d frontend/node_modules/.bin ]; then npm --prefix frontend ci 2>&1 | tail -2; fi
    uv run --no-sync python scripts/export_openapi.py frontend/lib/api/openapi.json \
      && npm --prefix frontend exec --no -- openapi-typescript frontend/lib/api/openapi.json \
           --output frontend/lib/api/schema.ts --silent \
      && echo "client generated"
    ;;
  static)
    uv run --no-sync ruff format --check backend tests scripts 2>&1 | tail -3
    uv run --no-sync ruff check backend tests scripts 2>&1 | tail -8
    uv run --no-sync pyright 2>&1 | tail -12
    ;;
  test)
    shift
    uv run --no-sync pytest "$@" 2>&1 | tail -40
    ;;
  frontend)
    npm --prefix frontend run lint 2>&1 | tail -6
    npm --prefix frontend run typecheck 2>&1 | tail -8
    npm --prefix frontend run test 2>&1 | tail -6
    ;;
esac
