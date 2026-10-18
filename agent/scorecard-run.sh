#!/usr/bin/env bash
# One run of the early-call scorecard (atlas-beliefs ticket 29b): the next entry of
# `agent/scorecard/runs.json` that has not been run yet, as an isolated Researcher session.
#
#   scorecard-run.sh [--dry-run]
#
# The run list is frozen in the image (case, company slug, as-of time, the protocol's question; no
# key, no outcome, no price). Atlas is asked which entries have been run: an entry is run when
# Atlas holds an isolated session with the same question, as-of time (as an instant) and seed
# company that has recorded at least one tool call. While an isolated session of theme `scorecard`
# is still open (not closed) and started less than 6 hours ago, this prints
# {"scorecard":"busy",...} and exits 0 without running anything. Otherwise it picks the first
# entry not run, and hands it to `run.sh researcher` with
# ATLAS_AGENT_THEME=scorecard, ATLAS_AGENT_QUESTION, ATLAS_AGENT_SEEDS (the slug),
# ATLAS_AGENT_AS_OF and ATLAS_AGENT_ISOLATED=true; run.sh opens the session itself. A run that
# failed after its session recorded a call still counts as run (its session exists) and is flagged by
# scripts/scorecard.py, not retried. Nothing left: prints {"scorecard":"done"} and exits 0.
#
# Environment:
#   CLAUDE_CODE_OAUTH_TOKEN   as for run.sh (not needed by --dry-run)
#   ATLAS_MCP_URL             the MCP endpoint, as for run.sh; the API is the same address without /mcp
#   ATLAS_AGENT_MODEL         the exact model ID (default claude-opus-5-5): an alias such as `opus`
#                             is refused, since the frozen configuration names the exact ID
#   ATLAS_SCORECARD_RUNS      the run list (default: scorecard/runs.json beside this script)
#   the rest of run.sh's settings (ATLAS_AGENT_TMP, ATLAS_AGENT_MAX_TURNS, ...) pass through
#
# --dry-run lists Atlas's sessions (reads only) to pick the entry, then passes --dry-run to
# run.sh, which calls nothing. Atlas unreachable: exits non-zero, runs nothing.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "usage: scorecard-run.sh [--dry-run]" >&2
  exit "${1:-2}"
}

die() {
  echo "scorecard-run.sh: $*" >&2
  exit 2
}

pass=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) pass+=(--dry-run) ;;
    -h | --help) usage 0 ;;
    *) usage ;;
  esac
done

model="${ATLAS_AGENT_MODEL:-claude-opus-5-5}"
mcp_url="${ATLAS_MCP_URL:-http://atlas.development.svc.cluster.local:8000/mcp}"
runs_file="${ATLAS_SCORECARD_RUNS:-$here/scorecard/runs.json}"

# The exact ID, never an alias: `claude-<family>-<version>` with dash-separated numbers.
model_re='^claude-[a-z]+(-[0-9]+)+$'
[[ "$model" =~ $model_re ]] \
  || die "ATLAS_AGENT_MODEL must be the exact model ID, like claude-opus-5-5, not an alias: $model"
url_re='^https?://[^[:space:]"\\]+$'
[[ "$mcp_url" =~ $url_re ]] || die "ATLAS_MCP_URL is not an http(s) URL: $mcp_url"
[[ -f "$runs_file" ]] || die "no run list: $runs_file"
command -v node >/dev/null 2>&1 || die "node is not installed"

