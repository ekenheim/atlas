# Spec: Atlas pilot, Phases 3–6a

Status: ready-for-agent
Map: [Map: Atlas pilot, Phases 3–6a](./map.md). Builds on the deployed Phases 0–2 (`.scratch/atlas-pilot/spec.md`, Atlas 0.1.2).

Vocabulary follows `CONTEXT.md`. The product spec (`hindsight_investment_research_build_plan.md` v1.1) is authoritative; deviations are in `docs/decisions.md`. Research behind this spec (on `research/*` branches): `seed-list`, `identity-apis`, `xbrl-normalization`, `serenity-skills-alignment`.

## Problem Statement

Atlas can now archive SEC filings, retain them into Hindsight and answer provenance-checked questions about two hand-picked companies. It can't yet do what it exists for:
- find the **Bottlenecks** in the photonics supply chain across a real universe of companies, including ones nobody seeded;
- establish **who supplies whom** from evidence;
- challenge a thesis with **independent counterevidence**;
- put **numbers** on a company's exposure;
- **freeze** what was believed at a decision time, so it can be judged later without hindsight.

The researcher still has to do all of that by hand, and nothing prevents later knowledge from contaminating a past view.

## Solution

1. **A 12-company photonics universe across seven supply-chain layers.** It's resolved deterministically to legal entities and listings, and fed by SEC EDGAR plus exchange sources (HKEXnews, LSE RNS, Euronext) for companies that don't file with the SEC.
2. **Discovery (Phase 3).** A budgeted Scout searches the web through SearXNG for leads. A lead naming an unseeded company becomes a Candidate for the owner to commit.
3. **Relationships (Phase 3).** An Investigator proposes span-backed Claims about supplier, customer, product and competitor links. A separate reviewer model and deterministic checks machine-review them into typed, directed, layer-tagged Relationships, and a human handles the exceptions.
4. **The research workflow (Phase 4).** A controlled Scout → Investigator → Skeptic ∥ Analyst → Editor workflow turns a theme question into a Hypothesis with a mechanism, falsifiers, counterevidence and open questions. It's published only through an owner gate.
5. **Scenarios (Phase 5).** Deterministic low/base/high scenarios on as-of XBRL financials and sourced or estimated assumptions (including bill-of-materials share) quantify exposure.
6. **Snapshots and replay (Phase 6a).** Publishing freezes an immutable Research Snapshot, and a replay test proves that a past-cutoff view can't see future sources.

## User Stories

### Universe and identity

