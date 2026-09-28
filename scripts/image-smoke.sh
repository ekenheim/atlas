#!/usr/bin/env bash
# Smoke-test the app image: non-root, read-only root filesystem, /tmp writable,
# liveness answers and the static frontend is served.
set -euo pipefail
image="${1:-atlas:dev}"
name="atlas-smoke-$$"
port="${ATLAS_SMOKE_PORT:-58000}"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT

docker run -d --name "$name" --read-only --tmpfs /tmp -p "127.0.0.1:${port}:8000" \
  -e ATLAS_DATABASE_URL="postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas" \
  -e ATLAS_ACTOR="smoke" -e ATLAS_ARCHIVE_ROOT="/tmp/archive" \
  "$image" api >/dev/null

uid="$(docker exec "$name" id -u)"
[[ "$uid" != "0" ]] || { echo "FAIL: container runs as root" >&2; exit 1; }

for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:${port}/health/live" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${port}/health/live" | grep -q '"status":"ok"' \
  || { echo "FAIL: /health/live" >&2; docker logs "$name" >&2; exit 1; }
curl -fsS "http://127.0.0.1:${port}/" | grep -q 'id="atlas-root"' \
  || { echo "FAIL: frontend not served" >&2; exit 1; }
echo "image smoke OK (uid ${uid}, read-only root)"
