# Implementation log

Per `START_HERE.md`: after each ticket or phase, record the files, the acceptance tests run and their **actual** results, open blockers, credential dependencies, version decisions and the next task. Say plainly when something was only tested against fixtures.

## 2026-09-28: ticket 01, walking skeleton

- **Built:**
  - uv project (Python 3.12.10, `uv.lock`)
  - `atlas` package: FastAPI app factory, settings, health, JSON logging, CLI `api | worker [--once] | migrate`, Alembic baseline revision `0001`
  - Next.js 16.3 static export (TypeScript 6.0 strict, ESLint 9)
  - multi-stage Dockerfile (non-root uid 10001, read-only-root compatible)
  - Compose: `postgres-app` (Postgres 17), `silo` (PGSTY Silo, pinned digest), `migrate`, `api`, `worker`
  - `scripts/ci.sh`, `scripts/image-smoke.sh`, `.github/workflows/ci.yml`
  - `.env.example`, README, AGENTS.md
- **Tests (TDD at the agreed seams):** 11 passing:
  - liveness
  - readiness: ok, database down, archive down (all fail closed with 503)
  - metrics
  - static frontend mount
  - CLI: missing required settings fail fast, `worker --once` with disabled-provider notices
  - settings: CRLF `.env` and CR-in-env stripping
  - migrations from an empty database

  A mutation check confirmed the fail-closed tests go red when readiness always reports ready.
- **CI entrypoint:** `scripts/ci.sh` passed locally end to end (≈3.5 min). **GitHub Actions has not run yet**: the workflow is committed but unverified on a runner.
- **Manual check:** `docker compose up -d --build --wait api`, then `/health/ready` reported database and archive `ok` and Hindsight/LiteLLM `not_configured`; `/` served the frontend; `/metrics` exposed `atlas_build_info`; logs are JSON.
- **Deviations and notes:**
  - The dev dependency is `httpx2`, because Starlette deprecates `httpx` for its test client.
  - The API host port defaults to 58080 (8000 was taken locally), configurable via `ATLAS_API_PORT`.
  - The Compose worker runs `--once` until the job queue exists (ticket 04).
  - The S3 archive backend is not wired into readiness yet; that's ticket 05.
- **Credentials:** none needed.
- **Next:** tickets 03 (audit trail), 04 (job queue), 05 (archive), 06 (EDGAR adapter), 11 (Hindsight gateway) and 18 (release pipeline) are unblocked. Ticket 02 (docs pack) and 20 (home-ops prerequisites) were unblocked already.

## 2026-09-28: ticket 02, Phase 0 documentation pack

- **Built (documentation only; no application code changed):**
  - `docs/architecture.md`: components, write and trust boundaries, Phase 1–2 data flow (Mermaid), clocks, local and cluster deployment
  - `docs/data-model.md`: Phase 1–2 tables with invariants, and a Mermaid ER diagram
  - `docs/threat-model.md`: assets, adversaries, trust rules (source text and third-party skill content are data, never instructions), threats T1–T25 mapped to tickets and tests, residual risks
  - `docs/source-licenses.md`: the entitlement inventory (statuses, license classes, allowed / lead-only / unlicensed / absent sources, processors, a site register)
  - `docs/evaluation-methodology.md`: principles, the gold-fixture format (case IDs, source hashes, manifest, schema, example), all 13 §9.5 categories plus `LAY` and `INF` from ticket 12, metrics, recording results
  - `docs/adr/0002-fresh-edgar-adapter-sibling-repos-reference-only.md`: the reuse ADR
  - a `docs/decisions.md` entry; ticket 02 marked done
- **Inputs:** spec Parts A and B; build plan §2, §4, §5, §6, §7.5, §9, §12, §13 and Appendix A; `docs/decisions.md`; ADR-0001; the feature matrix; `research/serenity-skills-alignment` and `research/home-ops-wiring` (read with `git show`; not merged into this branch). The sibling repositories were read only, to write ADR-0002.
- **Tests:** `scripts/ci.sh --no-image` passed: ruff format and lint clean, pyright 0 errors, frontend lint, typecheck and build OK, pytest 11 passed (the existing suite). No tests were added, because the ticket is documentation only.
- **Fixture vs live:** nothing was integrated or run live. Mermaid diagrams weren't rendered by a tool (no Mermaid renderer is installed); relative links were checked by a script.
- **Deviations and findings:**
  - Research docs on unmerged branches are cited by branch and path, since they are not on `main` yet.
  - The threat model found a gap: spec story 9 (secrets redacted in logs) isn't built. `backend/atlas/logs.py` has no redaction filter, and no ticket owns it explicitly.
  - Data-model open points are left to tickets 07, 14 and 15 (see the decisions entry).
- **Next:** the implementing tickets (03, 04, 07, 08, 12–15) follow `docs/data-model.md` and update it when they change a column. The first gold cases and their validator land with Phase 2 (`INJ`, `RET`, `NOX`, `CON`).
