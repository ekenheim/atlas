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

step "frontend: install, lint, types, unit tests, API client is current, static export"
if [[ -n "${CI:-}" || ! -d frontend/node_modules ]]; then
  npm --prefix frontend ci --no-audit --no-fund
fi
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
scripts/gen_api_client.sh --check
npm --prefix frontend run build

step "services: postgres + s3"
docker compose up -d --wait postgres-app silo

step "tests: unit + integration (includes migrations from empty)"
# In parallel (pytest-xdist): every test has its own database, bucket, archive and localhost
# ports, so tests are dealt out one by one (`load`); plain `uv run pytest` still runs serially.
uv run pytest -n auto --dist load

step "e2e: Playwright tests of the source viewer and Assertions (fixture-seeded API + static export)"
# Installs chromium (with its OS deps in CI). Locally it skips, saying why, if chromium
# can't be installed or launched; in CI that is a failure.
uv run python scripts/e2e.py

if [[ "$build_image" == 1 ]]; then
  step "image: build + smoke (non-root, read-only root)"
  docker build -q -t atlas:ci .
  scripts/image-smoke.sh atlas:ci
fi

step "CI passed"
