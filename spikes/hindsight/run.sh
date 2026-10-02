#!/usr/bin/env bash
# Usage: spikes/hindsight/run.sh <litellm-model> [extra-body-json] [compose args...]
# Loads LITELLM_URL / LITELLM_API_KEY from the repo's .env, or from the file
# ATLAS_SPIKE_ENV_FILE names (a worktree has no .env of its own), CRLF-safe, and
# (re)starts the local Hindsight with the given LLM alias.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"

while IFS='=' read -r key value || [[ -n "$key" ]]; do
  key="${key//$'\r'/}"; value="${value//$'\r'/}"
  [[ -z "$key" || "$key" == \#* ]] && continue
  value="${value%\"}"; value="${value#\"}"
  export "$key=$value"
done < "${ATLAS_SPIKE_ENV_FILE:-$root/.env}"
export LITELLM_URL="${LITELLM_URL%/}"

export ATLAS_LLM_MODEL="${1:?usage: run.sh <litellm-model> [extra-body-json]}"
empty_body='{}'
export ATLAS_LLM_EXTRA_BODY="${2:-$empty_body}"
shift $(( $# >= 2 ? 2 : 1 ))

docker compose -f "$here/compose.yaml" up -d --force-recreate "$@"
