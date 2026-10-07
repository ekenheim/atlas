#!/usr/bin/env bash
# The memory conformance check (memory-quality ticket 14): does Memory work as Hindsight's
# documentation and Atlas's spec promise, on our settings? Run it before any benchmark or pilot
# run; the release runs it --strict. See docs/runbooks.md, "Memory conformance".
#
#   scripts/memory-conformance.sh [options] [-- extra pytest args]
#
# Two halves, one report (results.json, summary.md; exit 1 when a behaviour fails):
#   known-answers  read-only on the live bank through a running Atlas's /api/v1: the answers
#                  of configs/memory/known-answers.yaml resolved, the five pilot questions
#                  recalled; recall at 10 and 50 per question, hop and test part. No LLM call.
#   behaviours     a throwaway bank (atlas-conformance-<random>) on the real Hindsight, retained
#                  through Atlas's real path from the recorded fixtures, ten checks, the bank
#                  always deleted. Hard caps through counting proxies: 10 retain operations and
#                  6 reflect/refresh/consolidation requests. Hindsight's own extraction of the
#                  19 sections (the owner's MiniMax) is the main cost; the report gives it.
#
#   --only PART      known-answers or behaviours (default: both)
#   --strict         a pending check (its ticket not merged yet) fails the run
#   --rehearse       everything against the fakes on localhost (what CI runs): no .env, no
#                    network beyond localhost, no quota
#   --base-url URL   the Atlas whose bank the known answers are read from (default production,
#                    https://atlas.ekenhome.se)
#   --recall-max-tokens N[,N...]
#                    the results budget (tokens) of the known answers' recalls; repeatable or
#                    comma-separated, the first decides the verdict (default: 8192, the
#                    investigations' setting, and 16000; recall at 10 and 50 per value)
#   --results DIR   where to write the report (default .scratch/live-runs/<UTC stamp>-memory-conformance)
#   --yes            don't ask before a live run
#   --dry-run        print what would run, and run nothing
#
# The live behaviours half reads Hindsight's URL and key from the environment
# (ATLAS_LIVE_HINDSIGHT_URL/_API_KEY), else HINDSIGHT_URL/HINDSIGHT_API_KEY in .env, else
# ~/.hindsight/config (never printed).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

mode=live only="" strict=0 yes=0 dry=0 results="" base_url="" recall_tokens=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --only) only="${2:?--only needs known-answers or behaviours}"; shift ;;
    --strict) strict=1 ;;
    --rehearse) mode=rehearse ;;
    --base-url) base_url="${2:?--base-url needs a URL}"; shift ;;
    --recall-max-tokens)
      value="${2:?--recall-max-tokens needs a number or a comma-separated list}"
      [[ "$value" =~ ^[0-9]+(,[0-9]+)*$ ]] || { echo "memory-conformance: --recall-max-tokens takes numbers" >&2; exit 2; }
      recall_tokens="${recall_tokens:+$recall_tokens,}$value"; shift ;;
    --results) results="${2:?--results needs a directory}"; shift ;;
    --yes) yes=1 ;;
    --dry-run) dry=1 ;;
    --) shift; break ;;
    -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
    *) echo "memory-conformance: unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
pytest_args=("$@")

say() { printf '==> %s\n' "$*"; }
die() { printf 'memory-conformance: %s\n' "$*" >&2; exit 2; }

