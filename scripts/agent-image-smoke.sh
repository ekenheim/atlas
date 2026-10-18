#!/usr/bin/env bash
# Smoke-test the scheduled-agents image (atlas-beliefs ticket 17): non-root, read-only root
# filesystem with /tmp writable, the pinned Claude Code installed and starting, `run.sh --dry-run`
# working, the skill folder in place, and no token baked in. Nothing here calls Anthropic or Atlas.
set -euo pipefail
cd "$(dirname "$0")/.."
image="${1:-atlas-agent:dev}"

# Every container runs as the cluster runs it: read-only root, a writable /tmp, no network needed.
run() { docker run --rm --read-only --tmpfs /tmp --network none "$@"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

uid="$(run --entrypoint id "$image" -u)"
[[ "$uid" != "0" ]] || fail "container runs as root"

# The Claude Code the Dockerfile pins, and no other.
pinned="$(sed -n 's/^ARG CLAUDE_CODE_VERSION=//p' agent/Dockerfile)"
[[ -n "$pinned" ]] || fail "agent/Dockerfile pins no CLAUDE_CODE_VERSION"
version="$(run --entrypoint claude "$image" --version)"
[[ "$version" == "$pinned "* ]] || fail "claude --version is '$version', the Dockerfile pins $pinned"

# The routine's own checks of its working environment: /tmp writable, the image's files not.
run --entrypoint sh "$image" -c '
  touch /tmp/probe || exit 11
  if touch /opt/atlas-agent/probe 2>/dev/null; then exit 12; fi
  test -f /opt/atlas-agent/.claude/skills/atlas-research/SKILL.md || exit 13
  test -f /opt/atlas-agent/.claude/skills/atlas-research/scout.md || exit 14
  test -x /opt/atlas-agent/agent/run.sh || exit 15
  node --version >/dev/null || exit 16
  test -x /opt/atlas-agent/agent/scorecard-run.sh || exit 17
  node -e '"'"'const r = JSON.parse(require("fs").readFileSync("/opt/atlas-agent/agent/scorecard/runs.json", "utf8")); if (!Array.isArray(r) || r.length === 0) process.exit(1)'"'"' || exit 18
' || fail "image layout (exit $?): /tmp writable, root read-only, skill folder, run.sh and scorecard-run.sh executable, node, the scorecard run list"

# A dry run, through the image's entrypoint, for each routine; with a fake token to prove the
# dry run never prints one.
for agent in scout researcher skeptic; do
  out="$(run -e CLAUDE_CODE_OAUTH_TOKEN=smoke-not-a-token "$image" "$agent" --dry-run)" \
    || fail "run.sh $agent --dry-run"
  grep -q -- "--strict-mcp-config" <<<"$out" || fail "$agent dry run has no --strict-mcp-config"
  grep -q "mcp__atlas" <<<"$out" || fail "$agent dry run allows no Atlas tools"
  ! grep -q "smoke-not-a-token" <<<"$out" || fail "$agent dry run printed the token"
done

# A real run with no token stops before it calls anything.
status=0
msg="$(run "$image" scout 2>&1)" || status=$?
[[ "$status" == 2 ]] || fail "run.sh scout without a token exited $status, not 2"
grep -q "CLAUDE_CODE_OAUTH_TOKEN is not set" <<<"$msg" || fail "no message about the missing token"

# No credential in the image's environment.
if run --entrypoint env "$image" | grep -q -E "OAUTH|API_KEY|AUTH_TOKEN"; then
  fail "a credential is set in the image's environment"
fi
echo "agent image smoke OK (uid ${uid}, claude ${pinned}, read-only root)"
