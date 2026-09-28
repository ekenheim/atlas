#!/usr/bin/env bash
# Generate the frontend's typed API client from the FastAPI OpenAPI schema.
#   scripts/gen_api_client.sh          rewrite frontend/lib/api/{openapi.json,schema.ts}
#   scripts/gen_api_client.sh --check  regenerate into a temp dir and diff (CI); exit 1 if stale
# Needs `uv sync` and `npm --prefix frontend ci` first.
set -euo pipefail
cd "$(dirname "$0")/.."
committed="$PWD/frontend/lib/api"
out="$committed"
if [[ "${1:-}" == "--check" ]]; then
  out="$(mktemp -d)"
  trap 'rm -rf "$out"' EXIT
fi

uv run python scripts/export_openapi.py "$out/openapi.json"
npm --prefix frontend exec --no -- \
  openapi-typescript "$out/openapi.json" --output "$out/schema.ts" --silent

if [[ "$out" != "$committed" ]]; then
  if ! diff -u "$committed/openapi.json" "$out/openapi.json" \
    || ! diff -u "$committed/schema.ts" "$out/schema.ts"; then
    echo "The API client is stale: run scripts/gen_api_client.sh and commit the result." >&2
    exit 1
  fi
  echo "API client is current with the OpenAPI schema."
fi
