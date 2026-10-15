# 17: Scheduled routines

Type: build
Status: in-review
Blocked by: none

## Question

Claude cloud routines (`/schedule`): a weekly Scout per theme; a Researcher on `issues/next` per theme; a Skeptic on the oldest proven Belief not challenged in 30 days; every output waits for the lead's judgement, nothing judged by a routine. Resolved after two weeks of routines logged with the lead's review time per week measured and the trust gate held (at or below 10%) on their sessions.

## Answer (the owner, 2026-10-15)

Atlas is LAN-only (`atlas.ekenhome.se` resolves to 192.168.50.155; no public record), so Claude cloud routines cannot reach its MCP server, and the API (with `/mcp`) has no authentication of its own. The owner chose **CronJobs in the cluster**: headless Claude Code (`claude -p`) on the owner's subscription through a `claude setup-token` token in a Secret the owner creates, against the in-cluster MCP URL (`http://atlas.development.svc.cluster.local:8000/mcp`). Nothing exposed publicly; nothing on the owner's PC.

## What to build (Atlas repo)

- `agent/Dockerfile` → image `ghcr.io/ekenheim/atlas-agent:X.Y.Z`: a pinned Node LTS slim base, `@anthropic-ai/claude-code` pinned to an exact published version at least two weeks old, non-root, read-only root with `/tmp` writable (`HOME=/tmp`), the skill folder `.claude/skills/atlas-research/` and `agent/` copied in. No secrets in the image.
- `agent/run.sh <scout|researcher|skeptic>`: writes the MCP config from `ATLAS_MCP_URL` (default the in-cluster URL above), requires `CLAUDE_CODE_OAUTH_TOKEN`, runs `claude -p "<the routine prompt>" --mcp-config ... --strict-mcp-config --allowedTools "mcp__atlas__*" Read Write Edit Glob --model "${ATLAS_AGENT_MODEL:-opus}" --max-turns <per agent> --output-format json`, writes the session's files under `/tmp/out`, and prints one summary line of JSON to stdout (agent, session id, turns, cost, duration, the result's first 2,000 characters) for the pod log; exit non-zero on failure. `--dry-run` prints the command without calling anything (for the smoke test).
- `agent/prompts/{scout,researcher,skeptic}.md`: the routine wrappers, each naming its skill prompt and inputs: theme `photonics` (env `ATLAS_AGENT_THEME`), as-of = the run's start time (UTC, with offset), the output folder, the call bound; the Researcher starts from `next_issue` (SKILL.md: a session whose prompt names no question) with recall of `bank: research` as an index and `bank: beliefs` for earlier conclusions; the Skeptic takes no Belief id (skeptic.md chooses the oldest proven Belief not challenged in 30 days; **as built, skeptic.md's own rule is the one in force**: the oldest proven Belief with no counterevidence since its last judgement); every prompt says no judgement is set and nothing published.
- Release workflow: build, smoke (`claude --version`, `run.sh scout --dry-run`, non-root) and push `atlas-agent` beside `atlas` with the same tags; CI's `static` stage builds nothing new but runs a unit test that every MCP tool a routine or skill prompt names exists in the server's tool registry (`atlas.mcp`).
- `docs/runbooks.md` "Scheduled agents": the owner's one step (`claude setup-token`, then the Bitwarden Secrets Manager secret `atlas-agent-claude` holding `CLAUDE_CODE_OAUTH_TOKEN`, mapped by a home-ops ExternalSecret), the CronJobs' shape, reading a run (pod log line, the session on the sessions page), stopping them (suspend the CronJob). `docs/decisions.md`: in-cluster routines, why not cloud routines. AGENTS.md: one bullet.

## Then (the lead, home-ops)

Three CronJobs in `kubernetes/apps/development/atlas/app/agents.yaml`: Scout weekly (Monday 05:00 UTC), Researcher Tuesday and Thursday 05:00, Skeptic Friday 05:00; `concurrencyPolicy: Forbid`, one attempt, `activeDeadlineSeconds` 5400; the token from the owner's Secret.

## Acceptance criteria

- [x] The prompt-tools unit test (`tests/unit/test_agent_routines.py`).
- [x] `run.sh --dry-run` output tested (`tests/unit/test_agent_run.py`, with the real run path under a stand-in `claude`).
- [ ] The image builds and smokes in the release workflow (run on a branch tag or verified in CI). Built and smoked locally under Docker (`scripts/agent-image-smoke.sh`, passed); the release workflow and CI's `suite` have not run it yet.
- [ ] Two weeks of routines logged (pod logs and sessions), the lead's review time per week measured, the trust gate at or below 10% on their sessions (the lead).
