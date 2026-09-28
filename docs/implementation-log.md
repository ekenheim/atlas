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
