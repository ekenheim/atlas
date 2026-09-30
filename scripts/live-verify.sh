#!/usr/bin/env bash
# Live verification of every Phase 3-6a part (tests/live/test_live_verify.py, ticket 32): SEC
# ingest with triage, retain, recall and reflect; the FCA NSM and AMF through the fetch gate;
# TradingView (once ticket 31 lands); discovery and Candidates; Claims into Relationships; an
# investigation to a Hypothesis, a scenario and publish; entity resolution. One throwaway app
# database and archive, one throwaway Hindsight bank (deleted at the end unless --keep-bank).
# Never run in CI. See docs/runbooks.md, "Live verification".
#
#   scripts/live-verify.sh [options] [-- extra pytest args]
#
# A live run SPENDS MINIMAX QUOTA and calls SEC, GLEIF, OpenFIGI, the FCA NSM, the AMF and
# SearXNG; it asks for confirmation unless --yes. Hard caps: at most 40 MiniMax chat
# completions and 25 Hindsight retain operations per run, each part within its own budget
# (a part asking for more is aborted); the report says what each part used.
#   --only PART          run only these parts (repeatable or comma-separated): sec, exchanges,
#                        tradingview, discovery, relationships, investigation, identity
#   --rehearse           every part against the fakes on localhost instead: no .env, no
#                        network beyond localhost, no quota (the harness's own check)
#   --companies A,B      the sec part's companies (default lumentum,coherent,axt,
#                        applied-optoelectronics)
#   --limit N            recent filings per company in the sec part (default 2)
#   --max-chat-calls N   a lower run cap on MiniMax chat completions (at most 40)
#   --stack S            cluster (default): the owner's cluster Hindsight (HINDSIGHT_URL/
#                        HINDSIGHT_API_KEY in .env, else ~/.hindsight/config)
#                        compose: the Compose `hindsight` profile on :58888 (started if needed)
#                        none: the Hindsight at ATLAS_LIVE_HINDSIGHT_URL as it is
#   --model M            the model the research roles ask LiteLLM for, and Atlas's extract and
#                        reflect aliases (default MiniMax-M3)
#   --keep-db            keep the run's app database (atlas_live_*) for inspection
#   --keep-bank          keep the run's throwaway Hindsight bank
#   --results DIR        where to write the report (default .scratch/live-runs/<UTC stamp>-verify)
#   --yes                don't ask before a live run
#   --dry-run            print what would run, and run nothing
#
# Settings are read from the environment, else the repo .env (CRLF-safe, never printed):
# LiteLLM (ATLAS_LITELLM_URL/_API_KEY or LITELLM_URL/_API_KEY; required), SEC's contact
# (ATLAS_SEC_USER_AGENT; the sec, discovery and identity parts), SearXNG (ATLAS_SEARXNG_URL or
# SEARXNG_URL; discovery and investigation skip without it), ATLAS_EXCHANGE_USER_AGENT
# (generic, default AtlasResearch) and ticket 31's ATLAS_TRADINGVIEW_* settings.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

all_parts="sec,exchanges,tradingview,discovery,relationships,investigation,identity"
mode=live stack=cluster model="MiniMax-M3" keep=0 yes=0 dry=0 results="" only=""
companies="" limit="" max_chat=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --only) only="${only:+$only,}${2:?--only needs a part}"; shift ;;
    --rehearse) mode=rehearse ;;
    --companies) companies="${2:?--companies needs slugs}"; shift ;;
    --limit) limit="${2:?--limit needs a number}"; shift ;;
    --max-chat-calls) max_chat="${2:?--max-chat-calls needs a number}"; shift ;;
    --stack) stack="${2:?--stack needs cluster, compose or none}"; shift ;;
    --model) model="${2:?--model needs a model name}"; shift ;;
    --keep-db) keep=1 ;;
    --keep-bank) export ATLAS_LIVE_KEEP_BANK=1 ;;
    --results) results="${2:?--results needs a directory}"; shift ;;
    --yes) yes=1 ;;
    --dry-run) dry=1 ;;
    --) shift; break ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "live-verify: unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
pytest_args=("$@")

say() { printf '==> %s\n' "$*"; }
die() { printf 'live-verify: %s\n' "$*" >&2; exit 2; }

[[ -n "${CI:-}" ]] && die "CI is set: the live verification never runs in CI"
case "$stack" in cluster|compose|none) ;; *) die "--stack must be cluster, compose or none" ;; esac
parts="${only:-$all_parts}"
IFS=',' read -r -a chosen <<< "$parts"
for part in "${chosen[@]}"; do
  [[ ",$all_parts," == *",$part,"* ]] || die "unknown part $part (choose from $all_parts)"
