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
## 2026-09-29: ticket 19, archive provisioning script

- **Built:**
  - `scripts/provision_archive.py`: a re-runnable minio-py (`Minio` + `MinioAdmin`) command, run as `uv run scripts/provision_archive.py --endpoint <url>`. Root credentials come from `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` only.
    - **Bucket:** `--bucket` (default `atlas-archive`), made with object lock at creation. Default retention is GOVERNANCE for `--retention-days` days (default 3650), and versioning is checked to be Enabled.
    - **Policy:** `--policy` (default `<bucket>-app`), scoped to the bucket. It allows `s3:GetBucketLocation`, `s3:ListBucket`, `s3:GetObject` and `s3:PutObject`, grants no delete, and explicitly denies `s3:BypassGovernanceRetention`.
    - **User:** `--user` (default `atlas`), with the policy attached. A 40-character secret is generated and printed once, as Bitwarden field lines (`S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`), and is never written to disk. It's printed as soon as the user exists, so a later failure can't lose it.
    - **Idempotent:** each step reports `ok` / `up to date` or the change it made. A run with no changes ends `No changes: already provisioned.`
      - It **refuses** (exit 1) an existing bucket without object lock, or with a different default retention, rather than change a lock.
      - A lock-enabled bucket with no rule, left by a crash between create and configure, gets the rule.
      - A policy that differs from the script's is updated. Extra policies on the user are reported as a warning.
    - `--rotate-secret` issues a new secret for an existing user, as the recovery path for lost credentials.
  - `minio` 7.2.20 is a **dev** dependency. The Dockerfile's `uv sync --no-dev` keeps it out of the app image, and the owner runs the script from a checkout.
  - `scripts/` is now covered by ruff (`scripts/ci.sh`) and strict pyright (`pyproject.toml` include).
  - Docs: the "Archive bucket provisioning" section in `docs/runbooks.md` (root credentials via `read -s`, storing the output in Bitwarden, rotation, Silo use), linked from rollout step 5. Plus one command line in `AGENTS.md`.
- **Tests:** `tests/integration/test_archive_provisioning.py`, 10 passing. They run the script as a subprocess against the Compose Silo as root, with unique names and 1-day retention:
  - the bucket has object lock `Enabled`, default retention `{Mode: GOVERNANCE, Days: 1}`, and versioning Enabled
  - the printed credentials are the scoped user's
  - the scoped user can put, get, head and check readiness through `open_archive` (the S3 backend), and the stored object carries GOVERNANCE retention
  - the scoped user **cannot** permanently delete a locked version, even with `BypassGovernanceRetention=True`; the version survives
  - the scoped user can't write to another bucket
  - **second run:** exit 0, `No changes`, no credentials printed, and the first secret still works
  - a run asking for a different retention is refused, and the lock is unchanged
  - an existing unlocked bucket is refused before any user is created
  - `--rotate-secret` prints a new secret; the new one works and the old one is rejected
  - missing root credentials exit 2 and name both variables
  - **Cleanup:** users and policies are removed, and Silo was checked afterwards: no `atlas-test*` users or policies left. Locked buckets are emptied with the root bypass where possible; otherwise their 1-day retention expires.
  - Red first: all 10 failed before the script existed.
- **CI:** `scripts/ci.sh --no-image` passed: ruff and pyright clean, frontend gates, 202 passed, 1 deselected.
- **Fixture vs live:** verified live against Silo (a MinIO fork) only. **Not run against the cluster MinIO**; the owner runs it in rollout step 5. The 3650-day default was not exercised live, since tests use 1 day. The admin API (`user-info`, `add-canned-policy`, `idp/builtin/policy/attach`) and error codes (`XMinioAdminNoSuchUser`/`NoSuchPolicy`, `ObjectLockConfigurationNotFoundError`) were observed on Silo and are MinIO's.
- **Deviations:**
  - A script under `scripts/`, not an `atlas` subcommand, so the app image needs no `minio`.
  - The mode is fixed to Governance (decision Q16), and only the days are configurable.
  - The bypass permission is also *explicitly* denied, not just omitted.
  - `--rotate-secret` was added beyond the ticket, as the only recovery path now that `mc` is gone.
- **Credentials:** none needed. The tests use the Compose dev root (`atlas-dev`), not a real secret.
- **Next:** the owner runs the script in rollout step 5. The app release (step 6) needs an ExternalSecret mapping the Bitwarden `S3_*` fields to `ATLAS_S3_*`, plus `ATLAS_ARCHIVE_BACKEND=s3`. The R2 copy CronJob needs its own read credentials; this policy is for the app only.
## 2026-09-29: ticket 07, ingest a Lumentum filing end to end

- **Built:**
  - Alembic revision `0004` (down_revision `0003`), with five tables:
    - `company`: slug, CIK, deterministic UUIDv5 ID
    - `security`: effective-dated, with a `btree_gist` exclusion constraint against overlapping (exchange, ticker) listings
    - `source_document`: unique (provider, canonical URL); immutable
    - `source_version`: `UNIQUE (document, raw_sha256)`, NOT NULL `available_at` and basis, `version_number`, `comparison_sha256`/`comparison_rule`, a unique `supersedes_version_id`
    - `fetch_observation`: append-only

    Triggers (ENABLE ALWAYS) enforce:
    - immutable content columns, no DELETE and no TRUNCATE
    - parse columns writable only while `pending`/`failed`
    - supersedes = the previous version of the same document

    Grants go to `atlas_app` when that role exists.
  - `configs/themes/ai-infrastructure.yaml` (version 1): Lumentum (CIK 0001633978, LITE on XNAS from 2015-08-04), a Coherent stub, and the photonics theme. `atlas.companies` loads and validates it and seeds idempotently; only real changes are audited.
  - `atlas.parsing`: the deterministic `html-text-v1` HTML/text normalizer (its rules are in the module docstring). JSON is `not_applicable`.
  - `atlas.ledger`:
    - `SourceLedger.record` resolves → hashes → archives raw → compares → creates a version (parsed and archived separately) or records an observation. Each row created gets an audit event in the same transaction.
    - `reads` covers the API queries.
    - `ingest` is the `ingest` job: it seeds the company, uses fixture replay (`ATLAS_SEC_FIXTURES_DIR/<slug>`) or live SEC (`ATLAS_SEC_LIVE`), makes conditional requests from the latest observation's validators, and returns artifacts (counts, new Source Version IDs, observations).
  - CLI: `atlas ingest --company SLUG [--key] [--forms] [--limit] [--max-attempts]` and `atlas companies seed`. `builtin_registry(settings)` registers `ingest`.
  - API (`/api/v1`, error envelope, `limit`/`offset` pages):
    - `GET /companies`, `/companies/{id}`, `/companies/{id}/sources`
    - `/sources/{id}`, `/sources/{id}/versions`
    - `/source-versions/{id}` (provenance + fetches)
    - `/source-versions/{id}/content?kind=raw|parsed` (streamed; raw served as a sandboxed attachment)
  - The SEC edge-script decision is in `docs/decisions.md`.
- **Files:**
  - new: `backend/atlas/{companies,parsing}.py`, `backend/atlas/ledger/{__init__,service,reads,ingest}.py`, `backend/atlas/api/{common,sources}.py`, `backend/atlas/db/migrations/versions/0004_source_ledger.py`, `configs/themes/ai-infrastructure.yaml`, `tests/integration/test_ingest.py`, `tests/unit/test_parsing.py`, `tests/fixtures/parser/golden.json`
  - small edits: `api/app.py` (router), `api/jobs.py` (envelope moved to `api/common.py`, re-exported), `audit.py` (`content_hash`), `cli.py`, `jobs/handlers.py`, `settings.py` (`sec_fixtures_dir`, `themes_config`), `Dockerfile` (`COPY configs/`), `.env.example`, `AGENTS.md`, `docs/data-model.md`, `docs/decisions.md`, `tests/integration/test_migrations.py` (head `0004`), `pyproject.toml`/`uv.lock` (`pyyaml` runtime, `types-pyyaml` dev)
- **Tests:** 31 new: 16 integration (real Postgres, a fresh DB each) and 15 unit.
  - Written first: the integration suite, red on missing settings and CLI.
  - The parser tests were written just after the parser, and then checked by mutation.
  - Gate tests at the CLI + single-pass worker + API seam:
    - unchanged ×2 → one version (4×304 + 1 hash-unchanged)
    - changed fixture → v2 supersedes v1
    - a varied SEC script → no new version, and the fetch's own hash recorded
    - raw bytes identical to the fixture files and equal to `raw_sha256`
    - `available_at` = the submissions `acceptanceDateTime`, basis `sec_acceptance`, with clock ordering checked
    - parse hash = the pinned golden, and the parsed object is separate
    - audit events match every entity 1:1, and `atlas audit verify` exits 0
  - Also: idempotent seeding, unknown company (exit 2), a company without fixtures fails visibly, 404 envelopes, 422 on a bad `kind`, pagination, DB-level rejection of UPDATE/DELETE/TRUNCATE, duplicate raw hash, a cross-document supersedes, NULL `available_at`, overlapping securities.
  - Mutation checks went red as expected: disabling the edge-script rule fails the script test, and dropping the conditional validators fails the unchanged test.
  - `scripts/ci.sh --no-image` **passed**: ruff, pyright strict 0 errors, frontend gates, **223 passed, 1 deselected** (live), 168 s.
