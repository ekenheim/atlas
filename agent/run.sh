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
#   ATLAS_AGENT_TMP           the writable directory (default /tmp): the output folder is
#                             $ATLAS_AGENT_TMP/out, the MCP config $ATLAS_AGENT_TMP/atlas-mcp.json
#
# Prints one JSON line to stdout (agent, session id, turns, cost, duration, the first 2,000
# characters of the result) for the pod log; exits non-zero when the run failed. --dry-run prints
# the command, the MCP config and the prompt, and calls nothing.
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

# What goes into the prompt and the JSON file is checked, not escaped.
url_re='^https?://[^[:space:]"\\]+$'
[[ "$mcp_url" =~ $url_re ]] || die "ATLAS_MCP_URL is not an http(s) URL: $mcp_url"
[[ "$theme" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "ATLAS_AGENT_THEME is not a theme slug: $theme"
model_re='^[][A-Za-z0-9._:-]+$'
[[ "$model" =~ $model_re ]] || die "ATLAS_AGENT_MODEL has characters a model name does not: $model"
[[ "$max_turns" =~ ^[1-9][0-9]*$ ]] || die "ATLAS_AGENT_MAX_TURNS is not a positive integer: $max_turns"
[[ "$call_bound" =~ ^[1-9][0-9]*$ ]] || die "ATLAS_AGENT_CALL_BOUND is not a positive integer: $call_bound"
[[ "$as_of" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([+-][0-9]{2}:[0-9]{2}|Z)$ ]] \
  || die "ATLAS_AGENT_AS_OF is not an ISO time with an offset: $as_of"

prompt_file="$here/prompts/$agent.md"
[[ -f "$prompt_file" ]] || die "no prompt for $agent: $prompt_file"
prompt="$(cat "$prompt_file")"
prompt="${prompt//'{{THEME}}'/$theme}"
prompt="${prompt//'{{AS_OF}}'/$as_of}"
prompt="${prompt//'{{OUT_DIR}}'/$out_dir}"
prompt="${prompt//'{{CALL_BOUND}}'/$call_bound}"
[[ "$prompt" != *'{{'* ]] || die "the $agent prompt has a placeholder nothing fills"

mcp_json="{\"mcpServers\":{\"atlas\":{\"type\":\"http\",\"url\":\"$mcp_url\"}}}"

# --tools limits the built-in tools to the four the routine needs (the MCP tools are the server's
# and unaffected); --allowedTools lets those and every Atlas tool run without a prompt (there is
# nobody to ask, and anything else is refused). `mcp__atlas` allows the whole server, and
# `mcp__atlas__*` is the same in the pattern form. --add-dir lets Write and Edit reach the output
# folder, which is outside the working directory (the read-only /opt/atlas-agent).
cmd=(
  claude -p "$prompt"
  --mcp-config "$mcp_config" --strict-mcp-config
  --tools "Read,Write,Edit,Glob"
  --allowedTools "mcp__atlas" "mcp__atlas__*" Read Write Edit Glob
  --add-dir "$out_dir"
  --model "$model"
  --max-turns "$max_turns"
  --output-format json
)

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

umask 077
mkdir -p "$out_dir"
printf '%s\n' "$mcp_json" >"$mcp_config"

result="$out_dir/claude-result.json"
errors="$out_dir/claude-stderr.txt"
started="$(date +%s)"
cd "$root"
status=0
"${cmd[@]}" >"$result" 2>"$errors" || status=$?
finished="$(date +%s)"

# The pod-log line, from claude's JSON result. Every string that leaves this script has the token
# replaced first.
summary_js='
const fs = require("fs");
const [agent, resultFile, errorFile, status, wall] = process.argv.slice(1);
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
const line = {
  agent,
  ok,
  exit_status: exit,
  session_id: object ? object.session_id ?? null : null,
  turns: object ? object.num_turns ?? null : null,
  cost_usd: object ? object.total_cost_usd ?? null : null,
  duration_ms: object ? object.duration_ms ?? null : null,
  wall_s: Number(wall),
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
'
exit_code=0
node -e "$summary_js" "$agent" "$result" "$errors" "$status" "$((finished - started))" || exit_code=$?
exit "$exit_code"
