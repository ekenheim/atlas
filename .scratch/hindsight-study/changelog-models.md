# Hindsight study: changelog (0.8.0 to 0.10.0), models, performance, FAQ

Reader's slice: `.agents/skills/hindsight-docs/references/changelog/index.md` (top through the 0.8.0 entry), `faq.md`, `developer/models.md`, `developer/performance.md`, `developer/rag-vs-hindsight.md`, `developer/index.md`, `developer/multilingual.md`, `developer/memory-defense/index.md`. Where needed I also opened `developer/configuration.md` rows the slice points at (the retain table and the multi-LLM chain), `openapi.json` request schemas, `docs/hindsight-feature-matrix.md`, `docs/research/extraction-bakeoff.md`, `docs/decisions.md` (metadata routing) and Atlas code. Quotes are verbatim; changelog quotes are the bullet text only (each bullet in the file is followed by attribution markup starting `<span`).

## 0. Version caveat (read first)

- The vendored changelog's newest entry is **0.10.0**; there is **no 0.10.1 entry**. The first heading is `## [0.10.0](https://github.com/vectorize-io/hindsight/releases/tag/v0.10.0)`. So nothing below can be attributed to 0.10.1 specifically; "0.10.0" is the latest the docs describe.
- `compose.yaml` and the feature matrix pin `hindsight-api:0.10.1-slim`, but `.scratch/atlas-pilot-review/issues/18-retains-on-minimax-by-metadata-routing.md` says: "On a throwaway local Hindsight 0.10.2 (the cluster's version)", and `docs/decisions.md` says "Verified on Hindsight 0.10.2". The repo disagrees with itself on what the cluster runs. Behaviour after 0.10.0 is not documented in this slice.

## 1. Changes 0.8.0 to 0.10.0 that bear on memory quality or retrieval

### Retain / extraction integrity

- **0.8.5 – opt-in fail-on-extraction-errors.** "Add an optional fail-on-extraction-errors mode for retain(), allowing stricter handling when fact extraction fails." The config row (`developer/configuration.md`) explains the default: "`HINDSIGHT_API_FAIL_ON_EXTRACTION_ERRORS` | When `true`, a retain operation that accumulated any fact-extraction errors is marked `failed` ... instead of `completed`, so silently-dropped facts surface as a hard failure. Default preserves existing behavior. Static, server-level. | `false`". **For Atlas:** a 10-K Item section is one retain item but many 3,000-char extraction chunks; with the default, a chunk whose extraction failed leaves the operation `completed` and Atlas only catches the all-zero case (zero-fact handling). Partial loss inside a long section is invisible today. It is a server-level switch on a shared server (hermes too), so it is the owner's call.
- **0.8.6 – zero-fact detection.** "Retain: detect and report documents that produce zero extracted facts at write time." Atlas already treats zero-fact sections (reprocess once, then `zero_fact`).
- **0.8.6 – idempotent async retries.** "Retain: async retries are now idempotent via caller-supplied operation_id." OpenAPI `RetainRequest.operation_id`: "Re-submitting with the same operation_id returns the original operation and creates no new work, so retrying after a lost or timed-out acknowledgement will not enqueue a duplicate." Atlas's `retain_batch` body is only `items` + `async` (`backend/atlas/hindsight/gateway.py`), so a lost acknowledgement leads to a second operation for the same sections (document_id upsert limits the damage, but costs a second extraction and budget).
- **0.9.2 – schema drift fails loudly.** "Retain retries and fails clearly when fact extraction encounters schema drift, instead of silently producing bad data." Relevant to MiniMax-M3 extraction.
- **0.9.2 – memory budget, not per-document limits.** "Retain now enforces a memory budget (rather than per-document limits) to prevent runaway memory usage on large inputs."
- **0.9.2 – re-retain deletes removed chunks.** "Re-retain now correctly deletes chunks that were removed when content is reduced, preventing stale data from lingering."
- **0.8.3 / 0.10.0 – oversized documents.** 0.8.3: "Fixed retain chunking so oversized documents no longer lose content when split into multiple sub-batches." 0.10.0: "Fixed retain processing for oversized items so sub-batches are rebuilt from the correct source span." and "Split append operations retain the full document body instead of only its trailing portion." Atlas's Item sections are often oversized; these were content-loss bugs before 0.10.0.
- **0.10.0 – reprocess actually re-extracts.** "Reprocessing retained content now re-runs extraction instead of leaving it unchanged." Atlas doesn't use Hindsight's reprocess route (it re-retains; `backend/atlas/retention/service.py` docstring), so unaffected, but the route was a no-op before 0.10.0.
- **0.10.0 – cross-bank collisions fixed.** "Retain operations no longer risk chunk ID collisions between banks." and 0.9.1: "Fix document statements being incorrectly shared across banks by scoping them to the correct bank." Atlas retains the same `srcv:` document IDs into the research bank and throwaway evaluation banks on the same server; before these fixes that could cross-contaminate.
- **0.10.0 – narrator.** "Stopped retain extraction from deriving its narrator from a bank's display name."
- **0.10.0 – metadata routing.** "Route retained items to an LLM chain member based on their metadata." The feature Atlas's `ATLAS_RETAIN_EXTRACTOR=minimax` relies on.
- **0.10.0 – inline attachments.** "Support images and files as first-class inline content when retaining memories." (Not used by Atlas; could matter for tables/charts in PDFs; untested.)
- **0.8.0 – attribution leak fixed.** "Fix incorrect fact attribution during retain caused by bank routing key leakage."
- **0.8.0 – no Markdown bold in prompt.** "Prevent fact extraction prompt formatting from breaking extraction by removing Markdown bold markers."

