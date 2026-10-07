#!/usr/bin/env bash
# The one CI entrypoint: GitHub Actions runs exactly this, and so should you.
# Fixture-only: no paid keys, no network beyond the local Compose services.
#   scripts/ci.sh               every stage, including the image build + smoke
#   scripts/ci.sh --no-image    every stage but the image (faster local loop)
#   scripts/ci.sh static        lint, types, frontend unit tests, API client (no Docker)
#   scripts/ci.sh suite         services, pytest, e2e, image (the Docker half)
#   scripts/ci.sh suite --no-image
# CI runs `static` on GitHub's runners first and `suite` on the self-hosted scale set only
# when it passes, so a lint error never takes a Docker runner.
set -euo pipefail
cd "$(dirname "$0")/.."
stage=all
build_image=1
for arg in "$@"; do
  case "$arg" in
    static | suite) stage="$arg" ;;
    --no-image) build_image=0 ;;
    *) echo "usage: scripts/ci.sh [static|suite] [--no-image]" >&2; exit 2 ;;
  esac
done
step() { printf '\n==> %s\n' "$*"; }

frontend_install() {
  if [[ -n "${CI:-}" || ! -d frontend/node_modules ]]; then
    npm --prefix frontend ci --no-audit --no-fund
  fi
}

static() {
  step "python: sync locked dependencies"
  uv sync --frozen

  step "python: format, lint, types"
  uv run ruff format --check backend tests scripts
  uv run ruff check backend tests scripts
  uv run pyright

  step "frontend: install, lint, types, unit tests, API client is current"
  frontend_install
  npm --prefix frontend run lint
  npm --prefix frontend run typecheck
  npm --prefix frontend run test
  scripts/gen_api_client.sh --check
}

suite() {
  step "python + frontend: sync locked dependencies, static export"
  uv sync --frozen
  frontend_install
  npm --prefix frontend run build

  step "services: postgres + s3"
  docker compose up -d --wait postgres-app silo

  step "tests: unit + integration (includes migrations from empty)"
  # In parallel (pytest-xdist): every test has its own database, bucket, archive and localhost
  # ports, so tests are dealt out one by one (`load`); plain `uv run pytest` still runs serially.
  # At most 8 workers: Postgres allows 100 connections; the runner requests 4 CPUs.
  uv run pytest -n auto --maxprocesses 8 --dist load

  step "e2e: Playwright tests of the source viewer and Assertions (fixture-seeded API + static export)"
  # Installs chromium (with its OS deps in CI). Locally it skips, saying why, if chromium
  # can't be installed or launched; in CI that is a failure.
  uv run python scripts/e2e.py

  if [[ "$build_image" == 1 ]]; then
    step "image: build + smoke (non-root, read-only root)"
    docker build -q -t atlas:ci .
    scripts/image-smoke.sh atlas:ci
  fi
}

[[ "$stage" == suite ]] || static
[[ "$stage" == static ]] || suite
step "CI passed ($stage)"
