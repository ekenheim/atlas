#!/usr/bin/env bash
# The live extraction smoke test (tests/live/test_extraction_smoke_live.py, ticket 28): the
# Investigator over three recorded EDGAR filings with MiniMax via LiteLLM, reporting every
# Claim's outcome and where each mismatched quote occurs in its passage. Needs no Hindsight
# (the recorded fake serves on localhost) and makes at most 6 chat completions (cap 10).
# Never run in CI. See docs/runbooks.md, "Live extraction smoke test".
#
#   scripts/live-extraction-smoke.sh [options] [-- extra pytest args]
#
# A live run SPENDS MINIMAX QUOTA (a few calls) and asks for confirmation unless --yes.
#   --rehearse     run against the scripted LiteLLM fake on localhost instead: no .env, no
#                  network beyond localhost, no quota
#   --model M      the model the Investigator's calls ask LiteLLM for (default MiniMax-M3)
#   --keep-db      keep the run's app database (atlas_live_extract_*) for inspection
#   --results DIR  where to write the report (default .scratch/live-runs/<UTC stamp>-extraction-<mode>)
#   --yes          don't ask before a live run
#   --dry-run      print what would run, and run nothing
#
# LiteLLM settings: ATLAS_LITELLM_URL/ATLAS_LITELLM_API_KEY, else the repo .env's
# LITELLM_URL/LITELLM_API_KEY or ATLAS_LITELLM_* (read CRLF-safe, never printed).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

mode=live model="MiniMax-M3" keep=0 yes=0 dry=0 results=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rehearse) mode=rehearse ;;
    --model) model="${2:?--model needs a model name}"; shift ;;
    --keep-db) keep=1 ;;
    --results) results="${2:?--results needs a directory}"; shift ;;
    --yes) yes=1 ;;
    --dry-run) dry=1 ;;
    --) shift; break ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) echo "live-extraction-smoke: unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
pytest_args=("$@")

say() { printf '==> %s\n' "$*"; }
die() { printf 'live-extraction-smoke: %s\n' "$*" >&2; exit 2; }

[[ -n "${CI:-}" ]] && die "CI is set: the live smoke test never runs in CI"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
results="${results:-.scratch/live-runs/$stamp-extraction-$mode}"
export ATLAS_LIVE_TESTS="$([[ "$mode" == live ]] && echo 1 || echo rehearse)"
export ATLAS_LIVE_RESULTS_DIR="$root/$results"
[[ "$results" == /* ]] && export ATLAS_LIVE_RESULTS_DIR="$results"
export ATLAS_LLM_ROLE_MODEL="$model"
[[ "$keep" == 1 ]] && export ATLAS_LIVE_KEEP_DATABASE=1

# The app database: start the Compose Postgres only if nothing answers on its port.
if ! (exec 3<>/dev/tcp/127.0.0.1/55432) 2>/dev/null; then
  if [[ "$dry" == 1 ]]; then
    echo "+ docker compose up -d --wait postgres-app"
  else
    docker compose up -d --wait postgres-app
  fi
fi

if [[ "$mode" == live ]]; then
  if [[ -f .env ]]; then
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
      key="${key//$'\r'/}"; value="${value//$'\r'/}"
      value="${value%\"}"; value="${value#\"}"
      case "$key" in
        LITELLM_URL|ATLAS_LITELLM_URL) : "${ATLAS_LITELLM_URL:=$value}" ;;
        LITELLM_API_KEY|ATLAS_LITELLM_API_KEY) : "${ATLAS_LITELLM_API_KEY:=$value}" ;;
      esac
    done < .env
  fi
  [[ -n "${ATLAS_LITELLM_URL:-}" && -n "${ATLAS_LITELLM_API_KEY:-}" ]] \
    || die "no LiteLLM settings: set ATLAS_LITELLM_URL/ATLAS_LITELLM_API_KEY or LITELLM_* in .env"
  export ATLAS_LITELLM_URL="${ATLAS_LITELLM_URL%/}" ATLAS_LITELLM_API_KEY

  say "live run: model $model via $ATLAS_LITELLM_URL (at most 6 chat completions)"
  if [[ "$yes" == 0 && "$dry" == 0 ]]; then
    answer=""
    read -r -p "This spends MiniMax quota. Continue? [y/N] " answer || true
    [[ "$answer" == [yY]* ]] || die "not confirmed; nothing was run"
  fi
fi

say "running the smoke test ($mode); report in $results"
suite=(uv run pytest -m live tests/live/test_extraction_smoke_live.py -v -rA
  --junitxml "$ATLAS_LIVE_RESULTS_DIR/junit.xml" "${pytest_args[@]}")
if [[ "$dry" == 1 ]]; then
  printf '+ %s\n' "${suite[*]}"
  say "dry run: nothing was run"
  exit 0
fi
mkdir -p "$ATLAS_LIVE_RESULTS_DIR"
printf '+ %s\n' "${suite[*]}"
set +e
"${suite[@]}" 2>&1 | tee "$ATLAS_LIVE_RESULTS_DIR/pytest.log"
status="${PIPESTATUS[0]}"
set -e
case "$status" in
  0) say "smoke test passed" ;;
  4) say "smoke test REFUSED by its preflight (see above); nothing was sent to a model" ;;
  *) say "smoke test FAILED (pytest exit $status)" ;;
esac
say "report: $results/{summary.md,results.json,junit.xml,pytest.log}"
if [[ "$mode" == live && "$status" != 4 ]]; then
  say "record the run: copy summary.md's facts into docs/implementation-log.md"
fi
exit "$status"
