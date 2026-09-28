# Spec: Atlas pilot, Phases 0–1 (skeleton + SEC provenance slice)

Status: ready-for-agent
Map: [Map: Atlas pilot, Phases 0–2](./map.md). This spec covers Phases 0–1. Phase 2 is appended once the map's tickets resolve.

Vocabulary follows `CONTEXT.md`. The authoritative product spec is `hindsight_investment_research_build_plan.md` v1.1; deviations are recorded in `docs/decisions.md`.

## Problem Statement

The researcher wants to build investment theses on primary evidence, and to be able to show later exactly what that evidence was, when it became public, and that it hasn't changed since. Today nothing exists: no repository skeleton, no archive and no source ledger. Without a trustworthy provenance foundation, everything built on top of it later (Hindsight memory, agent research, Hypotheses, Research Snapshots) would inherit unverifiable citations and timestamps. That is exactly the failure the platform exists to prevent.

## Solution

A runnable service skeleton, plus one end-to-end provenance slice for a single SEC filer (Lumentum):

1. A worker job fetches Lumentum's EDGAR submissions and selected filings.
2. The raw bytes are archived immutably under their content hash.
3. Each fetch is recorded as a Source Version with `available_at` taken from EDGAR's `acceptanceDateTime`.
4. A deterministic parse is produced and stored separately.
5. The researcher can open any Source Version in a minimal source viewer, see its exact provenance and original bytes, and record a reviewable Assertion bound to an exact quote span.

Re-fetching unchanged material creates nothing new. Changed material creates a new Source Version linked to its predecessor. Every mutation is written to a tamper-evident audit trail. The whole thing boots locally with fixtures only (no keys, no network), and one CI entrypoint proves it.

## User Stories

### Setup and operation

1. As the researcher, I want to boot the whole stack locally with one documented command sequence, so that I can use and develop Atlas without any cluster or paid keys.
2. As the researcher, I want a fixture-only mode that never touches the network, so that demos and tests are deterministic and free.
3. As the researcher, I want to opt in to live SEC fetching with a single setting, so that I can reproduce a real ingest when connectivity permits.
4. As the operator, I want every required setting validated at startup with an actionable message, so that a misconfiguration fails fast instead of mid-job.
5. As the operator, I want optional providers that lack credentials to log "disabled: missing X" once and carry on, so that missing optional keys never break the boot.
6. As the operator, I want a liveness endpoint and a readiness endpoint that checks the application database and the archive, so that I know when the service is actually usable rather than merely started.
7. As the operator, I want readiness to report not-yet-integrated dependencies (Hindsight, LiteLLM) as "not configured" rather than failing, so that Phase 1 is deployable before Phase 2 exists.
8. As the operator, I want Prometheus metrics for fetches, parses, retries, job outcomes and archive writes, so that failures are visible in Grafana later without code changes.
9. As the operator, I want structured JSON logs with secrets redacted, so that logs are searchable and safe to ship.
10. As the operator, I want one container image that runs as either the API or the worker, depending on its command, so that build and deploy stay simple.
11. As the operator, I want that image to run as non-root with a read-only root filesystem, so that it meets the cluster's security posture from day one.
12. As the developer, I want one CI entrypoint that runs lint, format checks, type checks, migrations and fixture-only tests, so that local and CI results can't drift.
13. As the developer, I want unit tests blocked from network access, so that no test silently depends on a live service.
14. As the developer, I want migrations that upgrade from empty and are tested, so that schema changes are safe to apply to the cluster database later.

### Collecting SEC material

15. As the researcher, I want Lumentum configured as a monitored company by CIK in configuration, not code, so that adding companies later is a config change.
16. As the researcher, I want the worker to fetch Lumentum's EDGAR submissions index and its relevant 10-K, 10-Q and 8-K filings, so that primary evidence enters the system.
17. As the researcher, I want Lumentum's XBRL companyfacts archived as a raw Source Version, so that Phase 5 can normalize it without re-fetching history.
18. As the researcher, I want every SEC request to carry the configured User-Agent (name and contact), so that Atlas complies with SEC fair-access rules.
19. As the researcher, I want all SEC traffic to share one rate limiter capped at 10 requests per second, so that concurrent jobs can't breach SEC limits together.
20. As the researcher, I want 429 and transient errors retried with backoff that honors Retry-After, so that throttling degrades gracefully instead of failing jobs.
21. As the researcher, I want conditional requests (ETag / If-Modified-Since) used where SEC supports them, so that unchanged material costs almost nothing to re-check.
22. As the researcher, I want fetch errors, permission denials and incomplete parses persisted explicitly, so that gaps in coverage are visible rather than silent.
23. As the researcher, I want an ingest job to be safely re-runnable with the same idempotency key, so that a crash or retry never duplicates work.
24. As the researcher, I want to see a job's status, attempts, failures and produced Source Versions, so that I can tell what an ingest actually did.