# Which entry is next: the first with no isolated session for its question, as-of time and seed.
pick_js='
const fs = require("fs");
const [mcpUrl, runsFile] = process.argv.slice(1);
const rowsOf = (body) => (Array.isArray(body) ? body : Array.isArray(body && body.items) ? body.items : []);
const get = async (base, path) => {
  const answer = await fetch(base + path, { signal: AbortSignal.timeout(30000) });
  if (!answer.ok) throw new Error(path + " answered " + answer.status);
  return answer.json();
};
(async () => {
  const runs = JSON.parse(fs.readFileSync(runsFile, "utf8"));
  if (!Array.isArray(runs) || runs.length === 0) throw new Error("the run list is empty");
  const base = String(mcpUrl).replace(/\/mcp\/?$/, "");
  const companies = rowsOf(await get(base, "/api/v1/companies?limit=500"));
  const sessions = [];
  for (let offset = 0; ; ) {
    const page = await get(base, "/api/v1/sessions?limit=500&offset=" + offset);
    const items = rowsOf(page);
    sessions.push(...items);
    offset += items.length;
    if (items.length === 0 || offset >= Number(page.total || 0)) break;
  }
  const isolated = sessions.filter((each) => each && each.isolated === true);
  // One run at a time: an isolated scorecard session still open (not closed) and started less
  // than six hours ago is a run in flight, or one that died without closing; either way this
  // firing waits rather than overlap it (two runs share one subscription window and one pod
  // log, and a second run read while the first is open is not a clean replay).
  const sixHours = 6 * 60 * 60 * 1000;
  const open = isolated.find(
    (each) =>
      each.theme === "scorecard" &&
      !each.finished_at &&
      Date.now() - Date.parse(each.started_at) < sixHours,
  );
  if (open) {
    process.stdout.write(
      JSON.stringify({ busy: true, line: { scorecard: "busy", session: open.id, started_at: open.started_at } }) + "\n",
    );
    return;
  }
  // An entry is run once its isolated session has recorded a tool call: a POST that timed out
  // after Atlas created the session, with no call after it, has not spent the entry.
  const ran = isolated.filter((each) => Number(each.tool_calls || 0) >= 1);
  for (const entry of runs) {
    const company = companies.find((each) => each && each.slug === entry.company);
    if (!company) throw new Error("the run list names a company Atlas does not have: " + entry.company);
    const want = Date.parse(entry.as_of);
    if (Number.isNaN(want)) throw new Error("not a time: " + entry.as_of);
    const done = ran.some(
      (each) =>
        String(each.question || "") === entry.question &&
        Date.parse(each.as_of) === want &&
        (each.seed_company_ids || []).map(String).sort().join(",") === String(company.id),
    );
    if (!done) {
      process.stdout.write(JSON.stringify(entry) + "\n");
      return;
    }
  }
  process.stdout.write(JSON.stringify({ done: true }) + "\n");
})().catch((error) => {
  process.stderr.write("scorecard-run.sh: Atlas could not be asked which runs are done: " + (error && error.message ? error.message : String(error)) + "\n");
  process.exit(1);
});
'
picked="$(node -e "$pick_js" "$mcp_url" "$runs_file")"

# The entry is read back through node (no jq in the image); each field is checked before it is
# used as an environment value.
field() { node -e 'const e = JSON.parse(process.argv[1]); process.stdout.write(String(e[process.argv[2]] ?? ""));' "$picked" "$1"; }

if [[ "$(field busy)" == true ]]; then
  node -e 'process.stdout.write(JSON.stringify(JSON.parse(process.argv[1]).line) + "\n")' "$picked"
  exit 0
fi
if [[ "$(field done)" == true ]]; then
  echo '{"scorecard":"done"}'
  exit 0
fi

case_id="$(field "case")"
company="$(field company)"
as_of="$(field as_of)"
question="$(field question)"
[[ "$company" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "the run list has a bad company slug: $company"
echo "scorecard-run.sh: running $case_id ($company) as of $as_of on $model" >&2

export ATLAS_AGENT_THEME=scorecard
export ATLAS_AGENT_QUESTION="$question"
export ATLAS_AGENT_SEEDS="$company"
export ATLAS_AGENT_AS_OF="$as_of"
export ATLAS_AGENT_ISOLATED=true
export ATLAS_AGENT_MODEL="$model"
export ATLAS_MCP_URL="$mcp_url"
exec "$here/run.sh" researcher ${pass[@]+"${pass[@]}"}
