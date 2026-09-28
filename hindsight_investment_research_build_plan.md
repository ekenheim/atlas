# Hindsight-Centred Investment Discovery Platform

Product requirements, technical design and executable implementation plan

- **Specification version:** 1.1 (revises 1.0 of 23 September 2026)
- **Revised:** 28 September 2026
- **Intended audience:** autonomous coding agent or engineering team
- **Project codename:** Atlas Research (working title)
- **Implementation language:** Python 3.12+ for backend/research, TypeScript for UI
- **Delivery target:** a self-hostable, evidence-driven research product with a working end-to-end pilot, deployed to the owner's home Kubernetes cluster (`home-ops`). It is not an autonomous trading system.

> **Instruction to implementation agent:** Read this whole document before coding. Inspect the existing repository, services, infrastructure and tests before creating new modules. If an optional provider requires unavailable credentials, deliver a real typed adapter, a fixture-backed development provider and a documented setup path. Do not report a live integration as tested when it was not.

## What changed in 1.1

| Area | 1.0 | 1.1 | Why |
|---|---|---|---|
| Deployment target | Compose first, Kubernetes "later if warranted" (Phase 7) | Compose for dev/CI; **deploy to the home cluster from Phase 2** (§13, Appendix A) | The cluster already runs Postgres, object storage, Hindsight, LiteLLM, SearXNG, Authentik and Prometheus. Reusing them is less work than re-creating them in Compose for production |
| Job orchestration | Prefect | **Postgres-backed job table + worker** (`SKIP LOCKED`), CronJobs for schedules | Run/task state is already a domain table (§5.8). Prefect is not running in the cluster (its Flux entry is commented out), and a second orchestrator adds a server with its own DB |
| LLM access | Unspecified provider | **All app LLM calls go through the cluster's LiteLLM proxy** with a dedicated virtual key and budget (§6.1, §13.3) | Central spend tracking, per-key budgets, model aliasing, one place to swap providers |
| Hindsight instance | "Pinned release" | **Dedicated Atlas Hindsight release**, pinned, Renovate automerge disabled (§6.1) | The shared `llm/hindsight` release has one tenant key for all banks, auto-merged upgrades and a drifting subscription model list. None of that is acceptable for reproducible research |
| Discovery | Exa, with a fixture fallback | **SearXNG (self-hosted, no key) as the default live provider**; Exa optional | A free live path exists in-cluster, so live discovery doesn't wait on a paid key |
| Frontend | Separate Next.js server | **Next.js static export served by FastAPI** (one image, one origin, one auth surface) | Single-user tool; SSR buys nothing |
| Relationship map | React Flow in Phase 3 | **Table/list view first**, React Flow once edges exist to show | The graph UI depends on reviewed edges, which are scarce early |
| Reproducibility | "Reproduce exactly what was known" | **Frozen snapshots are the reproducibility mechanism.** Replay banks measure the pipeline and don't reproduce it (§9.2) | LLM extraction is non-deterministic and hosted models get retired. Re-running is never byte-identical |
| SEC timestamps | Generic `available_at` | **Use EDGAR `acceptanceDateTime`**, and filter XBRL facts by `filed` date (§4.2, §5.7) | Exact public-availability clock for free. companyfacts mixes original and restated values |
| Market data | "Where licensed" | **Explicit Phase-6 decision gate**: no price provider is assumed (§9.3) | Paper tracking can't be evaluated without one, so name the gap early |
| Scope | 7 phases, all required for the pilot | **Pilot cut line after Phase 5**, with the replay leakage test pulled forward (§14) | Delivers the product's core value before the hardest subsystems |
| Tracing | OpenTelemetry + Phoenix/Langfuse | **Prometheus metrics + structured logs first**. OTel instrumentation stays in the code, but no collector is required | The cluster has Prometheus/Grafana and no tracing backend |
| Misc | Typos, a duplicated bootstrap prompt (old §18), references to an "AlphaOS" service | Fixed. The bootstrap prompt now lives only in `START_HERE.md`. The audit service is implemented here | Maintenance |

---

## 1. Mission and product definition

Build a continuously learning investment discovery and research system. It should:

- detect shifts in demand, technology, capacity and industry structure
- map the consequences through supply chains
- identify public companies with material economic exposure
- investigate alternative explanations
- build transparent financial scenarios
- keep a dated audit trail of beliefs and outcomes

The inspiration is discretionary, catalyst-driven, supply-chain-focused research: start from a structural change, trace demand to scarce inputs or enabling technologies, and investigate which companies might capture disproportionate economics. Do not turn that inspiration into assumptions of guaranteed returns, proprietary edge or mechanically proven trading rules. The software must make empirical evaluation possible.

### 1.1 Product questions

The platform should make it easy to answer:

1. Which demand, technology, policy or capital-expenditure changes are emerging in an industry?
2. Which inputs, equipment, materials and manufacturing steps might become constraints?
3. Which companies participate in those steps, and how strong is the evidence for each relationship?
4. What portion of each company's economics depends on the theme, directly or indirectly?
5. Which catalysts, assumptions, risks, alternative suppliers and substitute technologies matter?
6. How much of the prospective outcome is already implied by prices and consensus assumptions, where licensed data are available?
7. What did the platform believe at an earlier date, on the evidence available then, and what happened afterwards?
8. Which research gaps would change the thesis most if resolved?

### 1.2 Primary users and workflows

Primary user: one technically sophisticated individual researcher exploring concentrated, thematic opportunities. Build for a single user first, but keep interfaces compatible with multi-user authorization later (every mutation already carries an actor identity).

User flows:

- Start from an industry theme and generate an evidence-linked opportunity map.
- Open a company and inspect its products, customers, suppliers, competitors, catalysts, economics, source documents and thesis history.
- Ask a question in the research cockpit and get a grounded synthesis with clickable evidence and explicitly unresolved claims.
- Investigate one speculative relationship or bottleneck, collecting supporting and conflicting evidence.
- Turn an investigated idea into an explicit, falsifiable hypothesis and a scenario model.
- Review daily evidence updates: exactly what changed in the evidence base, and which theses may need review.
- Open a past research snapshot without the historical view seeing later facts.

### 1.3 Success definition

A pilot is useful when a person can:

- start from a broad AI-infrastructure theme
- discover and investigate a relevant company that was not in the seed list
- trace its product dependency through cited sources
- view the resulting economic scenario and the objections to the thesis
- reproduce exactly what was known when the candidate was proposed, by opening the frozen snapshot

No claim of financial alpha may be made from backfilled discovery alone. Live or paper-tracked outcomes are kept separate from historical reconstruction.

### 1.4 Non-goals for the initial version

