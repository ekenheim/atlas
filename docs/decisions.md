# Decisions and spec deviations

Deviations from `hindsight_investment_research_build_plan.md` v1.1, and decisions the spec left open. ADRs for hard-to-reverse architectural choices live in `docs/adr/`.

## 2026-09-28: charting session (`.scratch/atlas-pilot/map.md`)

- **Pilot auth (deviates from §11, §13.3, Appendix A).** The cluster has no Authentik forward-auth/OIDC pattern on internal routes. For the pilot, Atlas uses the cluster's standard private-CIDR Envoy `SecurityPolicy`, with the actor identity taken from config (as in local dev). Every mutation still records an actor and an audit event. Authentik is post-pilot.
- **All LLM traffic via LiteLLM, including Atlas Hindsight (tightens §6.1).** Unlike the shared `llm/hindsight` release, which calls `openai-codex` directly, the dedicated Atlas Hindsight's extraction and reflect models are LiteLLM routes. The extraction model is chosen by a bake-off among already-paid options (MiniMax, self-hosted, and the subscription routes if their terms allow it) rather than a new paid API.
- **The CI gate before the GitHub remote exists (§14 Phase 0).** One local entrypoint runs lint, types, migrations and fixture-only tests; the GitHub Actions workflow calls the same entrypoint. The remote `ekenheim/atlas` is added before Phase 2.
- **Embeddings (§6.1).** Reuse `qwen3-embedding-0.6b` via LiteLLM (1024 dims), the same as the shared Hindsight.
- **Release-driven deployment (refines §12, Appendix A).** The app lives in its own GitHub repo under `github.com/ekenheim`. Versioned releases publish images to GHCR, and the home-ops deployment pins a released version and is bumped per release, never tracking `main`. Home-ops holds only manifests.
- **Issue tracking.** Local markdown under `.scratch/`, permanently (see `docs/agents/issue-tracker.md`).

## 2026-09-28: Hindsight 0.10.1 feature matrix (`docs/hindsight-feature-matrix.md`)

- **Provenance resolution (refines §6.4):** reflect citations carry no `document_id`. Atlas resolves observations through `source_memory_ids` to world facts, then maps each world fact to its Source Version via `document_id` (`srcv:<sha256>`) and the preserved `metadata.source_version_id`. Content that reflect draws from raw chunks, with no memory ID, is unverified until matched to an archived span.
- **Bank configuration uses versioned templates (§6.2):** 0.10.1 supports template export, dry-run and import, so the config-API fallback isn't needed.
- **Response schemas avoid union types:** 0.10.1 returns 500 on `"type": [..., "null"]`.
- **Worker slots ≥ 3:** consolidation reserves 2; pacing uses `HINDSIGHT_API_LLM_MAX_CONCURRENT`.

## 2026-09-28: models, pacing and Hindsight integration (tickets 05 and 07)

- **LLM:** MiniMax-M3 with thinking disabled for both extraction and reflect, behind the LiteLLM aliases `atlas-extract` / `atlas-reflect`. There is no fallback model; on 429 or an outage the ingest queue pauses with backoff. Routed models are recorded per run from LiteLLM `/model/info`.
- **Pacing:** Hindsight runs 2 concurrent LLM calls with 4 worker slots, and the backfill runs in a nightly window.
- **Document IDs** are per Source Version UUID and section (ADR-0001), which deviates from the spec's `srcv:<sha256>` example.
- **Only strict tag matching** is allowed through the gateway.
- **Citation states:** resolved / unverified / broken. Only resolved citations count as Evidence.
- **Phase 2 mental models:** Theme status and Bottlenecks, refreshed on a daily cron (not after consolidation). No knowledge pages in Phase 2.

## 2026-09-28: archive durability (ticket 10)

- **Bucket provisioning by script, not OpenTofu (deviates from Appendix A):** OpenTofu isn't running, its state location is unknown, and most existing buckets are hand-made. A re-runnable minio-py script creates `atlas-archive` (object lock, Governance, 10-year default retention), a scoped `atlas` user without bypass rights, and prints the credentials for Bitwarden.
- **Off-cluster copy:** a nightly copy-only CronJob to R2 `atlas-archive-offsite`. Immutability is guaranteed on MinIO only.
- **Dev/CI S3:** MinIO images and binaries are no longer publicly distributed (the project was archived 2026-04-25). Compose/CI use PGSTY Silo (a MinIO fork, pinned by digest; RustFS as fallback), verified for versioning, object lock and `If-None-Match` (ticket 13). Dev defaults to the filesystem backend.
- **Cluster MinIO image:** it can't be re-pulled from quay. Spegel's peer-to-peer image cache mitigates this; the owner accepts the residual risk.

