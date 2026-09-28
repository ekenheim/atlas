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
## 2026-09-28: ticket 06, SEC EDGAR adapter

- **Built** (`backend/atlas/sources/`):
  - `adapter.py`: the async `SourceAdapter` protocol (discover / fetch / updates) and its typed models: `SearchQuery`, `SourceCandidate`, `SecFiling`, `FetchedDocument`, `FetchAttempt`, `HttpValidators`, `FetchError` (with `retryable` and the attempts).
  - `sec_http.py`: `SecHttpClient` with an injectable httpx2 transport. It sends the configured User-Agent (a contact email is required) and shares `SEC_RATE_LIMITER`, one process-wide token bucket (capacity 1, 10/s, thread-safe). It retries 429/5xx/timeouts/network errors with exponential backoff, honoring Retry-After as seconds or an HTTP-date. A Retry-After beyond a 600 s cap fails fast as retryable. Other 4xx aren't retried. It makes conditional requests (If-None-Match / If-Modified-Since → `not_modified`).
  - `edgar.py`: `EdgarAdapter` for configured CIKs:
    - submissions index, re-checked conditionally
    - 10-K/10-Q/8-K and their amendments (primary documents)
    - 8-K EX-99.* exhibits from the filing's `-index-headers.html`
    - XBRL companyfacts, fetched raw
    - `acceptanceDateTime` surfaced per filing as `available_at` (basis `sec_acceptance`); companyfacts falls back to `observed_discovery`
    - `updates(since)` returns filings accepted after the cursor, plus companyfacts only when there are any
  - `edgar_fixtures.py`: `FixtureReplay` (httpx2 handler: 403 without a User-Agent, 404 when unrecorded, 304 on matching validators) and `fixture_edgar_adapter`.
  - Settings: `ATLAS_SEC_LIVE` (default false → `sec disabled: missing ATLAS_SEC_LIVE`) and `ATLAS_SEC_USER_AGENT`, required with a contact email when live. Startup fails fast naming it.
- **Fixtures** (`tests/fixtures/edgar/lumentum/`, `manifest.json` records URL, headers and trimming): recorded live on 2026-09-28 with 9 SEC requests paced ≥1.5 s apart, as `Atlas Research ekenheim@gmail.com`. Recorded:
  - submissions JSON
  - 8-K 0001628280-26-055726: index headers, primary document, EX-99.1
  - 10-K 0001628280-26-057358 and 10-Q 0001628280-26-030777 primary documents
  - companyfacts
  - one live conditional GET (If-Modified-Since → 304, confirmed)

  Trimmed, but still valid:
  - submissions `filings.recent`: unrecorded 10-K/10-Q/8-K rows removed; Form 4/144/SD/13G rows kept
  - companyfacts: dei plus nine us-gaap concepts
  - 10-K and 10-Q bodies: cut at top-level element boundaries (byte slices, still well-formed XHTML)
- **Tests:** 39 passed, 1 deselected (live). New tests:
  - `tests/unit/test_sec_http.py` (14):
    - 429 + Retry-After with attempts recorded
    - HTTP-date Retry-After
    - 5xx/timeout backoff
    - 4xx not retried
    - attempt budget
    - Retry-After cap
    - conditional ETag/Last-Modified → 304
    - User-Agent on every request, and one without an email refused
    - the limiter cap: two clients × 8 concurrent requests, no 1 s window holds more than 10; a mutation check at 12/s goes red
  - `tests/unit/test_edgar_adapter.py` (11):
    - discovery and form filtering
    - `acceptanceDateTime` is exact UTC, cross-checked against the filing header's Eastern ACCEPTANCE-DATETIME
    - byte-exact fetch
    - conditional refetch
    - conditional submissions re-check
    - `updates`
    - User-Agent on all 7 requests
    - replay 403
    - a 429 through the adapter
    - a 404 not retried
  - Settings and CLI: SEC off by default, live requires the User-Agent, fail-fast CLI.
  - `tests/live/test_sec_edgar_live.py`: 4 real requests, behind the `live` marker. Excluded by default; skips without `ATLAS_SEC_USER_AGENT`.
