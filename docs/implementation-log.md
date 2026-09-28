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