- **Fixture vs live:** every ingest test replays the recorded EDGAR fixtures. The live path (`ATLAS_SEC_LIVE=true` → `SecHttpClient` with the configured User-Agent) is wired but **not run**. The only live request was one SEC call to verify Coherent's CIK (`data.sec.gov/submissions/CIK0000820318.json`, User-Agent `Atlas Research ekenheim@gmail.com`). The S3 archive backend is not exercised by the ingest tests (filesystem only). The contract suite covers S3.
- **Deviations:**
  - `source_document.accession` is not unique: an 8-K and its EX-99.1 share an accession. Identity is (provider, canonical URL).
  - PKs are named `id`.
  - New columns: `company.slug`, `source_document.{document_type,title}`, `source_version.{version_number,comparison_sha256,comparison_rule,byte_size,parse_error}`, and `parse_status` `not_applicable`.
  - `fetch_observation` resolves the per-fetch open point.
  - The re-parse table is deferred.
  - Two extra read routes (`/companies/{id}/sources`, `/sources/{id}`).
  - `published_at` is null for SEC.
  - LITE's `valid_from` day comes from Lumentum's separation announcement; the 10-K fixture only confirms August 2015.
  - Coherent's security is a TODO.
  - Not built: the submissions index as its own Source Version (the adapter doesn't return it) and fetch/parse/archive metrics (spec story 8).
- **Credentials:** none.
- **Next:** ticket 08 (Assertions) binds quotes to `source_version.parsed_object_uri` text. The viewer ticket uses the new read routes. Metrics for fetches, parses and archive writes remain open. Coherent fixtures and its security arrive in Phase 2.
## 2026-09-29: ticket 12, Hindsight in Compose and the bank template

- **Built:**
  - **Compose:** `hindsight` (0.10.1-slim at the cluster digest) and `hindsight-db` (pgvector pg18), both behind the profile `hindsight`, so the default stack and CI never start them. The settings match the spike:
    - provider `openai` at `${ATLAS_LITELLM_URL}/v1`
    - extra body `{"thinking":{"type":"disabled"}}` (`ATLAS_HINDSIGHT_LLM_EXTRA_BODY`)
    - `LLM_MAX_CONCURRENT=2` / `RETAIN_LLM_MAX_CONCURRENT=2`, `WORKER_MAX_SLOTS=4`
    - LLM, retain, reflect and mental-model-refresh timeouts at 300 s
    - embeddings `qwen3-embedding-0.6b` at 1024 dims; reranker `litellm` / `rerank`
    - a stable worker ID
    - models `atlas-extract` (retain, consolidation) and `atlas-reflect` (reflect, mental-model refresh), overridable with `ATLAS_LLM_EXTRACT_ALIAS` / `ATLAS_LLM_REFLECT_ALIAS`
    - host port `127.0.0.1:${ATLAS_HINDSIGHT_PORT:-58888}`

    The app services get `ATLAS_HINDSIGHT_URL` from `ATLAS_COMPOSE_HINDSIGHT_URL`, plus `ATLAS_LITELLM_URL`/`_API_KEY`. All three default to empty, which means disabled.
  - **Template:** `configs/hindsight/bank-template.json` (`template_version` `1.0.0`) wraps the Hindsight manifest. It holds:
    - the §6.2 retain, observations and reflect missions, with observations enabled
    - skepticism 4 and literalism 4 (the server default is 3)
    - the five §6.2 reflect directives

    It has no mental models; ticket 16 adds them.
  - **Applying it:** `atlas hindsight apply-template [--template PATH]` loads and validates the file, then runs the gateway's dry run and import. It then writes a `bank_template_application` row (version, manifest SHA-256, both results) and a `bank_template.applied` audit event (entity `hindsight_bank`, old/new hash = previous/new manifest SHA) in one transaction. It prints a JSON summary. Exit codes: 2 for a bad template or unconfigured Hindsight, 1 for a Hindsight or database error. The Dockerfile now copies `configs/` into the image.
  - **Gateway additions:** `server_health()` (`GET /health`) and `server_version()` (`GET /version`). They aren't bank-scoped and use a 5 s timeout.
  - **Readiness:**
    - `hindsight` is `ok` when `/health` reports `healthy`.
    - `litellm` is `ok` when `GET /model/info` with Atlas's key succeeds and both configured aliases have a deployment. This calls no model.
    - Anything else is `down`, and an unconfigured provider stays `not_configured`. LiteLLM needs both its URL and its key.
  - **LLM route recorder:** `atlas.llm_routes.LiteLLMRoutes.routes(aliases)` → `{alias: [RoutedDeployment(model, model_id)]}`. It raises `AliasNotRouted` if an alias is missing, and `LiteLLMUnavailable` on a transport error, a non-2xx response or an unexpected shape. The error never echoes the body or the key.
  - **Run record:** `atlas.runs.RunRecorder` (`from_settings`, `start(kind)`, `finish(run_id, tokens_in=, tokens_out=)`, `get`).
    - `start` records the code version, the Hindsight `api_version`, the bank's latest applied template version and the routed deployments per alias.
    - It raises `RunNotStartable` if no template has been applied (with no LiteLLM call and no row), and fails with no row if an alias isn't routed.
    - `code_version` is `ATLAS_CODE_VERSION`, which the release workflow sets to `github.sha` as a build arg; otherwise it's the package version.
  - **Migration `0005`** (down_revision `0003`, to be re-chained at merge): `bank_template_application` and `run`, with SELECT/INSERT (and UPDATE on `run`) granted to `atlas_app` when that role exists.
  - **Settings:** `ATLAS_HINDSIGHT_TEMPLATE_PATH`, `ATLAS_LLM_EXTRACT_ALIAS`, `ATLAS_LLM_REFLECT_ALIAS`, `ATLAS_CODE_VERSION`.
  - **Docs:** `.env.example`, README, AGENTS.md, and `docs/data-model.md` (actual `run` columns, plus `bank_template_application`).
- **LiteLLM `/model/info` shape assumed:** `{"data": [{"model_name": <alias>, "litellm_params": {"model": <provider/model>, ...secrets masked}, "model_info": {"id": <deployment hash>, ...}}]}`. Only `model_name`, `litellm_params.model` and `model_info.id` are read; `api_base` is never stored. Sources:
  - LiteLLM docs, Model Management: "`GET /model/info` returns the full model list with API keys masked"
  - the `/model/info` entry quoted in BerriAI/litellm issue #5524 (`model_name`, `litellm_params.{api_base,model}`, `model_info.{id,db_model,key}`)
  - the dev probe's `x-litellm-model-id` header, which is the deployment hash

  The docs page shows no full response example. The `{"data": [...]}` wrapper comes from LiteLLM's proxy source (`model_info_v1` returns `{"data": all_models}`), from memory rather than a fresh read, and was **not verified live**. The fixture `tests/fixtures/litellm/model-info.json` is hand-made in this shape, with illustrative model names and IDs. Replace it with a redacted real response when one is recorded.
- **New Hindsight recordings (real, from the running spike on 127.0.0.1:8888, 2026-09-29):** `spikes/hindsight/record_bank_template.py` recorded five interactions:
  - `research_template/01-import-dry-run`, `02-import` and `03-imported-config`: the actual template file, into a fresh bank `atlas-template-1790632603`
  - `monitoring/01-health` and `monitoring/02-version` (`api_version` 0.10.1)

  The run made no LLM calls: the bank's `llm-requests/stats` had no buckets afterwards, because a template without mental models queues no operations (`operation_ids: []`). Directive import is now verified on 0.10.1: all five directives were created and listed. The contract test now drives the real template file through the recorded dry run and import, so **editing the template requires re-running the recorder** (ticket 16 will). The recording count is 58 → 63, and all are classified.
- **Tests (actual results):** `scripts/ci.sh --no-image` **passed**: ruff format/lint clean, pyright strict 0 errors, frontend gates green, **225 passed**, 1 deselected (live). New tests:
  - `tests/unit/test_hindsight_contract.py` (+4):
    - the template file matches the recorded dry run and import
    - the imported config
    - health
    - version
  - `tests/unit/test_llm_routes.py` (7):
    - routes per alias with the bearer key and a single `GET /model/info`
    - a missing alias is named
    - 401 is unavailable and the key isn't echoed
    - unreachable
    - a bad shape
    - `from_settings` needs both URL and key
    - aliases come from config
  - `tests/integration/test_bank_template.py` (8), through the real CLI subprocess against the recorded fake served on localhost (`tests/fakes/serve.py`):
    - dry run then import, with the version, SHA and audit event recorded
    - re-apply chains the audit hashes
    - a failed dry run imports and records nothing
    - unreachable Hindsight
    - unconfigured Hindsight
    - three invalid template files
  - `tests/integration/test_readiness.py` (+6), each asserting the readiness status:
    - both up gives `ok`/`ok`
    - Hindsight unreachable
    - LiteLLM unreachable
    - key rejected
    - alias unrouted
    - URL without key gives `not_configured`
  - `tests/integration/test_runs.py` (8):
    - provenance at start
    - token totals at finish, and a double finish rejected
    - code-version fallback
    - the latest template version wins
    - no run before a template is applied
    - no run with an unrouted alias
    - configured aliases
    - no recorder unless both services are configured
  - `test_migrations` head is now `0005`.
  - Mutation checks: disabling the missing-alias check turned 3 tests red, and skipping `dry_run=true` turned 2 red.
- **Fixture-only vs live:**
  - **Live:** only the five Hindsight recordings above (config import, health, version) against the local spike.
  - **Fixture-only:** everything else. That includes all of LiteLLM (no `/model/info` call was made), readiness, the CLI and run records.
  - **Not run:** the Compose `hindsight` profile itself was not started; only `docker compose config` was checked, with and without the profile.
  - **Only faked:** the failed-dry-run test's 500 comes from the served fake refusing an unrecorded request, not from a real Hindsight rejection.
- **Deviations and notes:**
  - **Template file shape:** a wrapper `{template_version, manifest}` rather than a bare manifest, so the version isn't a field Hindsight might reject. The manifest SHA-256 is recorded too, so an edit without a version bump is still visible.
  - **Retain mission:** it adds one sentence beyond §6.2: "Keep figures, units and reporting periods exactly as stated."
  - **Directive wording:** the directives are Atlas's wording of the five §6.2 points.
  - **Dispositions:** 4/4 (above the default, per §6.2, and not tuned). Empathy is left at the server default.
  - **`run` and `bank_template_application` columns:** they follow the job table's conventions (`id`, `routed_models`) rather than `docs/data-model.md`'s `run_id` / `routed_models_json`. The data model now says so.
  - **`routed_models` shape:** it stores a list per alias (`[{model, model_id}]`), because an alias can load-balance over several deployments.
  - **LiteLLM readiness:** it requires the aliases to be routed, not just reachable, because an unrouted alias means no LLM call can succeed.
  - **Compose variables:** Compose interpolates every service even when its profile is off, so the Hindsight service uses `${VAR:-}` rather than `${VAR:?}`. Started without LiteLLM settings, it fails at boot rather than at `docker compose` time.
  - **`ATLAS_COMPOSE_HINDSIGHT_URL`:** it is separate from `ATLAS_HINDSIGHT_URL` because `.env`'s value is a host address.
  - **Token totals:** they are passed to `finish` by the caller. Wiring them from Hindsight's `/llm-requests` belongs to the jobs that create runs (tickets 13–15).
  - **No run creator yet:** nothing creates runs so far; ticket 13+ jobs should call `RunRecorder.start`.
  - **Spike recording:** the recordings used the already-running spike Hindsight (config-only calls, no LLM). They didn't start a new stack.
- **Credentials:** none. The recording script needs no key, and the `.env` was not read.
- **Next:**
  - ticket 16 adds the two mental models to the template, bumps `template_version` and re-records `research_template/*`
  - tickets 13–15 start runs through `RunRecorder`
  - record a real, redacted `/model/info` response to replace the hand-made fixture

## 2026-09-29: live check of the LiteLLM `/model/info` shape (ticket 12 follow-up)

- A read-only `GET /model/info` against the cluster LiteLLM with the `atlas-dev` key returned `{"data": [...]}` with 32 rows of `{model_name, litellm_params: {model, api_base, …}, model_info: {id, …}}`. That **matches** the shape ticket 12 assumed and faked in CI.
- The `atlas-extract` / `atlas-reflect` aliases are **not present yet**. They arrive with the home-ops `atlas/litellm` branch, which is still uncommitted: root-owned objects in home-ops `.git/objects`; see the ticket 20 entry. Until then, Atlas readiness reports LiteLLM as not routed.
## 2026-09-29: ticket 08, Assertions and review

- **Built:**
  - Alembic revision `0006` (down_revision `0005`): the `assertion` table with the §5.4 fields:
    - subject/object company, predicate, `value_json`
    - Source Version, `quote`, character offsets `span_start`/`span_end`, `page_or_anchor`
    - `event_start`/`event_end`, `epistemic_type`, `verification_status`
    - `independence_family_id` (reserved), `extracted_at`, `extractor_version` (`manual`), `created_by`
    - `reviewer_id`, `reviewed_at`, `superseded_by`

    It has CHECKs for the span length, the reviewed ⇔ reviewer/reviewed-at pairing, and superseded ⇔ `superseded_by` (never itself). Triggers (ENABLE ALWAYS) enforce:
    - an immutable statement
    - new rows `unreviewed`, citing a parsed Source Version
    - the review transitions
    - a live successor
    - no DELETE or TRUNCATE

    `atlas_app` gets SELECT/INSERT/UPDATE.
  - `atlas.assertions`:
    - `Assertions.create` reads the archived parse and requires `parsed[span_start:span_end] == quote` exactly. Offsets are code points; a refusal names where the quote does occur.
    - `Assertions.review` locks the Assertion and its successor in ID order, checks the transition and the successor, and updates only the review columns.
    - `list_assertions` and `get_assertion`.
    - Each mutation writes `assertion.created` / `assertion.reviewed` (old/new content hashes) in the same transaction, with `Actor.from_settings`.
  - API (`/api/v1`):
    - `POST /assertions` (201)
    - `POST /assertions/{id}/review`
    - `GET /assertions?company_id=&review_state=&source_version_id=` (paginated, oldest first)
    - `GET /assertions/{id}`

    Mutations return `{assertion, audit_event_id}`. Refusals use the error envelope: 422 `quote_mismatch` / `no_parsed_text` / `unknown_company` / `unknown_source_version` / `invalid_successor`, 409 `invalid_transition`, 404 `not_found`.
  - App-wide: FastAPI request validation errors now use the error envelope (`invalid_request`, 422).
- **Files:**
  - new: `backend/atlas/assertions.py`, `backend/atlas/api/assertions.py`, `backend/atlas/db/migrations/versions/0006_assertion.py`, `tests/integration/test_assertions.py`
  - small edits: `backend/atlas/api/app.py` (router and validation handler), `backend/atlas/api/common.py` (`invalid_request`), `tests/integration/test_migrations.py` (head `0006`), `docs/data-model.md` (§2.5 as built), `docs/decisions.md`, `AGENTS.md`
- **Tests:** 46 new integration tests (real Postgres, a fresh DB each, with Lumentum's 8-K accession ingested through the fixture `ingest` job and one worker pass), all at the API seam. They were written first and went red on the missing route. Quotes and offsets are hard-coded from the recorded EX-99.1, whose parse hash is checked against `golden.json`.
  - An exact span is accepted, including non-ASCII quotes, and starts `unreviewed` with the configured actor.
  - Rejected with `quote_mismatch`, with no row and no audit event: altered text, shifted offsets, UTF-8 byte offsets, a short or long span, whitespace or case differences, past the end, and text not in the source.
  - Also refused: a Source Version without a parse (companyfacts), unknown references, and malformed bodies (including a client-chosen review state or actor).
  - Transitions: an allowed path (disputed → corroborated → disputed → rejected) leaves the statement untouched. Six disallowed transitions each return 409 and change nothing.
  - Supersession links to the successor without editing; the superseded Assertion is final. Five invalid successors are refused.
  - The database refuses edits, deletes, TRUNCATE, invalid transitions and reviewed inserts.
  - Filters: company as subject or object, review state, both together, `source_version_id`, pagination, and an invalid state.
  - Audit: events are 1:1 with creates and reviews, with the configured actor and IDs matching the responses. The old/new hashes chain, refusals write nothing, and `atlas audit verify` exits 0.
  - Mutation checks went red as expected:
    - accepting any quote
    - prefix instead of exact match (after I added the span-longer case, which the first run missed)
    - allowing re-review of final states
    - subject-only company filter
    - the wrong audit action

  I also round-tripped the migration by hand (`0006` → `0005` → `0006`).
  - `scripts/ci.sh --no-image` **passed**: ruff, pyright strict 0 errors, frontend gates, **317 passed, 1 deselected** (live), 264 s. The first run had one failure in `tests/unit/test_sec_http.py::test_clients_share_one_process_wide_limit_of_ten_requests_per_second` (0.99899 s against a 0.999 s bound: a timing flake under load, unrelated). It passed 3/3 in isolation and in the full rerun.
- **Fixture vs live:** everything ran against the local Compose Postgres, with the filesystem archive and recorded EDGAR fixtures. No live SEC or S3 calls.
- **Deviations:**
  - §5.4 defines the states but not the transitions; the transition rules chosen are in `docs/decisions.md`.
  - `page_or_anchor` is a free label, because `html-text-v1` has no section anchors; the offsets are the binding.
  - I added a `source_version_id` list filter for the viewer.
  - `quote_or_span` is stored as `quote` plus offsets.
  - Subject and object are companies only (as `docs/data-model.md` planned).
  - The OpenAPI 422 schema of the pre-existing routes still shows FastAPI's default shape, although the body is now the envelope.
- **Credentials:** none.
- **Next:** ticket 10 (the viewer) creates and reviews Assertions through these routes. It must send code-point offsets, converting from the UTF-16 selection indices. If the retention ticket defines section anchors, `page_or_anchor` could then be validated against them.
## 2026-09-29: ticket 13, retain Source Versions into memory

- **Built:**
  - **Alembic revision `0007`** (down_revision `0005`; the lead re-chains it at merge):
    - `hindsight_operation`: Hindsight's operation ID, bank, kind (`retain`/`reprocess`), status as last reported, error, retry count, the Source Version and the batch's document IDs, result metadata, the submitting job, and submitted / last-polled / completed timestamps.
    - `memory_document`: Source Version, anchor, heading, character offsets, sectioner version, Hindsight document ID (unique), bank, operation, retain state (`pending`/`completed`/`failed`/`zero_fact`/`linked`), fact count, reprocess count (0–1), template version, linked-to Source Version, error.
    - Checks tie `linked` to a link and no document ID, and require a fact count for `completed`/`zero_fact` and an error for `failed`. An ENABLE ALWAYS trigger rejects DELETE, TRUNCATE and any change to a row's identity columns. Grants go to `atlas_app` when it exists.
  - **`atlas.retention`:**
    - `sections`: the `sec-items-v1` sectioner. It splits on Item headings for SEC primary documents (qualified by PART, skipping the table of contents, with a `cover` section before the body) and uses bounded 12,000-character chunks otherwise. The sections tile the parse.
    - `service`: the `retain`, `poll_operation` and `reprocess` jobs.
      - Retain decides between linking and retaining under an advisory lock on the raw hash.
      - IDs are `srcv:<source_version_uuid>:<anchor>`. The tags, metadata and timestamp are as the spec says.
      - It submits one batch per Source Version.
      - It polls status only, with a timeout.
      - It counts `memory_unit_count` per document. Zero facts get one reprocess (a re-retain under the same ID), then `zero_fact`. Failed operations mark their sections `failed` with the error.
      - Every write is audited.
    - `reads` and `GET /api/v1/source-versions/{id}/memory`: section documents, states, fact counts, per-state counts, and the operations.
  - **Ingest** enqueues a `retain` job for each new parsed Source Version when `ATLAS_HINDSIGHT_URL` is set. Artifacts gain `retain_jobs`. Companyfacts JSON isn't retained.
  - **Settings:** `ATLAS_RETAIN_POLL_TIMEOUT_SECONDS` (240), `ATLAS_RETAIN_POLL_INTERVAL_SECONDS` (5), `ATLAS_RETAIN_POLL_ATTEMPTS` (5).
  - **Coherent fixtures:** `tests/fixtures/edgar/coherent/`. Recorded live on 2026-09-28 with **4 SEC requests** (submissions, the FY2026 10-K `0000820318-26-000020`, the 10-Q `0000820318-26-000013`, companyfacts) as `Atlas Research ekenheim@gmail.com`, ≥2 s apart.
    - Trimming follows the Lumentum conventions: submissions to the 2026-05-06..2026-09-28 window with unrecorded 10-K/10-Q/8-K rows removed; companyfacts to dei plus the Lumentum concepts (GrossProfit is absent); the 10-K to its first 760 of 1231 top-level elements (through Item 7); the 10-Q to 59 of 456.
    - **Gap:** no Coherent 8-K. An 8-K needs its index headers plus each document (≥3 requests, with an unknown number of EX-99 exhibits), which could overrun the 6-request budget.
  - **Fake (`tests/fakes/hindsight.py`) derivations**, documented in its docstring:
    - `derive_retains` (off by default) answers an unrecorded async batch retain with `retain/04-batch`. It changes only `bank_id`, `items_count` and `operation_id` (UUIDv5 of the body). The operation is then served from `retain/05-batch-final` with only `operation_id` changed, and each document from `upsert/09-get-document` with only `id`, `bank_id`, `tags` and `document_metadata` changed.
    - `report_zero_facts` zeroes a derived document's counts.
    - `hold_retains` applies `hold_operation` to matching derived batches.
    - These derivations are needed because the recordings hold synthetic documents, so no real section's retain can match one. **Zero-fact documents, failed operations and never-finishing operations are derived, not recorded.**
- **Files:**
  - new: `backend/atlas/retention/{__init__,sections,service,handlers,reads}.py`, `backend/atlas/api/memory.py`, `backend/atlas/db/migrations/versions/0007_memory_documents.py`, `tests/fixtures/edgar/coherent/**`, `tests/integration/test_retention.py`, `tests/unit/test_sections.py`, `tests/unit/test_hindsight_fake_derivations.py`
  - small edits: `api/app.py` (router), `jobs/handlers.py` (registers the three kinds), `ledger/ingest.py` (enqueue retains), `settings.py`, `.env.example`, `configs/themes/ai-infrastructure.yaml` (Coherent comment), `tests/fakes/hindsight.py`, `tests/integration/test_ingest.py` (the no-fixtures test now removes Coherent's fixtures from a copy), `tests/integration/test_migrations.py` (head `0007`), `AGENTS.md`, `docs/data-model.md` (§3.2–3.3 as built), `docs/decisions.md`
- **Tests:** 25 new. The implementation was written just ahead of the integration suite, not strictly red first, and the suite was then checked by mutation.
  - `tests/integration/test_retention.py` (12, at the CLI + single-pass worker + API seam, real Postgres, the fake served on localhost):
    - sections, states, fact counts and tiling of the Lumentum 10-K
    - one batch per Source Version, with the exact IDs, tags, metadata, timestamp and content
    - exhibit chunks, and companyfacts not retained
    - Coherent alongside Lumentum, tagged apart
    - a replayed retain (new key via `atlas jobs enqueue retain`) sends nothing
    - a revised 8-K gets new document IDs, v1's are untouched, and DELETE or re-keying a row fails
    - an identical-bytes exhibit copy is `linked`, not re-retained
    - zero facts: reprocessed exactly once as a one-item batch, then `zero_fact`
    - a failed operation is visible with its error
    - a never-finishing operation: the poll times out twice, then the job fails, and the sections stay `pending` with status `processing`
    - no retain before a template is applied
    - 404 envelope
  - `tests/unit/test_sections.py` (9) and `tests/unit/test_hindsight_fake_derivations.py` (4).
  - Mutation checks each turned exactly their test red: disabling linking, skipping the reprocess, treating failed operations as successes, and dropping the "already retained" check.
  - `scripts/ci.sh --no-image` **passed**: ruff format/lint clean, pyright strict 0 errors, frontend gates green, **296 passed, 1 deselected** (live), 306 s.
- **Fixture-tested vs live:**
  - **Live:** only the 4 SEC requests that recorded the Coherent fixtures.
  - **Fixture only:** every Hindsight interaction, against the recorded fake with the derivations above. No live Hindsight or LLM call was made.
  - **Never tested against a real server:** the batch retain of real sections, per-document memory counts, zero-fact behaviour and failed operations.
- **Deviations and notes:**
  - PKs are `id` (the data model said `memory_document_id`).
  - Added columns: `section_heading`, `sectioner_version` and `error` on `memory_document`; `source_version_id`, `document_ids` and `result_metadata` on `hindsight_operation`.
  - Not built: `memory_ids_json` (Hindsight's document read gives counts, not IDs) and `error_class` (ticket 14).
  - Reprocess uses a re-retain under the same ID, because the documents `reprocess` route is unrecorded.
  - A zero-fact section awaiting reprocess is `pending` with fact count 0.
  - Retains don't start a `run` yet; `result_metadata.total_tokens` is stored per operation.
  - Failed sections aren't retried automatically, and a poll that exhausts its attempts leaves the operation unfinished (ticket 14's pause/backoff should revisit both).
  - Coherent's COHR security is still a TODO.
- **Credentials:** none.
- **Next:**
  - ticket 14: classify operation errors, pause the queue on 429, and back off the poll retries
  - ticket 15: resolve memories through `document_id` + `metadata.source_version_id` to `memory_document` rows
  - record a real retain of an Atlas section, a zero-fact document, and a failed operation against the spike, to replace the derivations
## 2026-09-29: ticket 09, source viewer (read-only)

- **Built:**
  - **Typed API client.**
    - `scripts/export_openapi.py` writes the FastAPI schema. It builds the app with placeholder settings, and no connection is opened.
    - `scripts/gen_api_client.sh` runs the export and then `openapi-typescript` 7.13. The results are committed as `frontend/lib/api/openapi.json` and `schema.ts`, marked `linguist-generated`.
    - `frontend/lib/api/client.ts` is a thin `fetch` wrapper typed from the generated `paths`: route, path and query params, and the 200 body. It throws `ApiError` carrying the error envelope's code and message.
    - CI runs `gen_api_client.sh --check`, which regenerates into a temp dir and diffs against the committed files.
  - **Pages.** All are static and client-fetched, with ids as `?id=` (no dynamic routes):
    - `/`: companies
    - `/company/`: the company and its Source Documents
    - `/source/`: the Source Document and its version history
    - `/version/`: the Source Version, with:
      - the provenance panel: URL (plus the origin URL when it differs), accession, form, publisher/tier/licence, raw, content and comparison SHA-256 (with the rule), bytes and media type, archive and parsed object URIs, parser version, parse status/error, fetch status, and supersedes/superseded-by links
      - a timestamps table: `available_at` with its recorded basis, and `published_at`, `event_at`, `fetched_at`, `first_seen_at` and `ingested_at`, each with what its clock means. An absent clock shows "not recorded".
      - source metadata
      - fetch observations
      - the parsed text in a `<pre>`, and a "Download original bytes" link to `content?kind=raw`
  - The UI is plain and accessible: semantic tables with row and column headers, labelled regions, loading and error states in `role=status`/`alert`, a skip link, and no design system.
  - **Playwright smoke test.** `frontend/e2e/source-viewer.spec.ts` and `frontend/playwright.config.ts`, driven by `scripts/e2e.py`. `scripts/ci.sh` gained two steps: the client check after typecheck, and `uv run python scripts/e2e.py` after pytest, while the Compose services are up and the frontend is built.
- **How the Playwright test gets its data:** `scripts/e2e.py` does all of it.
  1. It installs chromium (`--with-deps` when `CI` is set) and probes that it launches.
  2. It creates an empty database `atlas_e2e_<hex>` on the test Postgres (`ATLAS_TEST_DATABASE_URL`, default `127.0.0.1:55432`).
  3. It seeds that database through the public CLI, the same path as ticket 07's gate tests: `atlas migrate`, `atlas ingest --company lumentum --key e2e-smoke` and `atlas worker --once`. These run with `ATLAS_SEC_FIXTURES_DIR=tests/fixtures/edgar`, a temporary filesystem archive and a clean env, in a temp cwd so no developer `.env` is read. That replays the recorded Lumentum EDGAR filings.
  4. It starts uvicorn in-process on a free `127.0.0.1` port (never 55432, 59000, 58000 or 58080). `ATLAS_FRONTEND_DIR=frontend/out` puts the built export on the same origin as `/api/v1`.
  5. It runs `playwright test` with `ATLAS_E2E_BASE_URL`, then stops the API and drops the database.

  The spec's expected values come from the fixture files, never from the API:
  - accession and URL from the manifest
  - raw SHA-256 of the fixture bytes
  - content SHA-256 from `tests/fixtures/parser/golden.json`
  - `available_at` = the submissions `acceptanceDateTime`

  The test clicks from the company list to the FY2026 10-K's version 1. It then asserts each provenance row, that `available_at` has basis `sec_acceptance`, that `published_at` is "not recorded", and that `fetched_at` and `first_seen_at` hold timestamps. It also checks that the hash of the rendered parsed text equals the golden content hash (so the whole text is on the page), and that the downloaded original bytes hash to the fixture's SHA-256.
- **Files:**
  - new:
    - `scripts/{export_openapi.py,gen_api_client.sh,e2e.py}`
    - `frontend/lib/api/{openapi.json,schema.ts,client.ts}`, `frontend/lib/{use-api.ts,routes.ts}`, `frontend/components/ui.tsx`
    - `frontend/app/{globals.css,company/page.tsx,source/page.tsx,version/page.tsx}`
    - `frontend/e2e/source-viewer.spec.ts`, `frontend/playwright.config.ts`
  - edited:
    - `frontend/app/{layout,page}.tsx`
    - `frontend/package.json`/`package-lock.json` (dev deps `openapi-typescript`, `@playwright/test`, plus an `overrides` entry, see below)
    - `frontend/.gitignore`, `.dockerignore` (Playwright output)
    - `.gitattributes`, `scripts/ci.sh`, `AGENTS.md`, `docs/architecture.md`
  - No backend, migration or Python dependency changes.
- **Tests (actual results):**
  - Red first: the spec failed against the old skeleton page (no "Lumentum" link), while seeding and serving worked.
  - Green: 1 passed (≈3.5 s).
  - Mutation checks went red as expected:
    - rendering `text.slice(1)` failed the parsed-text hash
    - showing `fetched_at` in the `available_at` row failed the acceptance-time check
  - `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64 scripts/ci.sh --no-image` **passed**: ruff/pyright clean, lint/typecheck, "API client is current with the OpenAPI schema", build, **271 passed, 1 deselected** (live) in 199 s, and e2e **1 passed**.
  - Without the override, this Ubuntu 20.04 WSL box prints `e2e: SKIPPED: ... Playwright does not support chromium on ubuntu20.04-x64` and continues (exit 0). That is the local skip path.
- **Fixture vs live:** everything is fixture-seeded. No SEC or other network access beyond localhost, apart from npm and Playwright downloading packages and chromium. The CI path with `--with-deps` on GitHub's ubuntu-latest runner has **not run yet**; it runs on the next push.
- **Deviations:**
  - `openapi-typescript` 7.13 declares a peer of `typescript ^5`, and the repo pins TypeScript 6. `package.json` `overrides` points its peer at the root `typescript`; generation works with TS 6.
  - In CI, a browser that can't be installed or launched **fails** the step instead of skipping, so the gate can't silently disappear. Locally it skips with the reason and a hint (including `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE`).
  - The API is started with uvicorn in-process rather than via `atlas api`, which hard-codes port 8000. This avoids touching `cli.py`.
  - The Playwright test is Node (`@playwright/test`) orchestrated by a Python script, not a pytest test, so `uv run pytest` is unchanged.
  - "Toggle" between parsed text and raw (story 48) is the parsed text shown, plus the download link beside it.
  - Selection-to-Assertion and the Assertion list are out of scope (ticket 08 and later).
- **Credentials:** none.
- **Next:** the Assertion viewer ticket adds selection-to-Assertion on the parsed `<pre>` and the review list. Run `scripts/gen_api_client.sh` after ticket 08's routes merge, or CI's `--check` will fail. Confirm the e2e step on the first GitHub Actions run.
## 2026-09-29: ticket 10, Assertions in the viewer

- **Built:** on the Source Version page (`/version/?id=`), below the parsed text:
  - **New Assertion.** Selecting a passage in the parsed text quotes it in a form. The form shows the exact quote and its character offsets, and has:
    - the subject: the Source Document's company, read-only
    - a predicate (required)
    - an optional object company
    - an optional value, as JSON
    - an optional page or anchor
    - an epistemic type (required, no default)

    It posts to `POST /api/v1/assertions` with the quote and offsets. A refusal is shown in an alert with the API's code and message, for example `quote_mismatch: … it occurs at [186, 212)`. The form and selection stay put so they can be corrected. Success shows the new Assertion's ID and audit event ID in a status line and clears the selection.
  - **Offsets** (`frontend/lib/offsets.ts`). The parsed text is rendered verbatim as one text node in a `pre-wrap` `<pre>`, so a DOM offset in it is a UTF-16 index into the parsed text.
    - `utf16OffsetsIn` measures a Range against the element with `Range.toString()`, clipping a selection that reaches outside it.
    - `spanFromUtf16` converts to code points (Python `str` indices, which is what the API compares). A boundary between the halves of a surrogate pair widens to the whole character.
    - The quote is sliced from the API's text, not taken from `Selection.toString()`.
    - The page listens to `selectionchange`, so a keyboard selection (caret browsing) should be picked up as a mouse selection is. Only mouse selection is tested.
  - **Assertions list.** A table of the version's Assertions from `GET /api/v1/assertions?source_version_id=`, with:
    - quote, characters and anchor
    - predicate, object and value
    - who recorded it and when
    - epistemic type
    - review state, with reviewer and time
    - the successor, if superseded

    Each row's review buttons follow ticket 08's transitions (`frontend/lib/assertions.ts` mirrors `docs/decisions.md`; the API stays authoritative):
    - an open state (`unreviewed`, `corroborated`, `disputed`) offers Corroborate, Dispute and Reject (never its own state, never back to unreviewed), plus Supersede with a Successor select of this version's other open Assertions
    - `rejected` and `superseded` show "final" with no actions

    A review replaces the row with the API's answer, and a status line gives the audit event. A refusal (such as 409 `invalid_transition`) shows the API's reason in an alert. Focus moves to the row's new state, since the button pressed may be gone.
  - **Client** (`frontend/lib/api/client.ts`): a typed `post` over the generated `paths` (request body, and the 200/201 answer), `api.versionAssertions`, `api.createAssertion` and `api.reviewAssertion`. There are no new API routes, so the generated `schema.ts` is unchanged.
  - **Frontend unit tests:** `frontend/unit/*.test.ts`, run by Playwright's test runner via `playwright.unit.config.ts` (no browser, no second framework), as `npm --prefix frontend run test`. `scripts/ci.sh` runs it after typecheck.
- **Files:**
  - new: `frontend/components/assertions.tsx`, `frontend/lib/{offsets,assertions}.ts`, `frontend/e2e/assertions.spec.ts`, `frontend/unit/offsets.test.ts`, `frontend/playwright.unit.config.ts`
  - edited: `frontend/app/version/page.tsx` (`Content` loads the text once, for the `<pre>` and the Assertions), `frontend/lib/api/client.ts`, `frontend/app/globals.css`, `frontend/package.json` (`test` script, no new dependencies), `scripts/ci.sh` (the unit-test step and step labels), `scripts/e2e.py` (docstring), `AGENTS.md`
  - No backend, migration, Python dependency or API client regeneration changes.
- **Tests:**
  - `frontend/unit/offsets.test.ts` (10) was written first and went red (9 failed against a stub). The offsets are hand-counted from constructed strings:
    - ASCII
    - curly quotes before the span (BMP: one unit each, but three UTF-8 bytes)
    - 😀 before the span (UTF-16 3..10 → code points 2..9)
    - several astral letters before
    - an astral character inside the span
    - boundaries inside a surrogate pair
    - tabs and newlines counted verbatim
    - the quote equals the code-point slice
    - an empty selection
    - out-of-range offsets
  - `frontend/e2e/assertions.spec.ts` (2, real chromium, real API on the fixture-seeded database). The quotes and offsets are ticket 08's hand-checked values from the recorded EX-99.1. The test first checks that the page's text hashes to the golden `html-text-v1` hash, so those offsets hold for what is shown.
    1. The test clicks through to the press release. It selects the revenue sentence (1604–1676, after curly quotes, bullets and a dash) **with the mouse**, pressing inside its first character and releasing inside its last. It then checks the selection's text, the quote and characters shown, the subject, and the posted body (quote, offsets, predicate, value, anchor, epistemic type). The row shows `unreviewed` by `e2e-smoke`, with actions Corroborate/Dispute/Reject. Dispute and then Corroborate each update the state, the reviewer and the offered actions. A second Assertion (546–598, curly quotes inside the span) makes Supersede appear on the first. Superseding the first by it shows the successor and no actions; rejecting the second leaves it final. After a reload, both states come from the API.
    2. The test serves the parsed text with `😀 ` before it (a Playwright route). The margin quote then selects as 188–214 in code points, where UTF-16 would give 189–215, and that is what is posted. The real API refuses it, and the alert shows `quote_mismatch`, `[188, 214)` and "it occurs at [186, 212)". No row is added, and the form keeps the quote.
  - Mutation checks went red as expected:
    - sending the raw UTF-16 offsets failed e2e test 2 ("Characters 189–215") and 5 unit tests
    - offering "back to unreviewed" failed e2e test 1's action list
  - `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64 scripts/ci.sh --no-image` **passed**:
    - ruff clean, pyright strict 0 errors
    - lint, typecheck, frontend unit tests **10 passed**, API client current, build
    - pytest **342 passed, 1 deselected** (live) in 410 s
    - e2e **3 passed** (the 2 new plus ticket 09's smoke test)
- **Fixture vs live:** everything ran against the recorded Lumentum EDGAR fixtures, a local filesystem archive, the Compose Postgres, and chromium on this WSL box via the platform override. Nothing live beyond localhost. GitHub Actions' `--with-deps` path for the new specs hasn't run yet.
- **Deviations:**
  - The Supersede control only offers successors among this Source Version's open Assertions. The API accepts any open Assertion (for example, a correction citing a newer version), but the viewer has no cross-version picker yet.
  - The list takes one page of 500. A version with more Assertions would need paging.
  - The value field takes JSON only: plain text must be quoted (`"…"`). A non-JSON value is refused in the form, and nothing is sent.
  - `event_start`/`event_end` aren't in the form, since the ticket's form doesn't list them. The API accepts them.
  - There's no highlighting of existing Assertions in the text yet. `utf16OffsetsIn` already measures across element boundaries, so highlights won't break selection offsets.
- **Credentials:** none.
- **Next:** a cross-version successor picker, and highlighting Assertion spans in the text. Confirm the e2e step on the first GitHub Actions run.

## 2026-09-29: ticket 14, queue pause and pacing

- **Built:**
  - **Alembic revision `0008`** (down_revision `0007`):
    - `job.job_class` (`interactive`/`backfill`)
    - `hindsight_operation.error_class` (`quota`/`unavailable`/`permanent`)
    - the single-row `queue_pause` table (level, class, reason, kinds, backoff, paused/resume/episode/cleared times, the causing job), with checks tying the fields to `level > 0`
    - the append-only `queue_pause_event` history
    - grants to `atlas_app` when it exists
  - **`atlas.jobs.pacing`:**
    - failure classification. Quota is a 429 or a rate-limit or insufficient-quota message; unavailable is 502–504 or a connection failure to Hindsight or LiteLLM. Only dependency exceptions and operation errors are classified, never arbitrary exception text.
    - `TransientFailure`, `BackfillWindow` (`HH:MM-HH:MM` in a timezone, wrapping midnight) and `Pacing` (backoff 60 s × 2^(level−1), capped at 1 h)
  - **Queue and worker:**
    - A pausable kind's quota or outage failure pauses the queue (`JobQueue.pause`). The job is requeued without using up its attempt, and the failure is recorded with its classification.
    - A failure during an active pause doesn't escalate it.
    - Claiming skips paused kinds until `resume_after`, and backfill jobs outside the window.
    - A pausable success after the resume time clears the level.
    - Pacing uses an injectable clock; leases keep the DB clock.
    - `HandlerRegistry.register(..., pausable=True)`; retention registers `retain`, `poll_operation` and `reprocess` that way.
  - **Retention:**
    - A failed operation is classified from its error and its sub-batches' errors.
    - For quota or unavailable, the operation is recorded with `error_class`, the sections stay `pending`, and `TransientFailure` is raised. After the pause, the poll job's next attempt resubmits the same sections as a new operation (`memory_document.resubmitted`), without counting a reprocess twice.
    - Permanent failures behave as in ticket 13.
    - Backfill class propagates: a backfill ingest's retains are backfill, and a reprocess takes the class of the job that submitted the operation. Polls are always interactive.
    - `GET /source-versions/{id}/memory` operations now show `error_class`.
  - **`GET /api/v1/queue`:** the pause (paused, level, class, reason, kinds, backoff, paused at, resume after, episode start, cleared at, total pauses), the backfill window (open, next opening) and pending jobs by kind (queued, running, backfill queued, paused). `create_app(settings, clock=...)` is new.
  - **CLI:** `atlas ingest --backfill` and `atlas jobs enqueue --backfill`. The enqueue output now includes `job_class`. `atlas worker` applies the pacing from settings.
  - **Settings:** `ATLAS_BACKFILL_WINDOW` (`01:00-07:00`; empty means any time), `ATLAS_BACKFILL_TIMEZONE` (`UTC`), `ATLAS_QUEUE_PAUSE_BASE_SECONDS` (60) and `ATLAS_QUEUE_PAUSE_MAX_SECONDS` (3600, at most 3600), all validated at startup.
  - **Metrics** (`atlas.metrics.StateCollector` on the API's per-app registry, read from the database at scrape time):
    - `atlas_queue_paused`, `_pause_level`, `_pause_backoff_seconds`, `_pause_duration_seconds` and `atlas_queue_pauses_total{error_class}`
    - `atlas_queue_jobs{kind,job_class,status}` and `atlas_jobs_failed_total{kind}`
    - `atlas_hindsight_operations_total{kind,status,error_class}`
    - `atlas_retained_sections_total{outcome}` and `atlas_memory_sections_pending`
    - `atlas_zero_fact_sections_total`
    - `atlas_state_metrics_up` (0 when the database can't be read)
  - **Alert rules:** `configs/prometheus/atlas-alerts.yaml`, a PrometheusRule covering repeated permanent operation failures, repeated job failures, a zero-fact spike, a pause longer than 2 h and unreadable metrics. **Not deployed.**
  - **Fake:** `hold_operation`/`hold_retains` take an optional `error_message`, and `hold_retains` takes `times`. A repeated identical derived retain now gets a new operation ID (the first ID is unchanged).
- **Files:**
  - new: `backend/atlas/jobs/pacing.py`, `backend/atlas/api/queue.py`, `backend/atlas/metrics.py`, `backend/atlas/db/migrations/versions/0008_queue_pause.py`, `configs/prometheus/atlas-alerts.yaml`, `tests/integration/test_queue_pause.py`, `tests/unit/test_alert_rules.py`
  - edited: `jobs/{__init__,queue,worker,handlers}.py`, `retention/{service,handlers,reads}.py`, `ledger/ingest.py` (one call), and small additive edits to `api/app.py`, `cli.py` and `settings.py`
  - also edited: `tests/fakes/hindsight.py`, `tests/unit/{test_hindsight_fake_derivations,test_settings}.py`, `tests/integration/test_migrations.py` (head `0008`), `frontend/lib/api/{openapi.json,schema.ts}` (regenerated), `.env.example`, `AGENTS.md`, `docs/{decisions,data-model}.md`
  - The branch was fast-forwarded to `main` (ticket 09) first, to get `scripts/gen_api_client.sh`.
- **Tests:** 19 new, and `scripts/ci.sh --no-image` **passed**: ruff/pyright clean, frontend gates green, API client current, **361 passed, 1 deselected** (live), 386 s.
  - The e2e step skipped locally (ubuntu20.04). Re-run with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`: 1 passed.
  - The implementation came just ahead of the tests, not strictly red first. The tests were then checked by mutation.
  - `tests/integration/test_queue_pause.py` (9, at the CLI + single worker pass + API seam, with a controllable pacing clock, real Postgres and the fake on localhost):
    - a 429 operation failure pauses for 60 s. Its sections stay pending and the poll job is requeued at 0 attempts with classification `quota`. Nothing is claimed and Hindsight hears nothing at +59 s. At +60 s the identical batch is resubmitted and completes, and the pause clears.
    - an outage (Hindsight on a closed port) gives backoffs of exactly 60, 120, 240, 480, 960, 1920, 3600 and 3600 s. The retain job is never failed. It succeeds when Hindsight is back, and a later outage restarts at 60 s.
    - an unrelated operation error fails its sections as `permanent` without pausing
    - a pausable job failing for its own reason (no template) exhausts its retries without pausing
    - the window gates backfill jobs, for `01:00-07:00 Europe/Stockholm` (end exclusive) and `22:00-06:00 UTC` (wrapping), including `next_open_at`
    - a backfill ingest waits for the window, and its retains and reprocess are backfill while polls are interactive
    - the metrics during and after a pause, with a zero-fact section. Every metric the alert rules reference is exposed.
    - an unreadable database gives `atlas_state_metrics_up 0`
  - Unit tests: 8 settings validation cases, 1 alert-rule structure test, and 1 fake derivation test (error message and `times`). The existing derivation test now expects a new operation ID for a repeated identical batch.
  - **Mutation checks**, each going red as expected:

    | Mutation | Tests that failed |
    |---|---|
    | Disabling classification | 3 |
    | Removing the 1 h cap | the backoff test |
    | Removing the window gate | 3 window tests |
    | Never clearing | 2 |
    | Classifying every error as quota | the unrelated-failure test |
    | Burning the attempt on a pause | 2 |
    | Removing the pause gate from the claim | the worker pass loops forever; the run hung and was killed |
  - The alert rules' spec groups passed `promtool check rules` (prom/prometheus v3.5.0, one-off container): `SUCCESS: 5 rules found`.
- **Fixture-tested vs live:**
  - **Everything is fixture or localhost.** No live Hindsight, LiteLLM or MiniMax call was made.
  - **The quota error text is derived, not recorded:** an OpenAI-style `Error code: 429 ... RateLimitError`. The spike saw no 429. How Hindsight 0.10.1 actually reports a model 429 in `error_message` (and whether it retries internally first) is unverified.
  - The outage path used a real refused connection.
  - The alert rules were checked with promtool but never loaded into a Prometheus.
- **Deviations and notes:**
  - There's no per-job `run_after` backoff (data model §2.7 marks it not implemented); backoff is queue-level.
  - Pauses aren't audit events. They're operational state, kept in `queue_pause_event`.
  - "Clears on the next success" means the first pausable success at or after `resume_after`. A success during an active pause (a job in flight when it began) doesn't lift it early.
  - Backfill is a job class, not a kind set. A backfill ingest job (SEC fetching) also waits for the window.
  - A resubmitted operation's `job_id` is the original submitting job, not the poll job, so class inheritance holds.
  - There are no `reflect` or `refresh_mental_model` jobs yet. The LiteLLM side of the classifier (httpx2 transport errors and HTTP status errors) has no LLM-backed job to exercise it.
  - The frontend shows no queue page. The pause is visible through the API and metrics.
- **Credentials:** none.
- **Next:**
  - home-ops: include `configs/prometheus/atlas-alerts.yaml` in the atlas Kustomization, plus a ServiceMonitor for the API's `/metrics`.
  - Record a real Hindsight failed operation under a LiteLLM 429 (and a 503) against the spike, to replace the derived error text.
  - Tickets adding `reflect`/`refresh_mental_model` register them with `pausable=True`.

## 2026-09-29: ticket 15, recall and reflect with resolved citations

- **Built:**
  - **Alembic revision `0009`** (down_revision `0007`; the lead re-chains it at merge): `research_answer` with the question, applied scope (company IDs, theme slugs, and the tags and `tags_match` sent), the optional response schema, status (`pending`/`completed`/`failed`), answer text, structured output and its error, raw citations, citations with states, the quote rule, the run, the reflect job's ID, an error, and timestamps. CHECKs tie `completed` to its outcome columns and `failed` to an error, and structured output to a schema. An ENABLE ALWAYS trigger allows updates only of a `pending` row, never of its question, scope, schema, bank or job, and rejects DELETE and TRUNCATE. `atlas_app` gets SELECT/INSERT/UPDATE.
  - **`atlas.research`:**
    - `provenance`: the resolver. It takes observation → `source_memory_ids` → world fact → `document_id` → the `memory_document` row (Source Version, section, `available_at`), and checks that `metadata.source_version_id`/`section_anchor` agree with the ledger. Each answer quote is searched in the parsed text of the sections the resolved citations lead to. States: **resolved**, **unverified** (`no_memory_id`, `not_an_atlas_document`, `unknown_document`, `metadata_mismatch`, `no_source_memories`, `too_many_hops`, `quote_mismatch`) and **broken** (`memory_not_found`, `source_memory_not_found`). An observation takes its worst hop's state. `evidence_from` groups only resolved citations by section, with their matched quote spans.
    - `quotes`: the rule `whitespace-and-typographic-quotes-v1` (normalizes only whitespace runs and ‘’‚‛“”„‟), quote extraction from the answer's double-quoted passages, and span mapping back to the original code-point offsets. The rule is recorded in `docs/decisions.md` and stored on each answer.
    - `service`: scope → `company:<uuid>`/`theme:<slug>` tags matched `any_strict` (unknown companies or themes are refused with 422 before any call); synchronous `recall`; `request_reflect` records a pending answer (audited `research_answer.requested`) and enqueues `reflect`; the `reflect` job starts a `run` when LiteLLM is configured, calls reflect with `include.facts`, resolves, validates structured output with `jsonschema`, and stores it (`research_answer.answered`). The last failed attempt marks the answer `failed` (`research_answer.failed`).
    - `reads` and `handlers` (registers the `reflect` kind in `builtin_registry`).
  - **API:** `POST /api/v1/memory/recall` (memories with provenance, per-state counts, Evidence), `POST /api/v1/memory/reflect` (202: the pending answer, `job_id`, `audit_event_id`), and `GET /api/v1/memory/reflect/{id}` (answer, structured output and error, raw citations, citations with states, counts, `evidence` (resolved only), `evidence_missing`, quote rule, run, job status). Errors: 422 `unknown_company`/`unknown_theme`/`invalid_response_schema`/`invalid_request`, 503 `hindsight_not_configured`, 502 `hindsight_unavailable`/`hindsight_error`, 404.
  - **API client** regenerated (`scripts/gen_api_client.sh`).
  - **Fake derivations** (`tests/fakes/hindsight.py`, documented in its docstring): `derive_memories` (one world fact per derived document from `reflect/06-resolve-source-memory`; `derive_observation` from `reflect/02-resolve-memory`; strict-tag recalls from `tags/02-tags-any_strict`), `forget` (a 404 with a **hand-written** body: a deleted memory was never recorded), and `script_reflect` (`reflect/01-provenance` with the text, `based_on.memories` and structured output replaced; `ChunkContent` gives an `id: null` citation). Each changes only the named fields.
- **Files:**
  - new: `backend/atlas/research/{__init__,provenance,quotes,service,reads,handlers}.py`, `backend/atlas/api/research.py`, `backend/atlas/db/migrations/versions/0009_research_answer.py`, `tests/integration/test_research.py`
  - small edits: `api/app.py` (router), `jobs/handlers.py` (registers `reflect`), `pyproject.toml`/`uv.lock` (`jsonschema` runtime, `types-jsonschema` dev), `tests/fakes/hindsight.py`, `tests/unit/test_hindsight_fake_derivations.py`, `tests/integration/test_migrations.py` (head `0009`), `frontend/lib/api/{openapi.json,schema.ts}`, `AGENTS.md`, `docs/decisions.md`, `docs/data-model.md` (§3.4 as built)
  - The branch was fast-forwarded to `main` (ticket 09's client generator) before starting.
- **Tests:** 20 new: 16 integration (`tests/integration/test_research.py`, real Postgres with a fresh DB each; CLI apply-template and ingest + single worker passes + `/api/v1`; the fake served on localhost with `derive_memories`; the LiteLLM `/model/info` fake so runs are recorded) and 4 unit (fake derivations).
  - The implementation was written just ahead of the gate tests, **not strictly red first**; the suite was then checked by mutation.
  - Gate scenarios: cross-company recall (Lumentum + Coherent) with each memory resolved to its Source Version, section, offsets and `available_at`; strict scoping (one company, a theme); unknown/empty scope refused with no Hindsight call; recalled and cited observations resolved through both source facts; an observation with a deleted source is broken; a chunk-only answer is unverified (and its verbatim quote too, since nothing resolved leads to a section); typographic-apostrophe and line-break quotes resolve to the exact archived span, while a paraphrase, a case change and a quote from another section of the same 10-K are unverified; a deleted cited memory is broken and not Evidence; unknown documents and metadata that disagrees with the ledger are unverified; reflect runs as a job (pending → completed, the request sent, raw citations, states, run recorded and finished, audit `requested`/`answered`, `atlas audit verify` exits 0); structured output valid, schema-invalid and Hindsight-errored; union-type and non-object schemas refused before anything is recorded; a reflect that keeps failing ends `failed` after 3 attempts with the error audited; a stored answer is final in the database; 404 and 503.
  - Quotes, offsets and chunk text are hard-coded from the recorded EDGAR fixtures' parsed text.
  - Mutation checks went red as expected: chunks resolved, observations treated as facts (3 tests), a missing source memory ignored, a deleted cited memory resolved, quotes searched in the whole parse instead of the cited sections (after I added the out-of-section quote; the first run missed it), metadata not checked (after I added that test), structured output not validated, case folding and newline-blind whitespace. "Evidence from any state" survived, because unresolved citations already carry no sources (the check is redundant by construction).
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`) **passed**: ruff format/lint clean, pyright strict 0 errors, frontend gates and "API client is current", **362 passed, 1 deselected** (live) in 457 s, e2e 1 passed.
- **Fixture-tested vs live:**
  - **Fixture only:** every Hindsight interaction. Real-section facts, observations, strict recalls over them, deleted memories (404) and reflect answers citing them are **derived**; the answer texts are written by the tests. No live Hindsight or LLM call was made.
  - **Never tested against a real server:** a reflect `based_on` entry with `id: null` (the OpenAPI schema allows it, the bake-off saw chunk-sourced content, but no recording has one); the 404 body for a deleted memory; whether an observation keeps a deleted source's ID in `source_memory_ids`; recall of observations over Atlas-tagged facts; the tags an observation inherits.
- **Deviations and notes:**
  - Scope is a union (`any_strict` over all company and theme tags); there's no company ∧ theme intersection, since one strict mode applies to all tags.
  - Quotes are only the answer text's double-quoted passages; memory texts are never quote-validated (Hindsight rewrites facts); structured-output strings aren't scanned for quotes.
  - Recall isn't stored. `research_answer.job_id` has no FK: the job is enqueued right after the row commits. `evidence` and `evidence_missing` are derived on read. `run_id` is null when LiteLLM isn't configured.
  - Only resolved citations carry `sources`, so a broken or unverified observation doesn't show which of its hops still resolved.
  - Column names follow the repo conventions (`id`, `scope`, `citations`) rather than `docs/data-model.md`'s `*_json`; the data model now says so.
- **Credentials:** none.
- **Next:**
  - ticket 16: mental-model citations can reuse `ProvenanceResolver.resolve_answer`
  - record against the spike: a reflect whose `based_on` has an `id: null` entry, a deleted memory's 404, and consolidated observations over retained Atlas sections, to replace the derivations
  - the viewer can link resolved quote spans straight to Assertion creation (same code-point offsets)

## 2026-09-29: ticket 17, live test suite (built; **not run live**)

- **The live suite has NOT been run against real Hindsight, LiteLLM or MiniMax.**
  - A run spends the owner's MiniMax quota and needs their go-ahead.
  - Nothing in this entry is a live result: no Hindsight container was started, no LiteLLM endpoint (not even `/model/info`) was called, and no model was called.
  - How to run it: `docs/runbooks.md`, "Live test suite". Short version: `scripts/live-tests.sh --rehearse`, then `scripts/live-tests.sh --stop-before-llm --model MiniMax-M3`, then `scripts/live-tests.sh --model MiniMax-M3 [--profile full] [--down]`.
  - Record the first live run here from the `summary.md` it writes.
- **Built:**
  - **`tests/live/test_phase2_gate_live.py`**: the Phase 2 gate scenarios end to end, at the gate tests' seam (CLI apply-template and ingest, single worker passes, `/api/v1`). They share one run through module-scoped fixtures:
    - a preflight
    - the bank template applied (the bank config matches the file)
    - both companies' fixtures ingested as parsed Source Versions (forms `ATLAS_LIVE_FORMS`)
    - retain and wait for the operations: worker passes until no job is queued or running, waiting out queue pauses (recorded), up to a deadline. Then every section is in a final state, every operation completed, and every completed section has facts.
    - a bounded wait for consolidation (the observation count holds steady)
    - cross-company recall (`any_strict` over both companies): both companies present, and every memory resolved to its Source Version, section offsets and `available_at`
    - a reflect over the photonics theme. It completes with a run recorded, nothing is broken, every cited memory resolves, and Evidence exists. Unverified chunks and quotes are reported with their reasons, not failed.
    - zero-fact visibility: `fact_count` 0 and `reprocess_count` 1, matching the per-state counts and `atlas_zero_fact_sections`. It is skipped, saying so, if the run produced no zero-fact section.
    - Hindsight's LLM request stats, recorded

    Because the model's answers aren't scripted, the live assertions are those any correct answer must meet.
  - **`tests/live/stack.py`**:
    - the opt-in (`ATLAS_LIVE_TESTS=1` live, `=rehearse` for the fakes; anything else skips)
    - `ATLAS_LIVE_STOP_BEFORE_LLM`
    - the stack config (Hindsight URL, default the Compose profile's `:58888`; the LiteLLM URL/key; the aliases; a fresh bank `atlas-live-<stamp>` per run; poll timings 240 s × 15 attempts; deadlines)
    - the preflight
    - a fresh app database per run (`atlas_live_*`, dropped unless `ATLAS_LIVE_KEEP_DATABASE`)
    - the rehearsal: the recorded Hindsight fake with `derive_memories`, zero facts for cover sections, one derived observation over both companies' Item 1 facts, and a scripted reflect citing those facts, the observation, a raw chunk, two verbatim quotes and one paraphrase; plus the `/model/info` fake, all on localhost
    - `LiveReport`, which writes `results.json` and `summary.md` to `ATLAS_LIVE_RESULTS_DIR`
  - **The preflight** refuses a live run with `pytest.exit` (status 4) when:
    - `CI` is set
    - the LiteLLM settings are missing
    - Hindsight is unhealthy, unreachable or not 0.10.1
    - an alias isn't routed (the message suggests `--model MiniMax-M3`)
    - the app Postgres is unreachable

    It reads only `/health`, `/version` and `/model/info`.
  - **`tests/live/conftest.py`**: the scenarios are skipped unless `ATLAS_LIVE_TESTS` opts in (they are still collected). A rehearsal may reach localhost only (`allow_hosts`). Each scenario's outcome is kept for the report.
  - **`scripts/live-tests.sh`**, the runner:
    - refuses under `CI`
    - takes LiteLLM from `ATLAS_LITELLM_*` or the `.env`'s `LITELLM_*` (CRLF-safe, never printed)
    - starts `postgres-app` only if nothing answers on 55432
    - brings up the stack: the Compose `hindsight` profile (default), `spikes/hindsight/run.sh MiniMax-M3 '{"thinking":{"type":"disabled"}}'` (`--stack spike`), or an existing one (`--stack none`)
    - waits for `/health`
    - asks for confirmation before a live run (unless `--yes`)
    - runs the suite and records `summary.md`, `results.json`, `junit.xml` and `pytest.log` under `.scratch/live-runs/<stamp>-<mode>/` (gitignored)
    - with `--down` (`--purge` also removes the volume), removes only `hindsight`/`hindsight-db` afterwards, via a trap
    - other flags: `--rehearse`, `--stop-before-llm`, `--profile small|full` (`10-Q`, ~18k chars; or all recorded filings, ~470k chars), `--model`, `--keep-db`, `--results` and `--dry-run`
  - **`tests/unit/test_live_suite_guard.py`**, which runs pytest in a subprocess with the opt-in removed, checks three things:
    - the default run (CI's) deselects all 8 scenarios
    - `-m live` without the opt-in skips all 8, with the reason
    - an opted-in live run under `CI` exits 4, refused
- **Files:**
  - new: `tests/live/{stack,test_phase2_gate_live}.py`, `tests/unit/test_live_suite_guard.py`, `scripts/live-tests.sh`
  - edited: `tests/live/conftest.py`, `docs/runbooks.md` (the "Live test suite" section), `README.md`, `AGENTS.md`, `.gitignore`, and this ticket
  - no migrations, no app code and no shared settings changed
  - The branch was fast-forwarded to `main` (ticket 15) first.
- **Tests (actual results):**
  - Collection: the default `uv run pytest tests/live --collect-only` gives `no tests collected (9 deselected)`. `-m live` collects the 8 scenarios and the SEC smoke test.
  - `-m live` without the opt-in: `8 skipped`, "live Phase 2 suite not enabled: set ATLAS_LIVE_TESTS=1 …".
  - **Rehearsal** (`ATLAS_LIVE_TESTS=rehearse`, and again through `scripts/live-tests.sh --rehearse`): **7 passed, 1 skipped** (LLM usage: "a rehearsal makes no LLM calls"), in ~13 s. It showed:
    - two 10-Q Source Versions
    - both cover sections `zero_fact` after one reprocess (metric 2)
    - recall of 3 memories (1 observation, 2 world facts), all resolved, across both companies
    - a reflect with 5 resolved and 2 unverified citations (the chunk `no_memory_id`, the paraphrase `quote_mismatch`), a run recorded, and 2 Evidence sections
    - a `summary.md` and `results.json` written
  - **Stop before LLM**, rehearsed (`ATLAS_LIVE_STOP_BEFORE_LLM=1`): 3 passed (preflight, template, ingest) and 5 skipped ("stopped before LLM-backed calls").
  - **Refusals**, each exiting 4 with a `results.json` holding the reason:
    - an unreachable Hindsight (a closed localhost port)
    - `CI=1`
    - missing LiteLLM settings
  - **Runner:**
    - `--dry-run` printed the Compose and spike bring-up and teardown commands (`--down --purge`) and ran nothing
    - with no LiteLLM settings: exit 2
    - under `CI`: exit 2
    - unconfirmed (stdin closed): exit 2, "nothing was run"
    - `--stack none --yes` against a closed port: exit 4, "refused … nothing was sent to a model"
  - **Mutation checks** on the guard tests: removing the conftest skip turned the "skips without opt-in" test red, and removing the preflight's CI check turned the CI-refusal test red.
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`) **passed**: ruff format/lint clean, pyright strict 0 errors, frontend gates and "API client is current", **384 passed, 9 deselected** (the 8 live scenarios and the SEC smoke test) in 539 s, e2e 3 passed. The live suite is deselected there, so CI never calls MiniMax.
- **Fixture-tested vs live:**
  - **Live: nothing.**
  - **Rehearsed against the recorded fakes only:** the suite's own wiring (setup, polling loop, report). This proves nothing about real Hindsight or MiniMax behaviour.
  - **Never exercised:**
    - the Compose `hindsight` profile or the spike stack being started by the runner
    - the health wait
    - `list_observations` and `llm_request_stats` against a live bank
    - pacing and queue pauses against real 429s
    - the confirmation prompt answered "y"
- **Deviations and notes:**
  - **Default profile:** the small profile (the two 10-Qs) is the default, to keep the first run near the bake-off's cost. Those sections are mostly cover pages and financial tables, which the bake-off found are under-extracted. Expect few facts, and the recall or "every company has facts" scenarios may fail there for want of facts rather than a bug. `--profile full` covers the narrative 10-K Items but costs an estimated ~40 min and ~1M input tokens (extrapolated, not measured).
  - **Recorded bank:** the rehearsal uses the recorded template bank (`atlas-template-1790632603`), so `apply-template` replays as recorded. If ticket 16 changes the template and re-records it, the rehearsal follows automatically.
  - **Structured reflect:** the gate's structured-output scenarios (valid, schema-invalid, union types refused) are not in the live suite. Union types are refused before any call, and the other two depend on the model. Add one if wanted.
  - **Failure-injection scenarios:** deleted memories (broken), a replayed retain, revised sources and 429 pauses need failure injection or a second source revision. They stay fixture-only; the live suite records any pause it happens to see.
  - **Ticket status:** set to `ready-for-human`, not `done`. Boxes 1 and 3 need a live run.
- **Credentials:** none used. The runner reads the LiteLLM key from `.env` only when run live, and never prints or stores it.
- **Next:**
  - owner: run `--rehearse`, then `--stop-before-llm --model MiniMax-M3`, then a small live run; paste the summary here
  - after the home-ops `atlas/litellm` step, drop `--model` so the per-role aliases are exercised
  - consider the full profile once the small run's cost is known
## 2026-09-29: ticket 16, mental models

- **Built:**
  - **Bank template 1.1.0** (`configs/hindsight/bank-template.json`): two mental models, `theme-status` (Theme status: the major documented developments in optical interconnect capacity, with supporting and opposing evidence) and `bottlenecks` (Bottlenecks, worded with the glossary's test: no qualified second source or substitute within the timeframe, pricing power, and "demand growth alone does not make a Bottleneck"). Both have the trigger `refresh_after_consolidation: false`, `refresh_cron: "0 6 * * *"` and `min_refresh_interval_seconds: 43200`, and `max_tokens` 2048.
  - **Template validation** (`atlas.bank_template`): each mental model must set `refresh_after_consolidation: false` explicitly, a 5-field `refresh_cron` and a positive minimum interval, with unique IDs, or `apply-template` exits 2 before any call. `BankTemplate.mental_models` / `mental_model(id)` give typed access.
  - **Alembic revision `0010`** (down_revision `0009`): `mental_model_refresh`, one row per decision of a refresh job (skipped with `min_interval`/`not_stale`, submitted, completed, or failed with `quota`/`unavailable`/`permanent`), with the template version and interval that applied, Hindsight's `last_refreshed_at` before and after, the operation, and the content, its SHA-256 and raw citations. CHECKs tie the status to its fields; an ENABLE ALWAYS trigger allows updates only of a `submitted` row's outcome columns and rejects DELETE/TRUNCATE; `atlas_app` gets SELECT/INSERT/UPDATE.
  - **`atlas.mental_models`:**
    - `RefreshSchedule`: from `ATLAS_MENTAL_MODEL_REFRESH_AT` (06:30 UTC; empty disables) each day, one `refresh_mental_model` job per template model, keyed `refresh_mental_model:<bank>:<model>:<day>`. Nothing is scheduled before a template is applied.
    - `MentalModelRefresher` (the job, registered **pausable**):
      - skips inside the minimum interval, measured from the later of Atlas's last submitted or completed refresh and Hindsight's `last_refreshed_at`, so a refresh by Hindsight's own cron counts
      - skips a model Hindsight reports as not stale
      - otherwise refreshes, polls the operation (a retried attempt resumes the same operation), and records the content
      - a quota or outage failure raises `TransientFailure` (pause), and after the pause the job decides afresh
      - a completed refresh is audited `mental_model.refreshed`
    - `MentalModelReader`: each template model's content, `last_refreshed_at`, `is_stale`, history (from the gateway), the citations of the content and of every history entry resolved by ticket 15's `ProvenanceResolver.resolve_answer` (memories and quotes), Evidence (resolved only), `evidence_missing`, and Atlas's refresh records.
  - **API:** `GET /api/v1/mental-models` and `GET /api/v1/mental-models/{id}`. Errors: 404 for an ID the template doesn't define (no Hindsight call), 503 `hindsight_not_configured`, 502 `hindsight_unavailable`/`hindsight_error`, 500 `invalid_template`. The API client is regenerated.
  - **Jobs:** `Worker(..., schedules=...)` runs each schedule at the start of every pass, on the queue's clock. `builtin_schedules(settings, engine)` is new, and `builtin_registry(settings, clock=...)` passes the application clock to handlers that measure time. `atlas worker` uses both.
  - **Gateway:** `MentalModel.is_stale` (0.10.1 returns it; now in the contract test).
  - **Settings:** `ATLAS_MENTAL_MODEL_REFRESH_AT`, `ATLAS_MENTAL_MODEL_POLL_TIMEOUT_SECONDS` (240) and `ATLAS_MENTAL_MODEL_POLL_INTERVAL_SECONDS` (5).
  - **Fake derivations** (documented in `tests/fakes/hindsight.py`). They're on by default, because each is anchored to a recorded request:
    - the template import: a body that differs from the recorded 1.0.0 research-template request only in `mental_models` is served `research_template/01`/`02` with only `bank_id`, `mental_models_created` and, for the import, one derived `operation_ids` entry per model changed (as `bank_templates/03`/`04` show)
    - the imported models' reads (`mental_models/03-get`) and history (`06-history`)
    - `script_refresh` (`04-refresh`, `05-refresh-final`; `hold=`/`error_message=` for a failed refresh) and `apply_refresh` (a refresh Hindsight ran on its cron)

    `spikes/hindsight/record_bank_template.py` now strips `mental_models` from what it sends, so re-running it stays LLM-free.
- **Files:**
  - new: `backend/atlas/mental_models/{__init__,refresh,reads,handlers}.py`, `backend/atlas/api/mental_models.py`, `backend/atlas/db/migrations/versions/0010_mental_model_refresh.py`, `tests/integration/test_mental_models.py`
  - edited: `configs/hindsight/bank-template.json`, `backend/atlas/bank_template.py`, `backend/atlas/hindsight/models.py` (one field), `backend/atlas/jobs/{__init__,handlers,worker}.py`, `tests/fakes/hindsight.py`, `spikes/hindsight/record_bank_template.py`, and small additive edits to `api/app.py`, `cli.py`, `settings.py` and `.env.example`
  - tests edited: `tests/unit/{test_hindsight_contract,test_hindsight_fake_derivations,test_settings}.py`; `tests/integration/test_bank_template.py` (the import is now served derived, and it checks the created model IDs); `tests/integration/test_queue_pause.py` (`refresh_mental_model` is now a pausable kind); `tests/integration/test_migrations.py` (head `0010`)
  - docs: `AGENTS.md`, `docs/decisions.md`, `docs/data-model.md` (§3.4b and the ER diagram), `frontend/lib/api/{openapi.json,schema.ts}`
  - The branch was fast-forwarded to `main` (ticket 15) before starting.
- **Tests:** 18 new: 11 integration and 7 unit (2 fake derivations, 5 settings). The integration tests are in `tests/integration/test_mental_models.py`: real Postgres with a fresh DB each; CLI apply-template, ingest and enqueue; scheduled single worker passes on a controllable clock; `/api/v1`; the fake on localhost with `derive_memories`.
  - **Template:** it holds both models with the daily trigger and `refresh_after_consolidation: false`, and Bottlenecks carries the glossary test. Hindsight was sent exactly the file's models, and the API lists both in the bank with that trigger.
  - **Runaway triggers:** five (consolidation on, consolidation unset, no cron, a bad cron, a zero interval) are refused by `apply-template` with exit 2 and no Hindsight call.
  - **Daily schedule:**
    - nothing before 06:30; at 06:30 both are refreshed and recorded (scheduled day, template version, interval, operation, content hash, times); nothing more that day
    - a by-hand refresh inside the interval is skipped with no Hindsight call
    - on day 2, Hindsight's own cron refresh is found and recorded as a `min_interval` skip, while the stale Bottlenecks (Coherent retained) is refreshed
    - on day 3 both are skipped `not_stale`
    - three `mental_model.refreshed` audit events, and `atlas audit verify` exits 0
  - **Pause:** a 429-failed refresh pauses the queue for 60 s, with `refresh_mental_model` among the kinds. The job is requeued at 0 attempts and the refresh is recorded `failed`/`quota`. The other model's job isn't claimed, and nothing is asked at +59 s. At +60 s both complete and the pause clears.
  - **API:**
    - content, `last_refreshed_at`, citations: a resolved observation and fact leading to the Lumentum 10-K Item 1 section, a deleted memory broken, the typographic-apostrophe quote resolved to its archived span, a paraphrase unverified
    - counts, Evidence, and refresh records
    - history newest first, with each entry's citations resolved (and the pre-refresh placeholder)
    - the list equals the detail
    - 404 for an unknown model with no Hindsight call; 503 without Hindsight
  - The implementation came just ahead of the tests, not strictly red first; the suite was then checked by mutation. Each of these went red: no minimum-interval check (daily test), the kind not pausable (pause test), a schedule key without the day (daily test), no staleness check (daily test), citations not resolved (API test).
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`) **passed**: ruff format/lint clean, pyright strict 0 errors, frontend gates and "API client is current", **399 passed, 1 deselected** (live) in 572 s, e2e 3 passed.
- **Fixture-tested vs live:**
  - **Everything is fixture or localhost.** No live Hindsight, LiteLLM or LLM call was made, and the spike wasn't used. The template wasn't re-recorded, because a live import of mental models queues refreshes, which are LLM runs. So the 1.1.0 dry run and import are **derived**, as is every mental-model read, history entry and refresh. The refreshed contents are written by the tests.
  - **Never checked against a real server:**
    - that 0.10.1 accepts `refresh_cron` in an imported template and runs it
    - that its cron honours `min_refresh_interval_seconds` and staleness (the docs say so; the feature matrix never exercised it)
    - how it reports a re-import of existing models (the fake still says "created")
    - whether an import on every deploy re-queues refreshes of unchanged models (an LLM cost per deploy if so)
    - a failed refresh operation's error text under a 429
- **Deviations and notes:**
  - **Two schedulers,** by design of the spec: the template's `refresh_cron` (06:00 UTC, run by Hindsight, not pause-aware) and Atlas's daily job (06:30 UTC, pausable, rate-limited, recorded). Atlas's job mostly records Hindsight's refresh, and is the backstop when the cron didn't run; see `docs/decisions.md`.
  - The refresh job polls its own operation rather than handing off to `poll_operation`, and doesn't use `hindsight_operation` (its `kind` CHECK covers retains only); the refresh row carries the operation instead.
  - Citations are resolved on every read, not stored at refresh time. A read costs one Hindsight call per cited memory (cached per request), and a memory deleted later shows as broken.
  - A permanently failed refresh ends the job without a retry, so a bad refresh never loops.
  - The models have no tags: every memory in the bank is Atlas's and tagged, and a tagged model would default to `all_strict` on the server.
- **Credentials:** none.
- **Next:**
  - Against the spike, with the owner's approval for the LLM cost: import a template with one `refresh_cron` mental model, record the import, the model read and its history, and watch one cron tick with `min_refresh_interval_seconds`, to replace the derivations.
  - Decide whether deploy-time `apply-template` should skip the import when the manifest SHA is unchanged, if re-imports re-queue refreshes.
  - A viewer page for the two models.

## 2026-09-29: code review fix-up (spec axis)

- **Built** (each item with the tests that cover it):
  1. **Runs for mental-model refreshes** (Part B stories 15 and 32). A submitted refresh starts a `run` (kind `refresh_mental_model`: code, Hindsight and template versions, the routed model per alias from the LiteLLM route recorder) before asking Hindsight, and finishes it when the operation ends (tokens 0: the refresh operation reports none). A skip makes no run. `mental_model_refresh.run_id` links them, shown on the API's refresh records. Reflect jobs already recorded runs (ticket 15; covered by `test_reflect_runs_as_a_job_and_the_api_returns_the_stored_answer`), so nothing changed there. Test: `test_mental_models.py::test_refreshes_run_daily_and_never_inside_the_minimum_interval` (each completed refresh's run: kind, template 1.1.0, Hindsight 0.10.1 from the recording, the `atlas-reflect` route from the LiteLLM fixture, finished; a skip has none), against the `/model/info` fake.
  2. **Returned memories** (Part B story 10). When a retain or reprocess operation completes, the poll job lists each section's memories (new gateway call `document_memories`: `GET …/memories/list?document_id=…`, paged) and stores their IDs on `memory_document.memory_ids`; a zero-fact section gets `[]` without a call. `GET /source-versions/{id}/memory` returns them. Tests: `test_retention.py` (`…section_by_section…`: each section's `memory_ids` is the fake's fact for its document; the zero-fact test: `[]`; the linked test: null), `tests/unit/test_hindsight_gateway.py::test_a_documents_memories_are_listed_page_by_page_through_the_memory_list`, `tests/unit/test_hindsight_fake_derivations.py::test_a_derived_documents_memories_are_listed_by_document`.
  3. **Metrics.** Scrape-time from the database: `atlas_fetches_total{outcome}`, `atlas_fetch_retries_total`, `atlas_parses_total{status}`, `atlas_archive_writes_total{namespace}`, `atlas_job_retries_total{kind}`, `atlas_reflect_latency_seconds` (histogram, request to stored answer) and `atlas_llm_tokens_total{kind,direction}` (runs' input/output; retain/reprocess operations' total). In-process on the API: `atlas_recall_latency_seconds{outcome}`. The fixture replay now serves a URL recorded more than once in order, so a test can replay a 429. Tests: `test_ingest.py::test_metrics_count_fetches_parses_retries_and_archive_writes` (all zero on an empty DB; after one ingest with the 8-K throttled once: 5 new versions, 4 parsed and 1 not applicable, 5 raw and 4 parsed archive writes, 1 fetch retry; after a second: 4 not modified, 1 unchanged, writes unchanged, 2 retries; a Coherent ingest without fixtures: 2 job retries and 1 failed job), `test_research.py::test_metrics_report_recall_and_reflect_latency_and_llm_tokens` (recall `ok`/`refused` counts 0 → 1; reflect latency count 0 → 1; reflect tokens = the recorded reflect's usage; retain tokens = the recorded operation's `total_tokens` × batches). The existing `test_queue_pause.py` metrics test still passes and every alert-rule metric is still exposed.
  4. **Revised SEC versions** (Part A story 31). A superseding Source Version takes `available_at` = its `fetched_at`, basis `observed_revision` (new CHECK value); a first version keeps `sec_acceptance`. Test: `test_ingest.py::test_a_changed_filing_yields_a_new_source_version_linked_via_supersedes`, which asserted the opposite before (`available_at` equal to the original's) and now asserts the new basis, `available_at == fetched_at`, later than the first fetch, and the acceptance kept in metadata. Decision recorded as reversible.
  5. **Auditing.** `JobQueue` takes an actor (default the new `SYSTEM_ACTOR`, `atlas-system`) and writes `job.enqueued` with a new job, and `queue.paused` / `queue.pause_cleared` with the pause row's old and new hashes, each in the same transaction. The CLI, the reflect request, ingest's retains and the retention jobs enqueue as the configured actor; the mental-model schedule and the worker's pause as the system actor. Claims, leases, retries and completions aren't audited (decision recorded). Tests: `test_jobs.py::test_an_enqueue_is_audited_once_and_claims_and_leases_are_not` (one event for two enqueues of one key and a worker pass; the chain verifies), `test_queue_pause.py::test_a_429_failed_operation_pauses_the_queue_then_resumes_and_resubmits` (one `queue.paused` and one `queue.pause_cleared` by `atlas-system`; the chain verifies), and `test_ingest.py::test_every_mutation_is_audited_in_one_chain_that_verifies` (now expects the two `job.enqueued` events).
  6. **Documentation only:** (a) one `docs/decisions.md` entry listing every derivation in `tests/fakes/hindsight.py` (including the memory-list derivation added here) as an explicit deviation from "extended only by recording new real interactions", with the plan (ticket 17's live run checks them; each is replaced by a recording once one is captured); (b) an "Amendment" section in ADR-0001 (same content under the same ID is allowed and non-destructive; an ID never carries different content); (c) the EDGAR submissions index is discovery metadata, not a Source Version; (d) the A→B→A behaviour and its consequences, flagged **needs owner decision**, code unchanged.
- **Files:**
  - new: `backend/atlas/db/migrations/versions/0011_review_fixups.py` (revision `0011`, down `0010`: `memory_document.memory_ids`, `mental_model_refresh.run_id` (added to the guard's immutable columns), `observed_revision` in the basis CHECK)
  - edited: `backend/atlas/{audit,metrics,cli}.py`, `api/{app,research}.py`, `hindsight/{gateway,models}.py`, `jobs/queue.py`, `ledger/{ingest,service}.py`, `mental_models/{handlers,reads,refresh}.py`, `research/service.py`, `retention/{reads,service}.py`, `sources/edgar_fixtures.py`, `tests/fakes/hindsight.py`
  - tests: `tests/unit/{test_hindsight_gateway,test_hindsight_fake_derivations}.py`, `tests/integration/{test_assertions,test_ingest,test_jobs,test_mental_models,test_migrations,test_queue_pause,test_research,test_retention}.py`
  - docs: `docs/decisions.md`, `docs/adr/0001-…md`, `docs/data-model.md`, `AGENTS.md`; `frontend/lib/api/{openapi.json,schema.ts}` regenerated (`run_id` on refresh records, `memory_ids` on memory documents)
- **Tests:** 5 new (2 unit, 3 integration) and 8 extended. Items 1, 2, 4 and 5 went red first (a missing key, the old `available_at`, no audit events). The Part B metrics code came just ahead of its test; the test was then checked to go red with the recall histogram unwired. Two existing tests were adjusted for the new behaviour: `test_assertions.py`'s harness enqueues its ingest as the test's actor (the audit test expects one actor), and `test_research.py`'s observation test ignores the new `memories/list` lookups when checking which memories were read.
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`) **passed**: ruff format/lint clean, pyright strict 0 errors, frontend gates and "API client is current", **407 passed, 9 deselected** in 628 s, e2e 3 passed.
- **Fixture-tested vs live:** everything is fixture or localhost; no live Hindsight, LiteLLM or LLM call. The document-filtered memory list (`memories/list?document_id=`) is in the 0.10.1 OpenAPI schema but was never recorded, so the fake **derives** it; the live suite (ticket 17) is where it is first seen for real. That a refresh operation reports no tokens is from the one recorded refresh (`mental_models/05-refresh-final`).
- **Deviations and notes:**
  - Refresh runs record 0 tokens; Hindsight's per-bank LLM request log (`llm_request_stats`) could attribute them later.
  - `atlas_fetches_total` counts recorded fetches only: a failed fetch leaves no ledger row and fails its ingest job, so it shows in the job metrics instead.
  - `atlas_reflect_latency_seconds` includes queue wait (it measures the researcher's wait, request to stored answer).
  - Pauses and scheduled enqueues are audited as `atlas-system`, not the configured actor.
- **Credentials:** none.
- **Next:** the owner's decision on A→B→A (`docs/decisions.md`); record the document-filtered memory list and a real refresh operation in the live run, and replace their derivations.
## 2026-09-29: code review fix-up (standards axis)

A behavior-preserving refactor from the Standards review of tickets 14–17, rebased onto the spec-axis fix-up (`a19fa77`) and applied to its new code as well. It adds no migrations and changes no API contract: the exported OpenAPI schema is byte-identical, so the client didn't need regenerating.

- **What changed:**
  - **Glossary:**
    - in `mental_models/refresh.py`, `_snapshot`/`snapshot` became `_refresh_record`/`recorded` ("snapshot" is reserved for Research Snapshot)
    - `ledger.list_documents`/`get_document` became `list_source_documents`/`get_source_document`
    - in the frontend `company`, `source` and `version` pages, `document` variables and params became `sourceDocument`, so they no longer shadow the DOM global
  - **Job handlers:**
    - one `HindsightNotConfigured` (in `atlas.hindsight.errors`, next to the one `HINDSIGHT_NOT_CONFIGURED` message, which the CLI and the API also use)
    - one context manager, `atlas.jobs.resources.hindsight_resources(settings)`: it builds the gateway (raising when unconfigured) and the engine, then closes and disposes both
    - `reflect`, `refresh_mental_model` and the retention handlers use it; `_retention` is now a thin wrapper
    - `run_recorder(settings, engine)` does the same for the run recorder (closing it before the gateway and engine), which the `reflect` and `refresh_mental_model` handlers now share
  - **Engine factory:** `atlas.db.create_engine(settings)` (`pool_pre_ping=True`), used by `cli.py`, `api/app.py`, `ledger/ingest.py` and the handlers
  - **API error maps:** `api/common.py` now has `error_responses(*codes)`, `NOT_FOUND`, `INVALID`, `CONFLICT`, `HINDSIGHT_FAILURES` (502/503), `hindsight_not_configured()` and `hindsight_failed(error)` (502 `hindsight_unavailable`/`hindsight_error`). The assertions, research, mental-models and jobs routers use them, and `jobs.py` dropped its unused re-exports.
  - **Test harness:**
    - `tests/harness.py` holds `make_settings(archive_root, **overrides)` (built from values only, never from the environment), the shared `Atlas` harness (the union of the retention and research harnesses; research's `ingest(company)` is now `ingest_company`), `Clock`, `at`, `assert_source`, `scrape_metrics` (used by the `Atlas`, `Paced` and ingest harnesses' `metrics()`), and `REPO`/`THEMES`/`TEMPLATE`/`EDGAR_FIXTURES`/`BANK`/`LITE_10K`/`TEN_K_ANCHORS`/`ITEM_1`/`LITE_APOSTROPHE`/`QUOTA_ERROR`
    - `tests/integration/conftest.py` holds `database_url` (migrated), `engine`, `hindsight_fake` (default `derive_retains`; the research and mental-model modules override it with `derive_memories`), `hindsight` and `fake`
    - no test module imports from another test module any more
    - every `Settings.model_validate({...})` builder in `tests/unit` and `tests/integration` goes through `make_settings`
  - **Frontend:** `components/source-document.tsx` `SourceDocumentRows` (the accession, form with its document type, and "publisher via provider; tier, licence" rows), shared by the source and version pages; `Row` moved to `components/ui.tsx`
- **Files:**
  - new: `backend/atlas/db/engine.py`, `backend/atlas/jobs/resources.py`, `tests/harness.py`, `frontend/components/source-document.tsx`
  - edited backend: `backend/atlas/{cli,db/__init__,hindsight/__init__,hindsight/errors,ledger/__init__,ledger/reads,ledger/ingest,mental_models/refresh,mental_models/handlers,research/handlers,retention/handlers}.py`, `backend/atlas/api/{app,assertions,common,jobs,mental_models,research,sources}.py`
  - edited tests: `tests/integration/{conftest,test_archive_contract,test_archive_object_lock,test_archive_provisioning,test_assertions,test_audit,test_bank_template,test_ingest,test_jobs,test_mental_models,test_queue_pause,test_readiness,test_research,test_retention,test_runs}.py`, `tests/unit/{test_health,test_hindsight_gateway,test_llm_routes}.py`
  - edited frontend: `frontend/app/{company,source,version}/page.tsx`, `frontend/components/ui.tsx`
  - docs: `AGENTS.md` (layout)
- **Tests:** none added or removed; the existing suite is the safety net.
  - Before (on `5b519a9`): `uv run pytest` gave **402 passed, 9 deselected**. After the rebase onto `main` (`a19fa77`, 407 tests): 407 collected.
  - After: `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64 scripts/ci.sh --no-image` **passed**:
    - ruff format/lint clean, pyright strict 0 errors
    - frontend lint, typecheck, unit tests (10 passed) and build
    - "API client is current"
    - **407 passed, 9 deselected** in 633 s
    - e2e 3 passed
  - The exported OpenAPI schema was re-checked after the rebase: still byte-identical.
  - An intermediate run caught one harness slip (`test_runs`' settings builder passed `hindsight_url` twice), fixed before the green run.
- **Fixture-tested vs live:** nothing new; everything is fixture or localhost, as before.
- **Deviations and notes:**
  - The CLI's one-shot commands (enqueue, ingest, seed, audit verify, apply-template) used a plain engine; through the factory they now get `pool_pre_ping=True` too. That is one cheap ping per checkout on a short-lived engine, and pooling is otherwise unchanged.
  - `HindsightNotConfigured` stays a plain `Exception`, not a `HindsightError`, so failure classification and the API's `except HindsightError` are unchanged.
  - `test_bank_template.py` keeps its own `hindsight` fixture on purpose: one test makes the fake fail the dry run, and the shared fixture would re-raise that. It is documented as an override.
  - The module-local harnesses of `test_ingest.py` (no Hindsight) and `test_assertions.py` (its own actor) stay local. Only their settings, paths and database fixture are now shared.
  - Not changed:
    - the live suite's settings builder (`tests/live`, never run here)
    - `tests/unit/test_settings.py` (it tests `Settings` itself)
    - the `/sources/{document_id}` path parameter, which is API contract
    - `HindsightGateway.get_document`, which is a Hindsight memory document, not a Source Document
- **Credentials:** none.
- **Next:** nothing from this axis.

## 2026-09-29: ticket 17, first live run of the Phase 2 gate suite

Run with the owner's go-ahead: `scripts/live-tests.sh --model MiniMax-M3` (Compose `hindsight` profile, small profile = the two 10-Qs). Results: `.scratch/live-runs/20260929T062648Z-live/` (gitignored). Before it, the free rehearsal passed (7 passed, 1 skipped) and a stop-before-LLM stack check passed (2 passed, 6 skipped).

- **Stack:** Hindsight **0.10.1** at `127.0.0.1:58888`; alias `MiniMax-M3` routed to deployment `minimax/MiniMax-M3` (id `9317e83f…`); bank `atlas-live-20260929-062657`; template **1.1.0** applied with a dry run, then import (both mental models created).
- **Result: 7 passed, 1 skipped, in 3 min 24 s.** These paths are now **verified live**, not just against the fake:
  - preflight
  - template apply
  - ingest of both companies (no queue pauses)
  - retention: every section reached a final state through completed operations. Lumentum's 10-Q gave 2 sections and 41 facts (cover 8, Part I Item 1 33), with no reprocess.
  - cross-company recall: 55 memories (46 world, 9 observations; Lumentum 39, Coherent 16), **all 55 resolved** to Source Version sections, and 0 broken. This confirms the two-hop observation → source-memory → section path against a real server.
  - reflect: completed in 64 s with a recorded run. Citations: **87 resolved, 16 unverified, 0 broken**; 4 evidence sections.
  - LLM usage recorded: 20 calls, all success, 211k input / 20k output tokens (25k cached).
- **Skipped:** the zero-fact scenario, because no section produced zero facts. The zero-fact path is still **fixture-only**.
- **Unverified quotes:** 16, and they fall into two kinds.
  - Phrases the model put in quotation marks but that were its own words ("near-doubling of revenue", "deleveraging"). Unverified is the correct outcome.
  - Financial-table figures ("$144.2", "Net cash provided by operating activities $ 388.4 $ 62.3"). These probably differ from the parse only in table spacing, e.g. "$ 144.2". That would be a false negative of the quote rule `whitespace-and-typographic-quotes-v1`, which is conservative rather than unsafe. **Follow-up:** inspect those against the parsed text, and decide whether to normalize space after currency symbols and between table cells.
- **Not yet run live:** the full profile (`--profile full`, ~470k chars, est. ~1M input tokens); zero-fact reprocess; the queue pause on a real 429; the mental-model refresh on Hindsight's own cron.

## 2026-09-29: live Phase 2 gate run against the owner's cluster Hindsight

`scripts/live-tests.sh --stack cluster --model MiniMax-M3`: `hindsight.ekenhome.se` (the shared `llm/hindsight` release; its **server-wide extraction LLM is Codex, not MiniMax**, so `--model` affects only Atlas's routing check and run records).

- **Result: 7 passed, 1 skipped (zero-fact: none occurred), 2 min 24 s.**
  - Recall: 26 memories, **26 resolved**, 0 broken (Lumentum 19, Coherent 7).
  - Reflect: completed in 48 s. Citations: **37 resolved, 1 unverified** (the phrase "Most recent"), 0 broken; 4 evidence sections.
  - 16 LLM calls, all success, 48k input / 7k output tokens.
- **What running behind the cluster route needed.** The cluster's HTTPRoute exposes only `/v1` and `/mcp`; `/health` and `/version` land on the control-plane UI with a 404.
  - The live preflight now checks liveness via `GET /v1/default/banks` and takes a declared version (`ATLAS_LIVE_HINDSIGHT_VERSION`, 0.10.1 from the HelmRelease pin).
  - **App change:** runs fall back to `ATLAS_HINDSIGHT_VERSION`, recorded as `"<v> (declared)"`, when `/version` is unreachable, and refuse to start without it. An earlier cluster run failed reflect on exactly this. TDD: 2 tests.
- **Runner:**
  - `--stack cluster` reads `HINDSIGHT_URL`/`HINDSIGHT_API_KEY` from `.env`, else `~/.hindsight/config`.
  - Throwaway banks (`atlas-live-<stamp>`) are now **deleted at the end of a run** (`--keep-bank` to keep one). The leftover `atlas-live-20260929-064603` from the first cluster attempt was deleted. The cluster again has only `atlas-dev` and `hermes`.
- **Bank policy, clarified for the owner:** production is **one** long-lived research bank (`atlas-ai-infrastructure`); per-run banks exist only for test isolation; `atlas-dev` stays the coding agents' engineering-notes bank and is never used for research data.

## 2026-09-29: first cluster deploy (tickets 21–22), backlog incident, ingest lookback

- **Deployed:** home-ops PR #7071 (Atlas in `development`: one pod api+worker, archive PVC, Crunchy `atlas` DB, shared Hindsight bank `atlas-ai-infrastructure`, Renovate automerge off) and #7072 (reloader, `companies seed` initContainer, bootstrap ingest Job, nightly CronJob 01:30 UTC). Image `ghcr.io/ekenheim/atlas:0.1.0` (public). `https://atlas.<domain>/health/ready`: database, archive and Hindsight `ok`, LiteLLM `not_configured` (by design for now).
- **Incident:** the bootstrap ingest had no lookback. It pulled 543 Source Documents and queued 1,397 operations on the shared Hindsight (Codex subscription), using ~1.27M tokens before the owner approved cancelling. Cancelled: 1,329 pending operations in `atlas-ai-infrastructure` only; 58 retained documents kept; `hermes` and `atlas-dev` untouched. Atlas's 540 queued polls then drained (a `cancelled` status is terminal).
- **Fix (TDD):** default ingest lookback (730 days, `--since`, `--all-history`), the enqueue summary shows the job payload, and `atlas retention retry-failed`. 5 new integration tests.
- **Not yet done:** the Phase 2 in-cluster smoke check (a resolved recall through the deployed API); re-running the in-window cancelled sections (nightly, backfill class).

## 2026-09-29: ticket 02 (Phases 3–6a), Atlas LiteLLM key and the release version

- **home-ops PR #7086** (`atlas/litellm-key`, off `origin/main` @ `db10b37dd`, in the fresh clone `home-ops-atlas-pr`). Not merged; the owner merges.
  - It reuses ticket 20's saved `atlas/litellm` patch, minus the configmap: no aliases and no gateway restart.
  - The store now admits `development`, not `datasci`.
  - The key allows `MiniMax-M3`, `qwen3-embedding-0.6b` and `rerank`.
  - Atlas side: an ExternalSecret `atlas-litellm` (`ATLAS_LITELLM_API_KEY`), and `ATLAS_LITELLM_URL` plus both alias envs (`MiniMax-M3`) in the shared env. The Kustomization now dependsOn `litellm-stores` and `litellm-keys`.
- **Validation:**
  - yamllint on the 9 changed files: passed.
  - flux-local v8.4.0: 184 passed.
  - kubeconform v0.6.7 `-strict`, on the rendered `clustersecretstore/`, `keys/` and `atlas/app`: 20 valid, 0 invalid. The `LiteLLMVirtualKey` schema was generated from the pinned litellm-operator 0.0.19 CRD, which has `maxParallelRequests`.
- **Release version (TDD):**
  - Two tests in `tests/unit/test_health.py`:
    - `atlas_build_info` reports `Settings.version` when stamped. This one went red first.
    - `atlas.__version__` equals the installed distribution's version.
  - `Dockerfile` has `ARG ATLAS_VERSION`, and `release.yml` passes `steps.meta.outputs.version`.
  - `scripts/image-smoke.sh` checks the metric when `ATLAS_SMOKE_EXPECT_VERSION` is set. A local image built with `ATLAS_VERSION=9.8.7` passed the check, and a mismatched expectation failed it.
- **Open:** the ticket resolves once PR #7086 is merged and deployed, `/health/ready` reports litellm `ok`, and runs record routed models. The deployed 0.1.1 image already reads the LiteLLM and alias settings. The version stamp shows from the next release tag on.
## 2026-09-29: Phase 3-6a ticket 10, EDGAR dissemination time

- **Built:**
  - `backend/atlas/sources/edgar_calendar.py`: `edgar_dissemination_time(accepted, form)` (window 06:00–17:30 ET on an EDGAR business day, 22:00 for the Filer Manual §3.2 forms; otherwise 06:00 ET on the next business day, DST-correct via America/New_York), `is_edgar_business_day`, the explicit holiday table `EDGAR_HOLIDAYS` for 2019-01-01..2027-12-31 and `EdgarCalendarRangeError` outside it
  - `atlas.sources.edgar.filing_availability(filing)`: (available_at, basis), `sec_dissemination` only when EDGAR held the filing; used for every filing document's candidate, and the rule XBRL facts use (Phase 5)
  - migration `0012` (down_revision `0011`): basis `sec_dissemination`; append-only `source_version_availability_correction` (one per version, only later than recorded, ENABLE ALWAYS triggers); view `source_version_availability`
  - `atlas.ledger.availability.correct_availability` and CLI `atlas ledger correct-availability` (idempotent, audited `source_version.availability_corrected`)
  - readers switched to the view: ledger reads (API adds `recorded_available_at`, `recorded_available_at_basis`), citation/evidence provenance, retention's `--since` filter and retain timestamps; the version page shows a correction beside the recorded value
  - `tzdata` runtime dependency (the slim image has no system zone database guarantee)
  - docs: `docs/decisions.md` entry (SEC sources cited), `docs/runbooks.md` (run the correction once after `0012`; extending the table), `docs/data-model.md`, `docs/architecture.md`, `AGENTS.md`
- **Tests (TDD):**
  - new `tests/unit/test_edgar_dissemination.py` (9): 16:00 ET, 17:30:00 vs 17:30:01, 17:31 on a Friday, holiday eves (Thanksgiving, 3 July 2026, the 24–26 Dec 2025 closure), both 2026 DST changes, weekend/holiday/pre-06:00 acceptance, Form 4 until 22:00, the table's range errors, `filing_availability`
  - updated: the adapter's availability test (the fixture 10-Q, accepted Tuesday 18:03 EDT, is now 2026-05-06 10:00 UTC, `sec_dissemination`); the ingest gate test `test_available_at_is_when_edgar_disseminated_and_the_clocks_stay_distinct`; `assert_source` in `tests/harness.py`; the migration head (`0012`); the two live tests accept either SEC basis (not run: live)
  - new integration test `test_phase_1_versions_are_corrected_by_a_recorded_correction_never_by_an_edit`: a Phase-1-style version of the 10-Q gets a correction through the CLI, the API shows the corrected and recorded values, the version row is byte-for-byte unchanged, an in-window one isn't corrected, a rerun corrects nothing, the correction table rejects UPDATE/DELETE/TRUNCATE and an earlier value
  - red first: the unit tests failed on import, then passed; the integration tests were written before migration `0012` and the correction code, but not run red on their own
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 431 passed and 9 deselected in 13.5 min, e2e 3 passed)
- **Fixture-only vs live:** all tests are fixture-based. The rule was also checked offline against the submissions indexes recorded during the Phase 3-6a research (8,366 filings, 15 filers, 2019–2026): never earlier than EDGAR's `filingDate`; 59 later, all conservative (details in the decision). No new SEC requests beyond the 4 SEC pages read for the sources (Filer Manual Vol. II v78, Accessing EDGAR Data, EDGAR Calendar, the Dec 2025 closure notice) and three sec.gov searches.
- **Deviations:** the ticket's "next business day's opening" is 06:00 ET (EDGAR's opening; the manual gives no finer time). Held filings are decided by acceptance, not `filingDate` (conservative by hours for filings received before 17:30 and accepted after). The research note's `sec_filing_date` / `sec_filing_date_eod` bases aren't introduced: `sec_dissemination` covers held filings, and out-of-table dates fail instead of falling back.
- **Next:** after deploy, `atlas migrate` then `atlas ledger correct-availability` once in the cluster. Extend the holiday table when SEC publishes 2027's calendar (and before 2027-12-31). Phase 5 XBRL normalization calls `filing_availability` per fact.
- **Deployed (2026-09-29):** home-ops PR #7088 merged. `atlas_build_info{version="0.1.2"}` shows the version stamp is live, and `/health/ready` reports database, archive, Hindsight and litellm `ok` (this closes the LiteLLM-key ticket's open item). I checked the correction Job through the API against a sample of 80 of the 398 filing Source Versions: 5 now read `sec_dissemination` over a recorded `sec_acceptance` (held back by EDGAR). The other 75 were in the window and are uncorrected, as intended.

## 2026-09-29: Phase 3-6a ticket 07, role-call foundation

- **Built:**
  - `backend/atlas/roles/`: `contract.py` (`Role` with a versioned `Prompt` (`prompts/<name>.v<N>.md`, SHA-256 recorded), request and strict response models (`RoleOutput`; `NotStrict` at definition), the fixed `DIRECTIVES` and `REPAIR_DIRECTIVE`, `QuotedText` (always `trust: "low"`)); `caller.py` (`RoleCaller.call`: LiteLLM `POST /chat/completions` with the `atlas` key, model `ATLAS_LLM_ROLE_MODEL` (MiniMax-M3), extra body `ATLAS_LLM_ROLE_EXTRA_BODY` (thinking disabled), strict `json_schema` `response_format`, `metadata {run_id, role}`, retrieved text as JSON strings under `retrieved_data` in the user message; one repair then quarantine; per-run token budget with `TokenBudgetExhausted`; `TransientFailure` for 429 / `budget_exceeded` / 502-504 / outage 5xx / connection failures, `RoleCallFailed` otherwise); `records.py` (`run_usage`, `run_role_calls`)
  - migration `0015` (down_revision `0015`, re-chained at merge): `role_call`, `llm_call`
  - `GET /api/v1/runs/{run_id}/role-calls` (`api/runs.py`), API client regenerated
  - settings `llm_role_model`, `llm_role_extra_body`, `llm_role_timeout_seconds`, `run_token_budget` (default 200,000)
  - `tests/fakes/litellm.py`: scripted `/chat/completions` (`script_chat`, `ChatReply.json/text/error/unreachable`, `chat_requests()`); `/model/info` unchanged
  - docs: `docs/decisions.md` entry, `docs/data-model.md` §3.1a, `AGENTS.md` layout, `.env.example`
- **Tests:**
  - new `tests/integration/test_role_calls.py` (19, including a 5-case parametrized pause test): request shape (model, thinking off, strict schema, metadata, system = directives + prompt), per-call routed model/tokens and per-run sums through the API, retrieved text quoted and absent from the system message (an injection that tries to close the quoting), `<think>`/code-fence tolerance, repair once, quarantine (visible, output null), budget error before any request (and the repair skipped), `max_tokens` capped by the budget left, unknown run, quota/outage pausing the queue in a worker pass with the job requeued (429, `budget_exceeded`, 503, 500 "overloaded", connection refused), a 400 as an ordinary failure, model and extra body from config, no caller without LiteLLM, 404 for an unknown run
  - new `tests/unit/test_roles.py` (6): prompt loading and hash, missing version, prompts dir, strict schema, non-strict models rejected
  - migration head updated to `0015`
  - the tests were written before the code but not run red on their own (the import would fail); mutation checks instead: one attempt instead of two turned 3 tests red; dropping the `budget_exceeded` mapping turned its pause case red
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 458 passed and 9 deselected in 18.2 min, e2e 3 passed)
- **Fixture-only vs live:** all of it. No chat completion was made against LiteLLM. The chat reply and error shapes are hand-written from OpenAI's chat completion object and LiteLLM's error envelope; `model` = alias and the `x-litellm-model-id` header come from the 2026-09-28 dev probe. The `budget_exceeded` error type is from LiteLLM's key-budget documentation and hasn't been seen live. MiniMax's enforcement of `strict` json_schema was seen in the probe for one small call only.
- **Deviations:**
  - The only role is a trivial `example` role defined in the test module, with its prompt in `tests/fixtures/prompts/`. `backend/atlas/roles/prompts/` doesn't exist yet; the first real role adds it.
  - The budget is checked before each completion, so a run can overshoot by one prompt (`max_tokens` bounds the output). Parallel roles can both pass the check; the key's maxBudget is the backstop.
  - The role model isn't added to `llm_aliases()`: that would change every run's recorded routes and the `/model/info` readiness check. Each call records its routed model from the response instead.
  - `run.tokens_in/out` are not updated per call. The run's finisher sets them from `run_usage`.
- **Next:** tickets 08 (Scout) and later add roles and their prompts, and register their job kinds `pausable=True`. Ticket 14 finishes runs with `run_usage` and maps `TokenBudgetExhausted` to the `budget_exhausted` stop reason.
## 2026-09-29: Phase 3-6a ticket 03, PDF parsing and language

- **Built:**
  - `atlas.parsing`: parser version `text-v2` (HTML/text rules unchanged from `html-text-v1`, same hashes); PDF text via pypdf (pinned `==6.19.0`) with a `PageAnchor` per page (number, `/PageLabels` label, code-point range); image-only PDFs return `Unsupported(reason)`; `ParsedText.language` from `<html lang>` / PDF `/Lang`, else a deterministic script and function-word guess (`und` when unsure)
  - `SourceCandidate.language` (adapter declaration); EDGAR declares `en` (Reg. S-T Rule 306)
  - migration `0014` (down_revision `0015`, re-chained at merge): `parse_status` `unsupported`; `parse_error` set iff `failed` or `unsupported`; `source_version.language` (existing rows `en` via a column default that is then dropped) and `page_anchors` jsonb
  - ledger records the language (declaration, else parse) and anchors; API `SourceVersionSummary.language`, `SourceVersionDetail.page_anchors`; `atlas_parses_total{status="unsupported"}`
  - retention: `RETAINABLE_LANGUAGES = ("en",)` in `enqueue_retains` and the `retain` job (`not_retainable` with the language)
  - Assertions: an omitted `page_or_anchor` on a PDF version becomes its page label ("page 1 (PDF page 2)", "pages i–1 (PDF pages 1–2)")
  - viewer: Language and Pages rows; a "Pages" nav that scrolls the parsed text to each page (`utf16Index`, `domPosition` in `lib/offsets.ts`); API client regenerated
  - `scripts/make_pdf_fixtures.py` writes `tests/fixtures/pdf/` (three hand-built, uncompressed PDFs: English 3 pages with `/Lang` and roman labels, French 2 pages, image-only 2 pages); `scripts/e2e.py` also records the English PDF
  - docs: `docs/decisions.md` ("PDF parsing and language": library choice, rules, English-only retention), `docs/data-model.md`, `AGENTS.md`
- **Tests (TDD):** new `tests/unit/test_pdf_parsing.py` (14: fixtures regenerate byte-identical, text and anchors, pinned hash, process independence, `/Lang`, French detection, unsupported, non-PDF bytes raise, plain-text languages en/de/zh/ja/und, `<html lang>`); new `tests/integration/test_pdf_sources.py` (7: API text/language/anchors, no new version for same bytes, Assertion exact span + page label + shifted-span refusal, unsupported not quotable, French not retained, adapter declaration wins, a hand-enqueued retain job for French is `not_retainable` with no Hindsight call); new migration test (pre-0014 rows are `en`); new e2e `frontend/e2e/pdf-viewer.spec.ts`; frontend unit test for `utf16Index`; updated version strings in existing tests (golden.json gains `text-v2` with the same hashes), language/anchors checks in the ingest test, metrics statuses, migration head `0014`. Red first: the unit tests failed on import, the integration tests on missing fields.
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates with 11 unit tests, API client check, pytest 455 passed and 9 deselected in 21.9 min, e2e 4 passed)
- **Fixture-only vs live:** all fixture-based; the PDFs are synthetic and generated, not any issuer's document. No adapter fetches PDFs yet, so PDFs are recorded through `SourceLedger.record` under the SEC provider (the only one `describe` knows). Not tested against real HKEX/LSE/Euronext PDFs.
- **Deviations:** the ledger-level tests call `SourceLedger.record` directly (the adapter boundary) rather than an adapter's ingest; `und` counts as non-English and is not retained; Assertions get an automatic page label (not required by the ticket).
- **Next:** tickets 04–06 set `SourceCandidate.language` from each exchange's listing and extend `describe` for their providers; Investigator extraction (ticket 10) must filter on `RETAINABLE_LANGUAGES`. Real-world PDFs may need a check of pypdf's extraction on multi-column layouts.
## 2026-09-29: Phase 3-6a build ticket 01, photonics universe

- **Built:**
  - `configs/themes/ai-infrastructure.yaml` (version 2): the 12 verified photonics companies from the seed-list research (branch `research/seed-list`, `docs/research/seed-list.md`), each with `layer` (`substrate`, `epi`, `chip-laser`, `dsp`, `module`, `contract-manufacturing`, `system`) and `source_path` (`sec` or `exchange:<hkex|lse-rns|euronext>`); STMicroelectronics has `sec_forms: [20-F, 6-K]`; Soitec, IQE and Innolight have no CIK and list their unsponsored-ADR CIKs (1445214, 1550405, 2150915) under `ignored_ciks` with the reason. LEIs and tickers are comments only (see deviations).
  - `atlas.companies`: `CompanyConfig` gains `layer`, `source_path` (required), `sec_forms`, `ignored_ciks`; validation refuses a `sec` company without a CIK, an exchange company with a CIK or `sec_forms`, and any company whose CIK another lists as ignored. Seeding writes the new columns; the `Company` read (API) returns `layer`, `source_path`, `sec_forms`.
  - migration `0013` (down_revision `0012`): `company.layer`, `company.source_path`, `company.sec_forms` with CHECK constraints (layer enumeration, source-path pattern, `sec_forms` only on `sec`, `sec` needs a CIK).
  - SEC ingest refusal: `atlas ingest --company <non-sec>` exits 2 with "company 'x' is not an SEC filer (source path '…')…", enqueuing nothing; an ingest job enqueued past the CLI fails with `NotAnSecFiler` before seeding or fetching. The job uses the company's `sec_forms` when its payload names none.
  - API client regenerated (`frontend/lib/api/`); `docs/data-model.md` and `AGENTS.md` updated.
- **Tests:**
  - new `tests/integration/test_universe.py` (11): the 12 companies' layer/source path/CIK/forms through `/api/v1/companies` (expected values hand-written from the research note); idempotent re-seed (0 changes, no audit events); a changed layer updates in place with one audit; unsponsored-ADR CIKs are no company's CIK; a config using an ignored CIK as a filer, or giving an exchange company a CIK, is refused by `companies seed` (exit 2); the ingest CLI refuses Soitec, IQE and Innolight; a directly enqueued Innolight ingest job fails clearly with no fetch observation, document or company row; STMicroelectronics ingests its 20-F and 6-K (not the 11-K) from a hand-written EDGAR fixture.
  - updated: `test_companies_are_seeded_from_config_idempotently` and `test_every_mutation_is_audited_in_one_chain_that_verifies` (12 companies seeded instead of 2; the Lumentum/Coherent assertions are unchanged), the migration head (`0013`).
  - Not run red first: the config/code and the tests were written together; the tests passed on their first run (11 passed).
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 444 passed and 9 deselected in 21.7 min, e2e 3 passed). An earlier run failed only `test_every_mutation_is_audited_in_one_chain_that_verifies` (it counted 2 seeded companies), fixed above.
- **Fixture-only vs live:** everything is fixture-tested. The STMicroelectronics EDGAR responses are **hand-written** in the test (not recorded from SEC); no SEC, GLEIF or exchange request was made.
- **Deviations:**
  - One primary `layer` per company (the spec's "layer tag"); vertically integrated companies (Coherent: substrate→module; Lumentum; AAOI) get their primary layer, the rest is left to layer-tagged Relationships.
  - LEIs are not set in config: the CIK↔LEI link is owner-confirmed once per company (ticket 03). Securities are not added for the new companies: listing start dates need a primary source (ticket 03).
  - Ignored ADR CIKs live in config only (not a table); ticket 03's entity resolution can read them from the universe.
  - STMicroelectronics' 6-K ingests only its primary document; the adapter fetches EX-99 exhibits for 8-Ks only.
- **Next:** ticket 03 (identity) adds LEIs, securities and the owner CIK↔LEI confirmation; the exchange adapters ingest Soitec (Euronext), IQE (LSE RNS) and Innolight (HKEXnews). Consider fetching 6-K EX-99 exhibits for STMicroelectronics.
## 2026-09-29: Phase 3-6a ticket 11, Evidence Families

- **Built:**
  - `backend/atlas/ledger/families.py`: self-implemented 64-bit SimHash (rule `simhash64-w3-blake2b-v1`: NFKC + casefold, letter/digit tokens, word 3-shingles weighted by occurrence, unkeyed BLAKE2b-64 per feature; documented in the module docstring), `assign` (exact by `content_sha256`, else nearest member within the family's recorded Hamming threshold, else a new family; serialized by an advisory lock taken before the audit chain's), `audit`, and the backfill `assign_missing`
  - the ledger assigns a family in the transaction that records a new parsed Source Version (`SourceLedger(max_hamming_distance=...)`), audited `evidence_family.created` / `evidence_family.member_added`
  - migration `0016` (down_revision `0012`): append-only `evidence_family` (rule, `max_hamming_distance`) and `evidence_family_member` (content hash, SimHash, match kind, matched member, distance, `seq`)
  - setting `ATLAS_EVIDENCE_FAMILY_MAX_HAMMING_DISTANCE` (default 3)
  - API: `evidence_family_id` on version summaries, `evidence_family` (match, matched version, distance, SimHash, rule, threshold, member count) on `GET /api/v1/source-versions/{id}`, and `GET /api/v1/evidence-families/{id}` (members in assignment order); API client regenerated
  - CLI `atlas ledger assign-families` (idempotent backfill; prints `{"assigned": [...], "families_created": N}`)
  - fixtures `tests/fixtures/syndication/lumentum`: hand-assembled from the recorded Lumentum fixtures (the Q4 FY2026 EX-99.1 trimmed to 40 top-level elements; a synthetic 8-K/A re-filing it byte for byte; a synthetic 8-K carrying a wire-service copy; the recorded 10-Q as the unrelated document); the manifest says what is synthetic
  - docs: `docs/decisions.md`, `docs/data-model.md` (2.4b), `docs/runbooks.md` (run the backfill once after `0016`), `AGENTS.md`
- **Tests:**
  - new `tests/unit/test_evidence_families.py` (9): single-feature known answer from BLAKE2b, occurrence weighting, normalization (case, punctuation, whitespace, NFKC ligature and fullwidth digits, underscore), empty text, same fingerprint under three `PYTHONHASHSEED`s in subprocesses, Hamming basics, the wire copy within 3 bits and the 10-Q beyond, a small edit within 3
  - new `tests/integration/test_evidence_families.py` (4): the gate (CLI ingest + worker pass: the three copies are one family, one founder / one `content_hash` / one `simhash` within 3, the 10-Q its own, companyfacts none, audited, a re-ingest adds nothing, `audit verify` passes); append-only tables and 404; threshold 0 recorded per family and the wire copy then apart; `assign-families` backfills a version inserted as the old code would have, then is a no-op
  - updated: `test_every_mutation_is_audited_in_one_chain_that_verifies` (the four family events per parsed filing), the migration head (`0016`)
  - red first: not strictly; the unit and gate tests were written before running the code, and all passed on their first run
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 446 passed and 9 deselected in 21.6 min, e2e 3 passed)
- **Fixture-only vs live:** fixture-only. No live requests. The syndicated copies are synthetic, derived from recorded SEC documents; no real news-wire copy was fetched (non-SEC sources come with tickets 04–06 and 08).
- **Deviations:** families are never merged and a version joins only the nearest family (decision entry). Unparsed versions (companyfacts JSON, failed parses) get no family. `assertion.independence_family_id` stays unused: an Assertion's family is its Source Version's, by join. The frontend shows nothing yet (the ticket asked for the API).
- **Next:** after deploy, `atlas migrate` then `atlas ledger assign-families` once. Tickets 13 (edge table family count) and 15 (Skeptic's distinct families) join `evidence_family_member` on the Assertion's Source Version.
## 2026-09-29: Phase 3-6a build ticket 18, XBRL normalization

- **Built:**
  - `backend/atlas/financials/`: `xbrl.py` (companyfacts parsing with exact decimals; per-fact availability via `filing_availability`, falling back to 23:59:59 ET on `filed`, basis `sec_filing_date_eod`, for accessions missing from the submissions index or outside the EDGAR holiday table; restates/reaffirms linkage; suspect flags `sign_change`, `large_change`, `old_period`; `select_as_of`, never using `frame`/`fy`/`fp`), `metrics.py` (concept families with precedence, `concept_mismatch`, derived quarters from adjacent YTD values within one currency unit, `CurrencyMismatch`), `service.py` (insert-only storage, one `financial_normalization` row and audit event per companyfacts version and normalizer version), `reads.py` (API views)
  - migration `0017` (down_revision `0012`): `financial_observation` (accession, source version, `available_at` + basis, `accepted_at`, currency, `fx_basis`, restatement link, suspect reasons) and `financial_normalization`, both insert-only
  - `configs/financials/metrics.yaml` (versioned metric catalog); setting `ATLAS_FINANCIAL_METRICS_CONFIG`
  - `ingest` job: after recording, normalizes the company's companyfacts version unless already done, with the submissions index re-requested (conditionally) for acceptance times; artifact `financial_normalization`
  - API: `GET /api/v1/companies/{id}/financials?as_of=&metric=`, `GET /api/v1/companies/{id}/financial-observations?as_of=&taxonomy=&concept=&unit=`, `GET /api/v1/financial-observations/{id}` (with key history); API client regenerated
  - fixtures: Lumentum companyfacts re-trimmed with 8 concepts (Including revenue, capex, 4 debt tags, diluted and outstanding shares): 10-Q facts read from the recorded 10-Q's inline XBRL, 10-K facts from the research note's quoted values (exact at 0.1M); a **hand-written** Nokia (ifrs-full, EUR) sample under `tests/fixtures/edgar/nokia` from the research note (provenance and inferred fields in its manifest); `tests/fixtures/financials/themes.yaml` (test universe)
  - docs: `docs/decisions.md` "XBRL normalization", `docs/data-model.md` §3.6, `AGENTS.md`
- **Tests:**
  - new `tests/unit/test_xbrl_normalization.py` (15): held 10-Q invisible until dissemination (808.4M from 2026-05-06 10:00Z); fallback availability; Lumentum Q4 FY26 = 1,006.3M derived (FY 10-K − 9M 10-Q, available at the 10-K's acceptance); nothing before the 10-K; Q4 FY25 = 480.7M across tags; tag precedence; Nokia FY2023 22,258M → 21,138M at 17:00Z/17:30Z; a key restated twice; InventoryNet 2018 reaffirm/restate and frame ignored; EPS 3.29 suspect; fy/fp are the filing's; 53-week FY2021 and 98-day quarter; no cross-currency derivation; no derived share counts; observed_revision within an accession
  - new `tests/integration/test_financials.py` (9): normalized once and audited; observations reconcile to the recorded 10-Q's inline XBRL (values, units, periods); revenue reconciles to the Q4 release's EX-99.1 ($1,006.3 / $480.7 / $3,014.0 / $1,645.0); capex, debt, diluted shares; every figure has sources with accession, concept, period, unit, `available_at`; Nokia restatement through the API with history; currencies never mixed; insert-only triggers; errors
  - updated: `test_ingest.py` audit-chain expectation (+1 `financial_normalization.created`), migration head `0017`
  - a mutation check (suspect threshold 0.5 → 0.01) turned 2 unit tests red. Code was written before the tests, not strictly red-first.
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 457 passed and 9 deselected in 19.8 min, e2e 3 passed)
- **Fixture-only vs live:** everything is fixture-tested; no SEC request was made. The Nokia fixture and the Lumentum 10-K additions are transcribed from the research note, not recorded bytes.
- **Deviations:** derived quarters are computed at read time (as of the cutoff), not stored; the research note's composite total-debt rule isn't implemented (`total_debt` is the combined tag only); strict replay (`ingested_at <= as_of`) left to Phase 6a; linkage is fixed at insert, so an observation that later sorts before stored ones doesn't relink them (documented).
- **Next:** the scenario model (Phase 5) reads `/financials`; record a real Nokia (or STM) companyfacts and the older Lumentum submissions page when live SEC access is approved; an FX source before any conversion.

## 2026-09-29: Phase 3-6a ticket 10, Investigator Claims → Assertions

- **Built:**
  - `backend/atlas/claims/`: `predicates.py` (the §5.5 whitelist with direction and object kind, `predicate_refusal` ("works/partners with" map to nothing), the layer taxonomy `substrate`/`epi`/`chip_laser`/`dsp`/`module`/`contract_manufacturing`/`system`, `directional_cue`, `company_names`/`mentions`/`names_party`); `extraction.py` (the `extract_claims` job: passages from entity tags and recall hits, batched Investigator calls, per-Claim checks ending in the existing span check, Assertions created in the batch's transaction, resumable batches, budget and quarantine handling); `reads.py`; `handlers.py` (registered pausable)
  - `backend/atlas/roles/investigator.py` and `roles/prompts/investigator.v1.md`: the Investigator role on the ticket-07 foundation
  - migration `0019` (down_revision `0015`): `claim_extraction`, `claim` (insert-only, triggers ENABLE ALWAYS)
  - `GET /api/v1/claims`, `GET /api/v1/claims/{id}`, `GET /api/v1/claim-extractions/{id}` (`api/claims.py`); API client regenerated
  - metrics `atlas_claims_total{outcome}` and `atlas_claims_rejected_total{reason}`
  - small additive edits: `Assertions.create(..., extractor_version=)`, `Assertions.create_within(connection, ...)` and a public `check_quote`; `RoleCaller.call_recorded` (returns the role call's ID); settings `investigator_max_passages` (24), `investigator_passages_per_call` (6); `builtin_registry`; `tests/fakes/litellm.py` `ChatReply.answer` (content computed from the request)
  - docs: `docs/decisions.md` entry, `docs/data-model.md` §3.1c and the `extractor_version` note, `AGENTS.md`, `.env.example`
- **Tests:**
  - new `tests/integration/test_claims.py` (12): accepted Claims become Assertions at their exact span (Coherent `supplies` NVIDIA, NVIDIA `owns` Coherent via "the Company"), no inverse Assertion; the request (whitelist, layers, companies, entity-tagged passages only, lowercase "coherent" never tags); recall hits after entity tags, capped with a dropped count; 11 rejection reasons stored and visible, no Assertions; **the co-mention gate** (the Coherent 10-K peer-group sentence naming Lumentum, 10 adversarial company-predicate Claims in both directions plus `partners_with`: all rejected, zero Assertions); an LLM outage pausing the queue and the job resuming at batch 2 in the same run; budget exhaustion; a quarantined batch; skipped unknown versions; 404s; metrics; claim rows insert-only
  - new `tests/unit/test_claim_predicates.py` (27): whitelist, direction, undirected relations, layers, directional cues, co-mention sentences, names and first-person references
  - migration head updated to `0019`
  - mutation check: making `directional_cue` always match turns the gate test red
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 457 passed and 9 deselected in 19.8 min, e2e 3 passed)
- **Fixture-only vs live:** all of it. The Investigator's answers are written by the tests (computed from the passages sent, quoting the recorded Coherent 10-K); no chat completion was made against LiteLLM/MiniMax. Recall is the recorded Hindsight fake's derived strict recall.
- **Deviations:**
  - A Claim names a passage ID and offsets within the passage; Atlas converts them to Source Version offsets (the spec lists `source_version_id` and char offsets on the Claim). The stored Claim has both.
  - Directional language is checked here, before an Assertion is created, so every Assertion an extraction creates is Relationship-eligible; ticket 12's reviewer judges whether the direction is right and extends the cue list.
  - Layer slugs are chosen here; ticket 01's config should use the same.
  - No `POST` API to start an extraction: `atlas jobs enqueue extract_claims` (and ticket 14) enqueue it.
- **Open risk:** models count characters poorly, so live runs may reject true quotes as `quote_mismatch` (the reason says where the quote does occur). Measure it in the live suite before deciding whether Atlas may locate a quote that occurs exactly once in its passage.
- **Next:** ticket 12 forms Relationships from accepted Claims' Assertions (`value_json.layer`, `product`); ticket 14 enqueues `extract_claims` with its investigation's `run_id`.

## 2026-09-29: Phase 3-6a ticket 08, Scout and leads

- **Built:**
  - `backend/atlas/roles/scout.py` + `roles/prompts/scout.v1.md`: the Scout role on the ticket-07 role caller (request: theme id/title/description, research question, `max_queries`; strict response `{queries: [{query, purpose}]}`)
  - `backend/atlas/discovery/`: `searxng.py` (`SearXNGClient`: `GET /search?q&format=json&engines=bing,brave`, results with URL/title/snippet/engines/published day, `unresponsive_engines` as `{engine, reason}`; every failure is `SearchFailed`), `leads.py` (`canonical_url`, lead + sighting storage, `list_leads`), `service.py` (`Scout.discover`: Bottlenecks content as quoted gaps once refreshed, one Scout call, first ≤ 10 distinct queries kept, per-query search with failures recorded, retry reuses the Scout's queries, run finished with its tokens; `get_discovery`/`list_discoveries`), `handlers.py` (the pausable `discover` job; payload `{theme, question}`)
  - migration `0018` (down_revision `0015`): `discovery`, `discovery_query`, `lead` (tier always `C`, unique canonical URL), `lead_sighting`
  - `GET /api/v1/leads[?theme=]`, `GET /api/v1/discoveries[/{id}]` (`api/discovery.py`); API client regenerated
  - settings `searxng_url` (optional provider, logs `searxng disabled: missing ATLAS_SEARXNG_URL`), `searxng_engines` (default `bing,brave`), `searxng_timeout_seconds`, `discovery_max_queries` (default 10, ≤ 10)
  - metrics `atlas_discovery_queries_total{status}`, `atlas_discovery_unresponsive_engines_total{engine}`, `atlas_leads_total`
  - `tests/fakes/searxng.py` (scripted per query: fixture, HTTP error, dropped connection) and three hand-written fixtures in `tests/fixtures/searxng/`
  - docs: `docs/decisions.md` entry, `docs/data-model.md` §3.1c, `AGENTS.md`, `.env.example`
- **Tests:**
  - new `tests/unit/test_searxng.py` (21): request shape and configured engines, result fields and published dates, unresponsive engines, 403/429/502/connection failure and a non-SearXNG body as `SearchFailed`, no client without a URL, canonical-URL cases, non-web URLs
  - new `tests/integration/test_discovery.py` (15): the Scout request (role, strict schema, prompt, Bottlenecks gaps as quoted data, `gaps_source`) and the searches; no gaps before the model's first refresh; ≤ 10 distinct queries (12 proposed, one a case/space duplicate); the configurable cap (and > 10 refused); Tier C leads deduplicated across queries (tracking-parameter, `www.`, port and fragment variants), FTP result dropped; a rerun deduplicates (same lead IDs, sightings grow, no new leads); theme filter and paging; **leads never create retain jobs or Evidence** (only `discover` jobs, no Source Documents/Versions, Assertions or memory documents, nothing retained into the Hindsight fake, after a further worker pass); a failed search recorded while the others proceed, with unresponsive engines, and no pause; all searches failing fails the attempt without pausing and the retry reuses the Scout's queries (one LLM call); no SearXNG → the job fails before any LLM call; unknown theme; a Scout 429 pauses the queue; 404 for an unknown discovery; metrics
  - `tests/unit/test_cli.py`: the worker also logs `searxng disabled: missing ATLAS_SEARXNG_URL`; migration head → `0018`
  - the tests were written before the code (the import failed, so not run red on their own); the integration module then passed first time
  - `tests/integration/test_queue_pause.py`: `discover` added to the expected pausable kinds (the first CI run failed there, 1 of 494, as expected from the new pausable kind)
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 494 passed and 9 deselected in 17.9 min, e2e 3 passed)
- **Fixture-only vs live:** all of it. No SearXNG, LiteLLM or Hindsight request was made to a live service. The SearXNG fixtures are **hand-written**, not recordings, in the shape of SearXNG's JSON output (https://docs.searxng.org/dev/search_api.html): `results[]` with `url`, `title`, `content`, `engine`, `engines`, `publishedDate`, and `unresponsive_engines` as `[engine, reason]` pairs; the reasons ("timeout", "Suspended: access denied") are SearXNG's messages but weren't observed on the owner's instance. Whether that instance enables `format=json` for these engines, and how often Bing/Brave come back unresponsive, is unverified. The Scout's answers are scripted; the prompt hasn't been tried on MiniMax.
- **Deviations:**
  - The job payload requires the research `question`; the theme config has no question field yet.
  - The "open gaps" are the Bottlenecks model's whole content, read by the Scout, not gaps parsed by code.
  - Only SearXNG's first result page is read. The per-run lead budget (spec §7.4) is left to ticket 14; this ticket bounds queries.
  - Leads dedupe globally, not per theme; `http` and `https` stay distinct in the canonical URL, `www.` doesn't.
  - A discovery whose job exhausts its attempts leaves its run unfinished (its role calls stay visible).
- **Next:** ticket 09 resolves entity mentions in leads (the Sumitomo Electric fixture lead names an unseeded company) into Candidates; ticket 14 runs the Scout inside an investigation (it will need `Scout` to use the investigation's run instead of starting its own) and applies the lead budget. A live discovery against the owner's SearXNG belongs in the opt-in live suite.

## 2026-09-29: Phase 3-6a build ticket 02, entity resolution and identity review

- **Built:**
  - `backend/atlas/identity/`: `normalize.py` (name normalisation: trailing legal forms dropped, HOLDINGS kept; ISIN Luhn, LEI mod-97, CIK padding, canonical `-` tickers; operating/segment MICs, Bloomberg venue codes, venue currencies, SEC exchange labels), `http.py` (sync JSON client: per-source `TokenBucket`, 429/5xx retry honouring `Retry-After`/`ratelimit-reset`, `IdentitySourceError`), `sec.py` (`company_tickers_exchange.json`, submissions incl. former names and ADR-shell detection; shares `SEC_RATE_LIMITER`), `gleif.py` (record, ISIN, exact legal name, full text; no `fuzzycompletions`; 60/min), `openfigi.py` (keyless `/v3/mapping`, batches of 10, `-`↔`/` tickers, 25/min), `resolver.py` (`EntityResolver.resolve(Mention)` → `Resolution` with per-identifier `Proposal`s tiered exact/corroborated/candidate, or conflict), `service.py` (`find_in_universe`, **`resolve_mention`** (the entry point for ticket 09), `resolve_universe`/`store_resolution`, the `IdentityMappings` review service and reads)
  - migration `0020` (down_revision `0018`): `security.segment_mic`, `share_class_figi`, `underlying_security_id`, `adr_ratio`, `review_state` (`figi` documented as composite, `exchange_mic` as operating MIC); `company_alias`; `identity_mapping` (provenance, tier, review state; CHECK that an owner-confirmed mapping is never `committed`)
  - `GET /api/v1/identity-mappings[/{id}]`, `POST /api/v1/identity-mappings/{id}/confirm|reject` (audited; confirming an LEI/CIK rejects the company's other pending ones); `/companies` returns the new security fields and `aliases`; API client regenerated
  - `atlas companies resolve [--company slug]` (seeds, then resolves; needs `ATLAS_SEC_USER_AGENT`); settings `sec_files_url`, `sec_data_url`, `gleif_url`, `openfigi_url`; `TokenBucket.wait` (sync) in `sources/sec_http.py`
  - `atlas.companies.seed` no longer overwrites `cik`/`lei`/`isin`/`figi` when config doesn't name them (a re-seed kept wiping resolved values)
  - `tests/fakes/identity.py` + `tests/fixtures/identity/` (with `manifest.json`); docs: `docs/decisions.md` "Entity resolution", `docs/data-model.md` §2.2/2.2a, `AGENTS.md`, `.env.example`
- **Tests:**
  - new `tests/unit/test_identity_sources.py` (21): ticker file, class suffixes, null exchange, UA; submissions (former names, null LEI), ADR shell, unknown CIK; SEC 10/s, GLEIF 60/min and OpenFIGI 25/min spacing; GLEIF lapsed LEI, ADR ISIN → TSMC, full text parent + subsidiaries; OpenFIGI XNAS miss vs XNGS hit, composite/ADR rows, `BRK/B`, error/warning shapes, 10-job batches, 429 with `ratelimit-reset`, persistent 429
  - new `tests/unit/test_entity_resolution.py` (13): LITE by CIK (cik exact, LEI corroborated owner-only, listing XNAS/XNGS composite FIGI, XNAS never sent), COHR by ticker (lapsed LEI, aliases), LEI-only Coherent → corroborated CIK link, TSM ADR by ticker and by ISIN, "Lumentum" by name → 3 candidates and no fuzzy search, LITE ISIN + Coherent CIK conflict, ticker/CIK conflict, ticker without venue, invalid identifiers dropped, ignored and shell CIKs, name normalisation
  - new `tests/integration/test_identity.py` (11): the CLI against the served fake (committed vs pending table, FIGIs on the config listing, a new COHR listing, aliases), idempotent rerun (no audit events), owner confirm (LEI set, alias, 409 on repeat, re-seed keeps it, audit chain verifies), reject with reason (422 without; kept, not re-proposed), 404, committed not reviewable, no UA → exit 2, `--company`, DB refuses auto-committed owner links, `resolve_mention` offline for universe companies (name, ticker on segment MIC, former name inside/outside its interval) and externally for unseeded TSM and for Lumentum's ISIN
  - `test_migrations.py` head → `0020`
  - The tests and code were written together, not red first; the unit modules passed on their first run apart from one tier fix (an LEI from the input was wrongly owner-flagged when the CIK carried the link).
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 648 passed and 9 deselected in 38.4 min, e2e 4 passed). A first run was killed from outside mid-pytest (exit 144, no failures to that point).
- **Fixture-only vs live:** all of it. No SEC, GLEIF or OpenFIGI request was made. The identity fixtures are **hand-written** from the research note's trimmed live responses (branch `research/identity-apis`, 2026-09-29), apart from Lumentum's and Coherent's submissions, which are the recorded EDGAR fixtures. The manifest lists which answers are assumed (GLEIF legal-name case sensitivity; full-text results for "Soitec SA" and TSMC; LITE on XNMS/XNCM; COHR's composite row; TSM's XNYS venue FIGI, which is made up; TSMC's `stateOfIncorporation` F5) and one synthetic LEI (Lumentum Operations LLC). `atlas companies resolve` has not been run against the live sources.
- **Deviations:**
  - A listing that resolution finds and config doesn't name starts on the day Atlas observed it: no source gives a start date. Past listings (IIVI) are not created.
  - Tiers are per identifier, and a resolution's tier is its worst proposal's. For the universe (CIKs from config) every LEI is owner-confirmed. LITE by CIK is therefore overall `corroborated`, not the research's "exact".
  - Conflicts are never stored as mappings (they have no single value): `resolve_mention` returns them to the caller.
  - Only pending mappings can be reviewed; undoing a committed one isn't built. ADR underlying links and ratios are schema only (no source; set by the owner later).
  - The ticker file used is `company_tickers_exchange.json` (a superset of `company_tickers.json`). OpenFIGI search and the undocumented `efts.sec.gov` endpoints aren't used. Non-US jurisdictions are compared through the company's country, not EDGAR's foreign state codes.
  - The CLI integration tests run at the real rate limits (≈2 min for the module).
- **Next:** ticket 09 calls `atlas.identity.service.resolve_mention(connection, resolver, Mention(name=…, ticker=…, mic=…))` and treats `company_id is None` as unseeded (`tier`, `entity`, `candidates`, `review_reasons` carry the rest). The owner should run `atlas companies resolve` live once and confirm the 12 companies' LEIs, then compare the live answers with the assumed fixture values.
## 2026-09-29: Phase 3-6a ticket 12, Relationships and review

- **Built:**
  - `backend/atlas/roles/reviewer.py` + `roles/prompts/reviewer.v1.md`: the Reviewer role (request: layers and items `{subject, predicate + reads, object company or text, product, layer, source (tier, filer)}`; the quote and ±600 characters of context as quoted low-trust `retrieved_data`; strict response `{reviews: [{item_id, verdict, direction, layer, suggested_layer, reasoning}]}`)
  - `backend/atlas/relationships/`: `checks.py` (the directional-language checker: the Investigator's cues plus a hedge list; the verbatim-span and Tier A checks; `review_outcome` combining them with the Reviewer's answer into `machine_reviewed` or `needs_human_review` with reason codes); `review.py` (the pausable `review_relationships` job: explicit IDs or a sweep, eligibility (`not_eligible` for co-mention, no layer, off-whitelist, closed Assertions), deterministic checks, batched Reviewer calls only for passing Assertions, one transaction per Assertion, run kept across retries, quarantine/no-answer/budget handling); `service.py` (linking Assertions to edges, lifting exceptions, owner approve/reject, all audited); `reads.py` (edge table with Evidence and family counts, sorting and filtering, detail with Evidence spans and machine reviews); `handlers.py`
  - migration `0022` (down_revision `0018`): `relationship` (identity immutable, no delete), `relationship_assertion` and `relationship_review` (insert-only), `relationship_review_job`
  - `GET /api/v1/relationships` (filters `layer`, `review_state`, `predicate`, `company_id`; `sort` subject/predicate/object/layer/review_state/evidence_count/family_count/created_at/updated_at, `order`), `GET /api/v1/relationships/exceptions`, `GET /api/v1/relationships/{id}`, `POST /api/v1/relationships/{id}/review` (`api/relationships.py`); API client regenerated
  - metrics `atlas_relationships{review_state}` (gauge) and `atlas_relationship_reviews_total{outcome}`
  - small additive edits: setting `reviewer_assertions_per_call` (5), `builtin_registry`, `api/app.py`, `metrics.py`, `.env.example`
  - docs: `docs/decisions.md` entry, `docs/data-model.md` §3.1e, `AGENTS.md`
- **Tests:**
  - new `tests/unit/test_relationship_checks.py` (23): explicit/hedged/absent language (six hedges, "May" the month isn't one, direction left to the Reviewer), each deterministic check's reason, every Reviewer answer short of a confirmation going to the exceptions queue, a missing answer, the Reviewer role's strict schema
  - new `tests/integration/test_relationships.py` (11): **the gate** (Investigator Claim → Assertion → review job → a machine-reviewed directed Coherent `supplies` NVIDIA edge at `chip-laser` with its product; open it and slice its span from the parsed content; owner approval; audit trail; a second sweep calls no model); the Reviewer request (quote/context only in retrieved data, low trust); rejected, uncertain, wrong-layer and NVLink ("supplier ... NVIDIA NVLink") proposals in the exceptions queue with reasons, settled by the owner; a Tier B copy (inserted by the test and put in the 10-K's family by `atlas ledger assign-families`) adding Evidence without a second family, a hedged manual Assertion as an exception, a co-mention and a layer-less manual Assertion forming no edge, none of them sent to the Reviewer; sorting/filtering/paging and 422s; owner approve/reject/409/404/422 and `atlas audit verify`; a later confirmed witness lifting an exception and never overriding the owner; a quarantined answer; an LLM outage pausing the queue and resuming in the same run; metrics; insert-only and identity triggers
  - migration head → `0022`; `review_relationships` added to the pausable kinds in `test_queue_pause.py`
  - the tests were written before the code (import errors); two test-helper bugs fixed on the first run, then green
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): ruff, strict pyright, frontend gates, API client check and static export **passed**; the pytest step was killed externally (exit 144, no failure, at 39% after `test_relationships.py` passed), so pytest and e2e were rerun directly: **637 passed, 9 deselected** in 42.8 min; e2e **4 passed**
- **Fixture-only vs live:** all of it. The Investigator's and the Reviewer's answers are written by the tests; no chat completion was made against LiteLLM/MiniMax, and the Reviewer prompt hasn't been tried on a real model. The Tier B source is a test-inserted copy of the recorded 10-K (no adapter records non-Tier A sources yet).
- **Deviations:**
  - The layer is part of an edge's identity; the product isn't (listed from the Assertions). §5.5's `product_id`, `theme_id`, event dates and `effective_status` aren't modelled.
  - The deterministic directional-language check doesn't judge direction (who "we" is decides it); the Reviewer's `direction` does. It adds a hedge list to the Investigator's cues.
  - An Assertion without directional language (co-mention) is `not_eligible` and forms no Relationship, rather than an exception, to keep the gate "a co-mention is never a Relationship".
  - The Reviewer runs on the configured role model, not a separate "Skeptic model" deployment.
  - Extraction doesn't enqueue the review; ticket 14 chains them (payload `run_id` supported).
- **Next:** ticket 13 builds the edge-table page on `GET /api/v1/relationships` (sort/filter/paging in place; each Evidence item carries `source_version_id` and the span for the viewer); ticket 14 enqueues `review_relationships` after `extract_claims`; ticket 20's publish gate requires `review_state = approved` for dependent Relationships. The live suite should measure the Reviewer's agreement with the owner on real filings.
## 2026-09-29: Phase 3-6a ticket 14, investigation orchestration

- **Built:**
  - `backend/atlas/investigations/`: `model.py` (the read side: the §7.2 request, budgets and usage, premises, tasks, leads, documents, the research card, events), `service.py` (`Investigations`: the round-1 plan, `advance` (cancel on disproven premises or all-cancelled inputs, enqueue ready tasks in the same transaction, stop when all are done), `stop`, `disprove`, `resume`), `tasks.py` (`TaskRunner`: Scout, per-company Investigator, Editor; pause/failure/budget handling), `handlers.py` (the pausable `investigation_task` job)
  - `backend/atlas/roles/editor.py` + `roles/prompts/editor.v1.md`: the Research Editor role (findings citing Claim IDs, open questions, a verdict)
  - migration `0023` (down_revision `0018`): `investigation`, `investigation_premise`, `investigation_task`, `investigation_lead`, `investigation_document`, `investigation_event` (insert-only, triggers ENABLE ALWAYS), `claim_extraction.continues_id`
  - `api/investigations.py`: `POST /api/v1/investigations` (202), `GET /investigations/{id}`, `GET /investigations/{id}/events`, `POST /investigations/{id}/resume`, `POST /investigations/{id}/premises/{key}/disprove`; API client regenerated
  - metric `atlas_investigation_stops_total{reason}` (every reason exposed at 0)
  - small additive edits to shared/earlier code: `JobQueue.enqueue_within` (`enqueue` now calls it); `Scout.discover(..., run_id=)` and `DiscoverPayload.run_id` (a discovery inside a caller's run leaves the run open); `ClaimExtractor.extract(job, payload=None)`, `ExtractClaimsPayload.continues` and `ClaimExtraction.continues_id`; `claims.handlers.claim_extractor` (factored out of the handler); settings `investigation_max_leads` (10), `investigation_max_documents` (25); `builtin_registry`; `app.py`
  - docs: `docs/decisions.md` entry, `docs/data-model.md` §3.1e, `AGENTS.md`, `.env.example`
- **Tests:**
  - new `tests/integration/test_investigations.py` (15): the fixed plan and the §7.2 request at creation (skipped Skeptic/Analyst slots, dependencies, premises, default budgets, events); default seeds are the theme's companies; **a full run** (Scout → Investigator on Coherent's 10-K/10-Q, Lumentum with no documents → Editor) in one run, stopping `answered`, with the card's finding spans, families, entity IDs and needs_review filled from the accepted Claim, the Editor sent quotes and leads as low-trust data, run tokens filled (via `atlas_llm_tokens_total{kind="investigation"}`); Editor findings citing a lead or nothing are dropped as unsupported → `needs_review`; lead budget and `as_of` bound what is read, no accepted Claim → `no_new_independent_evidence` without an Editor call; the shared document budget; **budget exhaustion mid-extraction** stops resumably with no card and the run open, resume (422 for a budget that isn't larger) continues the extraction with only the remaining passages in the same run; a budget spent before the Editor resumes into the Editor; **an LLM outage** (Editor 503) pauses the investigation (`paused: true`, job requeued with no attempt used, no card) and it resumes to `answered` after the pause; disproving a company premise cancels only that company's Investigator task; disproving the question cancels the plan and stops `premise_disproven` with no LLM call; a Scout that is quarantined on all 3 attempts stops `needs_review` and finishes the run; request validation, 404s, 409s; 503 without SearXNG; stop metrics exposed at 0
  - `tests/integration/test_queue_pause.py`: `investigation_task` added to the pausable kinds; migration head → `0023`
  - the tests were written alongside the code, not run red first; all 15 passed on the first full run after one fix (premise ordering)
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 618 passed and 9 deselected in 39.6 min, e2e 4 passed). A first run was killed by a signal partway through pytest (no failure) and was rerun.
- **Fixture-only vs live:** all of it. The Scout's, Investigator's and Editor's answers are scripted in the tests; SearXNG is the hand-written fixture fake; Hindsight the recorded fake. The Editor prompt hasn't been tried on MiniMax.
- **Deviations:**
  - Tasks run as `investigation_task` jobs that call the Scout's and Investigator's services in-process, not as separate `discover`/`extract_claims` jobs, so the DAG advances in the same transaction without a scheduler. The discovery and extraction records still exist.
  - One Investigator task per seed company, so a company premise can be disproven alone.
  - A `budget_exhausted` stop leaves the run unfinished (so resume can continue in it); its tokens show from the role calls. Other stops finish the run with its totals.
  - Premises are disproven by the researcher (`POST .../disprove`); the Skeptic doing so is ticket 15.
  - "Fetched documents" are archived Source Versions read (the latest parsed version per document as of `as_of`); leads aren't fetched.
  - `answered` is the Editor's verdict gated by code (≥ 1 supported finding, none unsupported); every finding still has `needs_review: true` until its Assertions are corroborated.
  - Only round 1 exists; `max_rounds` is recorded and constrained, and the follow-up round is ticket 17.
- **Next:** ticket 15 fills the Skeptic slot (and can disprove premises); ticket 16 saves the Editor's card as a Hypothesis; ticket 17 adds the follow-up round and the workbench; ticket 19 fills the Analyst slot. A live investigation belongs in the opt-in live suite.
## 2026-09-29: Phase 3-6a ticket 04, HKEXnews (blocked), the fetch gate and manual import

- **Built:**
  - `backend/atlas/sources/robots.py`: robots.txt per RFC 9309 (groups for `AtlasResearch` merged, else `*`; longest match, allow wins ties; `*`/`$`; percent-encoding normalized; 4xx = unrestricted, 5xx/unreachable = disallow all)
  - `backend/atlas/sources/gate.py`: the site register (`configs/sources/sites.yaml`, `ATLAS_SOURCE_SITES_CONFIG`; per site hosts, terms URL/date, `automation: allowed|forbidden|unchecked`, `consent`, `block_reason`, rate), `FetchGate` (register → terms → robots.txt, read once per origin and archived) and `GatedHttpClient` (asks before every request; `FetchBlocked` carries the decision)
  - `backend/atlas/sources/hkexnews.py`: the HKEXnews adapter (title search by stockId, `result` as a JSON string, `DATE_TIME` Hong Kong time → UTC `publisher_timestamp`, PDF/HTML rows, paging on `hasNextRow` to 500 rows then fail); `SourceCandidate.announcement` (`ExchangeAnnouncement`) and `SourceCandidate.manual` (`ManualImport`)
  - `backend/atlas/ledger/exchange_ingest.py`: the shared exchange ingest (`EXCHANGE_SOURCES`: source path → register site, provider, adapter factory; today `exchange:hkex`); every gate decision recorded, blocked ones listed in the job's artifacts; `atlas.ledger.ingest` dispatches on `source_path` and refuses paths without an adapter (CLI too; `--forms` refused for exchange companies)
  - `backend/atlas/ledger/gates.py` + migration `0021` (down_revision `0018`): append-only `fetch_gate_decision`, `fetch_observation.gate_decision_id` with a trigger refusing a blocked decision; `GET /api/v1/companies/{id}/fetch-gate-decisions?status=` and `GET /api/v1/fetch-gate-decisions/{id}`; `FetchObservation.gate_decision_id` in the source-version API; client regenerated
  - `backend/atlas/ledger/manual_import.py` + `atlas sources import --company --file --origin-url --published-at [--title --publisher --media-type]`
  - ledger: exchange and manual-import Source Document identities; `published_at` set from the publisher's time; `FixtureReplay` `ignore_query`
  - config: `configs/sources/sites.yaml` (HKEXnews `forbidden` with the lead's block reason; Innolight IR `unchecked`); theme config v3 gives Innolight `exchange: {issuer_code: "03308", feed_id: "1000311764"}` (`CompanyConfig.exchange`); settings `exchange_live`, `exchange_user_agent`, `exchange_fixtures_dir`, `source_sites_config`
  - fixtures: `scripts/make_hkexnews_fixtures.py` → `tests/fixtures/hkexnews/innolight/` (hand-written), `tests/fixtures/robots/` (three robots files)
  - docs: `docs/decisions.md` (terms quoted, gate, RFC 9309, manual import), `docs/source-licenses.md` (§3 row, §5 register rows), `docs/data-model.md` (§2.4c, ER), `CONTEXT.md` (Fetch Gate Decision), `AGENTS.md`, `.env.example`; `tests/harness.py` passes `ATLAS_SOURCE_SITES_CONFIG` to the CLI
- **Tests:**
  - new `tests/unit/test_fetch_gate.py` (25): Innolight IR `Disallow: /` blocks every page and only `/robots.txt` is requested; `/uploads/` blocked, other pages fetched; the committed register blocks the IR site and HKEXnews (with the IIS reason) with zero requests; 13 RFC 9309 cases from `rules.txt`; `*` fallback for another token; the allowed decision's robots record (hash, status, read once); 404/HTML/503 robots; unregistered host; consent lifts a prohibition; register validation
  - new `tests/unit/test_hkexnews_adapter.py` (12): candidates, UTC times, announcement fields, search parameters, since/limit, paging and the 500-row cap, non-document rows, malformed answers, empty result, fetch
  - new `tests/integration/test_hkexnews.py` (8): with a **synthetic test consent**, ingest via `atlas ingest` + worker pass (3 versions, `publisher_timestamp`, languages en/zh/en, PDF anchors), retains for the 2 English only (retained into the Hindsight fake), each fetch's allowed gate decision (terms + 404 robots), a robots-disallowed path blocked and visible with no observation, re-ingest 304s, the DB trigger refusing a blocked decision, `--forms` refused; with the **committed register**, the ingest records one `blocked` decision (terms, the IIS reason, no robots read) and nothing else
  - new `tests/integration/test_manual_import.py` (8): import → `manual_import` document with origin URL, publisher from the register, `available_at`/`published_at` from `--published-at`, parsed, Evidence Family founder, retained, audited under `local-researcher`; same bytes again → `unchanged`, one version, no retain; a Chinese PDF archived, not retained; five refusals (naive time, bad time, bad URL, unknown company, unreadable file) exit 2 and record nothing
  - changed: `test_universe.py` (Soitec/IQE refused as "no adapter"; the directly enqueued job uses Soitec), `test_migrations.py` head `0021`
  - not run red first as whole modules; the tests were written against the design and fixed until green (line numbers in the robots expectations and the CLI's relative register path were the fixes)
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 655 passed and 9 deselected in 38.0 min, e2e 4 passed)
- **Fixture-only vs live:** everything. **No request was made to HKEXnews or Innolight** (terms forbid it; the IR robots files are from the seed-list research). The HKEXnews fixtures are hand-written from public descriptions of the title-search JSON (seed-list research; https://github.com/carrotly-ai/disclosures/blob/main/HKSG-FEASIBILITY.md) and their PDFs are synthetic. That `DATE_TIME` is Hong Kong time is unverified against a live response. The HKEX terms were read on the web (hkexnews and hkex.com.hk copies).
- **Deviations:**
  - **Scope change (lead, 2026-09-29):** HKEX's Terms of Use forbid automated access (IIS licence or written consent required), so Atlas does not fetch HKEXnews: `exchange:hkex` ingests record a `blocked` decision, and Innolight's documents come in through the new manual import. The HKEXnews adapter is kept and tested (behind a synthetic consent in tests) for a future licence/consent.
  - The acceptance's "recorded responses" are hand-written, not recorded.
  - A blocked request is a `fetch_gate_decision` row with `status = blocked`, not a `fetch_observation` (which needs a document and bytes); allowed ones are linked from their observations. A blocked ingest succeeds and lists its blocks.
  - SEC EDGAR fetches aren't gated (NULL `gate_decision_id`). A cross-host redirect isn't re-gated.
  - `--all-history` for an exchange company falls back to the adapter's 730-day lookback.
  - During the first CI run I stopped it with `pkill -f pytest` to apply the scope change; that pattern could also have stopped other worktrees' pytest runs at that moment (about 16:50 local).
- **Next:** tickets 05/06 add an `ExchangeSource` (FCA NSM for IQE, AMF info-financière for Soitec) and their register rows; the owner decides whether to seek an HKEX IIS licence or consent, and imports Innolight's interim results by hand meanwhile.
## 2026-09-29: Phase 3-6a ticket 28, live extraction smoke test (built; not yet run live)

- **Built:**
  - `tests/live/test_extraction_smoke_live.py`: the opt-in smoke test. It uses a throwaway database (`atlas_live_extract_*`), ingests the Lumentum and Coherent EDGAR fixtures and seeds the universe plus NVIDIA. Then it runs three `extract_claims` jobs through a worker pass, each with at most 4 passages in one call:
    - the Lumentum FY2026 10-K Item 1
    - the Lumentum Q4 FY2026 EX-99.1
    - the Coherent FY2026 10-K entity-tagged passages
  - The Lumentum filings name no other known company (0 entity-tagged windows), so a **stubbed recall** picks their sections. The handler is `ClaimExtractor` as `extract_claims` runs it, but with that recall. Hindsight is the recorded fake on localhost, used for the ingest and the run record only; no Hindsight is needed. The Investigator calls the real LiteLLM (`ATLAS_LLM_ROLE_MODEL`, default MiniMax-M3), or in a rehearsal the scripted fake.
  - Call cap: 3 calls × `MAX_ATTEMPTS` (2) = 6 worst case, asserted ≤ 10 at import and on the recorded attempts. Other bounds: a per-run token budget of 40,000, and one job attempt (no retry). The preflight refuses (exit 4) under `CI`, without LiteLLM settings, or when the model isn't routed (`/model/info` only).
  - `tests/live/extraction_smoke.py`: the report writer (`results.json` + `summary.md` under `ATLAS_LIVE_RESULTS_DIR`, default the gitignored `.scratch/live-runs/`):
    - per extraction: passages, calls and tokens
    - per Claim: predicate, outcome, reason_code
    - for each `quote_mismatch`: whether the quote occurs in its passage `exactly_once`/`multiple`/`not_at_all`, exactly and after folding whitespace/quotes/dashes, and for an exactly-once quote what the party and directional checks would decide once located
    - totals: the mismatch share of the Claims that reached the span check, and the >20% flag
  - `scripts/live-extraction-smoke.sh` (`--rehearse`, `--model`, `--keep-db`, `--results`, `--yes`, `--dry-run`). It reads LiteLLM settings from the env or `.env` (CRLF-safe, never printed) and asks before a live run.
  - `tests/live/conftest.py`: the smoke file is gated like the Phase 2 suite, with its own skip reason
  - docs: `docs/runbooks.md` "Live extraction smoke test", `AGENTS.md`
- **Tests:**
  - rehearsal (`scripts/live-extraction-smoke.sh --rehearse`): **1 passed**. 3 calls, 10 scripted Claims: 1 accepted, and 9 `quote_mismatch` classified as expected: exactly_once ×4 (one would be accepted once located), multiple ×2, not_at_all ×3.
  - `tests/unit/test_live_suite_guard.py`: +2. The smoke test is deselected by default, skipped without `ATLAS_LIVE_TESTS`, and refused (exit 4) under `CI`. 5 passed.
  - live mode without LiteLLM settings: refused before any call, and the report was written with the reason
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 605 passed and 10 deselected in 33 min, e2e 4 passed). The first run failed 1 test: the Phase 2 guard asserts that suite's skip message, which I had generalised. Each suite now has its own skip reason.
- **Fixture-only vs live:** only the rehearsal ran. **No chat completion was made against LiteLLM/MiniMax.** The live run (ticket box 2) is for the lead, with the owner's go-ahead; the decision entry (box 3) depends on its numbers.
- **Deviations:** the test builds the `extract_claims` handler itself, to stub the recall. It does not use `builtin_registry`, whose recall needs Hindsight. The run record's Hindsight version is the fake's.
- **Next:** run `scripts/live-extraction-smoke.sh --model MiniMax-M3` and record `summary.md` here. If the `quote_mismatch` share is over 20%, write the decision entry on locating exactly-once quotes, citing the `exactly_once`/`located_would_be_accepted` counts.

## 2026-09-29: Migrations renumbered (Phase 3-6a batch 1-2)

Tickets 01–04, 07, 08, 10–12, 14 were built in parallel with reserved revision IDs, then chained at merge in merge order, so the IDs ran out of numeric order. Nothing had been deployed, so they were renumbered to follow the chain. Earlier entries in this log use the old IDs; the mapping, old → new:
- 0015 → 0013 (role calls)
- 0014 → 0014 (PDF and language)
- 0013 → 0015 (company layer and source path)
- 0016 → 0016 (Evidence Families)
- 0017 → 0017 (financial observations)
- 0019 → 0018 (Claims)
- 0018 → 0019 (leads)
- 0020 → 0020 (identity)
- 0022 → 0021 (relationships)
- 0023 → 0022 (investigations)
- 0021 → 0023 (fetch gate)

The chain is now 0012 → 0013 → … → 0023.
## 2026-09-29: Phase 3-6a ticket 28, live extraction smoke run (LIVE, small sample)

- **What ran:** the Investigator's `extract_claims` against real MiniMax-M3 through the owner's LiteLLM, with the owner's go-ahead, at 2026-09-29T18:25Z, over recorded Source Versions: the Coherent FY2026 10-K, Lumentum's 10-K Item 1 and an EX-99.1 release.
- **Results (LIVE):** 4 Investigator calls, 18,979 tokens in / 918 out. **3 Claims proposed, 0 accepted, 3 rejected `quote_mismatch`**, all from the Coherent 10-K. Of the 3 quotes, 2 occur verbatim exactly once in their passage (the model's offsets were wrong) and would have passed every later check once placed; 1 was a paraphrase in no passage. The Lumentum 10-K Item 1 and the EX-99.1 produced no Claims.
- **Only this was measured:** one run, one model, three documents, three proposals. It says offsets are unreliable; it says nothing yet about recall (Claims the model missed), the directional-language check or the Reviewer on live output.
- **Deviation:** the ticket's first box (a committed opt-in live test producing the report) is left unticked: no such test is on the branch this entry was written from (`integrate-p3b`), so the run's harness is not recorded here.
- **Next:** the owner's decision below; a larger live sample once the investigation workflow is in place.

## 2026-09-29: Claim quotes are located, not trusted (owner decision after ticket 28)

- **Built:**
  - `backend/atlas/claims/extraction.py`: after the out-of-passage check, a Claim's quote is placed: at the model's offsets if it is exactly there (`model`), else at its one exact occurrence in the passage (`located`); no occurrence is `quote_mismatch` (the span check on the model's span, message unchanged); more than one is the new rejection `quote_ambiguous` (the reason lists up to five occurrences). The Assertion span check (`check_quote`) and every later check run on the final span. The model's offsets stay in `claim.proposed`.
  - migration `0024` (down_revision `0023`): `claim.offset_source` (`model` | `located`, null when never placed or recorded earlier); `claim` stays insert-only
  - `atlas.claims.reads.Claim.offset_source` (so `GET /api/v1/claims[/{id}]` shows it); API client regenerated
  - docs: `docs/decisions.md` "Claim quotes are located, not trusted" (the ticket-10 no-search bullet marked superseded), `docs/data-model.md` §3.1c; ticket 28's acceptance boxes
  - metrics: unchanged; `atlas_claims_rejected_total{reason}` groups by whatever reason codes exist, so `quote_ambiguous` appears without a code change
- **Tests** (`tests/integration/test_claims.py`, scripted LiteLLM fake at the extraction job/API seam):
  - new: wrong offsets + a quote once in its passage → accepted, `offset_source = located`, the proposed offsets kept, the Assertion's span the located one and exact in the parsed text; correct offsets → `model`; wrong offsets + a word the passage repeats → `quote_ambiguous`, no Assertion; a paraphrase → `quote_mismatch`, `offset_source` null
  - changed: the rejection-list test's shifted-offset case (which is now located and accepted) became the paraphrase case
  - migration head → `0024`
  - red first: the new tests failed on the missing `offset_source` field before the code; then two fixes (a word the passage really repeats; a stray tuple) and `test_claims.py` **15 passed**, `test_migrations.py` passed
  - `scripts/ci.sh --no-image` (with `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64`): **passed** (ruff, strict pyright, frontend gates, API client check, pytest 700 passed and 9 deselected in 63.3 min, e2e 4 passed)
- **Fixture-only vs live:** the change is fixture-tested only (scripted Investigator answers against the recorded Coherent 10-K). It has not been rerun against MiniMax; the smoke numbers above are from before it.
- **Deviations:** the out-of-passage check (`quote_outside_passage`) still runs first on the model's offsets, so a quote with offsets past the passage's end is rejected even if it occurs once in the passage (the rule only replaces the span check).
- **Next:** rerun the live smoke with this rule and compare `offset_source` counts.