- **CI:** `scripts/ci.sh --no-image` passed.
- **Fixture vs live:** every automated test is fixture/mock-only. The live smoke test was collected but **not run**, to stay within the ~10-request recording budget. The only live evidence is the recording session itself (200s, and a 304 for If-Modified-Since).
- **Deviations and notes:**
  - `httpx2` moved from dev to runtime dependencies.
  - Async tests use anyio's pytest plugin (already installed via httpx2).
  - `.gitignore` gets `!tests/fixtures/**/data/`, because SEC paths contain `data/`. `.gitattributes` marks `tests/fixtures/**` as `-text` so bytes and hashes stay exact.
  - data.sec.gov (submissions, companyfacts) sends no ETag/Last-Modified. Only www.sec.gov Archives sends Last-Modified, and it sends no ETag. So conditional requests effectively apply to filing documents.
  - The submissions index isn't returned as a candidate, and `filings.files` (older pages) isn't followed.
- **For tickets 07/08:**
  - SEC's Akamai edge appends a `<script src="/KSRe0…">` tag to Archives HTML. It was identical across this session's requests, but if it varies between sessions, an unchanged filing would hash differently. Check before relying on raw-hash dedup (the parser may need to strip it, or dedup may need a normalized hash).
  - The fixture adapter needs a fixture directory at runtime; the image doesn't ship `tests/`.
  - Store `FetchedDocument.validators` with the fetch observation so re-checks are conditional.
- **Credentials:** none (the SEC User-Agent is a contact string, not a secret).
- **Next:** ticket 07 (ingest slice) can build Source Versions from `FetchedDocument`.
## 2026-09-28: ticket 11, Hindsight gateway and recorded fake

