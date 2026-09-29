#!/usr/bin/env bash
# The live Phase 2 gate suite (tests/live/test_phase2_gate_live.py): brings up a local Hindsight
# 0.10.1, runs the suite against it with MiniMax via LiteLLM, records the results and, if asked,
# tears the Hindsight containers down. Never run in CI. See docs/runbooks.md, "Live test suite".
#
#   scripts/live-tests.sh [options] [-- extra pytest args]
#
# A live run SPENDS MINIMAX QUOTA (retain and reflect) and asks for confirmation unless --yes.
#   --rehearse          run the suite against the recorded fakes on localhost instead: no
#                       Hindsight container, no .env, no network beyond localhost, no quota
#   --stop-before-llm   preflight, template and ingest only (retention off); nothing LLM-backed
#   --stack S           compose (default): the Compose `hindsight` profile on :58888
#                       spike: spikes/hindsight/run.sh on :8888 (one alias for everything)
#                       none: use the Hindsight at ATLAS_LIVE_HINDSIGHT_URL as it is
#                       cluster: the owner's cluster Hindsight (HINDSIGHT_URL/HINDSIGHT_API_KEY
#                       in .env, else ~/.hindsight/config); nothing is started or stopped
#   --profile P         small (default): the two 10-Qs (~18k chars, about the bake-off's cost)
#                       full: every recorded filing (~470k chars; est. ~40 min, ~1M input tokens)
#   --model ALIAS       LiteLLM alias for both extraction and reflect (e.g. MiniMax-M3), until
#                       atlas-extract/atlas-reflect are routed; the spike stack defaults to it
#   --keep-db           keep the run's app database (atlas_live_*) for inspection
#   --keep-bank         keep the run's throwaway Hindsight bank (deleted at the end otherwise)
#   --down              afterwards, stop and remove the Hindsight containers (volume kept)
#   --purge             with --down, also delete the Hindsight volume (all its banks)
#   --results DIR       where to record results (default .scratch/live-runs/<UTC stamp>-<mode>)
#   --yes               don't ask before a live run
#   --dry-run           print what would run, and run nothing
#
# LiteLLM settings: ATLAS_LITELLM_URL/ATLAS_LITELLM_API_KEY, else the repo .env's
# LITELLM_URL/LITELLM_API_KEY (the spike's names; read CRLF-safe, never printed).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

mode=live stop=0 stack=compose profile=small model="" keep=0 down=0 purge=0 yes=0 dry=0
results=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rehearse) mode=rehearse ;;
    --stop-before-llm) stop=1 ;;
    --stack) stack="${2:?--stack needs compose, spike or none}"; shift ;;
    --profile) profile="${2:?--profile needs small or full}"; shift ;;
    --model) model="${2:?--model needs a LiteLLM alias}"; shift ;;
    --keep-db) keep=1 ;;
    --keep-bank) export ATLAS_LIVE_KEEP_BANK=1 ;;
    --down) down=1 ;;
    --purge) purge=1 ;;
    --results) results="${2:?--results needs a directory}"; shift ;;
    --yes) yes=1 ;;
    --dry-run) dry=1 ;;
    --) shift; break ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "live-tests: unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
pytest_args=("$@")

say() { printf '==> %s\n' "$*"; }
die() { printf 'live-tests: %s\n' "$*" >&2; exit 2; }
run() {
  printf '+ %s\n' "$*"
  [[ "$dry" == 1 ]] || "$@"
}

[[ -n "${CI:-}" ]] && die "CI is set: the live suite never runs in CI"
case "$stack" in compose|spike|none|cluster) ;; *) die "--stack must be compose, spike, none or cluster" ;; esac
case "$profile" in
  small) forms="10-Q" ;;
  full) forms="10-K,10-Q,8-K" ;;
  *) die "--profile must be small or full" ;;
