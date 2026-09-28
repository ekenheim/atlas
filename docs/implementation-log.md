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

## 2026-09-28: ticket 04, job queue and single-pass worker

- **Built:**
  - Alembic revision `0003` (`down_revision = "0001"`; re-chain onto ticket 03's `0002` at merge): the `job` table with a uuid5 ID from (kind, idempotency key), `UNIQUE (kind, idempotency_key)`, payload / failures / artifacts as JSONB, status, attempts, max attempts, lease owner and expiry, last error, and created / updated / started / finished timestamps. Check constraints: the status set, `attempts <= max_attempts`, a lease exists iff the job is running, and the JSON shapes. There's a partial index for the claim scan.
  - `atlas.jobs`:
    - `JobQueue`: idempotent `enqueue`, `get`, `claim`, `complete`, `fail`. The claim uses `FOR UPDATE SKIP LOCKED` and reclaims expired leases, recording each lost attempt as a failure. All clocks are the database's `now()`.
    - `HandlerRegistry` and `builtin_registry()`, with the built-in `noop` kind.
    - `Worker`: `run_once` processes jobs until none is runnable; `run_forever` polls and waits out database outages.
  - CLI:
    - `atlas worker` runs continuously; SIGTERM or SIGINT stops it after the current job. Settings `ATLAS_WORKER_POLL_SECONDS` (default 5) and `ATLAS_JOB_LEASE_SECONDS` (default 300).
    - `atlas worker --once` exits 1 with `database unavailable` when it can't reach the database.
    - `atlas jobs enqueue <kind> --key K [--payload JSON] [--max-attempts N]` prints the job as JSON, with `created: false` on a re-enqueue, and rejects unknown kinds and payloads that aren't objects (exit 2).
  - API: `GET /api/v1/jobs/{id}` returns the full job (status, attempts, failures, artifacts, lease, timestamps). An unknown ID gives 404 with `{"error": {"code": "not_found", "message": ...}}`.
  - Compose: the worker service now runs `["worker"]`.
- **Files:**
  - `backend/atlas/jobs/{__init__,queue,handlers,worker}.py`
  - `backend/atlas/api/jobs.py`
  - `backend/atlas/db/migrations/versions/0003_job_queue.py`
  - small edits to `api/app.py`, `cli.py`, `settings.py`, `compose.yaml` and `.env.example`
  - `tests/integration/test_jobs.py`
  - updated `tests/unit/test_cli.py` and `tests/integration/test_migrations.py`
- **Tests (TDD at the CLI, worker single pass and HTTP API seams, real Postgres on a fresh DB per test):** 14 new integration tests:
  - end to end: CLI enqueue, then `worker --once`, then the API shows the job
  - the same idempotency key gives one job, which isn't rerun
  - deterministic IDs per (kind, key)
  - CLI input validation
  - 4 concurrent worker threads × 40 jobs, each run exactly once
  - an expired lease is reclaimed, and the stale worker's late completion is rejected
  - a live lease isn't reclaimed
  - retries stop at 3 with every failure recorded
  - retry then success, with artifacts
  - a kind with no handler fails without retrying
  - an expired lease on the last attempt fails the job
  - 404 envelope and 422
  - continuous `atlas worker` picks up a new job and exits 0 on SIGTERM
  - `worker --once` on an empty queue

  Mutation check: removing `FOR UPDATE SKIP LOCKED` turns the concurrency test red. `scripts/ci.sh --no-image` passed: ruff and strict pyright clean, frontend gates green, **25 passed** (the 11 existing tests plus 14 new ones, 73.8 s).
- **Fixture-tested vs live:** everything runs against the real local Postgres 17; no external services are involved. `docker compose up worker` in continuous mode wasn't run as a container (no image build here; the lead builds after merge). The subprocess test covers the same CLI.
- **Deviations and notes:**
  - The ticket-01 unit test `worker --once` (unreachable DB, expected exit 0) now expects exit 1 with a clear `database unavailable` message and no traceback, since the worker needs the queue. The disabled-provider notice assertions are unchanged.
  - `test_migrations` now expects head `0003`, which stays correct after re-chaining (0001 → 0002 → 0003).
  - I added a `failures` JSONB history next to `last_error`, so the API shows every failed attempt.
  - Retries have no backoff: a failed job is requeued immediately, so one `--once` pass runs it up to the bound. Queue pause and backoff are ticket 14.
  - There's no lease heartbeat, so a handler that runs longer than `ATLAS_JOB_LEASE_SECONDS` can be reclaimed. The stale result is then discarded (fenced by owner and attempt), but handlers should stay idempotent.
  - The §5.8 budget and trace-ID columns and the `run`/`task` links are deferred (Phase 4).
  - The error envelope model lives in `api/jobs.py` for now; hoist it when a second router needs it.
- **Credentials:** none.
- **Next:** ticket 07 (ingest slice) registers the ingest kind in `builtin_registry()` and returns produced Source Version IDs as artifacts. Ticket 14 adds queue pause and backoff.