### Source Versions and provenance

25. As the researcher, I want each Source Document identified by its canonical URL or SEC accession, so that different quarterly filings are never merged because their titles look alike.
26. As the researcher, I want each fetch that yields new bytes to become a new, immutable Source Version with its raw SHA-256, so that no stored evidence can ever change.
27. As the researcher, I want fetching an unchanged filing twice to produce exactly one Source Version, so that the ledger isn't polluted with duplicates.
28. As the researcher, I want a changed document to produce a new Source Version linked to the one it supersedes, so that revision history stays auditable.
29. As the researcher, I want `available_at` for SEC filings set from EDGAR's `acceptanceDateTime`, with the basis recorded as `sec_acceptance`, so that point-in-time views use the true moment of public availability.
30. As the researcher, I want `published_at`, `event_at`, `fetched_at`, `first_seen_at` and `available_at` kept distinct, so that the clocks are never confused.
31. As the researcher, I want non-SEC material with an unknown availability time to fall back conservatively to the observed discovery time, with the basis recorded, so that availability is never overstated.
32. As the researcher, I want the parsed text stored as its own object with its parser version and content hash, so that re-parsing never alters the raw record.
33. As the researcher, I want to retrieve the original raw bytes of any Source Version through the API, so that I can verify evidence against its exact archived form.
34. As the researcher, I want to view a Source Document's full version history, so that I can see when and how it changed.
35. As the researcher, I want archive locations exposed only as authenticated application URIs, never raw object-store credentials, so that the archive can't leak.
36. As the researcher, I want source text treated as untrusted data, so that instructions embedded in a filing can never change system behavior.

### Assertions and review

37. As the researcher, I want to select a passage in a parsed Source Version and record it as an Assertion with subject, predicate and optional object or value, so that evidence becomes a structured, citable record.
38. As the researcher, I want the system to reject an Assertion whose quote span doesn't match the archived parsed text exactly, so that no Assertion can cite words the source doesn't contain.
39. As the researcher, I want every Assertion to carry an epistemic type (e.g. direct source statement, company claim), so that a company's claims are never mistaken for independent facts.
40. As the researcher, I want new Assertions to start as unreviewed, and to be able to mark them corroborated, disputed, rejected or superseded, so that review state is explicit.
41. As the researcher, I want to list Assertions filtered by company and review state, so that I can work through the review queue.
42. As the researcher, I want a superseded Assertion to point at its successor instead of being edited, so that the history of what I believed stays intact.

### Audit

43. As the researcher, I want every mutation (ingest, Assertion creation, review decision) to record an actor and an audit event, so that every change is attributable.
44. As the researcher, I want the audit trail hash-chained and enforced as append-only by the database itself, so that even a buggy code path can't rewrite history.
45. As the researcher, I want the local actor identity taken from configuration, so that attribution works now and can come from an authenticated principal later without changing the audit model.

### Source viewer

46. As the researcher, I want a minimal web view listing a company's Source Documents and versions, so that I can browse what has been collected.
47. As the researcher, I want the viewer to show a Source Version's full provenance (URL, accession, hashes, all timestamps and their basis, parser version, fetch status), so that I can judge the evidence at a glance.
48. As the researcher, I want to toggle between the parsed text and a download of the original bytes, so that I can check the parse against the original.
49. As the researcher, I want to create and review Assertions from the viewer, so that the provenance slice is usable end to end without API tooling.
50. As the researcher, I want the frontend served by the same backend on one origin, so that there's a single deployable and a single auth surface.

### Phase 0 foundations