### Entities and graph

- **0.9.2 – entity resolution flag.** "Retain and update_memory can now optionally resolve entities via a dedicated flag, enabling more controlled entity handling." OpenAPI `MemoryItem` has `entities` ("Optional entities to combine with auto-extracted entities.") and `resolve_entities` ("False takes your names literally"). Atlas sends neither (`RetainItem` has content, document_id, timestamp, context, metadata, tags). Opportunity: give each section the filer's canonical name (and known counterparties) as entities so "Lumentum", "Lumentum Holdings Inc.", "LITE" collapse to one node, which is what graph expansion walks.
- **0.9.2 – fewer bad merges.** "Entity resolution no longer merges entities based only on history-matched names, reducing incorrect merges."
- **0.9.0 – in-batch dedup.** "Improve entity deduplication within a batch to avoid duplicate/variant entities being created."
- **0.10.0 – entity labels.** "Added multi-valued open-text entity labels." With FAQ's `tag: true` (below), labels become hard recall filters.
- **0.8.6 – entity browsing.** "API/UI: filter memory lists by linked entity and add an entity timeline view."
- **0.8.6 – link quality.** "Retain/linking: fix within-batch cosine similarity and adjust causal-target offsets to improve link quality."
- **0.10.0 – entity counts.** "Entity mention counts are restored correctly when mentions are removed."

### Recall