## 2026-09-28: deploy shape (ticket 09)

- **Hindsight API is in-cluster only.** No route; the control-plane UI is on the internal route `atlas-hindsight.<domain>`.
- **No TEI reranker sidecar:** reranking goes through LiteLLM `rerank`.
- **`vector` extension:** created once by hand by the superuser, not by an init container.
- **Release deployment:** Renovate automerge is off for Atlas and for the dedicated Hindsight, so the owner's merge is the deploy. Home-ops PRs are prepared and validated locally and opened by the owner.
- **GHCR images are public for now** (can be made private later; that would need `ghcr-pull` in `datasci`).
- **CI replays the recorded Hindsight fixtures only.** Live Hindsight tests are manual.

## 2026-09-28: audit trail (ticket 03)

- **The database assigns the chain.** A BEFORE INSERT trigger on `audit_event` sets the gapless `id`, `occurred_at`, `prev_hash` and `event_hash` under a transaction-scoped advisory lock, so no code path can fork or forge the chain. Audit writers serialize until commit, so audited transactions must stay short. The hash format is documented in migration `0002`; `atlas audit verify` recomputes it independently in Python.
- **Append-only by trigger and by role.** Triggers (ENABLE ALWAYS) reject UPDATE, DELETE and TRUNCATE for every role, superusers included. Only the table owner can disable them, so the intended role split is: a migration role owns the schema and runs `atlas migrate`; the runtime role `atlas_app` (API, worker) holds only the privileges it needs, and on `audit_event` that is SELECT and INSERT. Migration `0002` grants these when `atlas_app` exists at migrate time; the deployment creates the role (and must re-run the grant if the role is created later). Later migrations should grant `atlas_app` the minimum on their own tables.
- **Tail truncation is out of the chain's reach.** Deleting the newest events (with the triggers disabled by the owner) leaves a valid shorter chain. `atlas audit verify` prints the head hash, so an external copy of it can detect this; anchoring it off-database is not built yet.
- **Content hashes are SHA-256 hex.** `old_hash` / `new_hash` must be 64 lowercase hex characters (a CHECK constraint), matching `raw_sha256` elsewhere.
## 2026-09-28: Phase 0 documentation pack (build ticket 02)

- **Reuse:** a fresh EDGAR adapter; the sibling repositories (`trading-research`, `alphaos`, `TradingDashboard`) are reference only, and their data is not an Atlas entitlement (ADR-0002).
- **License classes (§4.3, §5.3):** `source_document.license_class` takes one of `public_regulatory`, `public_issuer`, `lead_metadata`, `manual_lead`, `synthetic_fixture` or the reserved `licensed:<provider>`. Unlicensed sources get no Source Document at all. See `docs/source-licenses.md`.
- **Gold fixtures (§9.5):** JSON case files under `tests/evaluation/gold/`, with IDs `EV-<CAT>-<NNN>`, content-addressed source files, and a manifest that pins each case by hash. Gold quotes carry no offsets, so cases survive parser-version changes. Two categories beyond §9.5 come from ticket 12: layer conflation (`LAY`) and the partner-page inference trap (`INF`). See `docs/evaluation-methodology.md`.
- **Schema contract (§5):** `docs/data-model.md` is the contract for the Phase 1–2 migrations. Open points are left to the owning tickets: re-parse storage and per-fetch observations (07), stored recall (15) and the queue-pause representation (14).

## 2026-09-28: Postgres accounts in the cluster

- **The owner provisions the cluster Postgres accounts and databases** (`atlas`, `atlas-hindsight`, including the `vector` extension) themselves. Atlas's deployment only consumes the resulting credentials (via ExternalSecret/Bitwarden). The prepared home-ops branch `atlas/crunchy-users` is optional reference material, not a required rollout step, and agents should not ask the owner for anything Postgres-related in the homelab.
## 2026-09-29: source ledger and ingest slice (ticket 07)

