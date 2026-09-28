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