- **0.8.4 – prefer observations.** "Recall can now prefer observations to avoid returning raw facts that have been superseded." OpenAPI: drops a raw fact an observation in the results was consolidated from and backfills the slot. Atlas resolves observations two-hop anyway; using it would give the Scout's pointers more distinct sections per recall.
- **0.8.4 – per-stage scores and min_scores.** "Recall can now return structured per-stage scores and supports two-level min_scores filtering for finer result control." Atlas's pointer weight is 1/rank only.
- **0.8.4 – recency decay.** "Recall supports configurable recency decay (linear, exponential, or none) to tune ranking toward recent memory." Atlas does as-of research; recency is measured against `query_timestamp` (OpenAPI: "Used as the query-time anchor for relative temporal expressions and recency scoring"), which Atlas never sends (`recall` body: query, budget, tags, tags_match). Not documented whether decay is on by default.
- **0.9.2 – explicit temporal window.** "Recall callers can now supply an explicit temporal window instead of relying on parsed time expressions." Matrix: ranks, does not filter.
- **0.9.2 – four-digit numbers.** "Query analyzer no longer misinterprets lone four-digit numbers as years." (Questions with figures like "1600" no longer get a year window.)
- **0.9.2 – long BM25 queries.** "Recall with long BM25 queries keeps the most selective terms, improving relevance and avoiding degraded search results."
- **0.9.2 – over-budget facts.** "Recall now skips over-budget facts instead of stopping early, and avoids returning empty matches." (One huge fact no longer truncates the result list.)
- **0.9.0 – per-bank toggles.** "Add per-bank toggles to enable/disable temporal search, graph expansion, and reranking during recall." and "Allow configuring a per-budget cap on how many candidates the reranker considers during recall."
- **0.9.0 – time windows constrain graph.** "Fix recalls so `created_after`/`created_before` time windows also constrain graph expansion."
- **0.10.0 – ranking fixes.** "Fixed prioritized recall ranking so boosts are applied consistently in rank space." "Fixed full-text search ranking so each result is scored independently." "Improved recall ranking for broad date expressions by scoring the full date period." "Future-dated search items are safely handled in recency scoring."
- **0.10.0 – tags.** "Added fuzzy matching support for leaf tags within tag groups during recall." "Added a per-bank option to disable text search and use pure vector recall." (Atlas should not: BM25 is the arm for tickers, part numbers.)
- **0.8.3 – exact tags.** "Added support for exact tag matching (tags_match=exact) across the UI and client libraries."
- **0.8.4 – untagged observations.** "Recall can now accurately filter for untagged/global observations."

### Observations / consolidation

- **0.8.0 – semantic dedup.** "Add semantic deduplication of near-duplicate observations during consolidation (enabled by default, except on Oracle)." With per-version document IDs, a risk factor repeated in every 10-K/10-Q becomes one observation with many sources. `developer/index.md` says an observation carries "a proof count": that is a count of supporting memories, not of independent sources. Atlas's independence rule (Evidence Family) must not read proof counts as corroboration.
- **0.8.4 – observation vectors.** "Consolidation now keeps search vectors up-to-date for observations, improving recall quality and reliability."
- **0.8.4 – no dropped items.** "Consolidation no longer drops items when a dedup action is missing; it defaults to keeping data."
- **0.9.2 – source dates kept.** "Consolidation preserves source dates when observations are merged, improving timeline accuracy."
- **0.9.2 – partial batch failures.** "Consolidation now avoids retrying an entire batch when only some LLM calls fail, improving reliability of batch runs."
- **0.9.0 – language.** "Keep observations in the original source language during consolidation."
- **0.10.0 – deletion targets, atomic writes, stalls.** "Improved consolidation by explicitly identifying deletion targets and accounting for discarded batch responses." "Apply all memory writes from a consolidation response atomically." "Stop stalled consolidation tasks after a bounded idle period."
- **0.10.0 – scope change.** "Re-retaining a document with changed scope now invalidates outdated observations."
- **0.10.0 – imports.** "Prevented imports from creating observations that cite missing source units." (Before this, an observation could cite a `source_memory_id` that doesn't exist: Atlas's two-hop resolution would mark it broken.)
- **0.8.2 – observation scopes.** "Added support for observation scopes, including listing, filtering, visualization, and per-scope observation limits."

### Reflect

- **0.10.0 – no extrapolation.** "Reflect no longer states a specific value for a period the memories don't cover — it says the data isn't recorded instead of extrapolating a number from neighbouring periods." Matches Atlas's "Never fabricate figures" directive.
- **0.10.0 – tool failure.** "Reflection runs now fail when their retrieval tools fail, rather than continuing with incomplete results."
- **0.9.2 – no placeholder.** "Reflect runs now fail if no answer is produced, preventing placeholder memories from being stored."
- **0.9.1 – evidence under forced synthesis.** "Ensure retrieved evidence is never dropped when synthesis is forced during reflection."
- **0.8.0 – fresh mental model short-circuit.** "Avoid an unnecessary extra LLM call during reflect when a fresh mental model can be used directly." FAQ: "Reflect checks mental models first, so a fresh one can answer without descending into observations and raw facts." Atlas's reflect sends no `exclude_mental_models` (OpenAPI `ReflectRequest` has `exclude_mental_models`, `exclude_mental_model_ids`). Whether a tag-scoped reflect picks the untagged Theme status / Bottlenecks models is not documented in this slice; if it does, a reflect answer can rest on the model's prose rather than facts Atlas can resolve.

