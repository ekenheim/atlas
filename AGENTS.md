# Atlas Research: agent guide

Evidence-driven investment research platform built around Hindsight. Start with `START_HERE.md`; the authoritative spec is `hindsight_investment_research_build_plan.md` (v1.1).

## Commands

- `scripts/ci.sh`: the one CI entrypoint (GitHub Actions runs exactly this). `--no-image` skips the image build.
- `uv run pytest`: unit tests (network blocked by pytest-socket) and integration tests (localhost only; needs `docker compose up -d --wait postgres-app silo`).
- `uv run atlas api | worker [--once] | migrate`: the three roles of the one image.
- `uv run atlas audit verify`: check the audit hash chain; exits 1 if it is broken.
- `uv run scripts/provision_archive.py --endpoint <url>`: the owner's one-off archive bucket/user provisioning (root credentials from `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`; see `docs/runbooks.md`).
- `uv run atlas companies seed`: create or update the companies in `configs/themes/ai-infrastructure.yaml` (the 12-company photonics universe, each with its layer and source path; idempotent).
- `uv run atlas ingest --company <slug> [--key K]`: enqueue an ingest job for a company whose source path is `sec` (others are refused; recorded fixtures exist for `lumentum` and `coherent`); `atlas worker --once` runs it. Fixture mode needs `ATLAS_SEC_FIXTURES_DIR=tests/fixtures/edgar`; `ATLAS_SEC_LIVE=true` fetches from SEC. With `ATLAS_HINDSIGHT_URL` set (and the template applied), each new parsed Source Version is then retained; `GET /api/v1/source-versions/{id}/memory` shows its sections. `atlas jobs enqueue retain --key K --payload '{"source_version_id": "..."}'` retains one by hand. Add `--backfill` (to `ingest` or `jobs enqueue`) to make it backfill class: it and its retains run only in `ATLAS_BACKFILL_WINDOW` (default `01:00-07:00`, `ATLAS_BACKFILL_TIMEZONE`). A 429 or outage pauses the Hindsight job kinds with backoff (≤ 1 h); `GET /api/v1/queue` shows the pause, the window and pending jobs by kind.
- `GET /api/v1/companies/{id}/financials?as_of=&metric=` (canonical metrics from `configs/financials/metrics.yaml`, derived quarters included), `GET /api/v1/companies/{id}/financial-observations?as_of=` and `GET /api/v1/financial-observations/{id}` (with its restatement history): as-of XBRL financials. Each ingest normalizes the company's companyfacts Source Version once; every fact takes its filing's `available_at` (rules in `docs/decisions.md`, "XBRL normalization").
- `uv run atlas ledger correct-availability`: record (append-only, audited) the EDGAR dissemination-time correction for Source Versions ingested before that rule; idempotent (`docs/runbooks.md`).
- `uv run atlas ledger assign-families`: put parsed Source Versions recorded before Evidence Families into their family (new versions get one at ingest); idempotent. `GET /api/v1/source-versions/{id}` shows a version's `evidence_family`, `GET /api/v1/evidence-families/{id}` a family's members.
- `POST /api/v1/memory/recall` (synchronous) and `POST /api/v1/memory/reflect` (a `reflect` job; `GET /api/v1/memory/reflect/{id}` for the answer): scoped by `company_ids` and `theme_ids`, every citation resolved to a Source Version section and labeled resolved, unverified or broken (rules in `docs/decisions.md`).
- `uv run atlas hindsight apply-template`: dry-run, then import `configs/hindsight/bank-template.json` into the research bank, recording its version. A mental model whose trigger could run away (no explicit `refresh_after_consolidation: false`, no `refresh_cron`, no minimum interval) makes the template invalid.
- `GET /api/v1/mental-models[/{id}]`: the template's mental models (Theme status, Bottlenecks) with content, history, citations resolved like a reflect answer's, and Atlas's refresh records. `atlas worker` enqueues each model's daily `refresh_mental_model` job from `ATLAS_MENTAL_MODEL_REFRESH_AT` (06:30 UTC); the job is pausable and skips a model refreshed inside its minimum interval or with nothing new. `atlas jobs enqueue refresh_mental_model --key K --payload '{"mental_model_id": "theme-status"}'` asks for one by hand.
- `docker compose --profile hindsight up -d`: local Hindsight 0.10.1 + pgvector, via LiteLLM (needs `ATLAS_LITELLM_URL`/`_API_KEY`; never in CI).
- `scripts/live-tests.sh [--rehearse] [--stop-before-llm] [--model MiniMax-M3] [--profile small|full] [--down]`: the live Phase 2 gate suite (`tests/live/test_phase2_gate_live.py`) against real Hindsight + MiniMax. It is opt-in (the `live` marker **and** `ATLAS_LIVE_TESTS=1`), never runs in CI and spends MiniMax quota, so only run it with the owner's go-ahead. `--rehearse` runs it against the recorded fakes instead. See `docs/runbooks.md`, "Live test suite".
- `npm --prefix frontend run lint | typecheck | test | build`: the frontend gates; `test` runs the unit tests in `frontend/unit/` (no browser); `build` writes the static export to `frontend/out/`.
- `scripts/gen_api_client.sh [--check]`: regenerate the frontend's typed API client (`frontend/lib/api/{openapi.json,schema.ts}`) from the FastAPI OpenAPI schema; commit the result. CI runs `--check`, which fails on a stale client.
- `uv run python scripts/make_pdf_fixtures.py`: rewrite the hand-built PDF fixtures in `tests/fixtures/pdf/` (deterministic; a unit test checks the checked-in files match).
- `uv run python scripts/e2e.py`: the Playwright tests of the source viewer and its Assertions (needs `postgres-app` and a built `frontend/out/`). It seeds a fresh database from the Lumentum EDGAR fixtures, serves the API and export on a free port, and skips with a message locally if chromium can't be installed.