case "$only" in ""|known-answers|behaviours) ;; *) die "--only must be known-answers or behaviours" ;; esac
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
suffix="$([[ "$mode" == live ]] && echo memory-conformance || echo memory-conformance-rehearse)"
results="${results:-.scratch/live-runs/$stamp-$suffix}"
export ATLAS_CONFORMANCE_RESULTS_DIR="$root/$results"
[[ "$results" == /* ]] && export ATLAS_CONFORMANCE_RESULTS_DIR="$results"
export ATLAS_CONFORMANCE_STRICT="$strict"
export ATLAS_CONFORMANCE_PARTS="${only:-known-answers,behaviours}"

if [[ "$mode" == rehearse ]]; then
  # The rehearsal is the CI test: both halves against the fakes on one throwaway Atlas.
  suite=(uv run pytest tests/integration/test_memory_conformance.py -v -rA
    -k "rehearsal_passes" "${pytest_args[@]}")
else
  [[ -n "${CI:-}" ]] && die "CI is set: the live conformance check never runs in CI"
  export ATLAS_LIVE_TESTS=1
  [[ -n "$base_url" ]] && export ATLAS_CONFORMANCE_BASE_URL="${base_url%/}"
  [[ -n "$recall_tokens" ]] && export ATLAS_CONFORMANCE_RECALL_MAX_TOKENS="$recall_tokens"
  if [[ ",$ATLAS_CONFORMANCE_PARTS," == *",behaviours,"* ]]; then
    hs_url="${ATLAS_LIVE_HINDSIGHT_URL:-}" hs_key="${ATLAS_LIVE_HINDSIGHT_API_KEY:-}"
    if [[ -z "$hs_url" && -f .env ]]; then
      while IFS='=' read -r key value || [[ -n "$key" ]]; do
        key="${key//$'\r'/}"; value="${value//$'\r'/}"; value="${value%\"}"; value="${value#\"}"
        case "$key" in
          HINDSIGHT_URL) hs_url="$value" ;;
          HINDSIGHT_API_KEY) hs_key="$value" ;;
        esac
      done < .env
    fi
    if [[ -z "$hs_url" && -f "$HOME/.hindsight/config" ]]; then
      read -r hs_url hs_key < <(python3 -c 'import tomllib,pathlib;c=tomllib.loads(pathlib.Path.home().joinpath(".hindsight/config").read_text());print(c.get("api_url",""),c.get("api_key",""))')
    fi
    [[ -n "$hs_url" ]] || die "no Hindsight: set ATLAS_LIVE_HINDSIGHT_URL, HINDSIGHT_URL in .env or ~/.hindsight/config"
    export ATLAS_LIVE_HINDSIGHT_URL="${hs_url%/}" ATLAS_LIVE_HINDSIGHT_API_KEY="$hs_key"
    # The app database for the throwaway Atlas: start the Compose Postgres only if nothing
    # answers on its port.
    if ! (exec 3<>/dev/tcp/127.0.0.1/55432) 2>/dev/null; then
      if [[ "$dry" == 1 ]]; then echo "+ docker compose up -d --wait postgres-app"
      else docker compose up -d --wait postgres-app; fi
    fi
  fi
  say "live run: $ATLAS_CONFORMANCE_PARTS; Atlas ${ATLAS_CONFORMANCE_BASE_URL:-https://atlas.ekenhome.se}; Hindsight ${ATLAS_LIVE_HINDSIGHT_URL:-not used}"
  if [[ "$yes" == 0 && "$dry" == 0 && ",$ATLAS_CONFORMANCE_PARTS," == *",behaviours,"* ]]; then
    answer=""
    read -r -p "The behaviours half retains 19 sections into a throwaway bank (Hindsight extracts them on the owner's quota; at most 10 retain operations and 6 reflect/refresh/consolidation requests). Continue? [y/N] " answer || true
    [[ "$answer" == [yY]* ]] || die "not confirmed; nothing was run"
  fi
  suite=(uv run pytest -m live tests/live/test_memory_conformance_live.py -v -rA "${pytest_args[@]}")
fi

say "running the conformance check ($mode); report in $results"
if [[ "$dry" == 1 ]]; then
  printf '+ %s\n' "${suite[*]}"
  say "dry run: nothing was run"
  exit 0
fi
mkdir -p "$ATLAS_CONFORMANCE_RESULTS_DIR"
printf '+ %s\n' "${suite[*]}"
set +e
"${suite[@]}" 2>&1 | tee "$ATLAS_CONFORMANCE_RESULTS_DIR/pytest.log"
status="${PIPESTATUS[0]}"
set -e
case "$status" in
  0) say "conformance passed$([[ "$strict" == 1 ]] && echo ' (strict)')" ;;
  *) status=1; say "conformance FAILED: see $results/summary.md" ;;
esac
say "report: $results/{summary.md,results.json,pytest.log}"
[[ "$mode" == live ]] && say "record the run: copy summary.md's tables into docs/implementation-log.md as LIVE"
exit "$status"
