# 01: Walking skeleton

**What to build:** The project boots locally with one documented command sequence and fixture-only settings. One non-root, read-only-root image runs as either the API or the worker. The API serves a one-page static frontend and reports liveness, readiness (application database and archive) and Prometheus metrics. A single CI entrypoint (lint, format, types, migrations, network-blocked tests) is green locally and is what the committed GitHub Actions workflow calls. Spec Part A: Shape, Quality gates, stories 1–14.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Compose brings up the API, worker, application Postgres and the pinned Silo S3 server; readiness reports DB and archive status, and reports Hindsight/LiteLLM as 'not configured'
- [ ] Missing required settings fail at startup with an actionable message; missing optional providers log 'disabled: missing X' once
- [ ] The first migration applies cleanly from empty
- [ ] The CI entrypoint passes locally, and the GitHub Actions workflow invokes the same entrypoint
- [ ] README, AGENTS.md (commands, layout) and .env.example are written; .env values are whitespace-stripped (the CRLF-safe loader)
- [ ] The implementation log is started with this ticket's files, tests run and their results