## Layout

- `backend/atlas/`: the Python package (`api/` FastAPI app, `archive/` content-addressed archive (filesystem + S3), `assertions.py` Assertions (exact quote spans, review, supersession), `audit.py` hash-chained audit trail, `bank_template.py` applying the versioned bank template, `companies.py` the company universe from config, `db/` the engine factory (`create_engine`) and migrations, `financials/` XBRL companyfacts normalization (as-of observations, restatement links, metrics and derived quarters), `hindsight/` the only Hindsight HTTP client, `jobs/` Postgres job queue and worker (`pacing.py`: failure classification, the queue pause and the backfill window; `resources.py`: the gateway, engine and run recorder a Hindsight job handler holds for one attempt), `ledger/` the source ledger (Source Documents, Source Versions, fetch observations), Evidence Families (`families.py`, SimHash) and the `ingest` job, `llm_routes.py` the LiteLLM route recorder (`/model/info`), `metrics.py` Prometheus metrics read from the database at scrape time, `parsing.py` the deterministic HTML/text/PDF parser (pypdf, pinned exactly; page anchors, the language), `retention/` retaining Source Versions into the research bank section by section (the `retain`, `poll_operation` and `reprocess` jobs, the sectioner, the memory-document mapping), `research/` scoped recall and the `reflect` job, the provenance resolver (memory → Source Version section; citation states) and the quote rule, `mental_models/` the daily refresh schedule, the `refresh_mental_model` job and the mental-model read side, `roles/` research roles' LLM calls (versioned prompts, fixed directives, strict JSON schema, one repair then quarantine, per-run token budget; `GET /api/v1/runs/{id}/role-calls`), `runs.py` the minimal run record, `sources/` source adapters (SEC EDGAR), `settings.py`, `health.py`, `cli.py`)
- `tests/fakes/hindsight.py`: the recorded Hindsight fake (an `httpx2.MockTransport` replaying `spikes/hindsight/recordings/`; `hold_operation`, `derive_retains` (with each derived document's memory list), `report_zero_facts` and `hold_retains` (with an optional `error_message` and `times`), `derive_memories` (facts, `derive_observation`, strict recalls), `forget` and `script_reflect`, and by default the template import with mental models, the imported models' reads and history, `script_refresh` and `apply_refresh`, are its documented derivations, a deviation from the spec listed in `docs/decisions.md`); `tests/fakes/litellm.py` fakes LiteLLM `/model/info` and scripted `/chat/completions` (`script_chat` with `ChatReply.json`/`text`/`error`/`unreachable`); `tests/fakes/serve.py` serves a fake on localhost for the CLI subprocess and the API
- `frontend/`: Next.js static export, served by FastAPI: the source viewer (`app/` pages take `?id=`; `lib/api/client.ts` wraps the generated `schema.ts`; `components/assertions.tsx` creates Assertions from a selection and reviews them, with `lib/offsets.ts` converting DOM (UTF-16) selection offsets to the API's code points; `components/source-document.tsx` a Source Document's summary rows, shared by the source and version pages; `e2e/` the Playwright tests; `unit/` unit tests of the pure modules)
- `tests/unit`, `tests/integration`: tests at the agreed seams (HTTP API, CLI entry, migrations); `tests/harness.py` the shared harness (`make_settings`, the `Atlas` harness, `Clock`, `scrape_metrics`, shared fixture values; test modules never import from each other) and `tests/integration/conftest.py` the shared fixtures (`database_url`, `engine`, `hindsight` serving `hindsight_fake`); `tests/live`: opt-in live tests (the SEC smoke test; the Phase 2 gate suite, with its stack, preflight and report in `stack.py`)
- `configs/`: versioned config (Hindsight bank templates; `themes/` the company universe and themes; `prometheus/atlas-alerts.yaml` the PrometheusRule alert rules, not deployed from here)
- `spikes/hindsight/`: the Hindsight 0.10.1 spike, fixtures and recordings (contract-test source)
- `.scratch/`: the local issue tracker (the decision map and build tickets)

## Conventions

- Test-first at agreed seams only; test behavior through public interfaces, never internals. Real Postgres, never SQLite.
- Settings are `ATLAS_*` env vars (or `.env`), validated at startup. Optional providers log `<provider> disabled: missing <VAR>` once.
- Ruff and strict pyright must be clean; TypeScript is strict.
- Record each ticket's files, tests and results in `docs/implementation-log.md`. Never claim a live integration was tested when only fixtures were.

## Agent skills

### Issue tracker

Local markdown files under `.scratch/` (no remote tracker). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Hindsight skills

- `hindsight-docs` is the Hindsight 0.10.1 documentation and OpenAPI schema, pinned to the server version. The feature matrix and recordings win where they disagree.
- `hindsight-self-hosted` gives development memory in the **`atlas-dev`** bank on the owner's shared Hindsight, via the `hindsight` CLI. Never use Atlas's research banks for it, and keep decisions in the repo.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
