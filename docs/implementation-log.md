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

## 2026-09-28: ticket 05, archive (filesystem + S3)

- **Built:**
  - `backend/atlas/archive/`: one `Archive` class (`put(namespace, bytes) -> uri`, `get(uri)`, `exists(uri)`, `is_ready()`) over two backend stores, `filesystem.py` and `s3.py` (boto3). `open_archive(settings)` picks the backend.
  - URIs: `archive://<raw|parsed>/sha256/<hex>`. They are the same for both backends and carry no bucket, endpoint or credentials. Anything else raises `InvalidArchiveUri`, including path traversal and uppercase hex. Both stores use the object key `<namespace>/sha256/<hex>`.
  - Write-once:
    - Filesystem: a temporary file is fsynced, set to mode 0444 and hard-linked into place. The link fails if the key already exists.
    - S3: HEAD first, then `PutObject` with `If-None-Match: *` (a 412 counts as already stored) and a server-verified `ChecksumSHA256`.
  - `get` re-hashes and raises `ArchiveIntegrityError` rather than return bytes that don't match their URI.
  - Settings:
    - `ATLAS_ARCHIVE_BACKEND` (`filesystem`|`s3`, default `filesystem`)
    - `ATLAS_S3_ENDPOINT_URL`, `ATLAS_S3_BUCKET`, `ATLAS_S3_ACCESS_KEY_ID`, `ATLAS_S3_SECRET_ACCESS_KEY` (`SecretStr`): required only for s3, with one message that names each missing setting
    - `ATLAS_S3_REGION` (default `us-east-1`)
  - The CLI now prints cross-field setting errors without the `ATLAS_?` prefix.
  - Readiness `archive` uses the configured backend: filesystem checks for a writable root, s3 does a `HeadBucket`. The archive is on `app.state.archive` for the content API (ticket 07).
  - Dependencies: `boto3` (runtime) and `boto3-stubs[s3]` (dev, for strict pyright). The stub import is `TYPE_CHECKING`-only in the package.
- **Tests (TDD, red first):** 64 passing in total, 53 new:
  - `tests/integration/test_archive_contract.py`: 40 cases, the same 20 against the filesystem and against a fresh versioned Silo bucket. They cover:
    - known-digest URIs with no leaks
    - separate raw/parsed namespaces
    - exact round-trip (all byte values, CRLF/NUL, UTF-8, empty)
    - idempotent put that leaves the stored state untouched (inode/mtime on disk; the version list in S3)
    - never overwriting a pre-existing object, where a later `get` raises an integrity error
    - not-found
    - rejection of 8 malformed or foreign URIs
    - readiness
    - no secret in `repr`
  - `tests/integration/test_archive_object_lock.py`, 4 tests **live against Silo**. The bucket is created with `ObjectLockEnabledForBucket` and a default GOVERNANCE retention of 1 day, with a unique name per run. The tests check that:
    - the default retention is applied
    - an overwrite creates a new version, the original version keeps its bytes, and the archive refuses the tampered latest version
    - a plain delete adds a delete marker and keeps the version
    - a version delete without bypass is refused: any 4xx, no exact code asserted, and the version and bytes survive
  - `tests/integration/test_readiness.py`, 4 new tests: s3 ready, ready regardless of `ATLAS_ARCHIVE_ROOT`, bucket missing gives 503 `down`, endpoint unreachable gives 503 `down`. No bucket, endpoint or credentials appear in the body.
  - `tests/unit/test_cli.py`, 3 new tests: s3 without settings names all four; a partial config names only the missing one and never prints the secret; an unknown backend is rejected.
  - `tests/unit/test_settings.py`, 2 new tests: the default backend, and the secret stays out of `repr` and `model_dump`.
  - A mutation check confirmed the idempotence and no-overwrite tests fail on both backends when the store overwrites (no existence check, no `If-None-Match`, `os.replace`).
- **CI:** `scripts/ci.sh --no-image` passed: ruff, pyright strict (0 errors), frontend gates, 64 passed. The image build was not run (the lead runs it after merging).
- **Live vs fixture:** S3 behavior was exercised live against the Compose Silo (`127.0.0.1:59000`, root credentials). It was **not** tested against the cluster MinIO or as the scoped `atlas` user without bypass rights; ticket 19 provisions that user. Governance cleanup uses the root bypass. Leftover buckets, if any, expire after the one-day retention; none were left after this run.
- **Deviations and notes:**
  - `ATLAS_ARCHIVE_ROOT` is still required with `ATLAS_ARCHIVE_BACKEND=s3`, although it is unused there. Making it conditional would have stopped the existing fail-fast CLI test from reporting every missing setting at once, because pydantic runs cross-field checks only after field validation succeeds. Revisit at deploy (ticket 22).
  - `get` returns the latest version only. After tampering or a delete marker, the locked original is still in the bucket, but recovering it is an operator task.
  - `get` returns the whole object in memory; streaming can come with the content API if large filings need it.
  - Archive-write metrics are not added yet (spec story 8); they belong with the ingest service (ticket 07).
- **Credentials:** none. The tests use the Compose dev root credentials from `compose.yaml`, overridable with `ATLAS_TEST_S3_*`.
- **Next:** ticket 07 (ingest slice) uses `open_archive`/`Archive.put`. Ticket 19 (archive provisioning) can reuse the S3 settings names.