51. As the implementation agent, I want an ADR recording reuse decisions (fresh EDGAR adapter; sibling repos used as reference only), so that nobody re-litigates them.
52. As the implementation agent, I want architecture, data-model, threat-model, source-entitlement and gold-fixture-format documents, so that later phases build on explicit contracts.
53. As the researcher, I want the implementation log updated after each phase with the tests run and their actual results, blockers, credential dependencies and version decisions, so that progress claims are verifiable.
54. As the researcher, I want the Hindsight feature matrix delivered as part of Phase 0 (via the map's feature-check ticket), so that Phase 2 is designed against verified behavior.
55. As the researcher, I want a photonics theme stub in configuration naming the two anchor companies, so that later theme work extends config rather than code.

## Implementation Decisions

### Shape

- One Python 3.12 application managed with `uv` and a committed lockfile, plus one TypeScript frontend. One container image serves the FastAPI API (which also serves the frontend's static export) or runs the worker, selected by its command.
- Local stack in Compose: API, worker, application Postgres, and an S3-compatible server (MinIO images are no longer publicly pullable; the server is chosen by the map's ticket 13). The Hindsight service and its pgvector database are added to Compose by the feature-check ticket, not by this spec's slice.
- Configuration comes from environment and versioned config files (themes, providers, research policies), validated at startup with typed settings. Company universe and theme membership are config-only; no company is hard-coded.

### Modules (deep modules with small interfaces)

- **Archive.** Put and get immutable, content-addressed objects; raw and parsed objects are stored separately. Two backends behind one interface: local filesystem and S3-compatible (the cluster's MinIO in deployment). Writes are idempotent by hash; nothing is overwritten or deleted. It is exposed to callers only via internal application URIs; the API streams the content.
- **Source adapters.** The common asynchronous `SourceAdapter` protocol from spec §4.2 (discover, fetch, updates). Phase 1 implements the SEC EDGAR adapter and a fixture adapter that replays recorded EDGAR responses. The EDGAR adapter uses:
  - an HTTP client with an injectable transport
  - one process-wide token bucket (≤10 req/s), shared across jobs in the process
  - retry classification (retry 429/5xx/timeouts with backoff honoring Retry-After; don't retry other 4xx)
  - conditional requests
  - the configured User-Agent
- **Parser.** Deterministic HTML/text normalization with an explicit parser version, fully separate from any LLM work. The same input and version always produce identical output and content hash.
- **Source ledger (ingestion service).** Owns the Source Document / Source Version lifecycle:
  - resolves a candidate to a Source Document by canonical URL or accession
  - hashes the raw bytes
  - if they match the latest Source Version's raw hash, records the fetch observation without creating a version
  - otherwise archives the bytes, creates a new Source Version linked via `supersedes_version_id`, and triggers parsing

  `available_at` rules: SEC material uses `acceptanceDateTime` (basis `sec_acceptance`); anything else uses its reliable publisher timestamp or falls back to observed discovery time, with the basis recorded. Only the ingestion service writes to the archive and to Source Versions.
- **Assertions.** Creation validates that the quote span occurs exactly in the archived parsed text of the referenced Source Version, at the given anchor. New Assertions are `unreviewed`. Review transitions follow the `verification_status` set in spec §5.4. Supersession links to a successor and never edits. In Phase 1, Assertions are created by the researcher; no extractor exists yet.
- **Jobs.** A Postgres job table is the queue:
  - deterministic job IDs derived from an idempotency key
  - status, attempts, lease owner and expiry
  - claiming with `FOR UPDATE SKIP LOCKED`
  - bounded retries, recorded failures and produced artifacts

  The worker runs continuously, or in a single-pass mode used by tests. There is no external orchestrator and no scheduler in Phase 1.
- **Audit.** An append-only `audit_event` table with actor, action, old/new hashes and `prev_hash` chaining. Append-only is enforced in the database (trigger and role privileges), not only in code. Every mutating service writes an event in the same transaction as the change.
- **Actor.** The actor identity comes from configuration in local and pilot deployments (see `docs/decisions.md`). All services take the actor explicitly, so an authenticated principal can replace it later.

### Schema (Phase 1 migrations)

`company`, `security` (effective-dated identifiers), `source_document`, `source_version`, `assertion`, `audit_event`, `job`, with the fields from spec §5.1, §5.3, §5.4 and §5.8. `run` and `task` are deferred to Phase 4, but the job table leaves room for them. Constraints encode invariants where possible:

- uniqueness of (Source Document, raw hash)
- immutability of Source Version content columns
- non-null `available_at` and `available_at_basis`

### API (under `/api/v1`, typed responses, consistent error envelope, pagination, audit IDs on mutations)

- `GET /companies`, `GET /companies/{id}`
- `GET /sources/{id}/versions`
- `GET /source-versions/{id}` (metadata and provenance)
- `GET /source-versions/{id}/content` (raw or parsed, streamed via the API)
- `GET /assertions?company_id=&review_state=`, `POST /assertions`, `POST /assertions/{id}/review`
- `GET /jobs/{id}` (status, attempts, failures, produced Source Versions)
- `GET /health/live`, `GET /health/ready`, `GET /metrics`

Ingest jobs are enqueued by a CLI command or by config-driven seeding. There is no public ingest endpoint in Phase 1. The OpenAPI schema is the contract, and the frontend's API client is generated from it.

### Frontend

A Next.js static export with TypeScript strict mode, served by FastAPI. One screen family, the source viewer:

- the company's Source Documents
- version history
- the provenance panel
- parsed text with selection-to-Assertion
- raw download
- the Assertion list with review actions

### Quality gates

- Ruff (lint and format) and Pyright in strict mode for Python; ESLint and `tsc` strict for TypeScript.
- pytest with network blocked in unit tests.
- A single CI entrypoint that the committed GitHub Actions workflow also calls.

### Phase 0 documentation

- `README.md`, `AGENTS.md`, `.env.example`
- `docs/architecture.md`, `docs/data-model.md` (with the DB diagram)
- the threat model, `docs/source-licenses.md` (entitlement inventory), the gold-fixture format
- `docs/implementation-log.md`
- a reuse ADR in `docs/adr/`

The Hindsight feature matrix comes from the map's feature-check ticket.

### Anchors and budgets

- Lumentum is the Phase 1 company; Coherent joins in Phase 2.
- A photonics theme stub in config names both.
- Run budget defaults (for later LLM phases, recorded now in config): $2 per run, $25/month on the `atlas` LiteLLM key.

## Testing Decisions

- **What a good test is:** it exercises external behavior through the highest available seam and asserts on observable outcomes (API responses, archived bytes, rows as seen through the API, audit events), never on internal calls or private structure. Tests are deterministic and fixture-driven.
- **Primary seam: the API plus the worker in single-pass mode.** A test enqueues an ingest job for the Lumentum fixture, runs one worker pass, and asserts through `/api/v1`. The Phase 1 gate tests all live here:
  - Fetching an unchanged filing twice yields one Source Version.
  - A changed fixture yields a new, linked Source Version.
  - Original bytes are retrieved exactly and match `raw_sha256`.
  - `available_at` equals the fixture's `acceptanceDateTime`, with basis `sec_acceptance`.
  - An Assertion with a non-matching quote span is rejected.
  - Every mutation produced an audit event and the chain verifies.
- **Network boundary:** SEC HTTP is swapped at the transport layer with recorded EDGAR responses. This is where these tests live:
  - the mocked-429 retry test (honors Retry-After, eventually succeeds, and records attempts)
  - conditional-request behavior
  - User-Agent presence
  - the rate-limiter cap

  A live SEC smoke test exists behind an opt-in marker and is excluded from CI.
- **Real Postgres, never SQLite.** Tests run against Postgres in Compose, locally and in CI, because `SKIP LOCKED`, the append-only audit trigger and the migrations depend on real Postgres semantics. Dedicated tests cover these:
  - A direct UPDATE/DELETE on `audit_event` fails at the database level.
  - Two workers never claim the same job.
  - Migrations upgrade cleanly from empty.
- **Archive contract suite:** one parametrized suite runs against both the filesystem backend and the S3-compatible server in Compose (ticket 13), including versioning and object-lock behavior. It covers idempotent put by hash, exact round-trip, and no overwrite.
- **Parser:** unit tests on fixtures assert determinism (same input and version give the same content hash).
- **Frontend:** one Playwright smoke test against the static export served by FastAPI. It opens a Source Version, sees its provenance and parsed text, and creates an Assertion.
- **Prior art:** none. This is a new repository, so these tests establish the conventions for later phases.

## Out of Scope

- Everything in Phase 2: the Hindsight gateway, retain/recall/reflect, bank configuration, mental models, LiteLLM calls, and the home-ops deployment. Phase 2 is appended to this spec when the map clears.
- The Hindsight feature check itself. It's the map's task ticket, although its outputs are Phase 0 deliverables.
- Any LLM-based extraction; Assertions are researcher-created in Phase 1.
- XBRL normalization, as-of financial selection and restatement linkage (Phase 5). Companyfacts is only archived raw.
- Company IR, SearXNG, Exa and Firecrawl adapters; near-duplicate/syndication detection and Evidence Families (Phase 3).
- Entity resolution beyond the configured CIK; Relationships; Candidates; Hypotheses; Research Snapshots; Replay Banks.
- Authentik or any authenticated principal (post-pilot per `docs/decisions.md`).
- Scheduled monitoring and CronJobs.

## Further Notes

- **Choices made while synthesizing this spec rather than in the grilling rounds; reopen any of them if they're wrong:**
  - researcher-created Assertions in Phase 1
  - Pyright rather than mypy
  - the added `GET /jobs/{id}`, `GET /source-versions/{id}` and `POST /assertions` routes, which aren't in spec §11's list
  - ingest via CLI/seeding rather than an HTTP endpoint
  - deferring `run`/`task` tables to Phase 4
- The full photonics seed list (8–12 companies) is Phase 3 work. Phase 0 only needs the stub with the two anchor companies.
- Implementation may start immediately. Nothing here waits on the map's open tickets, except that the Hindsight Compose services and the feature matrix arrive through its feature-check ticket.
- **Phase 0 source-entitlement inventory and threat model inputs** from ticket 12 (`docs/research/serenity-skills-alignment.md` on its research branch):
  - Social/X archives, LinkedIn and paywalled datasets are unlicensed for Atlas.
  - Third-party agent skills can carry self-update instructions (a prompt-injection vector), so skill content is data, never instructions.
- Per `START_HERE.md`: never report a live integration as tested when only fixtures were exercised; the implementation log must state which.