esac
[[ "$purge" == 1 && "$down" == 0 ]] && die "--purge needs --down"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
results="${results:-.scratch/live-runs/$stamp-$mode}"
export ATLAS_LIVE_TESTS="$([[ "$mode" == live ]] && echo 1 || echo rehearse)"
export ATLAS_LIVE_FORMS="$forms"
export ATLAS_LIVE_RESULTS_DIR="$root/$results"
[[ "$results" == /* ]] && export ATLAS_LIVE_RESULTS_DIR="$results"
[[ "$stop" == 1 ]] && export ATLAS_LIVE_STOP_BEFORE_LLM=1
[[ "$keep" == 1 ]] && export ATLAS_LIVE_KEEP_DATABASE=1

# The app database: start the Compose Postgres only if nothing answers on its port.
if ! (exec 3<>/dev/tcp/127.0.0.1/55432) 2>/dev/null; then
  run docker compose up -d --wait postgres-app
fi

if [[ "$mode" == live ]]; then
  # LiteLLM: the ATLAS_* names win; otherwise the spike's names from .env (CRLF-safe).
  hs_url_env=""; hs_key_env=""
  if [[ -f .env ]]; then
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
      key="${key//$'\r'/}"; value="${value//$'\r'/}"
      value="${value%\"}"; value="${value#\"}"
      case "$key" in
        LITELLM_URL) : "${ATLAS_LITELLM_URL:=$value}" ;;
        LITELLM_API_KEY) : "${ATLAS_LITELLM_API_KEY:=$value}" ;;
        ATLAS_LITELLM_URL) : "${ATLAS_LITELLM_URL:=$value}" ;;
        ATLAS_LITELLM_API_KEY) : "${ATLAS_LITELLM_API_KEY:=$value}" ;;
        HINDSIGHT_URL) hs_url_env="$value" ;;
        HINDSIGHT_API_KEY) hs_key_env="$value" ;;
      esac
    done < .env
  fi
  [[ -n "${ATLAS_LITELLM_URL:-}" && -n "${ATLAS_LITELLM_API_KEY:-}" ]] \
    || die "no LiteLLM settings: set ATLAS_LITELLM_URL/ATLAS_LITELLM_API_KEY or LITELLM_* in .env"
  export ATLAS_LITELLM_URL="${ATLAS_LITELLM_URL%/}" ATLAS_LITELLM_API_KEY
  export LITELLM_URL="$ATLAS_LITELLM_URL" LITELLM_API_KEY="$ATLAS_LITELLM_API_KEY"

  [[ "$stack" == spike && -z "$model" ]] && model="MiniMax-M3"
  if [[ -n "$model" ]]; then
    export ATLAS_LLM_EXTRACT_ALIAS="$model" ATLAS_LLM_REFLECT_ALIAS="$model"
  fi
  thinking_off='{"thinking":{"type":"disabled"}}'
  export ATLAS_HINDSIGHT_LLM_EXTRA_BODY="${ATLAS_HINDSIGHT_LLM_EXTRA_BODY:-$thinking_off}"

  case "$stack" in
    compose) export ATLAS_LIVE_HINDSIGHT_URL="http://127.0.0.1:${ATLAS_HINDSIGHT_PORT:-58888}" ;;
    spike) export ATLAS_LIVE_HINDSIGHT_URL="http://127.0.0.1:8888" ;;
    none) [[ -n "${ATLAS_LIVE_HINDSIGHT_URL:-}" ]] || die "--stack none needs ATLAS_LIVE_HINDSIGHT_URL" ;;
    cluster)
      # The owner's cluster Hindsight: HINDSIGHT_URL/HINDSIGHT_API_KEY from .env, else the
      # hindsight CLI's ~/.hindsight/config (never printed). Its route exposes only /v1, so the
      # version is declared (the HelmRelease pin) rather than read from /version.
      if [[ -z "$hs_url_env" || -z "$hs_key_env" ]] && [[ -f "$HOME/.hindsight/config" ]]; then
        read -r cfg_url cfg_key < <(python3 -c 'import tomllib,pathlib;c=tomllib.loads(pathlib.Path.home().joinpath(".hindsight/config").read_text());print(c.get("api_url",""),c.get("api_key",""))')
        : "${hs_url_env:=$cfg_url}" "${hs_key_env:=$cfg_key}"
      fi
      export ATLAS_LIVE_HINDSIGHT_URL="${ATLAS_LIVE_HINDSIGHT_URL:-${hs_url_env%/}}"
      export ATLAS_LIVE_HINDSIGHT_API_KEY="${ATLAS_LIVE_HINDSIGHT_API_KEY:-$hs_key_env}"
      export ATLAS_LIVE_HINDSIGHT_VERSION="${ATLAS_LIVE_HINDSIGHT_VERSION:-0.10.1}"
      [[ -n "$ATLAS_LIVE_HINDSIGHT_URL" && -n "$ATLAS_LIVE_HINDSIGHT_API_KEY" ]] \
        || die "--stack cluster needs HINDSIGHT_URL/HINDSIGHT_API_KEY in .env or ~/.hindsight/config"
      ;;
  esac

  say "live run: Hindsight $ATLAS_LIVE_HINDSIGHT_URL ($stack), forms $forms," \
    "aliases ${ATLAS_LLM_EXTRACT_ALIAS:-atlas-extract}/${ATLAS_LLM_REFLECT_ALIAS:-atlas-reflect}" \
    "$([[ "$stop" == 1 ]] && echo '(stopping before LLM-backed calls)')"
  if [[ "$stop" == 0 && "$yes" == 0 && "$dry" == 0 ]]; then
    answer=""
    read -r -p "This spends MiniMax quota (profile $profile). Continue? [y/N] " answer || true
    [[ "$answer" == [yY]* ]] || die "not confirmed; nothing was run"
  fi

  teardown() {
    [[ "$down" == 1 ]] || return 0
    say "tearing down the Hindsight containers"
    case "$stack" in
      compose)
        run docker compose --profile hindsight stop hindsight hindsight-db
        run docker compose --profile hindsight rm -f hindsight hindsight-db
        if [[ "$purge" == 1 ]]; then run docker volume rm atlas_hindsight-db; fi
        ;;
      spike)
        if [[ "$purge" == 1 ]]; then
          run docker compose -f spikes/hindsight/compose.yaml down -v
        else
          run docker compose -f spikes/hindsight/compose.yaml down
        fi
        ;;
      none|cluster) ;;
    esac
  }
  trap teardown EXIT

  case "$stack" in
    compose) run docker compose --profile hindsight up -d hindsight ;;
    spike) run spikes/hindsight/run.sh "$model" "$ATLAS_HINDSIGHT_LLM_EXTRA_BODY" ;;
    none|cluster) ;;
  esac

  # A container just started needs a while; the suite's preflight has the last word.
  if [[ "$dry" == 0 && "$stack" != none && "$stack" != cluster ]]; then
    say "waiting up to 3 min for $ATLAS_LIVE_HINDSIGHT_URL/health"
    for _ in $(seq 60); do
      if curl -fsS "$ATLAS_LIVE_HINDSIGHT_URL/health" 2>/dev/null | grep -q healthy; then break; fi
      sleep 3
    done
  fi
fi

say "running the suite ($mode); results in $results"
suite=(uv run pytest -m live tests/live/test_phase2_gate_live.py -v -rA
  --junitxml "$ATLAS_LIVE_RESULTS_DIR/junit.xml" "${pytest_args[@]}")
status=0
if [[ "$dry" == 1 ]]; then
  run "${suite[@]}"
else
  mkdir -p "$ATLAS_LIVE_RESULTS_DIR"
  printf '+ %s\n' "${suite[*]}"
  set +e
  "${suite[@]}" 2>&1 | tee "$ATLAS_LIVE_RESULTS_DIR/pytest.log"
  status="${PIPESTATUS[0]}"
  set -e
fi

if [[ "$dry" == 1 ]]; then
  say "dry run: nothing was started or run"
  exit 0
fi
case "$status" in
  0) say "suite passed" ;;
  4) say "suite REFUSED by its preflight (see above); nothing was sent to a model" ;;
  *) say "suite FAILED (pytest exit $status)" ;;
esac
say "results: $results/{summary.md,results.json,junit.xml,pytest.log}"
if [[ "$mode" == live && "$status" != 4 ]]; then
  say "record the run: copy summary.md's facts into docs/implementation-log.md"
fi
exit "$status"