### Mental models

- **0.10.0 – delta refresh no longer overwrites.** "Mental-model and knowledge-page delta refreshes no longer overwrite stored content from what the newest batch alone says, such as replacing a running count or erasing an earlier recorded event."
- **0.10.0 – list returns metadata.** "Mental-model list responses now return metadata by default rather than full model content." Atlas reads one model at a time (`GET /mental-models/{id}`), so unaffected.
- **0.9.2 – stale citations removed.** "Mental model refresh now removes references to facts that no longer exist, preventing stale citations."
- **0.9.2 – timestamps.** "A mental model's last_refreshed_at records when the refresh finished again, not the source-data watermark, which is now carried by the new last_memory_seen_at." Atlas reads `last_refreshed_at` only (as the content's moment in `backend/atlas/discovery/service.py`), which is fine under the restored meaning.
- **0.9.2 – minimum interval; one queued refresh.** "Automatic mental-model refreshes now enforce a minimum interval to prevent overly frequent refresh cycles." "Mental models now ensure only one refresh is queued at a time, preventing refresh backlogs and duplication."
- **0.8.4 – cron.** "Mental models can now be refreshed on a cron schedule automatically."

### Shared-server fairness

- **0.10.0** "Prevented bulk ingestion in one bank from starving work in other banks." (Atlas shares the server with hermes.)

## 2. Models: what an extraction / consolidation LLM must do, recommendations, splitting

- **Output tokens.** `developer/models.md`: "Other LLM models not listed above may work with Hindsight, but they must support **at least 65,000 output tokens** to ensure reliable fact extraction." Default `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS` is 64000 and "must be greater than `HINDSIGHT_API_RETAIN_CHUNK_SIZE` (default: 3000)". MiniMax-M3's output ceiling is not documented here; `MiniMax-M3` is the `minimax` provider's default model ("| `minimax` | `MiniMax-M3` |"), which implies support, but it is not in the "Tested Models" table.
- **Smart model not needed for retain.** `developer/performance.md`: "The fact extraction process is structured and well-defined, so smaller, faster models work extremely well. Our recommended model is `gpt-oss-20b` (available via Groq and other providers)." Atlas's bake-off disagrees in degree: M2.7 paraphrased every quote and missed more facts than M3.
- **Reasoning effort.** performance.md: "If your model exposes a reasoning/thinking budget, set it low — extra reasoning tokens are pure latency for the extraction and consolidation paths." models.md on thinking models: reasoning tokens share the output cap, so a small cap truncates.
- **Splitting per operation.** models.md shows `HINDSIGHT_API_RETAIN_LLM_PROVIDER` etc.; configuration.md has `HINDSIGHT_API_CONSOLIDATION_LLM_MODEL` ("Falls back to `HINDSIGHT_API_LLM_MODEL`") and per-operation chains (`RETAIN` / `REFLECT` / `CONSOLIDATION` / `MENTAL_MODEL_REFRESH`), with "`MENTAL_MODEL_REFRESH`, which inherits the reflect chain". The docs never say a consolidation model must match the extraction model; they do not discuss mixing.
- **Metadata routing is retain-only.** configuration.md: "It is not a data boundary: the facts extracted from a routed document are stored in the same bank as everything else, and recall, reflect, consolidation, mental-model refresh and dry-run extraction all continue to use the primary LLM." Also "Nothing is stored." (Atlas records the extractor itself: `memory_document.extractor`.) And "Batch retain is not supported with this mode."
- **Per-member extra body.** configuration.md: "| `HINDSIGHT_API_LLM_<n>_EXTRA_BODY` / `_DEFAULT_HEADERS` | Per-member JSON overrides. | - |" (no fallback listed, unlike `_REASONING_EFFORT`, which falls back to the global). The bake-off found M3 thinking is disabled only through `EXTRA_BODY` behind `provider=openai`. Whether the shared server's MiniMax member (member 1, through LiteLLM) has `HINDSIGHT_API_LLM_1_EXTRA_BODY` set is not visible in this repo (home-ops PR #7180).
- **Codex as primary.** models.md, Codex section: a long-running service sharing `~/.codex/auth.json` with another Codex process can be left with a rotated refresh token; "Recall and `/health` keep working (the database and API are fine), but `/reflect` fails". Fix: dedicated `CODEX_HOME` (0.10.0: "Added separate credential directories for each Codex LLM provider configuration."). The shared server's primary is Codex, shared with hermes, the Codex CLI and LiteLLM's ChatGPT alias (`docs/decisions.md`), so consolidation, reflect and mental-model refresh all hang on that token. `openai-codex` default model: `gpt-5.4-mini`. Failover note: "there is no separate quota classifier or cooldown, so a rate-limited primary is re-tried (and fails) at the head of each request before the fallback serves it."
- **Leaderboard.** FAQ/models.md point to an external leaderboard for retain/reflect/consolidation; not vendored, not read.
- **Prompt caching.** Explicit caching only on Gemini/Vertex; MiniMax and Codex rows are blank. The bake-off nonetheless saw cached tokens (23.5k of 39.9k input).

## 3. Performance guidance for a bank of long financial filings

- **Read-optimised.** performance.md: "Hindsight is **architected from the ground up to prioritize read performance over write performance**." Retain "500ms-2000ms per batch", primary bottleneck "**LLM fact extraction**".
- **Auto-split.** performance.md: "**Automatic splitting**: Hindsight automatically splits large batches (>10,000 tokens) into optimized sub-batches" and "**Token-based**: Batching counts real tokens, not characters". configuration.md contradicts: "| `HINDSIGHT_API_RETAIN_BATCH_TOKENS` | Max characters per sub-batch for async retain auto-splitting | `10000` |".
- **Chunk size.** `HINDSIGHT_API_RETAIN_CHUNK_SIZE` "Max characters per chunk for fact extraction. Larger chunks extract fewer LLM calls but may lose context." default 3000. performance.md: "**Optimize chunks**: Larger chunks (1000-2000 tokens) are more efficient than many small ones". `RETAIN_CHUNK_BATCH_SIZE` "Each chunk produces roughly 17 facts". A 100k-char Item 7 is ~33 chunks, ~560 facts, all one document. Atlas's own section chunks are `MAX_CHUNK_CHARS = 12_000` for non-Item text.
- **Parallelism.** "For very large datasets, use multiple concurrent retention requests with different `document_id` values". Atlas already uses per-section document IDs.
- **Consolidation batch.** "Consolidation sends multiple facts to the LLM in a single call (default 8)."
- **Recall latency vs bank size.** performance.md: "**Typical query time**: 10-50ms for vector search on 100K+ facts" and "**Scalability**: Tested with millions of facts per bank". FAQ: "**Without reranking**: 50-100ms" / "**With reranking**: 200-500ms". "By default Hindsight reranks up to 300 candidates per recall". Atlas reranks remotely through LiteLLM `rerank`, so latency there is network + LiteLLM.
- **Budget.** `low` / `mid` / `high`; `high` for "Comprehensive questions, thorough analysis". Atlas recall uses `mid` by default.
- **max_tokens.** "Set `max_tokens` to control response size (default: 4096)". Atlas sends none, so each recall returns at most ~4096 tokens of memories. For pointer recall, that caps the number of sections a query can point to; not documented how many facts that is.
- **Backlog / zombies.** FAQ: zombie operations show as "a `pending_consolidation` (or similar) counter that never decreases on `/banks/{bank_id}/stats`"; cause "almost always an unstable `HINDSIGHT_API_WORKER_ID`". Atlas's local compose sets `HINDSIGHT_API_WORKER_ID: atlas-hindsight-1`; the cluster is Helm ("its StatefulSet wires the pod name automatically").

## 4. FAQ answers that correct likely misunderstandings

- **Tags are filters; metadata is not.** "Metadata is not a filter — use tags when you need recall to be scoped to a subset of documents." Metadata is "**Included in the fact extraction prompt**". Atlas's metadata today is `source_version_id`, `section_anchor`, `char_start`, `char_end`, `available_at` (+ `extractor`): mostly IDs and offsets the extractor can't use, while form, company and fiscal period are only in `context` via the title.
- **Tag filtering semantics.** FAQ: "Only memories tagged with a matching value are returned." The matrix (wins) observed that `tags_match=any` also returns untagged memories. Atlas only allows `any_strict`/`all_strict` (`backend/atlas/hindsight/models.py`), so it is safe.
- **No entity-to-entity edges.** "No. In Hindsight, entities (people, places, concepts, or classification labels) do not have direct arrows connecting them to one another." Connections come from shared entities, precomputed semantic links and causal links (`causes`, `caused_by`, `enables`, `prevents`). So Hindsight never stores "A supplies B" as an edge; supplier/customer direction exists only inside fact text. Atlas's Relationships remain the only typed, directed edges. `rag-vs-hindsight.md`'s multi-hop example ("Traverses Alice → Project Atlas → Kubernetes → outage via entity links") is about co-occurrence hops, and its depth is not documented here.
- **Entity labels as hard filters.** "Setting `tag: true` on a label group automatically writes each extracted label as a tag on the memory unit"; "This is a SQL-level filter applied before ranking, not a scoring signal". An Atlas use: a `layer` label (lasers, transceivers, ...) or a statement-kind label (capacity / customer / supply agreement) for pointer recall. Also `entities_allow_free_form: false` turns off open-world entities entirely (don't, for Atlas).
- **Mental models answer reflect first.** "Reflect checks mental models first, so a fresh one can answer without descending into observations and raw facts." Knowledge page = mental model with "Observations only by default" and "Delta refresh after each consolidation"; mental model refresh is "Off by default".
- **Don't pre-summarise.** "**Don't pre-summarize or pre-extract facts.** Hindsight does this automatically and needs the full conversation for context". Atlas's triage skips sections (not summarises), which is consistent; splitting a document into sections does remove cross-section context from each extraction.
- **Upsert replaces.** "Re-retaining with the same `id` replaces the old document and its facts". (Matrix: destructive; Atlas uses per-version IDs.)
- **Mission/directives/disposition affect reflect only.** `developer/index.md`: "These settings only affect the `reflect` operation, not `recall`." (retain_mission steers extraction separately; configuration.md.)
- **Stale observations.** `developer/index.md`: "when newer memories have been retained but not yet consolidated, `reflect` treats the affected observations as stale and verifies them against raw facts before relying on them". Recall has no such guard: a pointer from an observation may be stale.
- **Observations quote sources.** "Each observation references the source memories (with exact quotes) that support it, plus a proof count".

## 5. Multilingual and memory defense (low relevance)

- Default embedder and reranker are English-only; the `native` BM25 uses PostgreSQL's English dictionary. Atlas uses `qwen3-embedding-0.6b` and LiteLLM `rerank` and retains English only, so this matters only if French (AMF) or Chinese (HKEX) documents are ever retained: then pgroonga and a multilingual reranker per `multilingual.md`.
- Memory Defense is "disabled by default"; its `credit_card` pattern ("13 to 19 digits with regular separators") could redact long digit strings in filings if a policy were ever enabled on the research bank.

## Not covered

- I did not read the changelog past the 0.8.0 entry, nor configuration.md beyond the retain and multi-LLM rows quoted, nor the external Model Leaderboard.
- No 0.10.1 (or 0.10.2) changelog entry exists in the vendored docs.
- Not settled: whether recency decay is on by default; whether a tag-scoped reflect uses untagged mental models; how many facts `max_tokens=4096` holds; whether indexed chain members inherit the global `EXTRA_BODY`; MiniMax-M3's output-token ceiling.