- No automated brokerage execution, position sizing, margin, trade alerts framed as instructions, or options trading.
- No attempt to reproduce another investor's personal portfolio or infer undisclosed fills.
- No general-purpose web crawler, LLM training project or duplicate knowledge-graph platform.
- No circumvention of paid data entitlements and no scraping that violates source terms.
- No large agent swarm. A few budgeted roles with deterministic orchestration are enough.
- No false precision: no invented revenue exposures, customer concentrations, probabilities or citations.
- No MCP/agent-facing API in the pilot. A read-only MCP endpoint (for example via the cluster's toolhive gateway) is a post-pilot candidate.

---

## 2. Key architectural decision: Hindsight is the memory and graph core

Hindsight has its own fact extraction, entity linking, knowledge graph, multi-strategy recall, observations, mental models and reflective reasoning. Do not deploy Graphiti, Cognee, Neo4j or a second automated memory graph in the MVP. (The cluster also runs FalkorDB and Qdrant in `datasci`. Do not use them for Atlas either.)

A separate, small, typed `company_relationships` SQL table is allowed for explicitly reviewed supplier/customer/product edges that need precise application semantics. It is an operational projection of verified evidence, not a second extraction system.

### 2.1 Responsibilities and boundaries

| Layer | Primary responsibility | Technology (initial choice) |
|---|---|---|
| Source discovery | Find source material beyond the seeded companies | SearXNG adapter (in-cluster, no key) by default; Exa optional; fixture adapter for tests |
| Scheduled collection | Monitor SEC filings and known company pages | Direct SEC EDGAR client; polite HTTP collectors where permitted; Firecrawl optional and deferred |
| Primary evidence archive | Preserve immutable source versions, timestamps and content hashes | S3-compatible object store: local filesystem in dev, in-cluster MinIO bucket with versioning in deployment |
| Authoritative application database | Canonical entities, source metadata, assertions, review decisions, hypotheses, financial data, research snapshots, job state | PostgreSQL + SQLAlchemy 2 / Alembic (the cluster's Crunchy Postgres in deployment) |
| Memory and knowledge graph | Extract entities/facts and connect evidence; support discovery and evolving context | Hindsight (dedicated Atlas release), one connected research bank for the pilot |
| Research synthesis | Evidence-grounded summaries and unresolved questions | Hindsight recall/reflect plus tightly scoped investigator functions |
| LLM access (app-side) | Investigator / skeptic / analyst calls | OpenAI-compatible client pointed at the cluster LiteLLM proxy with a dedicated virtual key |
| Numeric financial research | Normalize as-of financial data; build scenarios; compare implied assumptions | SEC XBRL adapter; NumPy/Pandas; optional OpenBB adapter; PyMC only when justified |
| Job execution | Repeatable collection, ingestion and research jobs | Postgres job table + worker process (`SELECT … FOR UPDATE SKIP LOCKED`); Kubernetes CronJobs (or an in-worker scheduler in Compose) for schedules |
| API and UI | Human research workflow and audit exploration | FastAPI; Next.js static export served by FastAPI; React Flow later for the curated relationship view |
| Observability | Costs, sources, failures, latency, evaluation | Prometheus metrics + structured JSON logs; LiteLLM spend logs for LLM cost; OTel spans instrumented but exporter optional |

Why not store everything in Hindsight? Its extracted memories and graph are built for semantic research. They are not built for immutable raw-file preservation, transactional workflow, licensed market-data storage, numerical computation, access control or point-in-time validation. Hindsight retain complements the source archive and evidence ledger. It does not replace them.

### 2.2 Architecture

```
           SEED THEMES / USER QUESTION / MONITORED COMPANIES
                              |
                   Discovery and collection
          SEC | Company IR | SearXNG | Exa (opt) | Firecrawl (opt)
                              |
                   Provenance & license gate
                              |
        +---------------------+----------------------+
        |                                            |
 IMMUTABLE OBJECT ARCHIVE                     POSTGRES SOURCE LEDGER
 raw HTML/PDF/JSON, sha256                     dates, URLs, licenses,
 parsed text, version hashes                   canonical entities
        |                                            |
        +---------------------+----------------------+
                              |
                    EXTRACT + NORMALIZE
                     structured evidence
                              |
            +-----------------+------------------+
            |                                    |
      HINDSIGHT BANK                      SQL DOMAIN RECORDS
 facts/entities/graph                     assertions, relationships,
 observations/mental models               hypotheses, financials
            |                                    |
            +------------------+-----------------+
                               |
               INVESTIGATION / COUNTEREVIDENCE
                    / FINANCIAL SCENARIOS
                               |
                    REVIEW & APPROVAL GATES
                               |
             RESEARCH COCKPIT + THESIS HISTORY
                               |
                AS-OF SNAPSHOTS + EVALUATION
```

A source never bypasses the source ledger on its way to becoming an approved company relationship, financial fact or published thesis.

---

## 3. Pilot scope and research universe

Start with AI infrastructure, in six interconnected themes:

1. GPU/accelerator compute and server infrastructure.
2. Memory and packaging.
3. Optical networking, laser components and photonics.
4. Semiconductor materials, substrates and manufacturing tools.
5. Data-centre electricity, transformers and grid connections.
6. Cooling and thermal management.

Seed roughly 30–50 public companies across these themes. The seed universe is configuration-driven: do not hard-code any company as an investment opportunity. The pilot must also discover at least five plausible, previously unseeded companies or relevant subsidiaries for manual evaluation.

Include at least one European and one Asian company. This proves the system handles limited non-US disclosure coverage instead of silently assuming every issuer files a US 10-K. Where possible, pick a European company that is also an SEC foreign private issuer (20-F/6-K) plus one that is not, so both coverage paths get exercised.

Each theme defines a versioned research question, for example: *"Which components of scaling optical interconnect capacity are constrained, which publicly traded businesses are exposed, and what evidence would refute the shortage thesis?"*

Scope the initial data load to a rolling two to three years for seeded firms, where lawful and available. Don't imply every issuer has the same transcript or fundamental coverage. **One pilot theme (photonics) must work end to end before broadening to the full universe.** Photonics seed list: 8–12 companies. The other five themes stay as config stubs until the Phase 5 gate passes.

---

## 4. Evidence sources, permissions and ingestion rules

### 4.1 Source hierarchy

**Tier A: primary company and regulatory sources**

- SEC EDGAR submissions and XBRL company facts for relevant US filers (including 20-F/6-K foreign private issuers).
- Issuer investor-relations releases, presentations and legitimately accessible annual/interim reports.
- Exchange/regulatory notices for non-US listed companies, where source-specific adapters exist.
- Official customer/supplier disclosures and original technical specifications.

**Tier B: strong corroborating sources**

- Patents, formal technical papers, major equipment/customer announcements, official statistics, trade association datasets.
- Conference presentations when the materials are public and distributable.

**Tier C: lead-generation sources**

- General news, search snippets, blogs, public social posts and vendor marketing.
- These may suggest questions or leads. They must not, on their own, establish a material customer contract, shortage or revenue exposure.

Source quality is an attribute of a claim and its supporting material, not a blanket truth score for an entire website.

### 4.2 Initial adapters

Define a common asynchronous `SourceAdapter` protocol:

```python
class SourceAdapter(Protocol):
    provider_id: str
    async def discover(self, query: SearchQuery) -> list[SourceCandidate]: ...
    async def fetch(self, candidate: SourceCandidate) -> FetchedDocument: ...
    async def updates(self, since: datetime) -> list[SourceCandidate]: ...
```

Implement them in this order:

1. **SEC EDGAR.** Covers the submissions index, relevant 10-K/10-Q/8-K/20-F/6-K filings and XBRL `companyfacts`.
   - Send a proper SEC `User-Agent` (name + contact email, taken from config).
   - Use a shared token-bucket rate limiter at ≤ 10 req/s, with retries/backoff and conditional requests (ETag / If-Modified-Since) where available.
   - SEC endpoints have no browser CORS, so call them server-side.
   - For bulk history, prefer the official bulk files.
   - **`available_at` for filings = the filing's `acceptanceDateTime`** from the submissions index or filing header. It is exact and free; don't fall back to discovery time for SEC material.
2. **Company IR.** Configurable public sitemap/RSS/IR URLs and official PDF/HTML fetch. Honor robots.txt, site terms and rate limits. Record which gate allowed each fetch.
3. **SearXNG discovery.** The cluster's self-hosted metasearch (`llm/searxng`), JSON API, no key. This is the default live discovery provider. Record the query, engines used, response metadata and discovery date.
4. **Exa discovery (optional).** Semantic web search that disables itself cleanly when credentials are missing. Record the original query, API params, response metadata, discovery date and the follow-on source URL.
5. **Firecrawl (optional, deferred).** Only for dynamic sites or change detection where plain HTTP collectors fail or monitoring value has been shown. Record provider terms and costs.
6. **OpenBB (optional, Phase 5+).** Use only installed, supported providers. Log the data provider, entitlement, quote timestamp and license. The direct SEC client stays the authoritative free source for US filings.

Do not promise open access to earnings-call transcripts, global supplier databases or institutional consensus estimates. Create extension interfaces and mark coverage as absent until a licensed provider is connected.

### 4.3 Archiving and deduplication

- Fetch bytes and compute SHA-256 of the raw content. Preserve `first_seen_at`, `fetched_at`, `published_at`, `event_at` (if known), `available_at` and the URL.
- Store the raw source and a separately versioned parse. Every change creates a new `source_version` linked to its predecessor.
- Normalize tracking parameters and canonical URLs. Don't merge different quarterly filings because their titles are similar.
- Deduplicate exact bytes and detect near-duplicate syndication (e.g. MinHash/SimHash on normalized text). Link derivative articles to the original announcement as one evidence family.
- Persist fetch errors, permission denials, incomplete parses and missing coverage explicitly.
- Never send licensed or restricted full text to a third-party LLM provider without checking the provider's terms and model data policy. This includes Hindsight's own extraction LLM, which is a third-party provider when it points at a hosted model.
- Treat source documents as untrusted input. Ignore any instructions inside them that try to change tool behavior, prompts or security policy.

---

## 5. Canonical domain model

Use Pydantic v2 schemas with SQLAlchemy mappings and migration tests. Every immutable analysis run records:

- code version (git SHA)
- model/provider versions (the concrete model LiteLLM routed to, not just the alias)
- Hindsight server version
- prompt version
- source cutoff

The required conceptual schema is below. Names may vary where repository conventions are stronger.

### 5.1 company

`company_id UUID; legal_name; display_name; lei?; cik?; country; website?; parent_company_id?; created_at; updated_at; review_state`

A company is a legal entity, not a ticker. A separate `security` table stores ticker, exchange/MIC, ISIN, FIGI, instrument type, currency and effective-dated identifier intervals. It must support ticker changes, ADRs and multiple listing lines. LEI/CIK/FIGI are external mappings and aren't available for every company.

### 5.2 technology, product, industry_theme

Versioned named concepts with aliases and definitions. The `product_company` and `theme_exposure` associations require evidence IDs for any asserted economic dependency. A theme must be independent of any ticker or valuation.

### 5.3 source_document / source_version

```
source_document_id, origin_url, canonical_url, publisher, source_tier,
license_class, source_type, first_seen_at

source_version_id, source_document_id, raw_sha256, content_sha256,
object_uri, parsed_object_uri, parser_version, published_at, fetched_at,
available_at, available_at_basis, supersedes_version_id, fetch_status, metadata_json
```

`available_at` is the earliest time the material was publicly obtainable according to reliable records. `available_at_basis` records how it was determined (`sec_acceptance`, `publisher_timestamp`, `observed_discovery`, …). If it's unknown, conservatively use the later observed discovery time. Keep `published_at`, `event_at` and `available_at` distinct.

Archive URLs are authenticated application URIs, never exposed public object-store credentials.

### 5.4 assertion

```
assertion_id, subject_entity_id, predicate, object_entity_id?, value_json?,
source_version_id, quote_or_span, page_or_anchor?, event_start?, event_end?,
extracted_at, extractor_version, epistemic_type, verification_status,
independence_family_id, reviewer_id?, reviewed_at?, superseded_by?
```

- `epistemic_type`: `direct_source_statement`, `company_claim`, `third_party_report`, `agent_inference`, `quantitative_derived`.
- `verification_status`: `unreviewed`, `corroborated`, `disputed`, `rejected`, `superseded`.

A model's perceived confidence is not a substitute for evidence or reviewer state.

### 5.5 relationship

A typed, evidence-backed application projection:

```
relationship_id, subject_id, predicate, object_id,
product_id?, theme_id?, event_start?, event_end?, effective_status,
verification_status, supporting_assertion_ids[], reviewed_at?
```

Predicate whitelist: `manufactures`, `supplies`, `buys_from`, `uses_material`, `owns`, `competes_with`, `substitutes_for`, `expands_capacity_for`, `depends_on`.

Keep assertion direction explicit. A claim that A works with B must not automatically become "A supplies B".

### 5.6 hypothesis

```
hypothesis_id, thesis_statement, theme_id, related_company_ids[],
mechanism, measurable_predictions[], catalysts[], falsifiers[],
required_evidence[], alternative_explanations[], status, author,
created_at, first_published_at?, next_review_at?, version
```

Allowed states: `draft -> researching -> evidence_ready -> reviewed -> paper_tracking -> closed`, with side branches `rejected` and `needs_more_evidence`.

A hypothesis version is immutable after publication. A correction creates a new version and an explicit audit event.

### 5.7 scenario, financial_observation, research_snapshot

- **financial_observation:** company, concept, period start/end, fiscal period, unit, value, source accession/version, `filed`/`available_at` timestamps, currency/FX basis, restatement linkage.
  - XBRL `companyfacts` returns every reported value, including restated ones from later filings.
  - An as-of view must select, per (concept, period, unit), the value from the latest filing with `available_at <= as_of`. Later values are linked as restatements and never overwrite.
- **scenario:** associated hypothesis/version, assumption table, model code version, market-data as-of, outputs, sensitivity, analyst overrides.
- **research_snapshot:** as-of cutoff, considered source-version IDs, retrieved Hindsight evidence IDs **with the memory text as returned at the time**, serialized approved assertions, normalized financial dataset hash, prompts and model versions, Hindsight version, hypothesis version and outputs.
  - Immutable once committed.
  - Also written as a content-addressed JSON object to the archive, so it survives without the database.

### 5.8 run, task, job, evaluation, audit_event

- **run / task / job:** deterministic job IDs, idempotency key, retries, status, lease owner and expiry, budgets, trace IDs, timestamps, failures and artifacts. This table is the job queue (§2.1). No external orchestrator.
- **evaluation:** question set, reference evidence, predicted output, reviewer label, metric and evaluation date.
- **audit_event:** append-only actor/action/old/new hashes, hash-chained (`prev_hash`). Enforce append-only with DB permissions or a trigger, not just application code.

---

## 6. Hindsight integration: build this first, not a parallel graph

### 6.1 Deployment

**Version and API surface.** Pin one Hindsight release (the cluster runs 0.10.1 as of this revision) and write a **feature matrix** in Phase 0 for that exact version. Mark each of these as verified, behaves differently, or absent:

- retain (sync/async/batch) and document_id upsert
- recall with tags / strict tag matching
- reflect with JSON Schema output and fact provenance
- operations API
- bank templates
- observations
- mental models
- knowledge pages
- bank export/import

The sections below assume the documented behavior. Where the pinned version differs, the matrix wins and the difference goes in `docs/decisions.md`.

**Dev.** Docker Compose with the pinned image and a separate Postgres (pgvector) for Hindsight.

**Cluster: a dedicated Atlas Hindsight release**, not the shared `llm/hindsight`:

- The shared release has a single tenant API key across all banks, so any consumer holding it could read or delete research banks.
- Renovate auto-merges its image bumps, which changes extraction behavior in the middle of an experiment.
- Replay banks (§9.2) create and destroy banks and generate heavy extraction load that shouldn't compete with the assistants' memory.

The dedicated release reuses the same chart and the operational lessons in Appendix A. Renovate may *propose* Hindsight bumps for it, but automerge is disabled. An upgrade needs a green extraction-fixture run.

**Isolation.** Keep Hindsight's database logically separate from the application's domain tables (separate database, separate role). Never expose the control plane or an unauthenticated API outside the cluster. Set a stable `HINDSIGHT_API_WORKER_ID` so interrupted operations recover across restarts.

**Hindsight's LLM.**

- Hindsight needs structured-output-capable models for fact extraction, and it makes **non-streaming** calls. Any LiteLLM route that only serves streaming callers (the cluster's `chatgpt/*` subscription rungs, for example) will fail for Hindsight.
- Pick a provider with a **stable, dated model identifier** for the baseline. Subscription backends whose model lists change week to week (e.g. Codex) are unsuitable for research whose extraction should be comparable over time.
- Benchmark local OpenAI-compatible endpoints separately on the extraction fixture set for accuracy, cost and throughput. Don't assume any local model satisfies the interface until the compatibility tests pass.

**Atlas's own LLM calls** (investigator, skeptic, analyst) go through the cluster LiteLLM proxy:

- a dedicated virtual key (`atlas`) with a max budget
- per-role model aliases defined in config, not hard-coded model names
- `metadata.run_id` / `metadata.role` on every request, so spend is attributable per run
- structured output validated by Pydantic, with a bounded repair-retry and then quarantine

### 6.2 Bank policy

Create one pilot research bank (`atlas-ai-infrastructure`) so retrieval connects across themes. Use tags such as `theme:photonics`, `company:<canonical-id>`, `doctype:filing`, `source:sec`, and choose and test scoping carefully.

The default `tags_match='any'` can include untagged memories. For strict theme/company scoping, use the explicit strict mode. Banks are isolated from each other, so one bank per company would prevent automatic cross-company learning.

Replay banks use the prefix `atlas-replay-<experiment-id>` and are deleted after their evaluation artifacts are frozen.

Use a versioned bank template (or, if the pinned version has no templates, a versioned config file applied through the documented bank-config API) containing:

- **retain_mission:** extract economically material facts about capacity, supply agreements, customer dependencies, product specifications, manufacturing constraints, demand forecasts, capital expenditure and risk. Preserve the difference between what was explicitly stated and what was inferred.
- **observations_mission:** consolidate independently grounded industry developments while recording contradictions, conditionality and changed circumstances. Don't turn speculative language into certainty.
- **reflect_mission:** form source-grounded research syntheses. Distinguish factual statements, third-party claims, model assumptions and hypotheses. Seek disconfirmation.
- Higher skepticism and literalism than the default (subject to empirical testing). Don't treat disposition settings as a verified accuracy mechanism.
- **Reflect directives:** cite supporting evidence; say when facts are missing; never fabricate contract or exposure figures; flag uncertainty about the original source; never give trading orders.

Use the documented template import/dry-run flow (or config API). Never write directly to Hindsight's tables.

### 6.3 Retention policy and idempotency

Hindsight retain accepts content, context, timestamp, metadata, document_id and tags. Metadata values are strings. document_id is an upsert key: replacing a document deletes and re-extracts it. Therefore:

- Generate deterministic, immutable IDs per source version, e.g. `srcv:<sha256>`. Don't upsert every revision into the same document ID, or historical memory will disappear.
- Put the canonical source URL, source-version UUID, document hash, published/available dates, publisher, license and extractor version into metadata/context as appropriate.
- Use the source publication date as the contextual timestamp only when a document-level temporal anchor is warranted. Preserve the dates of the underlying events separately in the domain database. Don't confuse the retained/event timestamp with earliest public availability.
- Store complete raw content externally. Retain parsed text or selected sections with bounded chunk sizes and source anchors. Configure Hindsight to store original text only if retrieving original chunks is required, and only after a security/licensing review.
- Prefer async batch retain for large datasets, with operation IDs for idempotent retries. Wait for operation completion **and** consolidation before claiming the bank is up to date. Track documents that complete with zero extracted facts and decide whether to reprocess them.
- Record the mapping `source_version_id <-> Hindsight document_id <-> returned fact IDs` whenever it's accessible.

### 6.4 Retrieval and synthesis

- Use **recall** for evidence discovery. Inspect fact IDs, type, context, document ID, entity names, timestamps and metadata.
- Use **reflect** for synthesized research questions, and request fact provenance through the supported evidence include option. When machine-readable output is needed, pass an explicit JSON Schema and check `structured_output_error`. HTTP 200 does not guarantee structured success.
- Resolve returned memory references to source versions in the SQL ledger, then validate the original quotes/anchors against the archived parse. A Hindsight citation proves which memory the model used, not that the originating company statement is accurate.
- Hindsight observations and mental models are derived knowledge. They never count as independent corroborating source documents.

### 6.5 Observations, mental models and knowledge pages

Create a few curated standing questions, not one model per company on day one:

1. **Theme status:** What are the major documented developments in optical interconnect capacity, with supporting and opposing evidence?
2. **Bottlenecks:** Which specific inputs or processes have credible evidence of constraint? Which have credible evidence of expansion?
3. **Research gaps:** Which unresolved questions could have the largest impact on current hypotheses?
4. **Company-specific model (selective):** What is currently known about the product and economic exposure of a high-priority company?

Use knowledge pages (if the pinned version has them) for browsable research overviews where stable, frequently reused answers add value. Refresh on a rate-limited trigger (daily, or after consolidation with a minimum interval) and log changes. Draft or contentious company views need review before they're promoted to accepted thesis versions.

### 6.6 Hindsight's graph versus the application view

Don't claim Hindsight exposes arbitrary direct entity-to-entity supplier edges for precise graph traversal. Its memory graph is event/fact-centric and suited to retrieval and discovery. The UI renders a separate curated projection of verified typed relationships from SQL. Each edge links back to archived source evidence, and optionally to the Hindsight facts it came from. No graph database is needed at MVP scale.

---

## 7. Discovery and research agent design

Do not create swarms of unsupervised agents. Start with a deterministic finite-state workflow and a small number of typed roles. Agents are functions or graph nodes, not personalities with free rein over the infrastructure.

### 7.1 Roles

| Role | Trigger / input | Expected output | Must not do |
|---|---|---|---|
| Theme Scout | Theme and known developments | Versioned candidate leads: technologies, companies, research questions, source URLs | Assert that web mentions establish a commercial relationship |
| Supply-chain Investigator | Specific lead + retrieved memories | Causal chain, candidate entities, assertions, counterevidence, unresolved edges | Treat correlated mentions as supply contracts |
| Entity Resolver | Candidate names/identifiers | Canonical company, parent, security and alias mappings | Guess a ticker from a similar company name without review |
| Financial Analyst | Approved entity, filings, hypothesis | Time-stamped exposure estimates or ranges, scenarios and assumptions | Generate financial numbers without a source or model |
| Skeptical Reviewer | Hypothesis, source ledger, scenarios | Falsifiers, contradictions, missing evidence, sources to seek | Rewrite original claims to hide uncertainty |
| Research Editor | Reviewed outputs | Structured research card and mental-model refresh proposals | Publish unreviewed material as verified fact |
| Outcome Evaluator | Frozen snapshot plus later observations | Defined metrics and post-mortem | Read future data while generating historical hypotheses |

The Entity Resolver is mostly deterministic code (CIK/LEI/ISIN lookups, OpenFIGI/GLEIF where available, alias tables). An LLM may propose matches, but it never commits them.

### 7.2 Shared agent contract

Every investigation request includes:

```
run_id, research_question, theme_id, seed_entity_ids,
as_of_utc, allowed_source_tiers, available_budget,
max_depth, max_new_leads, approved_tool_list,
relevant_hindsight_bank, hypothesis_id?
```

Every returned claim includes `claim_text`, `epistemic_type`, `original_source_version_ids`, `source_spans`, `independent_evidence_families`, `entity_ids`, `validity_dates`, `limitations`, `counterevidence_ids`, `needs_review` and `open_questions`.

Enforce this with Pydantic, and reject or quarantine invalid outputs. Agent numeric confidence is diagnostic only. Never display it as a calibrated probability unless it has been calibrated against a reference set.

### 7.3 Investigation workflow

1. Start from a seed theme or a fresh external event.
2. Retrieve known context from Hindsight and from the authoritative source/relationship tables.
3. Form specific research questions. Search new primary sources before broad commentary.
4. Extract atomic assertions and resolve canonical company/product entities.
5. Detect exact and near-duplicate source families and label independence.
6. Build a proposed causal supply chain, with each edge explicitly marked verified, reported, inferred or unknown.
7. Dispatch a counterevidence search in parallel with the financial-exposure research.
8. Join on evidence IDs. One agent's conclusion never counts as a second independent confirmation.
9. Identify which new uncertainty could materially change the conclusion, and optionally run one bounded follow-up round.
10. Produce a structured research card in draft status, plus a proposed Hindsight retention/refresh payload for provenance-reviewed findings.
11. A human approves material typed relationships, numerical exposures and paper-tracking enrollment.
12. Freeze a research snapshot at the actual publication/decision timestamp.

### 7.4 Research loops and budgets

First version limits:

- at most two investigative rounds
- at most 10 new web leads per question
- at most 25 fetched documents
- a configurable token/spend ceiling per job, enforced by the app and backstopped by the LiteLLM key budget

These are operational starting limits, not measured optimal settings.

Stop when any of these happens:

- the question is answered to the evidence requirements
- new independent evidence stops arriving
- the budget is exhausted
- human review is required

Use an explicit DAG, with async parallelism only where tasks are independent. When an upstream premise is disproven, cancel the queued follow-ups that depend on it, but don't silently kill other investigations or erase their findings. Record the reason for every stop or cancellation.

### 7.5 Prompt and tool security

- System directives are fixed in code. Retrieved web text is always lower-trust quoted data.
- Research agents have read access to Hindsight and the allowed collectors. Only ingestion services write to source archives. Only the review service promotes assertions or thesis versions. Enforce this with separate DB roles/credentials where practical, not only code paths.
- No arbitrary shell execution from agent outputs, no unsupervised purchases or financial transactions, no secrets in prompts or traces.
- Force source URLs, document IDs and quote spans into typed outputs, and validate them against the actual fetched source versions.
- Keep a fixture-backed tool layer so agents can be tested without live API calls.

---

## 8. Investment hypothesis engine

The output is hypotheses and scenarios, not a single opaque stock-ranking score.

### 8.1 Hypothesis template

```yaml
thesis: "Demand for optical interconnects may outgrow qualified substrate supply"
mechanism:
  demand_driver: "Interconnect bandwidth and optical module deployments"
  possible_constraint: "Qualified specialist substrate capacity"
  economic_capture_question: "Which firms have scarce capacity and pricing power?"
predictions:
  - "Publicly disclosed lead times should increase or stay elevated"
  - "Qualified capacity expansion should lag plausible demand scenarios"
  - "Exposed firms should show related sales or margin impact"
catalysts:
  - "New customer qualification disclosures"
  - "Capacity expansion and pricing disclosures"
alternatives:
  - "Alternate materials or suppliers reduce scarcity"
  - "Inventory effects temporarily mimic demand"
falsifiers:
  - "Verified capacity exceeds plausible demand"
  - "Product is immaterial to the candidate company's economics"
  - "Thesis is already embedded in optimistic market assumptions"
required_evidence:
  - "Source-linked company product disclosure"
  - "At least one original document establishing a relevant industry relationship"
  - "Explicit basis for every numeric assumption"
```

This is an illustrative research question only. Never present the example as a current shortage finding.

### 8.2 Economic transmission model

Keep three questions separate:

1. **Physical/industry:** How much additional demand might the relevant market require? What capacity and substitution paths exist?
2. **Company economic exposure:** What units, share, utilization, contract terms and margin contribution might the company capture?
3. **Market expectations:** How much growth is already implied by the current price and by investor/analyst assumptions, where data are licensed and reliable?

For a simple scenario:

```
Incremental product revenue        = incremental addressable units
                                     × feasible company share
                                     × realized price
Incremental operating contribution = incremental revenue
                                     × incremental operating margin
Illustrative equity sensitivity    = scenario enterprise value
                                     − net debt and other claims
```

Keep estimated quantities separate from sourced quantities. Provide a low/base/high assumption set (or a continuous distribution) and a sensitivity chart. Handle share dilution, debt, cyclicality, currency, execution and timeline. Show missing estimates explicitly instead of replacing them with invented numbers.

PyMC is optional for the first vertical slice. A deterministic scenario model with transparent uncertainty ranges is a better baseline. Add Bayesian models only where reasonable priors, a likelihood and relevant historical data can be defended. For sparse data, run sensitivity analysis instead of reporting unjustified posterior precision. Scenario prototyping can happen in the cluster's marimo instance, but the production scenario code lives in the app and is unit-tested.

### 8.3 Candidate investigation states, not pseudo-scientific rankings

The cockpit supports these states: `lead`, `investigating`, `evidence_ready`, `needs_more_evidence`, `paper_tracking`, `rejected` and `closed`. Filters may show uncertainty, coverage, catalyst timing and theme. Never conflate an LLM-generated conviction rating with a validated return expectation.

---

## 9. Temporal integrity and prospective evaluation

This subsystem is critical. Without it, the platform can look brilliant in hindsight simply by learning about companies after their rally.

### 9.1 At least three distinct clocks

- **event_at:** when the underlying development occurred.
- **published_at / available_at:** when the evidence became publicly usable (record both the release time and the conservative observed availability).
- **ingested_at / analyzed_at:** when our system processed it.

`available_at <= as_of` is the mandatory gate for historical reconstruction. For strict replay of what the system actually knew, also require `ingested_at <= as_of`. Every evaluation discloses which convention it uses.

Hindsight's `query_timestamp` anchors relative dates and recency. Its `temporal_window` ranks memories outside the window lower but doesn't exclude them. Neither is an as-of security boundary. Never run point-in-time simulations against the live production bank on the assumption that date hints prevent contamination.

### 9.2 Historical bank isolation and what "reproducible" means

There are two different things here:

- **Reproducing what the system believed** means opening the frozen `research_snapshot`, which stores the retrieved memory text, assertions, prompts, model versions and outputs as they were. This is exact, and it's the only exact mechanism.
- **Replaying the pipeline at a cutoff** means creating an isolated replay bank (`atlas-replay-*`) populated only with material eligible at the cutoff, in chronologically valid order, waiting for the intended retain/consolidation lifecycle. Keep prompts and model versions fixed per experiment. Replays evaluate the pipeline. They don't reproduce a past run byte-for-byte, because LLM extraction is non-deterministic and hosted models get retired.

Test replay banks against prepared cutoffs using intentional future-fact contamination fixtures. Replay extraction costs real LLM spend, so replay fixtures should be small and replay jobs budgeted like investigations.

The most credible performance evidence comes from prospective snapshots generated and frozen before outcomes occur. Keep those snapshots independent of later Hindsight updates. Keep rejected and ignored candidates too, so the evaluation isn't winner-only.

### 9.3 Market-data requirements

To evaluate market returns you need:

- corporate-action-adjusted prices and delisting outcomes
- correct exchange calendars and currency basis
- survivorship-aware universe membership
- transaction-cost assumptions

Don't compare later-available revised financial data against an earlier thesis. Label stale, missing, delisted or illiquid security coverage instead of silently dropping failures.

**Decision gate (before Phase 6):** no price provider is part of the current stack. Pick one, record its license and coverage (including the non-US names) in `docs/source-licenses.md`, and put it behind the same adapter/fixture pattern. Until then, paper tracking records snapshots and fundamental outcomes only, and return metrics show as "no market data provider".

### 9.4 Metrics

- **Information quality:**
  - source recall@k against curated evidence
  - citation correctness
  - verified edge precision/recall
  - canonical entity accuracy
  - contradiction discovery rate
  - number of independent source families
- **Research usefulness:**
  - share of investigations that produce a falsifiable thesis
  - completeness of disconfirmation
  - previously unseeded plausible companies found
  - share with a documented economic transmission mechanism
  - reviewer time saved
- **Operational:**
  - cost per run
  - source retrieval failures
  - extraction yield, including zero-fact documents
  - stale mental models
  - successful as-of isolation
  - end-to-end latency
  - retry safety
- **Prospective financial outcomes (exploratory):**
  - matched sector/size/currency benchmarks at fixed 1/3/6/12-month horizons
  - later fundamental changes against frozen scenarios
  - drawdown and concentration of paper-tracked candidates

  Predefine measurement conventions and compare against a naive thematic baseline. Make no statistical alpha claims from a small, overlapping, unblinded pilot.

### 9.5 Evaluation fixture design

Build 20–30 small labeled research tasks before optimizing prompts. Include:

- Clearly verified supplier relationships.
- Co-mentions with no actual relationship.
- An old contract that has expired or been superseded.
- One announcement mirrored by ten news sites.
- Subsidiary/parent/ticker ambiguity.
- A company explicitly reporting no material financial exposure.
- A hopeful management projection contradicted by a later filing.
- Documents describing past events but published later.
- Future-fact contamination traps.
- An XBRL value later restated by a subsequent filing.
- Non-US coverage gaps and currency mismatches.
- A document containing prompt injection.
- A failed or zero-extraction Hindsight retain operation.

The human researcher adjudicates gold labels and disagreements. Store the benchmark with stable source hashes and immutable case IDs. Fixture documents are synthetic or redistributable. Don't commit licensed full text.

---

## 10. Research cockpit UX specification

A Next.js (static export) frontend with TypeScript strict mode, served by the FastAPI backend and backed by a typed API client generated from the OpenAPI schema. React Flow is used for the curated (not fabricated) relationship view once reviewed edges exist.

### 10.1 Screens

Pilot screens are marked **(P)**. The rest follow after the pilot cut line.

- **A. Theme Explorer (P):** themes, latest documented changes, companies and products per theme, company count and coverage gaps, time controls, and search with provenance preview. Filtering by publication time changes authoritative source queries. A historical snapshot is a separate, explicit mode.
- **B. Company Dossier (P):** identity and securities, disclosed products, claimed/verified customer relationships, normalized available financials, timeline of filings and developments, relevant Hindsight memory results and research hypotheses.
- **C. Industry Relationship Map:** typed, directed, evidence-backed edges, with distinct visual treatments for reviewed, reported and inferred relationships. Every edge opens its original source span, and the user can hide speculative edges. Start with 2-hop exploration so the network stays readable. **Pilot version: a sortable edge table with the same data and links.**
- **D. Research Workbench (P):** question entry, investigation plan, agent trace, evidence tray, contradictions, open questions, approve/reject actions, a bounded follow-up button, and save-as-hypothesis.
- **E. Hypothesis Dossier (P):** thesis, mechanism, prerequisites, falsifiers, catalysts, scenario assumptions, sensitivity, history and prospective evaluation state.
- **F. Evidence Inbox:** new source versions, deduplication family, material changes, affected hypotheses, ingestion failures and the approval queue. No alert for a difference that hasn't been validated to affect a fact or hypothesis.
- **G. Evaluation Dashboard:** gold-fixture results, extraction/provenance errors, point-in-time tests, paper-tracked candidate outcomes, operating costs. Operational metrics also go to Grafana. This screen is for research-quality metrics.

### 10.2 Interaction requirements

- Search company aliases and security identifiers without collapsing legal entities.
- Every generated factual claim has a clickable source trail. Unsupported assertions are visibly labeled.
- Every number discloses its source, period, currency, conversion basis and latest known/available timestamp.
- Historical snapshots show their exact date and evidence cutoff.
- Show new vs contradicted vs unchanged claims between two thesis versions.
- Provide a human approval action for verified relationships and for paper-tracking enrollment.
- Export a research dossier as JSON and Markdown, with citations and run metadata.
- A UI without backend persistence and an evidence-linked vertical slice is not an acceptable deliverable.

---

## 11. API specification

Version all HTTP routes under `/api/v1`. Required high-level endpoints (pagination/auth parameters follow project conventions):

```
GET    /themes
GET    /themes/{id}/map?as_of=...
GET    /companies?query=...
GET    /companies/{id}
GET    /companies/{id}/relationships
GET    /sources/{id}/versions
GET    /source-versions/{id}/content          # streams via the API, or a short-lived signed URL
GET    /assertions?company_id=&review_state=
POST   /assertions/{id}/review
POST   /investigations
GET    /investigations/{id}
GET    /investigations/{id}/events
POST   /investigations/{id}/follow-up
POST   /hypotheses
GET    /hypotheses/{id}
POST   /hypotheses/{id}/publish-version
POST   /hypotheses/{id}/enroll-paper-tracking
POST   /hypotheses/{id}/scenarios
GET    /snapshots/{id}
POST   /replay-jobs
GET    /evaluations
GET    /health/live
GET    /health/ready          # checks app DB, object store, Hindsight, LiteLLM reachability
GET    /metrics               # Prometheus
```

Return stable typed response models, with input validation, consistent error envelopes, pagination and audit IDs. Long-running jobs expose status and events. Never block an HTTP request until a deep-research investigation finishes. Polling is fine for the MVP; SSE can follow.

No endpoint exposes secrets, raw provider tokens or internal Hindsight credentials.

**Auth:**

- In the cluster, the app sits behind Authentik (forward auth or OIDC) on the **internal** gateway only, and the actor identity comes from the authenticated principal.
- In local dev, a single configured local actor is used.
- Every mutation records the actor identity and writes an audit event.

---

## 12. Codebase and development standards

The app lives in **its own repository**. The `home-ops` repo only holds the deployment manifests (Appendix A). Suggested layout:

```
atlas-research/
  README.md
  AGENTS.md
  pyproject.toml
  uv.lock
  .env.example
  compose.yaml
  Dockerfile                 # multi-stage: frontend static export + Python API/worker
  configs/
    themes/ai-infrastructure.yaml
    hindsight/bank-template.json
    providers.yaml
    llm-roles.yaml           # role -> LiteLLM alias, budget
    research-policies.yaml
  backend/
    app/
      api/               # FastAPI endpoints and auth
      domain/            # Pydantic contracts and domain services
      db/                # SQLAlchemy/Alembic
      sources/           # SEC, IR, SearXNG, Exa, Firecrawl, fixtures
      archive/           # immutable raw and parsed source storage
      ingestion/         # extraction, dedupe, provenance, Hindsight bridge
      entity_resolution/
      hindsight/         # typed gateway, bank templates, operation polling
      llm/               # LiteLLM client, structured-output validation, cost capture
      research/          # planner, scout, investigator, skeptic, editor
      financials/        # XBRL normalization, scenarios, optional OpenBB
      evaluation/        # fixtures, point-in-time replay, prospective scoring
      jobs/              # Postgres job queue, worker, schedules
      telemetry/
  frontend/
    app/                 # Next.js screens (output: 'export')
    components/
    lib/api-client/      # generated from OpenAPI
  tests/
    unit/
    integration/
    contract/
    e2e/
    fixtures/
    evaluation/
  scripts/
    seed-theme.py
    run-photonics-demo.py
    export-dossier.py
  docs/
    architecture.md
    data-model.md
    decisions.md
    hindsight-feature-matrix.md
    deployment.md
    evaluation-methodology.md
    source-licenses.md
    runbooks.md
  .github/workflows/     # lint, typecheck, test (fixture-only), image build + push to GHCR
```

Coding requirements:

- Python type checking (pyright or mypy strict), Ruff lint/format, pytest, Pydantic v2, SQL migrations and contract fixtures. TypeScript strict mode, ESLint, and frontend component/e2e tests (Playwright).
- `uv` with a committed lockfile. Pin Hindsight and provider library versions, with a tested upgrade process.
- Dependency injection for external APIs and LLMs. No network access in unit tests (enforce with `pytest-socket` or similar).
- Deterministic parser/normalizer functions, kept separate from stochastic LLM extraction.
- Every external provider has retry classification, rate limiting, a mock/fixture implementation, metric labels and a documentation page covering entitlements.
- Secrets come from env vars (Kubernetes Secrets synced by external-secrets in the cluster) and are never committed. Validate every required setting at startup with actionable missing-credential messages. Optional providers log "disabled: missing X" once instead of failing.
- Keep audit events for human edits and corrections. Write backwards-compatible schema migrations.
- One container image runs as `api` or `worker` depending on its command. It runs as non-root with a read-only root filesystem and a writable `/tmp` emptyDir. Images are multi-arch only if a non-amd64 node needs them.

---

## 13. Deployment and operations

### 13.1 Local Compose (dev + CI)

Services: `api` (also serves the frontend), `worker`, `postgres-app`, `hindsight`, `hindsight-db` (pgvector), `minio` (or filesystem storage for the fastest bootstrap). Add health checks, persistent volumes and startup ordering, but don't mistake Compose ordering for application readiness. The API's `/health/ready` is the readiness truth.

CI runs the fixture-only path with no paid keys. Hindsight in CI either uses a recorded-response fake gateway (unit/contract tests) or a real Hindsight container with a fixture LLM, depending on what the Phase 0 spike shows is feasible.

### 13.2 Home cluster (from Phase 2)

Deploy to the `home-ops` cluster as soon as Phase 1 passes, and treat it as the primary environment. Dev keeps using Compose. Appendix A lists the concrete wiring and known traps.

### 13.3 Reliability and security

- **Backups:**
  - The app DB and the Atlas Hindsight DB are on Crunchy Postgres with pgBackRest, which the platform already provides.
  - Object archive: a versioned bucket, replicated off-cluster.
  - Test a full restore of all three (archive + Hindsight + domain) together, once, and document it as a runbook.
- Immutable archival for published snapshots and source versions: bucket versioning, plus object lock if the bucket supports it. Retention/legal-review controls apply.
- Per-provider request budgets, fair access, 429 backoff, robots/terms gates and an emergency disable switch (a config flag the worker reads live).
- Hindsight ingestion queue recovery with a stable worker ID and operation status polling.
- Structured logs and Prometheus metrics around source fetch, parse, retain, consolidate, recall, reflect, research jobs, evaluations and costs. Alert (PrometheusRule) on repeated failures, zero extraction, dead letters and snapshot validation failures.
- Private by default: internal gateway only, never through the Cloudflare tunnel. Authentication, short-lived signed object URLs, sensitive-log redaction, and a disclosed model-provider configuration.

### 13.4 Cost management

- Every run records provider usage and estimated spend. For LLM calls the source of truth is LiteLLM's spend log, filtered by the `atlas` key and `metadata.run_id`. The app stores the per-call usage it received as a cross-check.
- Budget ceilings: per run (app-enforced) and per key (LiteLLM `max_budget`).
- Source collection caching, search-result deduplication and refresh-interval limits.
- Default to a minimal number of mental models with daily change-sensitive refresh.
- Test local versus hosted LLMs on the same extraction fixture set, and report accuracy, cost and throughput. Pick providers from measured results, not theoretical token economics.

---

## 14. Implementation work packages and acceptance gates

Follow this order. When executing autonomously, finish the current phase's tests and artifacts before starting the next one. Record deviations in `docs/decisions.md`.

**Pilot cut line: Phases 0–5 plus the leakage test from Phase 6a.** Phases 6b and 7 follow the pilot review.

### Phase 0: repository audit, Hindsight spike and vertical-slice design

Tasks:

- Inspect existing code and services, and document the reuse strategy.
- Pin architecture and dependency versions.
- **Hindsight spike:** run the pinned version in Compose and produce `docs/hindsight-feature-matrix.md` (§6.1) from live calls.
- Write the threat model, API contracts, DB diagram and gold-fixture format.
- Define the photonics seed list and run budget.
- Configure quality gates.

Deliverables: `docs/architecture.md`, ADRs, `AGENTS.md`, source-entitlement inventory, Hindsight feature matrix, initial fixture pack, implementation checklist.

Gate: clean local boot of the empty service skeleton; CI green for formatting, static checks, migrations and tests.

### Phase 1: provenance and SEC vertical slice

Tasks:

- Migrations for company/security/source/source_version/assertion/audit/job.
- Object archive.
- One configured SEC company: filing and companyfacts fetch, HTML parse.
- Immutable content hashing, `acceptanceDateTime`-based `available_at`, idempotent repeat fetch.
- Reviewable source API and a minimal source viewer.

Gate:

- Fetching an unchanged filing twice creates one source version, and a changed source creates a new one.
- A source can be retrieved with its original bytes and exact provenance.
- The mocked 429 retry test passes.
- A real SEC smoke test passes where connectivity permits.

### Phase 2: Hindsight memory integration and first cluster deploy

Tasks:

- Hindsight in Compose.
- Bank template/config, typed gateway, async retain and operation polling.
- Mapping to the source ledger.
- Provenance-aware recall/reflect.
- Observations and two curated mental models.
- Health check.
- **First home-ops deployment** (Appendix A): API + worker + dedicated Hindsight.

Gate:

- Ingest a fixture covering two related companies and retrieve cross-company context from the same bank.
- Resolve every cited memory to archived evidence.
- Missing and zero-fact failures are visible.
- A replayed identical operation doesn't duplicate work.
- A source revision stays separately auditable.
- The same flow works against the in-cluster deployment.

### Phase 3: discovery, entity resolution and typed relationships

Tasks:

- Photonics seed theme/companies.
- Company IR adapter; SearXNG + fixture discovery (Exa optional).
- Identity mapping; extraction of assertions; duplicate source-family detection.
- Typed edge review workflow; relationship edge table UI.

Gate:

- A relevant unseeded company can be discovered through SearXNG or a deterministic fixture.
- A reviewer can establish a directed supplier/product edge and open its original source.
- Syndicated stories count as one evidence family.
- A co-mention-only fixture is not marked as a verified supplier link.

### Phase 4: controlled research workflow

Tasks:

- Scout, Investigator, Skeptic and Financial Analyst contracts.
- Deterministic finite-state DAG on the job table.
- Independent counterevidence search; cost/depth limits.
- Thesis lifecycle and research workbench.
- Evidence-linked research dossier export.

Gate:

- One end-to-end photonics investigation reaches a reviewable hypothesis with a source trail, at least one falsifier and one explicit unresolved question.
- No unsupported claims are promoted.
- Budget exhaustion and provider outages produce a resumable partial investigation, not invented answers.

### Phase 5: financial scenarios

Tasks:

- SEC XBRL normalization with filed/available timestamps and restatement linkage.
- Attach numeric data to the company dossier.
- A transparent low/base/high scenario model with assumptions and sensitivities.
- Missing-data flags. OpenBB adapter optional.

Gate:

- A representative fixture reconciles to the original XBRL values, units and periods.
- Restatement and currency tests pass.
- Scenarios recompute deterministically.
- No source-free financial figure passes validation.

Introduce PyMC only after a documented modeling justification.

### Phase 6a: snapshots and leakage test (inside the pilot)

Tasks: immutable publication snapshots, a minimal isolated replay bank, and the future-fact contamination fixture.

Gate:

- A published snapshot cannot be altered.
- A later contradictory source leaves it untouched.
- The contamination test fails closed: 0 future-dated fixtures accepted.

### Phase 6b: continuous updates and prospective evaluation (post-pilot)

Tasks:

- Scheduled monitoring (CronJobs), source diffs and Hindsight retain/consolidation.
- Affected-hypothesis detection; reviewer evidence inbox.
- Gold-case evaluation runs; evaluation dashboard.
- **Market-data provider decision (§9.3)**, then prospective paper tracking.

Gate:

- An update to one source propagates to the impacted research without rewriting unrelated thesis history.
- All paper-tracked outcomes use frozen publication dates and assumptions known in advance.

### Phase 7: operational hardening (post-pilot)

Tasks: backup/restore drill, auth review, rate limits, source license review, alerts, runbooks, integrated e2e, React Flow map, accessibility and UI review.

Gate:

- Fresh-machine Compose bootstrap and the demo work from documented commands.
- A clean restore of archive + Hindsight + domain records succeeds.
- No critical dependency or secret leaks in CI.
- The pilot review is complete.

---

## 15. Pilot acceptance rubric: minimum demo that must work

The final demo includes one fully working photonics investigation. A reviewer must be able to:

1. Boot the project locally and load a fixture-only demo without any commercial API keys.
2. Turn on permitted public SEC/IR fetching and reproduce a real document ingest where connectivity permits.
3. Inspect archived document versions and their evidence/metadata.
4. Ask a cross-company Hindsight research question and see source-resolved retrieved memories.
5. Discover a relevant company not in the original seed list through SearXNG, a controlled discovery provider or a fixture.
6. Open a reviewed relationship edge and inspect the document statement backing it.
7. View a skeptical research card with counterevidence, competing explanations and genuine missing-data labels.
8. Create or modify a financial scenario and see deterministic updated outputs with traceable assumptions.
9. Approve a hypothesis into a frozen, dated research snapshot and export the dossier.
10. Add a later contradictory source to the fixture data, rerun collection, and see an update proposed without the frozen old snapshot changing.
11. Run a historical cutoff test with a deliberately future-dated source and show that it is excluded from the replay bank.
12. Review source counts, extraction/verification failures, run costs and benchmark results.

Suggested initial engineering thresholds. These are subject to review, not promises:

- 100% source-link resolution for published claims
- 0 accepted future-dated fixtures in point-in-time tests
- 0 duplicate immutable source versions for repeated identical fetches
- 100% passing core contract tests
- zero source-free published numeric facts

Track other precision/recall numbers on the human-labeled fixture pack and improve them, instead of declaring arbitrary thresholds met.

---

## 16. Risks and explicit mitigations

| Risk | Mitigation |
|---|---|
| Hindsight graph treated as typed commercial truth | Curated SQL relationship projection; original-source review and explicit epistemic labels |
| LLM cites its own earlier summary as independent evidence | Always trace back to source-version IDs; source independence families; derived knowledge never counts as an extra witness |
| Hindsight document_id upsert destroys historical source memory | Immutable document ID per version, plus a separate audit/archive |
| Hindsight upgrade silently changes extraction | Dedicated release, automerge off, version recorded per run, fixture run before upgrade |
| Hindsight feature assumed but absent in the pinned version | Phase 0 feature matrix from live calls; spec defers to the matrix |
| Temporal leakage in backtests | Strict external `available_at` filter; isolated replay banks or frozen snapshots; adversarial tests |
| Delayed publication masquerades as early knowledge | Distinct event, published, available, ingested and analyzed times; SEC acceptance timestamps |
| XBRL restatements leak into historical views | As-of selection by filing availability; restatement linkage |
| False customer/contract inferences | Directed predicate whitelist, human review and rejection fixtures |
| Identity confusion from ticker/parent/subsidiary | Canonical legal-company IDs, effective-dated securities, external identifier validation |
| Unlicensed or unsafe crawling | Source entitlement ledger, rate limits, policy compliance and provider kill switches |
| Autonomous research runaway spend | Per-run budget, LiteLLM key budget, depth limits, dedupe, stop conditions and cost reporting |
| Subscription/hosted model retired or renamed | Stable dated model IDs for extraction; frozen snapshots as the reproducibility mechanism |
| Poor non-US financial coverage | Coverage flags, regional adapters, no filling gaps with synthetic facts |
| Economic significance overstated | Physical/financial/valuation stages; sensitivity; counterevidence; materiality question |
| Small-sample historical backtest overclaims edge | Frozen prospective tracking, predeclared evaluation, baseline comparison, rejected candidates included |
| Vendor/API changes | Pinned versions, typed gateways, adapter contract tests and documented upgrade checks |

---

## 17. Required verification and initial development commands

Don't assume package interfaces stay static. Before building adapters, read the installed version's SDK signatures, docs and release notes. For Hindsight specifically, prove in a sandbox that retain, recall, reflect, batch operations, provenance extraction, bank templates, mental-model refreshes and export/restore behave as this document expects (the Phase 0 feature matrix).

Suggested commands in the generated repository:

```bash
cp .env.example .env
# Fill in only the credentials you intend to test.
docker compose up -d postgres-app hindsight-db hindsight minio
uv sync
uv run alembic upgrade head
uv run pytest tests/unit tests/contract
uv run python scripts/seed-theme.py --config configs/themes/ai-infrastructure.yaml --theme photonics
uv run python scripts/run-photonics-demo.py --provider fixtures
npm --prefix frontend install
npm --prefix frontend run dev
```

These are the commands the project should end up supporting. They don't show that anything already works. If integrating with an existing codebase, replace them with equivalents and update the README. CI must run fixture-only, without paid keys.

---

## 18. Primary technical references (review at implementation time)

1. Hindsight quick start and SDK: https://hindsight.vectorize.io/developer/api/quickstart
2. Hindsight retain API: https://hindsight.vectorize.io/developer/api/retain
3. Hindsight recall API (temporal caveat, strict tag scoping): https://hindsight.vectorize.io/developer/api/recall
4. Hindsight reflect API, structured output and provenance: https://hindsight.vectorize.io/developer/api/reflect
5. Hindsight memory banks and configuration: https://hindsight.vectorize.io/developer/api/memory-banks
6. Hindsight bank templates: https://hindsight.vectorize.io/developer/api/bank-templates
7. Hindsight mental models: https://hindsight.vectorize.io/developer/api/mental-models
8. Hindsight knowledge pages: https://hindsight.vectorize.io/developer/api/knowledge-pages
9. Hindsight operations / retry safety: https://hindsight.vectorize.io/developer/api/operations
10. Hindsight monitoring and recovery: https://hindsight.vectorize.io/developer/monitoring
11. Hindsight repository / deployment / Helm chart: https://github.com/vectorize-io/hindsight
12. SEC EDGAR developer APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
13. SEC fair-access guidance: https://www.sec.gov/about/webmaster-frequently-asked-questions
14. SearXNG search API: https://docs.searxng.org/dev/search_api.html
15. LiteLLM proxy (virtual keys, budgets, spend logs): https://docs.litellm.ai/docs/proxy/virtual_keys
16. OpenBB: https://docs.openbb.co/odp/python
17. OpenBB coverage/licensing warning: https://docs.openbb.co/odp/python/extensions/providers
18. Exa API: https://docs.exa.ai/
19. Firecrawl documentation: https://docs.firecrawl.dev/
20. GLEIF API: https://www.gleif.org/en/lei-data/gleif-api
21. OpenFIGI: https://www.openfigi.com/api
22. PyMC: https://www.pymc.io/projects/docs/en/stable/

> **Implementation discipline:** current SDK behavior and source entitlements take precedence over the example syntax in this specification. Document every difference found through a live contract test. This is a research platform, not a promise of investment returns.

---

## Appendix A: home-ops deployment target

This is the cluster the app will run in. It's a GitOps monorepo: Flux reconciles `kubernetes/apps/<namespace>/<app>/`, and each app has a `ks.yaml` (Flux Kustomization), a `kustomization.yaml` and a `HelmRelease`. The app repo builds images, and home-ops only references them.

**Placement.** Namespace `datasci`. It sits alongside marimo/MLflow, and it already has the `ghcr-pull` secret, which is needed if the image is private. The `ghcr-pull` secret is hand-created and only exists in `development` and `datasci`, so a different namespace means copying it or publishing public images. Layout:

```
kubernetes/apps/datasci/atlas/
  ks.yaml                # atlas + atlas-hindsight Kustomizations, dependsOn crunchy/minio/external-secrets
  app/                   # HelmRelease (bjw-s app-template: api + worker controllers, CronJobs), ExternalSecrets, HTTPRoute
  hindsight/             # dedicated Hindsight HelmRelease (chart oci://ghcr.io/vectorize-io/charts/hindsight)
```

**Workloads.** Use one app-template HelmRelease with controllers `api` (Deployment) and `worker` (Deployment), plus CronJobs for scheduled collection. Things to know:

- app-template 5.x defaults `automountServiceAccountToken: false`. Atlas doesn't need the Kubernetes API, so leave it off.
- Set resource requests/limits (repo policy for `datasci`).
- Use a `topologySpreadConstraints` policy of `ScheduleAnyway`, never `DoNotSchedule`. A tainted node deadlocks rollouts otherwise.

**Postgres (Crunchy, `database` ns).**

- Add users/databases `atlas` and `atlas-hindsight` in `crunchy-postgres/cluster/cluster.yaml`. Credentials come through ExternalSecrets from the `crunchy-pgo-secrets` store.
- The primary is **TLS-only**, so use `sslmode=require` (not `verify-full`).
- Run migrations against the **direct primary, not pgbouncer**. The pool is transaction mode, which breaks the advisory locks that Alembic and the job queue rely on. The worker's `SKIP LOCKED` queue also needs session semantics.
- `vector` is not a trusted extension. A superuser must `CREATE EXTENSION vector` once in the Hindsight database before its first boot.
- Database ownership (`datdba`) lands asynchronously after first creation. A "permission denied for schema public" error that doesn't clear within minutes means the userinit controller's watch has stalled: restart `crunchy-userinit-controller`, and don't drop the DB.
- ESO cannot merge into a Secret owned by another ExternalSecret. Use one ExternalSecret per target Secret and list them all under `envFrom`.

**Hindsight chart quirks** (from the existing `llm/hindsight` release):

- `existingSecret` is envFrom on the API and control plane, and it must contain the key `postgres-password`.
- The slim image has no torch, so enable the chart's TEI reranker sidecar.
- The API pod mounts an RWO PVC but the chart sets no deployment strategy. The default RollingUpdate hangs on Multi-Attach, so add a postRenderer patch to `strategy: Recreate`.
- Tenant auth: `HINDSIGHT_API_TENANT_EXTENSION=hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension` + `HINDSIGHT_API_TENANT_API_KEY` from Bitwarden.
- Point its LLM at a stable non-streaming-capable provider (§6.1).

**LLM access.** The LiteLLM proxy runs in the `llm` ns. Create a `LiteLLMVirtualKey` CR (in `llm/litellm/keys/`) named `atlas` with a `max_budget`. The operator mints the Secret `litellm-key-atlas`. Copy it into `datasci` via ExternalSecret or reference it cross-namespace, following whatever pattern the other keys use. Model aliases come from the LiteLLM configmap pools. `chatgpt/*` rungs only serve streaming callers.

**Object storage.** Create a bucket `atlas-archive` with versioning (and object lock, if created that way) plus a dedicated access key on the in-cluster MinIO. MinIO users, policies and buckets are managed by OpenTofu under `terraform/minio`, not by hand. The MinIO console no longer has admin pages, so use `mc` or OpenTofu. Replicate the bucket off-cluster alongside the existing R2 backups.

**Secrets.** Every runtime secret lives in a Bitwarden item (e.g. `atlas`: `SEC_USER_AGENT`, `EXA_API_KEY` (optional), `HINDSIGHT_API_KEY`, `S3_*`) synced by external-secrets. For optional fields, use `{{ index . "EXA_API_KEY" }}` in templates: a missing plain field can fail the whole secret. Never commit plain-text secrets. Any in-Git sensitive value is `*.sops.yaml`.

**Networking and auth.** Use an HTTPRoute on the **internal** Envoy gateway only, with Authentik in front. No Cloudflare tunnel exposure. external-dns creates the internal record.

**Observability.** Add a ServiceMonitor for `/metrics`, a PrometheusRule for the §13.3 alerts, and a Gatus endpoint. Gatus is registered by the template line in the app's `kustomization.yaml`; `GATUS_*` vars alone do nothing.

**GitOps traps.**

- Flux post-build substitution is strict: any literal `${VAR}` in a manifest, even in a comment or a config string, fails the whole Kustomization. Escape it as `$${VAR}`.
- PRs to home-ops can auto-merge within minutes, so opening a PR is effectively deploying. Validate with `flux-local` / `kubeconform` locally first.
- Renovate will track the Atlas image tags and digests. Disable automerge for the dedicated Hindsight image.

**Backups.** Crunchy pgBackRest covers both databases. The object archive needs its own off-cluster replication. VolSync is only needed if a PVC holds state, and the design keeps state out of PVCs apart from Hindsight's.
