#!/usr/bin/env bash
# One scheduled agent run (atlas-beliefs ticket 17): headless Claude Code on the owner's
# subscription, against Atlas's MCP server.
#
#   run.sh <scout|researcher|skeptic> [--dry-run]
#
# Environment:
#   CLAUDE_CODE_OAUTH_TOKEN   required (not for --dry-run): the owner's `claude setup-token` token.
#                             Claude Code reads it from the environment; it is never put on a
#                             command line, in a file, or in any output (output is redacted).
#   ATLAS_MCP_URL             the MCP endpoint (default: the in-cluster service)
#   ATLAS_AGENT_THEME         the theme (default photonics)
#   ATLAS_AGENT_MODEL         the model alias or name (default opus)
#   ATLAS_AGENT_MAX_TURNS     the turn bound (default per agent)
#   ATLAS_AGENT_CALL_BOUND    the tool-call bound the prompt gives (default per agent)
#   ATLAS_AGENT_AS_OF         the as-of time, ISO with offset (default: now, UTC)
#   ATLAS_AGENT_QUESTION      (researcher only) the question, verbatim: overrides `next_issue`
#   ATLAS_AGENT_SEEDS         (researcher only) seed company slugs, comma-separated; needs the
#                             question
#   ATLAS_AGENT_ISOLATED      (researcher only) `true`: run.sh itself opens an isolated Atlas
#                             session (`POST /api/v1/sessions` with `isolated: true`, the theme,
#                             the question, the seeds, the as-of time and the model; the run
#                             fails if it cannot) BEFORE claude starts, and gives the Researcher
#                             its id; `open_session` is not among its tools, so it cannot leave
#                             isolation (ticket 29b). Needs the question. Default false. The
#                             early-call scorecard's runs (ticket 29): `agent/scorecard-run.sh`
#                             passes all of it and the exact model ID in ATLAS_AGENT_MODEL
#   ATLAS_AGENT_TMP           the writable directory (default /tmp): the output folder is
#                             $ATLAS_AGENT_TMP/out, the MCP config $ATLAS_AGENT_TMP/atlas-mcp.json
#
# Prints one JSON line to stdout (agent, session id, the Atlas session id, turns, cost, duration,
# started_at and finished_at in UTC, the first 2,000 characters of the result) for the pod log;
# exits non-zero when the run failed. --dry-run prints the command, the MCP config and the
# prompt, and calls nothing (no network: an isolated run shows a placeholder for the session id).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"

usage() {
  echo "usage: run.sh <scout|researcher|skeptic> [--dry-run]" >&2
  exit "${1:-2}"
}

agent=""
dry_run=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    -h | --help) usage 0 ;;
    scout | researcher | skeptic)
      [[ -z "$agent" ]] || usage
      agent="$arg"
      ;;
    *) usage ;;
  esac
done
[[ -n "$agent" ]] || usage

die() {
  echo "run.sh: $*" >&2
  exit 2
}

# Per agent: the turn bound (a turn is one model step; a tool call is at most one per step in
# the worst case, and the files are written at the end) and the call bound each skill prompt
# is written for (scout.md 60, SKILL.md about 150, skeptic.md 80).
case "$agent" in
  scout)
    default_turns=100
    default_calls=60
    ;;
  researcher)
    default_turns=230
    default_calls=150
    ;;
  skeptic)
    default_turns=140
    default_calls=80
    ;;
esac

mcp_url="${ATLAS_MCP_URL:-http://atlas.development.svc.cluster.local:8000/mcp}"
theme="${ATLAS_AGENT_THEME:-photonics}"
model="${ATLAS_AGENT_MODEL:-opus}"
max_turns="${ATLAS_AGENT_MAX_TURNS:-$default_turns}"
call_bound="${ATLAS_AGENT_CALL_BOUND:-$default_calls}"
tmp_dir="${ATLAS_AGENT_TMP:-/tmp}"
out_dir="$tmp_dir/out"
mcp_config="$tmp_dir/atlas-mcp.json"
as_of="${ATLAS_AGENT_AS_OF:-$(date -u +%Y-%m-%dT%H:%M:%S+00:00)}"
question="${ATLAS_AGENT_QUESTION:-}"
seeds="${ATLAS_AGENT_SEEDS:-}"
isolated="${ATLAS_AGENT_ISOLATED:-false}"