done
[[ -z "$limit" || "$limit" =~ ^[1-9][0-9]*$ ]] || die "--limit must be a positive number"
[[ -z "$max_chat" || "$max_chat" =~ ^[0-9]+$ ]] || die "--max-chat-calls must be a number"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
suffix="$([[ "$mode" == live ]] && echo verify || echo verify-rehearse)"
results="${results:-.scratch/live-runs/$stamp-$suffix}"
export ATLAS_LIVE_TESTS="$([[ "$mode" == live ]] && echo 1 || echo rehearse)"
export ATLAS_LIVE_RESULTS_DIR="$root/$results"
[[ "$results" == /* ]] && export ATLAS_LIVE_RESULTS_DIR="$results"
export ATLAS_LIVE_VERIFY_PARTS="$parts"
[[ -n "$companies" ]] && export ATLAS_LIVE_VERIFY_COMPANIES="$companies"
[[ -n "$limit" ]] && export ATLAS_LIVE_VERIFY_LIMIT="$limit"
[[ -n "$max_chat" ]] && export ATLAS_LIVE_VERIFY_MAX_CHAT_CALLS="$max_chat"
[[ "$keep" == 1 ]] && export ATLAS_LIVE_KEEP_DATABASE=1
export ATLAS_LLM_ROLE_MODEL="$model"

# The app database: start the Compose Postgres only if nothing answers on its port.
if ! (exec 3<>/dev/tcp/127.0.0.1/55432) 2>/dev/null; then
  if [[ "$dry" == 1 ]]; then
    echo "+ docker compose up -d --wait postgres-app"
  else
    docker compose up -d --wait postgres-app
  fi
fi

if [[ "$mode" == live ]]; then
  # The ATLAS_* names in the environment win; otherwise .env's (both spellings, CRLF-safe).
  hs_url_env="" hs_key_env=""
  if [[ -f .env ]]; then
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
      key="${key//$'\r'/}"; value="${value//$'\r'/}"
      value="${value%\"}"; value="${value#\"}"
      case "$key" in
        LITELLM_URL|ATLAS_LITELLM_URL) : "${ATLAS_LITELLM_URL:=$value}" ;;
        LITELLM_API_KEY|ATLAS_LITELLM_API_KEY) : "${ATLAS_LITELLM_API_KEY:=$value}" ;;
        HINDSIGHT_URL) hs_url_env="$value" ;;
        HINDSIGHT_API_KEY) hs_key_env="$value" ;;
        ATLAS_SEC_USER_AGENT) : "${ATLAS_SEC_USER_AGENT:=$value}" ;;
        SEARXNG_URL|ATLAS_SEARXNG_URL) : "${ATLAS_SEARXNG_URL:=$value}" ;;
        ATLAS_EXCHANGE_USER_AGENT) : "${ATLAS_EXCHANGE_USER_AGENT:=$value}" ;;
        ATLAS_TRADINGVIEW_*) [[ -n "${!key:-}" ]] || export "$key=$value" ;;
      esac
    done < .env
  fi
  [[ -n "${ATLAS_LITELLM_URL:-}" && -n "${ATLAS_LITELLM_API_KEY:-}" ]] \
    || die "no LiteLLM settings: set ATLAS_LITELLM_URL/ATLAS_LITELLM_API_KEY or LITELLM_* in .env"
  export ATLAS_LITELLM_URL="${ATLAS_LITELLM_URL%/}" ATLAS_LITELLM_API_KEY
  : "${ATLAS_LLM_EXTRACT_ALIAS:=$model}" "${ATLAS_LLM_REFLECT_ALIAS:=$model}"
  export ATLAS_LLM_EXTRACT_ALIAS ATLAS_LLM_REFLECT_ALIAS
  [[ -n "${ATLAS_SEC_USER_AGENT:-}" ]] && export ATLAS_SEC_USER_AGENT
  [[ -n "${ATLAS_SEARXNG_URL:-}" ]] && export ATLAS_SEARXNG_URL="${ATLAS_SEARXNG_URL%/}"
  [[ -n "${ATLAS_EXCHANGE_USER_AGENT:-}" ]] && export ATLAS_EXCHANGE_USER_AGENT
  for part in sec discovery identity; do
    if [[ ",$parts," == *",$part,"* && -z "${ATLAS_SEC_USER_AGENT:-}" ]]; then
      die "the $part part calls SEC: set ATLAS_SEC_USER_AGENT (name and contact email) in .env"
    fi
  done

  case "$stack" in
    cluster)
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
    compose) export ATLAS_LIVE_HINDSIGHT_URL="http://127.0.0.1:${ATLAS_HINDSIGHT_PORT:-58888}" ;;
    none) [[ -n "${ATLAS_LIVE_HINDSIGHT_URL:-}" ]] || die "--stack none needs ATLAS_LIVE_HINDSIGHT_URL" ;;
  esac

  say "live run: parts $parts; Hindsight $ATLAS_LIVE_HINDSIGHT_URL ($stack); model $model;" \
    "SearXNG $([[ -n "${ATLAS_SEARXNG_URL:-}" ]] && echo configured || echo 'not configured (discovery, investigation skip)')"
  if [[ "$yes" == 0 && "$dry" == 0 ]]; then
    answer=""
    read -r -p "This spends MiniMax quota (at most ${max_chat:-40} chat completions, 25 retains) and calls live sources. Continue? [y/N] " answer || true
    [[ "$answer" == [yY]* ]] || die "not confirmed; nothing was run"
  fi
  if [[ "$stack" == compose && "$dry" == 0 ]]; then
    docker compose --profile hindsight up -d hindsight
    say "waiting up to 3 min for $ATLAS_LIVE_HINDSIGHT_URL/health"
    for _ in $(seq 60); do
      if curl -fsS "$ATLAS_LIVE_HINDSIGHT_URL/health" 2>/dev/null | grep -q healthy; then break; fi
      sleep 3
    done
  fi
fi

say "running the verification ($mode); report in $results"
suite=(uv run pytest -m live tests/live/test_live_verify.py -v -rA
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
  0) say "verification passed (skipped parts say why in the report)" ;;
  4) say "verification REFUSED by its preflight (see above); nothing was sent to a model" ;;
  *) say "verification FAILED (pytest exit $status): see the report's table" ;;
esac
say "report: $results/{summary.md,results.json,junit.xml,pytest.log}"
if [[ "$mode" == live && "$status" != 4 ]]; then
  say "record the run: copy summary.md's table into docs/implementation-log.md as LIVE"
fi
exit "$status"
