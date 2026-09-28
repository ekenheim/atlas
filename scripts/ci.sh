#!/usr/bin/env bash
# The one CI entrypoint: GitHub Actions runs exactly this, and so should you.
# Fixture-only: no paid keys, no network beyond the local Compose services.
#   scripts/ci.sh             full run (includes image build + smoke)
#   scripts/ci.sh --no-image  skip the image build (faster local loop)
set -euo pipefail
cd "$(dirname "$0")/.."
build_image=1
[[ "${1:-}" == "--no-image" ]] && build_image=0
step() { printf '\n==> %s\n' "$*"; }

step "python: sync locked dependencies"
uv sync --frozen

step "python: format, lint, types"
uv run ruff format --check backend tests scripts
uv run ruff check backend tests scripts
uv run pyright

step "frontend: install, lint, types, static export"
if [[ -n "${CI:-}" || ! -d frontend/node_modules ]]; then
  npm --prefix frontend ci --no-audit --no-fund
fi
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build

step "services: postgres + s3"
docker compose up -d --wait postgres-app silo

step "tests: unit + integration (includes migrations from empty)"
uv run pytest

if [[ "$build_image" == 1 ]]; then
  step "image: build + smoke (non-root, read-only root)"
  docker build -q -t atlas:ci .
  scripts/image-smoke.sh atlas:ci
fi

step "CI passed"
