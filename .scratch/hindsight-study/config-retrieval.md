# Hindsight 0.10.1 configuration: retrieval and reasoning (reader notes)

Slice: `.agents/skills/hindsight-docs/references/developer/configuration.md`, read through the lens of what decides what recall and reflect return. Cross-checked against `docs/hindsight-feature-matrix.md`, the recorded bank-template schema `spikes/hindsight/recordings/bank_templates/01-schema.json` (the authoritative list of what a bank template can set in 0.10.1), Atlas's `configs/hindsight/bank-template.json`, `backend/atlas/hindsight/gateway.py`, `backend/atlas/research/service.py`, `compose.yaml` (the local Hindsight Atlas runs; the cluster's settings are not in this repo) and `docs/decisions.md`.

Scope labels: **server** = env var, process-wide, needs a restart, not settable by Atlas on a shared server; **bank** = hierarchical, settable in the bank template / `PATCH .../config` (confirmed by presence in the recorded `BankTemplateConfig` schema); **model** = per mental model `trigger`; **request** = per call.

The config page's own security model says retrieval tuning is static: "Performance tuning: `llm_max_concurrent`, `llm_timeout`, retrieval settings, optimization flags" (Static Fields). The recorded `BankTemplateConfig` schema confirms which retrieval knobs are nevertheless per bank: `enable_text_search`, `enable_temporal_retrieval`, `enable_graph_retrieval`, `enable_reranking`, `recall_budget_*`, `recall_include_chunks`, `recall_max_tokens`, `recall_chunks_max_tokens`, `reflect_source_facts_max_tokens`, `reflect_default_options`, `mental_model_min_refresh_interval_seconds`, `consolidation_llm_batch_size`, `consolidation_llm_parallelism`, `consolidation_max_memories_per_round`, `consolidation_source_facts_max_tokens[_per_observation]`, `max_observations_per_scope`, `observation_scope_limits`, `enable_auto_consolidation`, dispositions, missions. Everything else below is server-only.

---

## 1. The recall pipeline (what the docs say)

"Recall runs four retrieval arms (semantic, BM25, graph, temporal) and then reranks the fused candidates with a cross-encoder." Semantic always runs. Fusion is RRF; then a reranker cap; then rerank; then recency and strategy-boost adjustments.

### 1.1 Budget (request: `budget`; bank: `recall_budget_*`)

- `budget` = `low`/`mid`/`high`, default `mid`. It maps to an integer `thinking_budget` "used by every retrieval method (semantic, BM25, graph, temporal)".
- `HINDSIGHT_API_RECALL_BUDGET_FUNCTION` default `fixed`: "`thinking_budget = recall_budget_fixed_<level>` (independent of `max_tokens`)".
- Fixed: low `100`, mid `300`, high `1000` — "Items per retrieval method per fact type when `budget=mid` and function is `fixed`. | `300`".
- Adaptive (opt-in): `round(max_tokens * ratio)` with ratios 0.025 / 0.075 / 0.25, clamped to [20, 2000].
- All per bank (in `BankTemplateConfig`).
- What budget does NOT change: the final number of results returned (that is the response `max_tokens`, which is not in this page; the recall API page owns its default). Budget is candidate breadth per arm per fact type, i.e. how deep each arm digs before fusion.
- Reranker candidate cap can be set per budget level: `HINDSIGHT_API_RERANKER_MAX_CANDIDATES_{LOW,MID,HIGH}` (server; `0` = fall back to `RERANKER_MAX_CANDIDATES`).

### 1.2 Semantic arm
- `HINDSIGHT_API_SEMANTIC_MIN_SIMILARITY` default `0.3` (server). Candidates below are not returned by the arm.
- Five embedding gates (semantic `0.3`, graph seed `0.3`, temporal `0.1`, semantic-link creation `0.7`, observation dedup `0.97`): "Their defaults preserve the behavior calibrated for `BAAI/bge-small-en-v1.5`." and the page says to recalibrate all five when changing embedding model.
- Atlas's local compose uses `HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL: qwen3-embedding-0.6b` ("the same model and dimension as the cluster release"). So all five thresholds are uncalibrated for Atlas's embedding model. Nobody has measured the cosine distribution of qwen3-embedding-0.6b on Atlas's facts. Effect: if qwen3 similarities run high, `0.3` admits near-everything (BM25/semantic noise); if low, relevant memories are cut before fusion; `0.7` semantic-link density and `0.97` dedup shift too.