- **Built:**
  - `backend/atlas/hindsight/` (`gateway.py`, `models.py`, `errors.py`): `HindsightGateway`, the only code that speaks HTTP to Hindsight, bound to one bank. Typed operations:
    - `retain_batch` (always `async: true`, one operation per batch; returns only the operation handle, never an outcome)
    - `operation`, and `wait_for_operation` (polls with a timeout)
    - `recall` with a `TagScope` or `scope=None`
    - `reflect` with an optional `response_schema` and `include.facts`
    - `get_memory` (the observation → `source_memory_ids` → world fact hops) and `get_document` (memory count per fact type, for ticket 13's zero-fact check)
    - `list_observations` and `knowledge_page_tree`
    - `apply_bank_template` (dry run, then import) and `bank_config`
    - `create_mental_model`, `refresh_mental_model`, `get_mental_model` and `mental_model_history`
    - `llm_request_stats`
  - Gateway errors: `HindsightRuleViolation`, `HindsightHTTPError`/`HindsightNotFound`, `HindsightUnavailable`, `HindsightProtocolError` and `OperationTimeout`.
  - Enforced 0.10.1 rules:
    - `TagScope` accepts only `any_strict`/`all_strict`, and the gateway re-checks at call time. `any`, `all` and `exact` are rejected before any call.
    - A union type (`"type": [...]`, `anyOf`, `oneOf`) anywhere in a reflect `response_schema`, or in a template mental model's schema, is rejected before any call.
    - `Operation.succeeded` is `status == "completed"` and nothing else.
    - Observations are listed via `memories/list?type=observation` and pages via `knowledge-base/tree`.
  - `tests/fakes/hindsight.py`: `RecordedHindsight`, an `httpx2.MockTransport`. It replays a recording only when the method, path, query and JSON body match exactly, and raises `UnrecordedRequest` otherwise.
  - Settings: `ATLAS_HINDSIGHT_API_KEY` (optional, sent as a bearer token) and `ATLAS_HINDSIGHT_BANK_ID` (default `atlas-ai-infrastructure`). `.env.example` is updated.
  - `httpx2` is now a runtime dependency. It was already the dev test-client dependency.
- **Tests (TDD at the transport boundary):** 69 new, and `scripts/ci.sh --no-image` passed with 80 tests.
  - `tests/unit/test_hindsight_contract.py` (46 cases): the gateway is driven through the fake with each recording's request inputs, and its typed result is checked against the recorded response. Expected values are read from the recordings. `test_every_recording_is_classified` requires every one of the 58 files to be either exercised (46) or listed as a route Atlas doesn't call (12, each with a reason: the sync retain, the temporal window, export/import, knowledge-page create/get, consolidate, the operations list, the bank PUT, the template schema/export).
  - `tests/unit/test_hindsight_gateway.py` (23 cases):
    - polling until a terminal status
    - the timeout carrying the last status
    - `failed` counting as a failure without an error message
    - non-strict tags, empty scopes, and nested `type`-list/`anyOf`/`oneOf` schemas rejected with zero calls
    - template schema check before the dry run
    - an empty batch and naive timestamps rejected
    - the bearer header present or absent
    - transport errors raising `HindsightUnavailable`
    - `from_settings`

  A mutation check confirmed the relevant tests go red for each of these: allowing `any`, dropping the type-list check, skipping polling, sending a sync retain, and listing via `/observations`.
- **Fixture-only:** everything. No live Hindsight call was made. Readiness is ticket 12.
- **Deviations and notes:**
  - **Derived operation states:** the spike recorded only terminal (`completed`) operation statuses. To test polling, timeouts and `failed`, `RecordedHindsight.hold_operation` serves a recorded status response with only its `status` field changed. This is the one departure from "never hand-write responses", and it's documented in the fake.
  - **LLM request log:** only `llm-requests/stats` was recorded, so only that is exposed. The per-call `GET …/llm-requests` list needs a real recording first.
  - **Untested paths (no recording):** HTTP error mapping (404 → `HindsightNotFound` for a deleted memory, 422/429/5xx → `HindsightHTTPError` with `status_code`). Ticket 14 (429 pause) and ticket 15 (broken citations) should record these.
  - `reflect(..., include_facts=True)` is the default, because Atlas needs the citations. The structured recording was made without `include`, so its contract test passes `include_facts=False`.
  - `anyOf`/`oneOf` are rejected as union types conservatively. Only the `type`-list form was verified to return 500.
  - `scope` is a required keyword on `recall`/`reflect`, so bank-wide access (`scope=None`) is always explicit.
- **Credentials:** none needed.
- **Next:** ticket 12 (Hindsight in Compose, bank template, readiness) is unblocked.
## 2026-09-28: ticket 20, home-ops prerequisites (PRs 1–3)

- **Built:** three local branches in home-ops (`/mnt/c/Users/ekenh/home-ops-upgrade`), each in its own worktree under the session scratchpad, all off `main` @ `c1531a6b0`. Not pushed. The canonical checkout's `main` working tree was not touched.
  - `atlas/crunchy-users` @ `29dfa1c19`: PGO users/databases `atlas` and `atlas-hindsight` in `database/crunchy-postgres/cluster/cluster.yaml`, with a comment pointing at the `vector` runbook.
  - `atlas/litellm` (**changes staged, not committed**; see Deviations):
    - configmap: aliases `atlas-extract` / `atlas-reflect`, both `<<: *minimax-m3`. The anchor is new, on the existing `MiniMax-M3` route's `litellm_params`. Each alias has its own `model_info`, because the configmap forbids anchored `model_info`.
    - configmap: the PRIVACY note amended with the Atlas exception for public-market research.
    - `keys/atlas.yaml`: `LiteLLMVirtualKey` `atlas` → Secret `litellm-key-atlas` (`api-key`); `maxBudget: "25"`, `budgetDuration: 30d`, `maxParallelRequests: 3`; models `atlas-extract`, `atlas-reflect`, `qwen3-embedding-0.6b`, `rerank`.
    - `clustersecretstore/` plus a Flux Kustomization `litellm-stores` (dependsOn `external-secrets`): ClusterSecretStore `litellm-key-secrets` with `remoteNamespace: llm` and `conditions: [{namespaces: [datasci]}]`; SA `external-secrets-llm` with a namespaced Role/RoleBinding in `llm` allowing only `get` on `litellm-key-atlas`.
  - `atlas/renovate` @ `1b2ab3564`: two rules appended last in `.github/renovate/packageRules.json5`, both `automerge: false`: `matchFileNames: kubernetes/apps/datasci/atlas/**` (covers the dedicated Hindsight, whose package names it shares with `llm/hindsight`) and `matchPackageNames: ghcr.io/ekenheim/atlas`.
  - Atlas repo: `docs/runbooks.md` covers the home-ops PR merge order (with per-step checks and the names later releases depend on) and the one-off `CREATE EXTENSION vector` in `atlas-hindsight`.
- **Validation (actual results):**
  - **yamllint:** `yamllint -c .yamllint.yaml -s .` passed on all three worktrees. This mirrors home-ops CI, whose config ignores `.github/`.
  - **kubeconform v0.6.7:** `-strict`, default k8s schemas, run on the 6 changed manifests (10 resources): Valid 10, Invalid 0, Skipped 0.
    - CRD schemas were generated from the **pinned** CRDs, not the datree catalog CI uses, because the sandbox refused that URL: litellm-operator 0.0.19, external-secrets 2.11.0, pgo 6.0.3, and Flux Kustomization from flux CLI v2.0.0-rc.1.
    - A negative check (a misspelled `maxParallelRequest`, `conditions[].namespace`) was rejected, which confirms the schemas are strict.
  - **flux-local v8.4.0** (the CI image), `test --all-namespaces --path kubernetes/flux/config`:
    - crunchy-users 182 passed, renovate 182 passed, litellm 183 passed (+1, the new `litellm-stores` Kustomization).
    - With `--enable-helm`, as CI runs it: litellm 325 passed. It was not re-run with helm on the other two, which change no HelmRelease.
  - **renovate-config-validator** (renovate 44.117.0 via npx, node 22.0 under the required engine): "Config validated successfully".
    - Its only warning is a config migration for the existing terraform rule's `matchPackagePatterns`, which predates this change.
  - `${…}`: none of the changes contain a literal `${`, so nothing needed escaping. No ExternalSecrets were added in these PRs, so the `{{ index . "X" }}` rule doesn't apply yet. No secrets.
  - **CRD check:** `maxParallelRequests` (int64) is in the 0.0.19 `LiteLLMVirtualKey` CRD, and the controller sends it as `max_parallel_requests` (checked in upstream source at tag 0.0.19). So the cap is included.
  - **Atlas `scripts/ci.sh --no-image`:** passed, 11 tests (docs-only change here).
- **Fixture vs live:** nothing was applied to the cluster. No kubectl, no LiteLLM calls. The alias resolution was checked by parsing the rendered `config.yaml`: both aliases' `litellm_params` equal MiniMax-M3's.
- **Deviations and open issues:**
  - **`atlas/litellm` is not committed.** 33 of the 256 loose-object dirs in home-ops' `.git/objects` are owned by root (created 2026-09-19 to 2026-09-28, before this session), so git cannot write objects hashing into them. The litellm branch's trees do, deterministically. The crunchy and renovate commits happened to avoid them. A workaround that packed the objects into the repo was refused by the permission classifier and not pursued.
    - The changes are staged in the `atlas/litellm` worktree, and a patch plus the commit message are saved in the scratchpad.
    - **Owner:** `sudo chown -R "$USER": /mnt/c/Users/ekenh/home-ops-upgrade/.git/objects`, then commit in that worktree with the saved message.
  - `rerank` in the key routes to `hindsight-tei-reranker.llm`, the **shared** Hindsight's TEI sidecar. Atlas's reranking therefore depends on `llm/hindsight` staying up (the configmap says the same for memini).
  - The ClusterSecretStore is named `litellm-key-secrets` (after `crunchy-pgo-secrets`), not `litellm-keys` as the research note suggested, to avoid confusion with the `litellm-keys` Flux Kustomization.
- **Credentials:** none needed.
- **Next:** the owner fixes the object-store ownership and commits `atlas/litellm`, reviews the three branches, then pushes and opens them in the order in `docs/runbooks.md`. After PR 1, run the `vector` step. PR 4 (`atlas-hindsight` release) and PR 6 (the app) are later tickets.

## 2026-09-28: log redaction (spec Part A story 9; gap found by ticket 02)

- **Files:** `backend/atlas/logs.py` (`RedactingJsonFormatter`, `redact`), `tests/unit/test_logs.py`.
- **Behavior:** every formatted log record (message, extras and tracebacks) is redacted before it reaches stderr: credentials in URLs, `Bearer` tokens, `sk-` API keys, and `password|secret|token|api_key|access_key=…` values.
- **Tests (TDD):** 5 new; 4 went red first, then green. Unit suite 117 passed; ruff and strict pyright clean.
- **Limits:** pattern-based. A secret logged in an unrecognized shape isn't caught; don't log secrets at all, and treat redaction as the safety net.