1. As the researcher, I want the photonics theme seeded with the 12 verified companies (AXT, Soitec, IQE, Coherent, Lumentum, MACOM, STMicroelectronics, Marvell, Zhongji Innolight, Applied Optoelectronics, Fabrinet, Ciena) and their layers, so that research covers the whole chain from substrate to system.
2. As the researcher, I want each company resolved to its legal entity, LEI, CIK and listings through a deterministic tiered pipeline, so that tickers, ADRs and subsidiaries are never confused.
3. As the researcher, I want name-only or conflicting identity matches queued for my review instead of committed, so that no company is misidentified silently.
4. As the researcher, I want each company's CIK↔LEI link confirmed once by me, because no authoritative source links them.
5. As the researcher, I want securities stored effective-dated, with ADR links, operating and segment MICs, FIGI level and currency, so that renames and multiple listings resolve correctly.
6. As the researcher, I want companies that don't file with the SEC ingested from their exchange's primary disclosure feed (HKEXnews, LSE RNS, Euronext or the issuer's regulatory filings), so that non-US coverage isn't silently missing.
7. As the researcher, I want annual reports and results announcements in PDF parsed deterministically into text with page anchors, so that they can back Assertions like HTML filings do.
8. As the researcher, I want robots.txt and site terms honoured and the allowing gate recorded per fetch, and sources that forbid automation marked as blocked instead of fetched, so that Atlas stays within source terms.
9. As the researcher, I want non-English documents archived and marked as not extracted, so that the gap is visible rather than guessed at.

### Discovery and Candidates

10. As the researcher, I want the Scout to turn a theme question and the Bottlenecks mental model's open gaps into at most 10 SearXNG queries per run, so that discovery is focused and cheap.
11. As the researcher, I want search results stored as Tier C leads (URL, title, snippet, query, engines, date), deduplicated by canonical URL, so that I can see what was found and why.
12. As the researcher, I want leads never counted as Evidence and never retained into Hindsight, so that web noise can't masquerade as proof.
13. As the researcher, I want a lead naming an unseeded company to propose a Candidate after entity resolution, so that new companies surface for evaluation.
14. As the researcher, I want to commit or reject Candidates, with commits triggering ingest and rejections kept with their reason, so that the universe grows deliberately and evaluation isn't winner-only.
15. As the researcher, I want Candidates to follow the §8.3 states (lead, investigating, evidence_ready, needs_more_evidence, paper_tracking, rejected, closed), so that each company's research status is explicit.

### Relationships

16. As the researcher, I want the Investigator to read archived parsed text and propose Claims that each name a Source Version and an exact quote span, so that every proposal is checkable.
17. As the researcher, I want Claims whose span validates to become Assertions automatically, and ones that don't to be discarded with the reason recorded, so that paraphrases never enter the ledger.
18. As the researcher, I want only whitelist predicates with explicit direction, never inferring `supplies` from `buys_from` or from "works with", so that direction errors can't creep in.
19. As the researcher, I want each Relationship tagged with its supply-chain layer, so that layer-confusion errors (a substrate maker called an epi supplier) are caught.
20. As the researcher, I want syndicated copies of one announcement grouped into one Evidence Family (content hash plus SimHash), so that one press release counts as one witness.
21. As the researcher, I want a separate reviewer model plus deterministic checks (a verbatim span in the archive, a Tier A source, explicitly directional language) to mark qualifying Relationships machine-reviewed, so that I don't have to click through every edge.
22. As the researcher, I want rejected or uncertain proposals in an exceptions queue that I review, so that my time goes to the ambiguous cases.
23. As the researcher, I want a sortable edge table (subject, predicate, object, layer, review state, Evidence count and family count) where every edge opens its source span, so that I can audit the graph.
24. As the researcher, I want a co-mention-only fixture never to become a Relationship, so that the most common false inference is guarded by a test.

### Research workflow

25. As the researcher, I want to start an investigation from a theme question and get a fixed, visible plan (Scout → Investigator → Skeptic ∥ Analyst → Editor), so that research is controlled rather than free-roaming.
26. As the researcher, I want each role's input and output to follow the §7.2 contract, validated with Pydantic and quarantined when malformed, so that bad model output can't corrupt the record.
27. As the researcher, I want per-run budgets (≤2 rounds, ≤10 leads, ≤25 fetched documents, a token ceiling) backed by the LiteLLM key budget, so that no investigation runs away.
28. As the researcher, I want every stop to record its reason (answered, no new independent evidence, budget exhausted, needs review), so that I know why an investigation ended.
29. As the researcher, I want a disproven premise to cancel only its dependent follow-ups, so that other findings survive.
30. As the researcher, I want an LLM outage or quota limit to pause and later resume the investigation, never to produce invented text, so that failures are honest.
31. As the researcher, I want the Skeptic to search independently for counterevidence using the bear checklist (substitutes, second sources, capacity additions, inventory cycle, dilution/financing, customer concentration), so that challenges aren't the Investigator's echo.
32. As the researcher, I want neither the Investigator's conclusions nor Hindsight Memory ever counted as an independent witness, so that corroboration is real.
33. As the researcher, I want investigation progress visible (plan, events, Evidence tray, contradictions, open questions) through the API and a workbench page, so that I can follow and steer.
34. As the researcher, I want to launch one bounded follow-up round on an open question, so that I can push on the most important uncertainty.

### Hypotheses and dossiers

35. As the researcher, I want to save an investigation's result as a Hypothesis with statement, mechanism, predictions, catalysts, falsifiers, required Evidence and alternatives (§5.6, §8.1), so that the thesis is explicit and falsifiable.
36. As the researcher, I want Hypotheses to follow the §5.6 lifecycle, with published versions immutable and corrections as new versions, so that history can't be rewritten.
37. As the researcher, I want publishing to require at least one falsifier, at least one unresolved question and my approval of the Relationships the Hypothesis depends on, so that nothing half-supported is published.
38. As the researcher, I want a Hypothesis dossier page and a JSON/Markdown export with citations and run metadata, so that I can read, share and archive the research.
39. As the researcher, I want the difference between two Hypothesis versions shown as new, contradicted and unchanged claims, so that I can see what changed my mind.

### Financials and scenarios

40. As the researcher, I want XBRL companyfacts normalized to as-of values per (concept, period, unit) from the latest filing available at the as-of date, never using `frame`, so that historical views don't see restatements early.
41. As the researcher, I want per-concept tag precedence (revenue tags drift over time), restatements linked rather than overwritten, and suspect values flagged, so that numbers are consistent and anomalies visible.
42. As the researcher, I want quarterly values derived where only annual and year-to-date values exist (Q4 = FY − 9M) and 52/53-week fiscal years handled, so that series are complete and correct.
43. As the researcher, I want IFRS filers' facts (e.g. Nokia-style `ifrs-full`) and currencies handled, and no mixing of currencies without a stated FX basis, so that non-US numbers are trustworthy.
44. As the researcher, I want every financial figure to show its source (accession, concept, period, unit, `available_at`), so that numbers are traceable.
45. As the researcher, I want a deterministic low/base/high scenario per Hypothesis version (units × share × price → revenue × margin → contribution → valuation, including bill-of-materials share), so that exposure is quantified transparently.
46. As the researcher, I want every scenario input labelled sourced (an XBRL fact or Assertion span) or estimated (with its basis), and missing inputs shown as missing, so that no number is invented.
47. As the researcher, I want a ±20% sensitivity table per input and byte-identical recomputation for identical inputs, so that results are explainable and reproducible.

### Snapshots and replay

48. As the researcher, I want publishing a Hypothesis version to freeze a Research Snapshot (§5.7: cutoff, considered Source Versions, retrieved Memory text as returned, Assertions, the financial dataset hash, prompts and model versions, Hindsight version, outputs), so that I can reproduce exactly what was known.
49. As the researcher, I want the snapshot stored as content-addressed JSON in the archive plus an insert-only database row, verified by hash on every read, so that it can't be altered unnoticed.
50. As the researcher, I want a later contradictory source to propose an update without changing the frozen snapshot, so that past beliefs stay intact.
51. As the researcher, I want a replay of the pipeline at a cutoff to run in an isolated `atlas-replay-*` bank on the local Hindsight, seeded only with Source Versions available at the cutoff, so that it can be evaluated without contaminating production.
52. As the researcher, I want a deliberately future-dated fixture accepted 0 times in the replay, so that leakage is tested, not assumed.

### Operations

53. As the operator, I want Atlas's own LLM calls to go through LiteLLM with the `atlas` key, recording the routed model and tokens per call with `metadata.run_id` and role, so that spend and provenance are attributable.
54. As the operator, I want metrics for discovery queries, leads, Candidates, Claims (accepted/rejected), Relationships by review state, investigation stops by reason, scenario runs and snapshots, so that the research pipeline is observable.
55. As the operator, I want a small labelled evaluation set (a first 10–15 cases from the §9.5 categories, including the layer-confusion and co-mention traps) runnable on demand, so that quality regressions are measurable.

## Implementation Decisions

### Universe, identity and sources

- **Theme config:** add the 12 companies with layer tags (substrate, epi, chip/laser, DSP, module, contract manufacturing, system) and their source path: `sec` (10-K/10-Q/8-K, or 20-F/6-K for STMicroelectronics under US GAAP) or `exchange:<hkex|lse-rns|euronext>`.
- **Unsponsored-ADR CIKs are ignored:** SEC ticker files list CIKs for Soitec, IQE and Innolight, but those hold only unsponsored-ADR paperwork, not company filings.
- **Entity resolution** is a deep module with a four-tier outcome:
  - **exact:** CIK or LEI or ISIN agreement
  - **corroborated:** two independent identifiers agree
  - **candidate:** name-only or single-source
  - **conflict**

  Only exact and corroborated commit automatically; candidate and conflict go to a review queue. CIK↔LEI is always owner-confirmed once per company. Sources:
  - SEC `company_tickers*.json` (10 requests/s)
  - GLEIF API (60/min; never `fuzzycompletions`; lapsed LEIs still identify)
  - OpenFIGI keyless (25/min; mapping jobs of 10; needs **segment MICs** such as `XNGS`)

  Each source is behind a transport-injectable client with recorded fixtures.
- **Schema for identity** extends `security` and adds `company_alias` and `identity_mapping`:
  - FIGI level (composite/share-class)
  - ADR link and ratio
  - operating vs segment MIC
  - currency
  - mapping provenance (source, observed_at)
  - a review state on mappings
  - uniqueness per (MIC, ticker, validity)
- **Exchange source adapters** implement the existing `SourceAdapter` protocol:
  - **HKEXnews:** Innolight (HKEX 03308, listed July 2026; its own IR site disallows robots)
  - **LSE RNS:** IQE
  - **Euronext/issuer regulated information:** Soitec

  `available_at` uses the exchange's publication timestamp (basis `publisher_timestamp`), otherwise observed discovery. Each adapter records its terms/robots gate; blocked sources produce a visible `blocked` fetch status. Most US issuers' IR sites block automation, so US names stay SEC-only.
- **PDF parsing:** deterministic text extraction with page anchors (a pinned library, a new parser version). Scanned or image-only PDFs are marked `parse_status=unsupported`. Non-English documents are archived with `language` set and excluded from retention and extraction.

### Discovery

- **Scout role:** a LiteLLM call (MiniMax-M3 via the `atlas` key, strict JSON schema) that generates ≤10 queries from the theme question plus the Bottlenecks mental model's open gaps.
- **SearXNG client:** engines named explicitly (`bing,brave`), `format=json`, recording `unresponsive_engines`.
- **Leads** are stored in a `lead` table (Tier C metadata), deduplicated by canonical URL, and never retained into Hindsight. Entity mentions in leads go through entity resolution; unseeded matches create `candidate` rows (§8.3 states).
- **Commit and reject** are owner API actions:
  - a commit adds the company to the universe (a DB-backed extension of the theme config) and enqueues its ingest;
  - rejected Candidates are kept with their reason.

### Relationships

- **Investigator extraction:** operates on archived **parsed text** (sections chosen via Hindsight recall hits and entity tags) and returns Claims `{subject, predicate, object, product?, layer, quote, source_version_id, char offsets, epistemic_type}`. Claims are validated by the existing Assertion span check; failures are recorded as `claim_rejected` with the reason.
- **Predicate whitelist (§5.5)** with explicit direction; there's no mapping from "partners/works with". Layer taxonomy: substrate → epi → chip/laser → DSP → module → system, plus contract manufacturing.
- **Evidence Families:**
  - exact duplicates by `content_sha256`;
  - near-duplicates by 64-bit SimHash on normalized parse text, Hamming ≤ 3 (tunable; recorded per family);
  - one family is one witness.
- **Review:**
  - **Reviewer role:** a separate LLM call with its own prompt and schema.
  - **Deterministic checks:** a verbatim span, a Tier A source, directional language (a pattern list plus the reviewer's classification).
  - **All pass →** `machine_reviewed`. **Otherwise →** `needs_human_review` (the exceptions queue).
  - The owner can approve or reject any Relationship. Approval is required for Relationships referenced by a Hypothesis version being published.
  - Every state change is audited.
- **Edge table:** the API plus a frontend page, sortable and filterable by layer and review state; each edge links to its Assertions and source spans.

### Research workflow (Phase 4)

- **An Investigation** is a `run` (the full run/task model extends the Phase 2 minimal run) with `task` rows per role on the existing job queue:
  - a deterministic DAG: Scout → Investigator → (Skeptic ∥ Financial Analyst) → Editor
  - an optional single follow-up round
- **Roles:**
  - each is a function with a §7.2 request/response contract, validated with Pydantic, with a bounded repair-retry then quarantine
  - prompts are versioned in the repo; directives are fixed in code; retrieved text is always quoted, low-trust data
- **Budgets and stops:**
  - budgets per run are config (defaults ≤2 rounds, ≤10 leads, ≤25 fetched documents, a token ceiling), tracked from LiteLLM usage and backed by the key's `maxBudget`
  - stop reasons: `answered | no_new_independent_evidence | budget_exhausted | needs_review | premise_disproven`
  - cancellations are scoped to dependent tasks
  - LLM transient failures use the existing queue pause
- **Skeptic:** an independent search (its own SearXNG and SEC/exchange queries) driven by the bear checklist. Its findings are separate Claims/Assertions tagged counterevidence. Independence is enforced by requiring distinct Evidence Families and excluding Memory and other roles' outputs as witnesses.
- **Financial Analyst:** produces the scenario inputs (Phase 5 module).
- **Editor:** assembles the research card or Hypothesis draft and proposes mental-model refresh inputs.
- **Hypothesis:**
  - the §5.6 schema and lifecycle; versions are immutable after publication
  - **publish gate:** ≥1 falsifier, ≥1 unresolved question, dependent Relationships owner-approved, a snapshot written
  - the version diff classifies claims as new, contradicted or unchanged
  - export as JSON and Markdown

### Financials and scenarios (Phase 5)

- **XBRL normalizer:**
  - it reads archived companyfacts Source Versions;
  - `available_at` of each fact = its **filing's** availability via `filing_availability` (EDGAR dissemination rules), never the companyfacts fetch time;
  - **as-of selection:** the latest filing with `available_at ≤ as_of` per (concept, period, unit); `frame` is ignored for as-of;
  - per-concept tag precedence lists, versioned in config;
  - later values are linked as restatements and never overwrite;
  - a suspect flag for implausible jumps (e.g. EPS mis-tags);
  - derived quarters (Q4 = FY − 9M), with 52/53-week calendars supported;
  - `us-gaap` and `ifrs-full`.
- **Storage:** a `financial_observation` table (§5.7) with source accession and version, `available_at`, currency and FX basis, and restatement linkage.
- **Fixtures:** the companyfacts fixtures are re-trimmed to include the concepts used (current revenue tag, capex, debt, diluted shares) and an IFRS filer's sample.
- **Scenario:**
  - a pure deterministic function over a versioned assumption table;
  - each input is `sourced(ref)` or `estimated(basis)`, and missing inputs block that output line;
  - low/base/high plus ±20% single-input sensitivity;
  - outputs are hashed; the same inputs give byte-identical outputs;
  - attached to a Hypothesis version;
  - no PyMC.

### Snapshots and replay (Phase 6a)

- **Research Snapshot:**
  - canonical JSON of the §5.7 contents, stored at `snapshots/<sha256>` in the archive;
  - a `research_snapshot` row (insert-only, trigger-enforced; the audit event references the hash);
  - hash verification on read;
  - a known limitation: filesystem storage isn't WORM until MinIO object lock.
- **Contradiction flow:** a later contradictory Source Version or Assertion creates a proposed update (a flag on the Hypothesis/Candidate) and never mutates the snapshot.
- **Replay:**
  - a job creates `atlas-replay-<id>` on a **local** Hindsight (Compose profile; the live-suite runner stack);
  - it re-retains only Source Versions with `available_at ≤ cutoff`, in chronological order;
  - it waits for consolidation, runs the fixed question set, records results, then deletes the bank.
  - A synthetic future-dated fixture must be accepted 0 times, i.e. absent from recall and resolved citations.

### API and frontend

- **API additions** under `/api/v1`, with typed responses and the error envelope:
  - `themes`, `themes/{id}/map`
  - `companies` identity/review
  - `candidates` (list, commit, reject)
  - `leads`
  - `relationships` (list, review, approve)
  - `investigations` (create, get, events, follow-up)
  - `hypotheses` (create, get, publish-version, diff, export)
  - `hypotheses/{id}/scenarios`
  - `snapshots/{id}`
  - `replay-jobs`
  - `evaluations`

  The API client is regenerated.
- **Frontend pages** (pilot scope): Theme explorer (A), Company dossier (B), edge table (C, pilot version), Research workbench (D), Hypothesis dossier (E). They're plain and accessible, like the viewer.

## Testing Decisions

- **Seams:** as for Phases 0–2.
  - **Primary:** the HTTP API plus worker single passes.
  - **Network boundaries are faked at the transport** from recorded responses:
    - LiteLLM (Atlas's role calls; scripted, schema-valid outputs per test)
    - SearXNG
    - GLEIF, OpenFIGI and SEC tickers
    - HKEXnews, LSE RNS and Euronext feeds
    - the existing Hindsight fake and EDGAR fixtures
  - **No live LLM or service calls in CI.** The live suite gains opt-in scenarios for discovery and one investigation.
- **Gate tests (§14 Phases 3–6a):**
  - an unseeded company is discovered via the SearXNG fixture and becomes a Candidate
  - a reviewer can establish a directed supplier/product edge and open its source
  - syndicated stories count as one Evidence Family
  - a co-mention-only fixture is never a Relationship
  - one end-to-end photonics investigation reaches a reviewable Hypothesis with a source trail, ≥1 falsifier and ≥1 unresolved question
  - no unsupported claim is promoted
  - budget exhaustion and an LLM outage produce a resumable partial investigation
  - an XBRL fixture reconciles to the filed values, units and periods
  - restatement and currency tests
  - scenarios recompute byte-identically
  - no source-free financial figure passes validation
  - a published snapshot can't be altered (DB and hash)
  - a later contradictory source leaves the snapshot untouched
  - replay accepts 0 future-dated fixtures
- **Unit tests:**
  - entity-resolution tiers (from recorded identity fixtures, including the XNGS/XNAS, lapsed-LEI and ADR cases)
  - SimHash families
  - the directional-language checker
  - the scenario math
  - the XBRL as-of selector with worked examples from `xbrl-normalization.md` (Lumentum Q4 = $1,006.3M; Nokia FY2023 restatement)
  - the EDGAR/exchange availability rules
- **Evaluation:** a first 10–15 gold cases in the `docs/evaluation-methodology.md` format, including the layer-confusion and partner-page traps, run by `atlas evaluate`, with results stored.
- **Prior art:** the Phase 0–2 harnesses (`tests/harness.py`, the recorded fakes, `scripts/e2e.py`).

## Out of Scope

- Phase 6b (scheduled monitoring and the evidence inbox; the market-data provider decision; paper-tracking outcomes) and Phase 7 (hardening, restore drill, React Flow graph).
- Earnings-call transcripts without a licensed provider; Exa/Firecrawl/OpenBB.
- Non-English extraction.
- The parked items: LiteLLM-centralised Hindsight traffic, LLM failover, a dedicated Atlas Hindsight.
- Market-implied expectations (§8.2 question 3) beyond a placeholder: no licensed price data.

## Further Notes

- **Choices made while synthesizing this spec, not grilled; reopen any that are wrong:**
  - SimHash Hamming ≤ 3
  - the Candidate universe extension stored in the DB rather than config
  - `task` rows per role
  - the frontend page scope (A–E)
  - a first evaluation set of 10–15 cases rather than 20–30
  - replay on the local Hindsight via the live-suite stack
- **Cost:** the Investigator, Reviewer and Skeptic spend MiniMax tokens on the `atlas` key ($25 per 30 days, max 3 parallel). Hindsight retention of new sources spends Codex on the shared server; keep ingest bounded (lookback, 8-K selection) and consider the parked dedicated Hindsight before large expansions.
- **Timestamps:** Phase 5 must use `filing_availability` for XBRL facts (ticket 10).
- **Build order suggestion:** identity and universe → exchange adapters and PDF → discovery → relationships → workflow → XBRL and scenarios → snapshots and replay. Frontend pages are built alongside their API.