### 1.3 BM25 arm
- `HINDSIGHT_API_TEXT_SEARCH_EXTENSION` default `native` (Postgres tsvector + GIN), `..._NATIVE_LANGUAGE` default `english` (server).
- `HINDSIGHT_API_BM25_MAX_QUERY_TERMS` default `16`: "because native ranking has no IDF and re-ranks every match"; over the cap, "the most **selective** terms are kept" (`BM25_SELECTIVE_TERMS` default `true`, from `pg_stats`).
- `HINDSIGHT_API_BM25_MIN_SCORE` default `0`.
- Per bank: `enable_text_search` (default true).
- Relevance: native BM25 has no IDF, so a query term like "optical" that occurs in most of a photonics bank's facts contributes as much as "InP substrate". Atlas's Scout queries and bear-checklist items are natural-language sentences; anything over 16 terms is trimmed to the rarest 16.

### 1.4 Graph arm
- `HINDSIGHT_API_GRAPH_RETRIEVER` default `link_expansion`: "Fast graph expansion from semantic seeds via entity co-occurrence, semantic kNN, and causal links. Target latency under 100ms."
- `HINDSIGHT_API_GRAPH_SEED_MIN_SIMILARITY` `0.3` (seeds must be semantically similar to the query).
- `HINDSIGHT_API_LINK_EXPANSION_PER_ENTITY_LIMIT` `200` (fan-out per entity), `..._TIMEOUT` `10` s.
- Semantic links are created at retain at cosine ≥ `HINDSIGHT_API_SEMANTIC_LINK_MIN_SIMILARITY` `0.7` — "This directly controls semantic graph density." Not retroactive.
- Causal links: `HINDSIGHT_API_RETAIN_EXTRACT_CAUSAL_LINKS` default `true` (server).
- Entity co-occurrence depends on entity resolution at retain (two-stage; trigram 0.15 candidate gate, merge score ≥ 0.6, `ENTITY_MERGE_MIN_SIMILARITY` 0.3). Entity labels (`entity_labels`, `entities_allow_free_form`) are per bank and Atlas's template sets none.
- Per bank: `enable_graph_retrieval` (default true).
- Relevance for multi-hop supply chain: the graph arm is the only arm that can surface a memory about company B from a query that names company A (via co-occurring entity "B" in A's facts). Its seeds are the semantic hits, so it is only as good as entity resolution: e.g. "Lumentum", "Lumentum Holdings", "LITE" must resolve to one entity. Not documented: how a graph hit's score enters RRF beyond being one of four ranked lists.
- With tag scoping (`any_strict` by company/theme), the graph arm can only reach memories inside the scope — a theme-wide scope is what lets multi-hop work at all. Whether graph expansion is applied before or after the tag filter is not documented in this page.

### 1.5 Temporal arm
- `HINDSIGHT_API_TEMPORAL_SEMANTIC_MIN_SIMILARITY` `0.1`. `HINDSIGHT_API_QUERY_ANALYZER_LANGUAGES` default empty (auto-detect; "auto-detection dominates recall's CPU cost").
- Per bank: `enable_temporal_retrieval` — "`false` also skips the date-aware query analysis that feeds it".
- The arm fires on a temporal constraint parsed out of the query text ("FY2026", "last quarter"). Feature matrix: a `query_timestamp`/`temporal_window` is "not a hard filter" (2024 window returned 2026 results ranked first). So the temporal arm adds candidates; it never removes them. For as-of research, Atlas must keep its own `available_at` cutoff (it does, for pointers).

### 1.6 Fusion and reranker
- `HINDSIGHT_API_RERANKER_MAX_CANDIDATES` `300`: "Max candidates to rerank per recall (RRF pre-filters the rest)". `HINDSIGHT_API_RECALL_MAX_CANDIDATES_PER_SOURCE` `0` (no per-arm cap).
- `HINDSIGHT_API_RECALL_STRATEGY_BOOSTS` (server, default empty): e.g. `graph:high`; "The boost is applied in two places: before the reranker cap (so favoured candidates survive the `HINDSIGHT_API_RERANKER_MAX_CANDIDATES` budget) and after reranking (to nudge them up the final order)". Rank-space divisors low 2, medium 4, high 8.
- Reranker: `HINDSIGHT_API_RERANKER_PROVIDER` default `local` (cross-encoder ms-marco-MiniLM-L-6-v2). Atlas's compose uses `litellm` with model `rerank` (the slim image has no local cross-encoder). `HINDSIGHT_API_RERANKER_LITELLM_MAX_TOKENS_PER_DOC` unset = no truncation.
- Failover: unindexed = member 0; `HINDSIGHT_API_RERANKER_<n>_PROVIDER`; "Ending the chain with `rrf` makes recall **fail open**: results come back in the order the retrieval stages produced". Without it, a reranker outage fails recall. Atlas's compose has no fallback. Retries: `RERANKER_MAX_RETRIES` 3, `RETRY_BUDGET` 10 s.
- Scores across providers are not comparable ("a request served by a fallback member can score differently").
- Per bank: `enable_reranking` — "`false` returns the RRF-fused ordering directly — faster, but less precise."

### 1.7 Recency
- `HINDSIGHT_API_RECENCY_DECAY_FUNCTION` default `linear` (server): "`linear` (default) decays in a straight line from full freshness (today) to a floor reached at `HINDSIGHT_API_RECENCY_DECAY_LINEAR_WINDOW_DAYS`." Window default `365`. `exponential` (half-life `90`), `none`.
- Applied "during reranking" as "a small freshness adjustment to its final rank". Not documented: which timestamp is "a memory's age" (occurred_start, mentioned_at or created_at), how big the adjustment is relative to reranker scores, and whether `query_timestamp` replaces "today".
- Relevance: (a) a theme-wide recall used as a reading index will rank facts from the latest 10-Q slightly above the same claim from a two-year-old 10-K — mostly what Atlas wants; (b) for replay banks at a past cutoff, "today" is the real today, so if age is mentioned_at/created_at (all replayed facts are created on the replay day) recency is flat; if occurred_start, older filings are penalised relative to the cutoff. Undocumented; affects replay comparability only at the margin.

### 1.8 Query length and admission
- `HINDSIGHT_API_RECALL_MAX_QUERY_TOKENS` `500`: "API requests exceeding this limit are rejected with HTTP 400"; internal recalls (reflect, consolidation) truncate instead.
- Admission lanes: recall waits up to `30000` ms, reflect `5000` ms, retain `2000` ms (sync only) before "503 + `Retry-After`". `ADMISSION_*_MAX_IN_FLIGHT` `0` = derived from CPU quota.
- `HINDSIGHT_API_RECALL_MAX_CONCURRENT` 32 per worker; `RECALL_CONNECTION_BUDGET` 4.
- `HINDSIGHT_API_TOKENIZER_ENCODING` `o200k_base` (server): every token budget is counted with it.

### 1.9 Observations vs world facts vs experiences in recall
- This page does not document how recall mixes fact types in its output or whether budgets are split per type beyond "Items per retrieval method per fact type". So each arm retrieves up to `thinking_budget` items *per fact type* (world, experience, observation), and they compete after fusion. The recall request's `types` filter is not in this page.
- Atlas's gateway sends neither `types` nor `max_tokens` nor `include`: `body: dict[str, JsonValue] = {"query": query, "budget": budget, **_scope_fields(scope)}`. Observations therefore compete with world facts in the pointer ranking; Atlas resolves an observation through `source_memory_ids`, so an observation can point to several sections at one rank.

## 2. Reflect

### 2.1 Loop limits (server unless noted)
- `HINDSIGHT_API_REFLECT_MAX_ITERATIONS` `10`: "Max tool call iterations before forcing a response".
- `HINDSIGHT_API_REFLECT_MAX_CONTEXT_TOKENS` `100000`: forces final synthesis.
- `HINDSIGHT_API_REFLECT_WALL_TIMEOUT` `300` s → HTTP 504. Atlas's gateway `DEFAULT_REQUEST_TIMEOUT = 300.0` equals it exactly, so a slow reflect may race the client timeout and the 504.
- `HINDSIGHT_API_REFLECT_LLM_TIMEOUT` default 30 s per call (Atlas compose: 300).
- `HINDSIGHT_API_REFLECT_MAX_COMPLETION_TOKENS` unset = uncapped; visible length governed by the reflect/mental-model `max_tokens` "via a prompt directive plus a post-hoc rewrite".
- `HINDSIGHT_API_LLM_TEMPERATURE_REFLECT` default `0.9` (server) — high; the daily mental models and reflect syntheses are sampled at 0.9. Consolidation is `0.0`, retain `0.1`.

### 2.2 What reflect reads (tools)
From config page + the recorded trigger schema: tools include `search_observations`, `recall`, `search_mental_models` and `expand` (fetches a memory's source chunk/document; disabled if document text is not stored).
- Internal recall knobs (bank; and per mental model via `trigger.include_chunks`, `trigger.recall_max_tokens`, `trigger.recall_chunks_max_tokens`): `HINDSIGHT_API_RECALL_INCLUDE_CHUNKS` `true`, `HINDSIGHT_API_RECALL_MAX_TOKENS` `2048`, `HINDSIGHT_API_RECALL_CHUNKS_MAX_TOKENS` `1000`. "an explicit ask from the model wins".
- `HINDSIGHT_API_REFLECT_SOURCE_FACTS_MAX_TOKENS` default `-1`: "`-1` disables source facts (default), `0` enables with no limit, `>0` enables with a token budget." — so by default `search_observations` returns observation text without the world facts behind them. Per bank (`reflect_source_facts_max_tokens`).
- `HINDSIGHT_API_REFLECT_DEFAULT_OPTIONS` (bank `reflect_default_options`): `reflect_search_observations_max_tokens` (schema: "None means use the shipped default (5000)") and `reflect_search_observations_include_entities` (entities "can be more than half the serialized tool payload").
- Disposition (bank): skepticism, literalism, empathy, 1–5, default 3. Atlas sets skepticism 4, literalism 4.
- `HINDSIGHT_API_REFLECT_MISSION` (bank `reflect_mission`).
- Relevance: chunk text in reflect context is what the feature matrix flags as unresolvable ("Chunk-sourced reflect content (no memory ID) cannot be resolved this way"). Atlas can trade chunk budget for fact budget per bank or per model (e.g. `include_chunks: false`, `recall_max_tokens: 4096`) to make syntheses more resolvable; or enable source facts so observations come with their grounding.

### 2.3 Mental models
- Refresh drives "the same agent as interactive reflect, so by default it uses the reflect LLM".
- `HINDSIGHT_API_MENTAL_MODEL_MIN_REFRESH_INTERVAL_SECONDS` `0` (bank `mental_model_min_refresh_interval_seconds`; model `trigger.min_refresh_interval_seconds` wins). Parked, folded triggers; explicit refreshes ignore it.
- `HINDSIGHT_API_MENTAL_MODEL_REFRESH_TICK_SECONDS` `300`: cron check cadence; "A due model is refreshed only when it is stale (new memories in its scope since the last refresh)."
- History: `ENABLE_MENTAL_MODEL_HISTORY` true, `MENTAL_MODEL_HISTORY_MAX_ENTRIES` 50 — after 50 refreshes old content is deleted on Hindsight's side (Atlas keeps its own refresh records).
- Trigger fields from the recorded schema (all per model): `mode` (`full` default | `delta`), `refresh_after_consolidation` (schema default `false`), `refresh_cron`, `min_refresh_interval_seconds`, `fact_types`, `exclude_mental_models` (default `false`), `exclude_mental_model_ids`, `tags_match`, `tag_groups`, `include_chunks`, `recall_max_tokens`, `recall_chunks_max_tokens`, `response_schema`, `keep_trace` (default false; "This is the only way to diagnose a cron- or consolidation-driven refresh"), `reflect_search_observations_*`.
- Atlas's template sets only `refresh_after_consolidation: false`, `refresh_cron: "0 6 * * *"`, `min_refresh_interval_seconds: 43200` and `max_tokens: 2048`. Consequences: (1) `exclude_mental_models` is false, so Theme status may read Bottlenecks' content and vice versa through `search_mental_models` — a synthesis feeding a synthesis, and citations to a mental model are not resolvable to a Source Version; (2) chunks on (unresolvable content); (3) no `keep_trace`, so Atlas cannot see how many facts retrieval returned vs used; (4) `mode: full` regenerates from scratch at temperature 0.9 daily.
- Atlas's refresh job handles both its own explicit refresh and Hindsight's cron: `refresh.py` skips "a model refreshed inside its minimum interval ... whether Atlas asked for that one or Hindsight ran it on its own `refresh_cron`" and models Hindsight reports not stale. Fine.

## 3. LLM selection and routing per operation (server-only)

- Per-op groups: `RETAIN_`, `REFLECT_`, `CONSOLIDATION_`, `MENTAL_MODEL_REFRESH_` `LLM_{PROVIDER,MODEL,BASE_URL,MAX_CONCURRENT,MAX_RETRIES,TIMEOUT,REASONING_EFFORT,EXTRA_BODY,...}`. Refresh falls back to reflect, which falls back to global. "Recall: Does not use LLM (pure retrieval)".
- Multi-LLM chains `HINDSIGHT_API_LLM_<n>_*` + `HINDSIGHT_API_LLM_STRATEGY` (`failover`, `round-robin` with weights, `metadata` retain-only). Per-op chains: "Each operation can define its own members + strategy with the `RETAIN` / `REFLECT` / `CONSOLIDATION` / `MENTAL_MODEL_REFRESH` prefix"; a per-op slot without members inherits the global chain, except `MENTAL_MODEL_REFRESH` inherits reflect's.
- Metadata routing: "recall, reflect, consolidation, mental-model refresh and dry-run extraction all continue to use the primary LLM". Atlas knows (decisions.md: "So consolidation of the facts MiniMax extracted still spends the ChatGPT quota, uncounted by Atlas as before."). The owner could set a `CONSOLIDATION_LLM_*` group on the shared server to move consolidation off the 40-ops budget; Atlas cannot do this itself.
- Concurrency: `HINDSIGHT_API_LLM_MAX_CONCURRENT` default `32`; per-op caps compose with it; "process-global semaphores read from the environment once at startup". The refresh cap is "separate from the reflect cap". Atlas compose: global 2, retain 2.

## 4. Consolidation (what decides observation quality and cost)

- `HINDSIGHT_API_ENABLE_OBSERVATIONS` true; `ENABLE_AUTO_CONSOLIDATION` true (bank) — runs after every retain/delete/update.
- `HINDSIGHT_API_CONSOLIDATION_LLM_BATCH_SIZE` `8` (bank): "Number of facts sent to the LLM in a single consolidation call. Higher values reduce LLM calls and improve throughput at the cost of larger prompts."
- `CONSOLIDATION_MAX_MEMORIES_PER_ROUND` `100` (bank): round yields slot; "Mental model refreshes only run on the final round."
- `CONSOLIDATION_RECALL_BUDGET` `low`; `CONSOLIDATION_MAX_TOKENS` `1024` (recall for related observations).
- `CONSOLIDATION_DEDUP_THRESHOLD` `0.97`: each new/updated observation near an existing one triggers "a focused 1-by-1 LLM \"merge or keep\" call" — extra LLM calls, threshold calibrated on bge-small.
- `CONSOLIDATION_MAX_ATTEMPTS` 3 × (LLM_MAX_RETRIES+1); quota exhaustion reschedules the job rather than retrying.
- `CONSOLIDATION_LLM_PARALLELISM` 4 tag groups (bank).
- `CONSOLIDATION_SOURCE_FACTS_MAX_TOKENS` 4096, per observation 256 (bank).
- `MAX_OBSERVATIONS_PER_SCOPE` -1; `OBSERVATION_SCOPE_LIMITS` (bank).
- `CONSOLIDATION_WALL_TIMEOUT` 7200 s without progress; `CONSOLIDATION_RECONCILE_INTERVAL_SECONDS` 300.
- Budget arithmetic for the 40-ops/5h window: a retained section producing ~N facts costs about ceil(N/8) consolidation calls plus dedup calls. Raising `consolidation_llm_batch_size` per bank (e.g. 16–24) roughly halves/thirds that, at prompt-size cost. Whether the shared server's 40-op budget counts LLM calls or Hindsight operations is an Atlas-side question (Atlas counts "Hindsight operations submitted").

## 5. Workers and draining (server)

- `HINDSIGHT_API_WORKER_MAX_SLOTS` `10`; `WORKER_CONSOLIDATION_RESERVED_SLOTS` `2` floor; others 0; reservations are floors, not caps. "Consolidation's bank-serialization constraint (no two consolidation tasks for the same bank concurrently)". `WORKER_CONSOLIDATION_BANK_PRIORITY` pattern priorities.
- `WORKER_POLL_INTERVAL_MS` 500, `WORKER_MAX_RETRIES` 3, `WORKER_TASK_RETRY_BACKOFF_SECONDS` 60, `BACKPRESSURE_DEFER_SECONDS` 120.
- `RETAIN_WALL_TIMEOUT` 3600; `RETAIN_MAX_CONCURRENT` 4 (DB phases).
- Atlas compose: `WORKER_MAX_SLOTS: "4"` (feature matrix: ≤ 2 starves retain).
- Relevance: one consolidation per bank at a time, so a burst of Atlas retains drains serially through the research bank's consolidation regardless of slots; the reading index (observations) lags retains until consolidation drains. Pointers taken during a backlog see world facts but not the new observations.

## 6. Other settings touching retrieval quality
- `HINDSIGHT_API_STORE_DOCUMENT_TEXT` true (server per page note, though schema lists `store_document_text` as bank): with false, reflect's `expand` tool and recall chunks vanish. Atlas keeps default.
- `HINDSIGHT_API_LLM_STRICT_SCHEMA[_REFLECT]`, `LLM_REASONING_EFFORT`: per server.
- `HINDSIGHT_API_LLM_TRACE_*`: per-bank LLM request log, 1-day retention by default — Atlas's way to see consolidation spend.

## 7. What bears on Atlas's use

1. **Reading index rank order** = RRF over four arms → top 300 reranked by LiteLLM `rerank` → linear 365-day recency nudge → (no strategy boosts). Atlas controls only `budget`, tags and (unused) `max_tokens`/`types`. Per bank it could switch arms off or set `recall_budget_*`. Server-only: boosts, recency, thresholds, reranker chain.
2. **Uncalibrated thresholds** for qwen3-embedding-0.6b (all five gates). Highest-leverage unknown; measurable read-only by inspecting recall traces / similarity on a sample of Atlas queries.
3. **No reranker fail-open**: a LiteLLM rerank outage fails every recall (pointer recalls fail → Scout continues with fewer pointers). Owner could add `HINDSIGHT_API_RERANKER_1_PROVIDER=rrf`.
4. **Native BM25, no IDF, 16-term cap**: favour short, specific queries.
5. **Graph arm for multi-hop** depends on entity resolution; no entity labels; `RECALL_STRATEGY_BOOSTS=graph:low` (server) would protect graph candidates from the reranker cap.
6. **Reflect / mental models**: chunks on (unresolvable), source facts off, mental models can read each other, temperature 0.9, no trace. All but temperature fixable per bank/model in the template.
7. **Budget**: consolidation runs on the primary LLM; `consolidation_llm_batch_size` per bank is Atlas's own lever; dedup calls add more.

## Not covered / not settled
- Recall API defaults (`max_tokens`, `types`, `include.chunks`, `trace`) are on the recall API page, not here.
- How recency's "age" is computed, recency magnitude, and whether `query_timestamp` shifts "today": not documented here.
- Exact RRF constant and per-arm weighting: not documented.
- Whether tag filters apply before graph expansion: not documented.
- Reflect tool list taken from the trigger schema descriptions and the `STORE_DOCUMENT_TEXT` note, not from a dedicated reflect page (owned by the lead).
- Skimmed, not studied: database, vector extensions, embeddings provider list, file processing/storage, MCP, auth, observability, webhooks, control plane UI.
- Cluster Hindsight env is not in this repo; only `compose.yaml` (local) was checked.
