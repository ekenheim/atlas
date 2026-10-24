#!/usr/bin/env bash
# An implementer's checks for the worktree this script sits in, run inside WSL (native pytest
# fails in the harness's CLI subprocess on Windows). From Git Bash in the worktree:
#   MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu -- bash "$(wslpath -a .scratch/tools/wsl_checks.sh 2>/dev/null || echo /mnt/c/.../.scratch/tools/wsl_checks.sh)" static
# or, simpler, give the /mnt/c path of this file. Commands:
#   sync                 uv sync --frozen into this worktree's own venv
#   static               ruff format --check, ruff check, pyright
#   test <pytest args>   the named test modules only (the runners run the suite)
#   frontend             lint, typecheck, unit tests
#   client               regenerate frontend/lib/api
#   run <command...>     any command with the venv's environment (e.g. run uv run atlas --help)
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root" || exit 1
export PATH="/home/linuxbrew/.linuxbrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
# One venv per worktree, named after the worktree's path, outside /mnt/c (slow) and out of git.
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/atlas-$(printf '%s' "$root" | md5sum | cut -c1-10)"
case "${1:-}" in
  sync)
    uv sync --frozen 2>&1 | tail -2
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
    if [ ! -d frontend/node_modules/.bin ]; then npm --prefix frontend ci 2>&1 | tail -2; fi
    npm --prefix frontend run lint 2>&1 | tail -6
    npm --prefix frontend run typecheck 2>&1 | tail -8
    npm --prefix frontend run test 2>&1 | tail -6
    ;;
  client)
    if [ ! -d frontend/node_modules/.bin ]; then npm --prefix frontend ci 2>&1 | tail -2; fi
    uv run --no-sync python scripts/export_openapi.py frontend/lib/api/openapi.json \
      && npm --prefix frontend exec --no -- openapi-typescript frontend/lib/api/openapi.json \
           --output frontend/lib/api/schema.ts --silent \
      && echo "client generated"
    ;;
  run)
    shift
    "$@"
    ;;
  *)
    echo "usage: wsl_checks.sh sync|static|test <args>|frontend|client|run <command...>" >&2
    exit 2
    ;;
esac
