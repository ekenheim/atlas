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
- **CI entrypoint:** `scripts/ci.sh` passed locally end to end (≈3.5 min). **GitHub Actions passed** on the first push (run 36480960995, commit `1413ee8`, 2026-09-28, ≈1.5 min, including the image build + smoke).
- **Manual check:** `docker compose up -d --build --wait api`, then `/health/ready` reported database and archive `ok` and Hindsight/LiteLLM `not_configured`; `/` served the frontend; `/metrics` exposed `atlas_build_info`; logs are JSON.
- **Deviations and notes:**
  - The dev dependency is `httpx2`, because Starlette deprecates `httpx` for its test client.
  - The API host port defaults to 58080 (8000 was taken locally), configurable via `ATLAS_API_PORT`.
  - The Compose worker runs `--once` until the job queue exists (ticket 04).
  - The S3 archive backend is not wired into readiness yet; that's ticket 05.
- **Credentials:** none needed.
- **Next:** tickets 03 (audit trail), 04 (job queue), 05 (archive), 06 (EDGAR adapter), 11 (Hindsight gateway) and 18 (release pipeline) are unblocked. Ticket 02 (docs pack) and 20 (home-ops prerequisites) were unblocked already.

## 2026-09-28: ticket 03, audit trail and actor

- **Built:**
  - Alembic revision `0002` (down_revision `0001`): the `audit_event` table (actor, action, entity type/id, old/new content hashes, `prev_hash`, `event_hash`, `occurred_at`, gapless `id`), with CHECK constraints on non-blank text and SHA-256 hex hashes
  - a BEFORE INSERT trigger that assigns the chain position under an advisory lock (callers can't forge `id`, `prev_hash` or `event_hash`)
  - ENABLE ALWAYS triggers rejecting UPDATE, DELETE and TRUNCATE
  - `REVOKE ALL FROM PUBLIC`, plus a SELECT/INSERT grant to the runtime role `atlas_app` when it exists
  - `atlas.audit`: `Actor` (`from_settings`; blank names refused), `record(connection, actor, action, *, entity_type, entity_id, old_hash, new_hash)` in the caller's transaction, and `verify_chain` (independent Python recomputation)
  - CLI `atlas audit verify` (exit 0 ok, exit 1 broken, prints the head hash)
  - `ATLAS_ACTOR` must be non-blank at startup
- **Files:**
  - `backend/atlas/audit.py`
  - `backend/atlas/db/migrations/versions/0002_audit_event.py`
  - `backend/atlas/cli.py`, `backend/atlas/settings.py` (small additive edits)
  - `tests/integration/test_audit.py`, `tests/unit/test_audit_actor.py`
  - `tests/unit/test_cli.py` (blank actor), `tests/integration/test_migrations.py` (head is now `0002`)
  - `AGENTS.md`, `docs/decisions.md`
- **Tests (TDD, red first on the missing module):** `scripts/ci.sh --no-image` passed: ruff, pyright strict (0 errors), frontend gates, **28 pytest passed** (163 s). The new tests, all on fresh databases in the real Postgres 17:
  - the chain links across separate and shared transactions and verifies
  - an empty trail verifies
  - 6 concurrent writers × 5 events form one valid chain
  - a rolled-back change leaves no event and no gap
  - UPDATE, DELETE and TRUNCATE are rejected as superuser and table owner
  - `session_replication_role = replica` doesn't bypass the guard
  - a raw INSERT can't choose its chain position
  - the `atlas_app` role can read and append, but UPDATE/DELETE are denied by privileges
  - the database rejects a blank actor
  - `atlas audit verify` detects a tampered event, a re-hashed event (broken link) and a missing middle event
  - unit: `Actor` refuses blank names; the CLI refuses a blank `ATLAS_ACTOR`

  I also checked by hand that the migration round-trips (`0002` → `0001` → `0002`).
- **Fixture vs live:** everything ran against the local Compose Postgres. The `atlas_app` role split is only exercised in tests: the test creates the role, NOLOGIN, cluster-wide, and leaves it in the dev cluster. It isn't deployed anywhere yet.
- **Deviations:**
  - The DB trigger, not the app, computes the chain.
  - Deleting the newest events with the triggers disabled by the owner isn't detectable from the chain alone. `verify` prints the head hash so it can be anchored externally, but that anchoring isn't built (see `docs/decisions.md`).
  - Audit writers serialize until commit.
- **Next:**
  - Tickets 07 and 08 call `record` with `Actor.from_settings(settings)` in the same transaction as each mutation.
  - Ticket 04's migration will be re-chained after `0002`, and `test_migrations` must then expect its head.
  - The deployment creates `atlas_app` (tickets 20–22), and later migrations grant it minimal privileges.
## 2026-09-28: ticket 18, release pipeline

- **Built:**
  - `.github/workflows/release.yml`: runs on push of a tag `v*.*.*`, in two jobs:
    - `ci` (`contents: read`) runs `scripts/ci.sh --no-image`.
    - `publish` (`needs: ci`, `packages: write`) builds the existing multi-stage Dockerfile for `linux/amd64` only, loads it locally and runs `scripts/image-smoke.sh` on it. Only then does it log in to GHCR with `GITHUB_TOKEN` and push `ghcr.io/ekenheim/atlas` (the second build is served from the buildx cache).
  - Tags: `{{version}}` (the full semver without the `v`, e.g. `1.2.3`) and `sha-<full commit SHA>`. No `latest` tag.
  - OCI labels come from `docker/metadata-action`: `org.opencontainers.image.version` and `.revision`, plus `.source` pinned explicitly to `https://github.com/ekenheim/atlas`.
  - Actions are pinned to their current majors: `docker/setup-buildx-action@v4`, `docker/metadata-action@v6`, `docker/login-action@v4` and `docker/build-push-action@v7` (all the Node 24 majors of March 2026). The checkout, uv and node setup steps match `ci.yml` (`actions/checkout@v4`, `astral-sh/setup-uv@v6`, `actions/setup-node@v4`).
  - `docs/deployment.md` (new): the release process, the tag scheme, how to cut a release, the one-time step of making the GHCR package public, and the Renovate deploy path. There's also a short "Releases" section in the README.
- **Tests and results (actual):**
  - `actionlint` 1.7.12 (`docker run --rm -v <worktree>:/repo -w /repo rhysd/actionlint:latest`): 0 errors in `ci.yml` and `release.yml`.
  - Local image: `docker buildx build --platform linux/amd64 --load -t atlas:release-test` with the three OCI labels passed by hand. Then `ATLAS_SMOKE_PORT=58318 scripts/image-smoke.sh atlas:release-test` printed `image smoke OK (uid 10001, read-only root)`, and `docker image inspect` showed the labels, arch `amd64` and user `10001`.
  - The worker role in the same image (`--read-only --tmpfs /tmp`, `worker --once` against the local Postgres) exited 0 with the disabled-provider notices.
  - `scripts/ci.sh --no-image`: passed, with 11 tests passing. The first attempt failed at the pytest step with a transient `Current directory does not exist` on the `/mnt/c` worktree; a direct `uv run pytest` and a full rerun both passed.
- **Unverified:** the publish path has never run on GitHub. That covers the GHCR login, the push, the tags and labels as metadata-action actually computes them, and the package-to-repo link. No tag has been pushed; that is the owner's step. The first acceptance box stays unticked until the first real `v*.*.*` tag publishes successfully. After that first release, the package must be made public once in GitHub's UI (`docs/deployment.md`).
- **Deviations and notes:**
  - The ticket asks for "the version tag". I publish `X.Y.Z` (the full semver, no `v`) and the SHA tag, with no floating `X.Y`, `X` or `latest` tags, so Renovate tracks exact versions.
  - The publish job smokes the image before pushing it. This goes beyond the ticket, but the non-root/read-only acceptance box is then checked on every release.
  - Provenance attestations are left at the build-push-action default. GHCR may list an extra `unknown/unknown` attestation manifest, which is harmless.
- **Credentials:** none (`GITHUB_TOKEN` only).
- **Next:**
  - The owner tags the first release (e.g. `v0.1.0`), checks the run and the package, and sets the package to Public.
  - Then ticket 21 (home-ops releases/Renovate).
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