# What goes into the prompt and the JSON file is checked, not escaped.
url_re='^https?://[^[:space:]"\\]+$'
[[ "$mcp_url" =~ $url_re ]] || die "ATLAS_MCP_URL is not an http(s) URL: $mcp_url"
tmp_re='^([A-Za-z]:)?/[A-Za-z0-9._/-]+$'
[[ "$tmp_dir" =~ $tmp_re ]] || die "ATLAS_AGENT_TMP is not an absolute path of plain characters: $tmp_dir"
[[ "$theme" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "ATLAS_AGENT_THEME is not a theme slug: $theme"
model_re='^[][A-Za-z0-9._:-]+$'
[[ "$model" =~ $model_re ]] || die "ATLAS_AGENT_MODEL has characters a model name does not: $model"
[[ "$max_turns" =~ ^[1-9][0-9]*$ ]] || die "ATLAS_AGENT_MAX_TURNS is not a positive integer: $max_turns"
[[ "$call_bound" =~ ^[1-9][0-9]*$ ]] || die "ATLAS_AGENT_CALL_BOUND is not a positive integer: $call_bound"
[[ "$as_of" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([+-][0-9]{2}:[0-9]{2}|Z)$ ]] \
  || die "ATLAS_AGENT_AS_OF is not an ISO time with an offset: $as_of"

# The question goes into the prompt as text (never a shell word or JSON), so it is checked for
# length and for control characters; seeds and the isolation flag must fit what they name.
[[ "$isolated" == true || "$isolated" == false ]] || die "ATLAS_AGENT_ISOLATED is not true or false: $isolated"
if [[ -n "$question" || -n "$seeds" || "$isolated" == true ]]; then
  [[ "$agent" == researcher ]] \
    || die "ATLAS_AGENT_QUESTION, ATLAS_AGENT_SEEDS and ATLAS_AGENT_ISOLATED are the researcher's"
fi
[[ "$isolated" == false || -n "$question" ]] || die "ATLAS_AGENT_ISOLATED needs ATLAS_AGENT_QUESTION"
if [[ -n "$seeds" ]]; then
  [[ -n "$question" ]] || die "ATLAS_AGENT_SEEDS needs ATLAS_AGENT_QUESTION"
  seeds_re='^[a-z0-9][a-z0-9-]*(,[a-z0-9][a-z0-9-]*)*$'
  [[ "$seeds" =~ $seeds_re ]] || die "ATLAS_AGENT_SEEDS is not comma-separated company slugs: $seeds"
fi
if [[ -n "$question" ]]; then
  [[ ${#question} -le 1000 ]] || die "ATLAS_AGENT_QUESTION is over 1,000 characters"
  control_re='[[:cntrl:]]'
  [[ ! "$question" =~ $control_re ]] || die "ATLAS_AGENT_QUESTION has a control character or a newline"
fi

prompt_file="$here/prompts/$agent.md"
[[ -f "$prompt_file" ]] || die "no prompt for $agent: $prompt_file"
prompt="$(cat "$prompt_file")"
prompt="${prompt//'{{THEME}}'/$theme}"
prompt="${prompt//'{{AS_OF}}'/$as_of}"
prompt="${prompt//'{{OUT_DIR}}'/$out_dir}"
prompt="${prompt//'{{CALL_BOUND}}'/$call_bound}"

# The researcher's inputs (a wrapper without these placeholders is unchanged): the frontier's
# question by default; the lead's question and seeds when given; an isolated session when asked.
# The check for a placeholder nothing fills runs before the question is put in, so a question
# that happens to hold braces is no placeholder; the question is quoted in the replacement so a
# `&` in it is no back-reference.
question_block="Question: none is given. Start from \`next_issue\` (\`theme\`: $theme): Atlas's frontier. Use the title of the Issue it returns as the question, verbatim. If it returns no Issue, write \`researcher-report.md\` in the output folder saying so, open no session, and stop."
seeds_block="Seed companies: the companies the Issue names (slugs); if it names none, choose at most three with \`companies\` by the layer the question names."
start_block="Start: after \`open_session\`, call \`prior_work\` and follow \`SKILL.md\`'s \"Start from what Atlas holds\": spend your calls on documents public after its \`latest_session_as_of\` and on the gaps earlier sessions named, and cite an existing Fact rather than recording its span again. Call \`examine_belief\` for a Belief you tested."
recall_block="Recall: allowed. \`recall\` with \`bank: research\` is an index to find sections to \`read\`, never evidence. \`recall\` with \`bank: beliefs\` is in use: it returns earlier sessions' judged conclusions and the Facts they rest on; test one against what you read and never cite it."
isolation_block=""
if [[ -n "$question" ]]; then
  question_block="Question (given by the lead; use it verbatim and do not call \`next_issue\`): {{QUESTION_TEXT}}"
  if [[ -n "$seeds" ]]; then
    seeds_block="Seed companies: ${seeds//,/, } (slugs; pass them to \`open_session\` as \`seeds\`)."
  else
    seeds_block="Seed companies: none are given; choose at most three with \`companies\` by the layer the question names."
  fi
fi
# An isolated session is allowed an explicit list of Atlas tools, not the whole server (the
# scorecard's runs, ticket 29a): the Belief, Issue and prior-work tools are not among them, and
# Atlas refuses most of them besides. `open_session` is not among them either (ticket 29b):
# run.sh opens the session itself, so the agent cannot open another, non-isolated, one. The same
# list is the prompt's `Tools:` line and --allowedTools. `off_list` is every other tool of the
# server, named in the prompt (tests/unit/test_agent_run.py checks that the two lists together
# are the server's tools, so a new tool cannot slip through unnamed).
isolated_tools="close_session companies search read locate record_fact get_fact judge_statement relate_facts propose_belief cite_belief recall"
off_list="open_session supersede_belief examine_belief list_beliefs get_belief prior_work open_issue narrow_issue complete_issue next_issue list_issues draft_hypothesis get_hypothesis signal_leads upcoming_reports newest_documents"
# What the prompt shows in the session's place until run.sh has opened it (a dry run never does).
session_ref="<the Atlas session id: run.sh opens it before you start>"
if [[ "$isolated" == true ]]; then
  start_block="Start: this is an isolated session (a replay of a past date) and its Atlas session is already open: its \`session_id\` is $session_ref. Pass that \`session_id\` to every tool call. Do not call \`open_session\` (it is not available to you) and open no other session. Atlas gives an isolated session no prior work and records a Fact for every span you quote, so research from the archive: \`search\`, \`read\`, \`locate\`, \`record_fact\`. When you have written the files, call \`close_session\` with your card."
  off_names=""
  for tool in $off_list; do off_names+="${off_names:+, }\`$tool\`"; done
  recall_block="Recall: allowed for \`bank: research\` only: facts, never observations, an index to find sections to \`read\`, never evidence. Your tools are exactly the ones on the Tools line below. These Atlas tools are not available to you, and any rule above that names one does not apply: $off_names."
  # The wrapper's two lines that tell the agent to pass these to `open_session` say otherwise.
  old_seeds=" (slugs; pass them to \`open_session\` as \`seeds\`)."
  new_seeds=" (slugs; already the session's seeds)."
  seeds_block="${seeds_block//"$old_seeds"/"$new_seeds"}"
  old_as_of="(the start of this run; pass it to \`open_session\` unchanged)"
  new_as_of="(the session's as-of time; the session is already open with it)"
  prompt="${prompt//"$old_as_of"/"$new_as_of"}"
  isolation_block="- Knowledge: use only what the tools return. Do not use anything you know about the company, its market, its prices or the years after the as-of time from outside this session; a statement no Fact you recorded carries is not scored. Every Belief you propose is a proposal for the lead to read, and Atlas will never judge it. Cite only Facts you recorded in this session."
  tools_line="$(grep '^Tools: ' "$prompt_file")"
  prompt="${prompt//"$tools_line"/"Tools: ${isolated_tools// /, }"}"
fi
prompt="${prompt//'{{QUESTION_INPUT}}'/$question_block}"
prompt="${prompt//'{{SEEDS_INPUT}}'/$seeds_block}"
prompt="${prompt//'{{START_INPUT}}'/$start_block}"
prompt="${prompt//'{{RECALL_INPUT}}'/$recall_block}"
prompt="${prompt//'{{ISOLATION_INPUT}}'/$isolation_block}"
[[ "${prompt//'{{QUESTION_TEXT}}'/}" != *'{{'* ]] || die "the $agent prompt has a placeholder nothing fills"
prompt="${prompt//'{{QUESTION_TEXT}}'/"$question"}"

mcp_json="{\"mcpServers\":{\"atlas\":{\"type\":\"http\",\"url\":\"$mcp_url\"}}}"

# --tools limits the built-in tools to the four the routine needs (the MCP tools are the server's
# and unaffected); --allowedTools lets those and every Atlas tool run without a prompt (there is
# nobody to ask, and anything else is refused). `mcp__atlas` allows the whole server, and
# `mcp__atlas__*` is the same in the pattern form. --add-dir lets Write and Edit reach the output
# folder, which is outside the working directory (the read-only /opt/atlas-agent).
allowed=("mcp__atlas" "mcp__atlas__*" Read Write Edit Glob)
if [[ "$isolated" == true ]]; then
  allowed=()
  for tool in $isolated_tools; do allowed+=("mcp__atlas__$tool"); done
  allowed+=(Read Write Edit Glob)
fi
# Built again once an isolated run has the session's id in its prompt.
build_command() {
  cmd=(
    claude -p "$prompt"
    --mcp-config "$mcp_config" --strict-mcp-config
    --tools "Read,Write,Edit,Glob"
    --allowedTools "${allowed[@]}"
    --add-dir "$out_dir"
    --model "$model"
    --max-turns "$max_turns"
    --output-format json
  )
}
build_command

quote() {
  local plain_re='^[A-Za-z0-9_@%+=:,./-]+$'
  local sq="'\\''"
  if [[ "$1" =~ $plain_re ]]; then
    printf '%s' "$1"
  else
    printf "'%s'" "${1//"'"/$sq}"
  fi
}

if [[ "$dry_run" == 1 ]]; then
  printf 'agent: %s\n' "$agent"
  printf 'question: %s\n' "${question:-none (next_issue)}"
  printf 'seeds: %s\n' "${seeds:-none}"
  printf 'isolated: %s\n' "$isolated"
  if [[ "$isolated" == true ]]; then
    atlas_base="${mcp_url%/}"
    atlas_base="${atlas_base%/mcp}"
    printf 'session: run.sh would open it before claude starts (POST %s/api/v1/sessions, isolated, theme %s, actor atlas-%s); the prompt shows a placeholder for its id\n' \
      "$atlas_base" "$theme" "$agent"
  fi
  printf 'command:'
  for word in "${cmd[@]}"; do
    if [[ "$word" == "$prompt" ]]; then printf ' <prompt>'; else printf ' %s' "$(quote "$word")"; fi
  done
  printf '\n'
  printf 'working directory: %s\n' "$root"
  printf 'mcp config (%s): %s\n' "$mcp_config" "$mcp_json"
  if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    printf 'CLAUDE_CODE_OAUTH_TOKEN: set\n'
  else
    printf 'CLAUDE_CODE_OAUTH_TOKEN: not set (a real run needs it)\n'
  fi
  printf 'prompt:\n%s\n' "$prompt"
  exit 0
fi

[[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]] \
  || die "CLAUDE_CODE_OAUTH_TOKEN is not set (docs/runbooks.md, \"Scheduled agents\")"
command -v claude >/dev/null 2>&1 || die "claude is not installed"
command -v node >/dev/null 2>&1 || die "node is not installed"
# The subscription token, not a metered API key, pays for the run.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
# --tools leaves out ToolSearch, so the MCP tools' schemas must be sent up front, never deferred
# behind a search the agent cannot call (Claude Code defers them when their definitions are large).
export ENABLE_TOOL_SEARCH=false

umask 077
mkdir -p "$out_dir"
printf '%s\n' "$mcp_json" >"$mcp_config"

result="$out_dir/claude-result.json"
errors="$out_dir/claude-stderr.txt"
started="$(date +%s)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# An isolated run opens its Atlas session itself, before claude starts (ticket 29b): the agent is
# given the id and has no `open_session`, so it cannot leave isolation by opening another. The
# seed slugs are looked up to ids as the matcher did. If anything fails, claude is never called:
# the one JSON line says why (ok false) and the run exits 1.
open_js='
const [mcpUrl, agent, theme, question, seeds, asOf, model, startedAt] = process.argv.slice(1);
const token = process.env.CLAUDE_CODE_OAUTH_TOKEN || "";
const redact = (text) => (token ? String(text).split(token).join("[redacted]") : String(text));
const fail = (reason) => {
  const line = {
    agent, ok: false, exit_status: null, session_id: null, atlas_session_id: null,
    reason: redact(reason), started_at: startedAt,
    finished_at: new Date().toISOString().replace(/\.[0-9]+Z$/, "Z"),
  };
  process.stderr.write("run.sh: could not open the isolated Atlas session: " + redact(reason) + "\n");
  process.stdout.write(JSON.stringify(line) + "\n");
  process.exit(1);
};
const rowsOf = (body) => (Array.isArray(body) ? body : Array.isArray(body && body.items) ? body.items : []);
(async () => {
  try {
    const base = String(mcpUrl).replace(/\/mcp\/?$/, "");
    const ids = [];
    if (seeds) {
      const answer = await fetch(base + "/api/v1/companies?limit=500", { signal: AbortSignal.timeout(30000) });
      if (!answer.ok) fail("the company lookup answered " + answer.status);
      const companies = rowsOf(await answer.json());
      for (const slug of seeds.split(",")) {
        const found = companies.find((each) => each && each.slug === slug);
        if (!found) fail("unknown seed company: " + slug);
        ids.push(String(found.id));
      }
    }
    const made = await fetch(base + "/api/v1/sessions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        question, theme, seed_company_ids: ids, as_of: asOf, model, actor: "atlas-" + agent, isolated: true,
      }),
      signal: AbortSignal.timeout(30000),
    });
    const text = await made.text();
    if (made.status !== 201) fail("POST /api/v1/sessions answered " + made.status + ": " + text.slice(0, 300));
    let body = null;
    try { body = JSON.parse(text); } catch (_) { body = null; }
    if (!body || typeof body.id !== "string" || !/^[A-Za-z0-9-]+$/.test(body.id)) fail("the session answer has no id");
    if (body.isolated !== true) fail("Atlas opened a session that is not isolated");
    process.stdout.write(body.id + "\n");
  } catch (error) {
    fail("Atlas is unreachable: " + (error && error.message ? error.message : String(error)));
  }
})();
'
atlas_session=""
if [[ "$isolated" == true ]]; then
  open_status=0
  opened="$(node -e "$open_js" "$mcp_url" "$agent" "$theme" "$question" "$seeds" "$as_of" "$model" "$started_at")" || open_status=$?
  if [[ "$open_status" != 0 ]]; then
    printf '%s\n' "$opened"
    exit 1
  fi
  atlas_session="$opened"
  prompt="${prompt//"$session_ref"/"$atlas_session"}"
  build_command
fi

cd "$root"
status=0
"${cmd[@]}" >"$result" 2>"$errors" || status=$?
finished="$(date +%s)"
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# The pod-log line, from claude's JSON result. Every string that leaves this script has the token
# replaced first.
summary_js='
const fs = require("fs");
const [agent, resultFile, errorFile, status, wall, mcpUrl, asOf, question, seeds, startedAt, finishedAt, openedSession] = process.argv.slice(1);
const token = process.env.CLAUDE_CODE_OAUTH_TOKEN || "";
const redact = (text) => (token ? String(text).split(token).join("[redacted]") : String(text));
const first = (text, n) => Array.from(String(text)).slice(0, n).join("");
const read = (file) => { try { return fs.readFileSync(file, "utf8"); } catch (_) { return ""; } };
const raw = read(resultFile);
let data = null;
try { data = JSON.parse(raw); } catch (_) { data = null; }
const object = data && typeof data === "object" && !Array.isArray(data) ? data : null;
const exit = Number(status);
const ok = exit === 0 && object !== null && object.is_error === false && object.subtype === "success";
// The Atlas session the run opened: for a run that is not isolated, the one Atlas lists with the
// as-of time of the run (the agent passes it to open_session unchanged), preferring one whose actor names the agent.
// session_id is the Claude Code session. Atlas unreachable or no such session: null.
// Scorecard cases share as-of dates, so a run given a question also matches the session by its
// question, and by its seed companies when it was given slugs (looked up to ids; a lookup that
// fails leaves the seeds out of the match).
const rowsOf = (body) => (Array.isArray(body) ? body : Array.isArray(body && body.items) ? body.items : []);
const fetchRows = async (base, path) => {
  const answer = await fetch(base + path, { signal: AbortSignal.timeout(5000) });
  return answer.ok ? rowsOf(await answer.json()) : null;
};
const atlasSession = async () => {
  // An isolated run opened its session itself: that id, with no matching.
  if (openedSession) return openedSession;
  try {
    const base = String(mcpUrl).replace(/\/mcp\/?$/, "");
    const items = await fetchRows(base, "/api/v1/sessions?limit=50");
    if (items === null) return null;
    const want = Date.parse(asOf);
    let same = items.filter((each) => each && Date.parse(each.as_of) === want);
    if (question) same = same.filter((each) => String(each.question || "") === question);
    if (question && seeds) {
      const companies = await fetchRows(base, "/api/v1/companies?limit=500");
      const ids = companies === null ? [] : seeds.split(",").map((slug) => {
        const found = companies.find((each) => each && each.slug === slug);
        return found ? String(found.id) : null;
      });
      if (companies !== null && ids.every((id) => id !== null)) {
        const wanted = ids.slice().sort().join(",");
        same = same.filter((each) => (each.seed_company_ids || []).map(String).sort().join(",") === wanted);
      }
    }
    const own = same.find((each) => String(each.actor || "").includes(agent)) || same[0];
    return own ? String(own.id) : null;
  } catch (_) {
    return null;
  }
};
(async () => {
const line = {
  agent,
  ok,
  exit_status: exit,
  session_id: object ? object.session_id ?? null : null,
  atlas_session_id: await atlasSession(),
  turns: object ? object.num_turns ?? null : null,
  cost_usd: object ? object.total_cost_usd ?? null : null,
  duration_ms: object ? object.duration_ms ?? null : null,
  wall_s: Number(wall),
  started_at: startedAt,
  finished_at: finishedAt,
  subtype: object ? object.subtype ?? null : null,
  is_error: object ? object.is_error ?? null : null,
  result: redact(first(object ? (typeof object.result === "string" ? object.result : JSON.stringify(object.result ?? null)) : "unparseable output: " + raw, 2000)),
};
// The files stay in the output folder for whoever reads the run: with the token cut out.
const errors = redact(read(errorFile));
if (token) {
  fs.writeFileSync(resultFile, redact(raw));
  fs.writeFileSync(errorFile, errors);
}
const tail = errors.split("\n").filter(Boolean).slice(-50).join("\n");
if (tail) process.stderr.write(tail + "\n");
process.stdout.write(JSON.stringify(line) + "\n");
process.exit(ok ? 0 : 1);
})();
'
exit_code=0
node -e "$summary_js" "$agent" "$result" "$errors" "$status" "$((finished - started))" "$mcp_url" "$as_of" "$question" "$seeds" "$started_at" "$finished_at" "$atlas_session" || exit_code=$?
exit "$exit_code"