- **SEC's edge-injected `<script>` (the ticket 06 warning).** SEC's Akamai edge appends `<script type="text/javascript" src="/KSRe0…"></script>` to Archives HTML, and the token may vary between fetches. Decision:
  - **Raw bytes stay exactly as fetched.** `raw_sha256` hashes them, the archive stores them, and `GET /source-versions/{id}/content?kind=raw` returns them byte for byte, script included. Nothing is stripped before hashing.
  - **Change detection uses a second hash,** `comparison_sha256`: the SHA-256 of the raw bytes after the version's `comparison_rule` removed bytes that are not content. The rule `sec-edge-script-v1` applies to `sec_edgar` HTML (`text/html`, `application/xhtml+xml`) and removes every `<script …>…</script>` element (case-insensitive, non-greedy, on the bytes). Everything else uses `identity` (the raw hash). The rule is safe because EDGAR does not accept scripts or other active content in filed HTML documents, so a script in an Archives document can only come from SEC's serving layer, never from the filer.
  - A refetch whose raw hash differs but whose comparison hash matches the latest version's is **unchanged**: no new Source Version. The fetch observation keeps that fetch's own `raw_sha256`, and its exact bytes are archived (`fetch_observation.object_uri`), so nothing fetched is lost.
  - The parser drops script elements anyway, so the parse is unaffected either way.
  - Tested in `tests/integration/test_ingest.py::test_a_varying_sec_edge_script_alone_is_not_a_new_source_version` and `tests/unit/test_parsing.py::test_a_different_sec_edge_script_does_not_change_the_parse`.
  - A rule change is a new rule name. Versions keep the rule they were compared under, and a comparison only matches under the same rule.
- **Source Document identity is (provider, canonical URL), not the accession.** One EDGAR accession holds several documents (the 8-K and its EX-99.1), so `accession` is an indexed attribute, not unique (the data model had it unique). For SEC, the canonical URL (the accession's Archives folder plus the file name) is equivalent to (accession, document).
- **Per-fetch observations get their own table,** `fetch_observation` (append-only), resolving the data model's open point. Every fetch that returned or confirmed content is a row with its outcome (`new_version`, `unchanged`, `not_modified`), its hashes and its HTTP validators. The latest observation's validators make the next fetch conditional, so an unchanged Archives document costs one 304.
- **The parse lives on the Source Version, written once.** The ledger parses in the same transaction that creates the version (`html-text-v1`, archived under `archive://parsed/…`). A recorded parse is never overwritten (trigger). Re-parsing under a later parser version will need a separate `source_parse` record; that is deferred until a second parser version exists (the other open point).
- **Parser rules (`html-text-v1`)** are documented in `backend/atlas/parsing.py`. The content hash of each recorded fixture is pinned in `tests/fixtures/parser/golden.json`, so a change in output without a version bump fails the tests.
- **Clocks for SEC material:** `available_at` = `acceptanceDateTime` (basis `sec_acceptance`); `published_at` and `event_at` stay null (EDGAR's release time is the acceptance time, and the filing and report dates go in `metadata`); `first_seen_at` is the adapter's discovery time; `fetched_at` is the fetch; `ingested_at` is the database commit time. companyfacts has no acceptance time, so it uses `observed_discovery`.
- **Company IDs are deterministic** (UUIDv5 of the CIK, else the slug), and `company` has a `slug` column (the config key). Seeding is an idempotent upsert that audits only real changes. Coherent's CIK `0000820318` was verified with one SEC request (`data.sec.gov/submissions/CIK0000820318.json`: "COHERENT CORP.", COHR on NYSE, formerly II-VI INC). Its security is a TODO in the config: the listing start date isn't taken from a primary source yet.
- **Primary keys are named `id`,** following tickets 03 and 04, rather than the data model's `<table>_id`. Foreign keys keep `<table>_id`.
- **Raw content is served as an untrusted download:** `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox; default-src 'none'`, with the stored media type and no added charset. SEC HTML is never rendered on the application's origin (spec story 36). Parsed text is `text/plain; charset=utf-8` under the same headers.
- **An ingest job with fetch failures fails after recording everything else.** Its error lists each failed URL (spec story 22), and the retry is cheap because unchanged documents answer 304 or match by hash. Discovery failures (the submissions index) fail the attempt at once.
- **API additions beyond the spec's list:** `GET /api/v1/companies/{id}/sources` (the viewer's document list, story 46) and `GET /api/v1/sources/{id}`. Lists are paginated with `limit` (1–500, default 50) and `offset`, returning `{items, total, limit, offset}`.
