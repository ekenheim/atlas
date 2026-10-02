# Hindsight 0.10.1 configuration, read for INTAKE (what a retain turns into)

Reader: config-intake slice. Source: `.agents/skills/hindsight-docs/references/developer/configuration.md` (all 3,039 lines read; provider-example blocks, reranker-chain, auth, egress, file storage, observability and control-plane sections skimmed and grepped for intake terms only), checked against `docs/hindsight-feature-matrix.md`, `spikes/hindsight/recordings/` and Atlas code. No network, no CLI.

Scope legend: **server** = env var only, restart needed; **bank** = hierarchical, settable via bank config API and the bank template (`manifest.bank`); **strategy** = can sit inside a named `retain_strategies` entry; **request** = per retain call / per item.

## 1. What Atlas's bank resolves to today (recording)

`spikes/hindsight/recordings/research_template/03-imported-config.json` (the template applied to a fresh bank) shows the resolved intake config: `retain_extraction_mode: "concise"`, `retain_chunk_size: 3000`, `retain_structured_chunk_size: null`, `entity_labels: null`, `entities_allow_free_form: true`, `retain_strategies: null`, `retain_default_strategy: null`, `enable_auto_consolidation: true`, `consolidation_llm_batch_size: 8`, `consolidation_max_memories_per_round: 100`, `consolidation_source_facts_max_tokens: 4096` / `_per_observation: 256`, `max_observations_per_scope: -1`, `store_document_text: true`. Overrides set by Atlas: only `retain_mission`, `reflect_mission`, `enable_observations`, `observations_mission`, `disposition_literalism`, `disposition_skepticism`.

Atlas's retain item (`backend/atlas/retention/service.py`, `retain_item`): `content` = the section's parsed text, `document_id` per version+section, `timestamp` = `available_at`, `context` = `"{title}: {heading or anchor}"`, `metadata` (source_version_id, section_anchor, char offsets, available_at, optional `extractor`), `tags`. The gateway posts `{"items": [...], "async": true}` with no `strategy`, no `entities`, no `update_mode`, no `observation_scopes` (`backend/atlas/hindsight/gateway.py`). The sectioner cuts SEC filings at Item headings (sections can be tens of thousands of characters) and everything else into chunks of at most `MAX_CHUNK_CHARS = 12_000` (`backend/atlas/retention/sections.py`).

Local/spike server env (`compose.yaml`): LLM via LiteLLM `openai` provider, `HINDSIGHT_API_EMBEDDINGS_PROVIDER: openai` with `qwen3-embedding-0.6b` at 1024 dims, reranker LiteLLM `rerank`, `LLM_MAX_CONCURRENT 2`, `WORKER_MAX_SLOTS 4`. No `EMBEDDINGS_QUERY_PREFIX`, no entity thresholds, no causal-link or fail-on-error settings. The cluster's own env lives in home-ops (not read).

## 2. Extraction modes and instructions

| Setting | Default | Scope | What it does |
|---|---|---|---|
| `HINDSIGHT_API_RETAIN_EXTRACTION_MODE` / `retain_extraction_mode` | `concise` | server, bank, strategy | `concise`, `verbose`, `verbatim`, `chunks`, `custom` |
| `HINDSIGHT_API_RETAIN_MISSION` / `retain_mission` | unset | server, bank, strategy | "injected into the extraction prompt alongside the built-in rules — it narrows focus without replacing the underlying logic"; works with every mode except `chunks` (ignored there) |
| `HINDSIGHT_API_RETAIN_CUSTOM_INSTRUCTIONS` / `retain_custom_instructions` | unset | server, bank, strategy | only in `custom` mode; "Replaces the built-in selectivity rules entirely. The structural parts of the prompt (output format, temporal handling, coreference resolution) remain intact" |

Mode semantics (doc, "Customizing retain: when to use what"):
- `concise`: default.
- `verbose`: "richer facts with full context, relationships, and verbosity. Slower and uses more tokens".
- `verbatim`: "Each chunk is stored as a single memory unit with its original text preserved exactly — no summarization or rewriting. The LLM still runs to extract entities, temporal information, and location".
- `chunks`: no LLM; "No entity extraction, no temporal indexing — only embeddings"; "User-provided entities passed via `RetainContent.entities` are the sole source of entity data."
- `custom`: as above.

Relevance to Atlas: Atlas never quotes memory text (memory is an index to sections), so what matters is whether the facts point to the right section and whether entities/links make multi-hop recall work. `concise` + the mission is the measured baseline (`docs/research/extraction-bakeoff.md`, not re-read here). `verbatim` would make each 3000-char chunk one memory whose text *is* the filing text (pointers would then lead to chunk-sized text, entities still extracted) — a candidate for exhibits/transcripts where facts lose figures, testable only by experiment. `verbose` may keep supplier/customer qualifiers that `concise` drops.

## 3. Retain strategies (per-call extraction profiles)

"Named strategies let you ingest different content types into the same bank using different extraction settings. A strategy is a set of hierarchical field overrides applied on top of the resolved bank config." Any hierarchical field can be overridden, "including `retain_extraction_mode`, `retain_chunk_size`, `retain_structured_chunk_size`, `entity_labels`, `entities_allow_free_form`, `retain_mission`, etc." Configured per bank (`retain_strategies`, `retain_default_strategy`; also present in the template schema recording `bank_templates/01-schema.json`); chosen per retain **call** via `strategy` (`client.retain(..., strategy="documents")`). `HINDSIGHT_API_RETAIN_DEFAULT_STRATEGY` is the server-wide default name.

Granularity: the doc shows `strategy` on the call, not per item. So Atlas would have to batch by document type (10-K/10-Q sections vs 8-K exhibits vs TradingView transcripts) to use different missions/modes. Atlas's batches are per Source Version, so this is a natural fit. Atlas uses none today.

## 4. Chunking

| Setting | Default | Scope | Notes |
|---|---|---|---|
| `HINDSIGHT_API_RETAIN_CHUNK_SIZE` / `retain_chunk_size` | `3000` (characters) | server, bank, strategy | "Larger chunks extract fewer LLM calls but may lose context." One extraction LLM call per chunk |
| `HINDSIGHT_API_RETAIN_STRUCTURED_CHUNK_SIZE` | unset (= chunk size) | server, bank, strategy | "Max characters for a single JSONL line or conversation turn to keep whole" |
| `HINDSIGHT_API_RETAIN_CHUNK_BATCH_SIZE` | `100` | server, bank | "Each chunk produces roughly 17 facts, so the default 100 chunks ≈ 1700 facts per batch." |
| `HINDSIGHT_API_RETAIN_BATCH_TOKENS` | `10000` | server | "Max characters per sub-batch for async retain auto-splitting" |
| `HINDSIGHT_API_RETAIN_SUBBATCH_CONCURRENCY` | `1` | server | sub-batches of one document at a time |
| `HINDSIGHT_API_RETAIN_MEMORY_BUDGET_MB` | `128` | server | backpressure on extracted-but-unwritten state |
| `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS` | `64000` | server | extraction call output cap |
| `HINDSIGHT_API_TOKENIZER_ENCODING` | `o200k_base` | server | "Vocabulary used for every token count and chunk boundary" |

Not documented in this file: chunk overlap (no overlap setting exists here), how a chunk boundary is chosen (sentence/paragraph), or whether `context` is repeated into every chunk's prompt. A 10-K Item 1A of ~60k characters becomes ~20 extraction calls of 3000 characters each; Atlas's `context` ("title: heading") is the only document-level framing the per-chunk call has, as far as this page says.

## 5. Entity extraction and resolution

- `entity_labels` (controlled vocabulary, `LabelGroup` items) and `entities_allow_free_form` (default `true`): "configured per bank via the [bank config API] ..., not as global environment variables"; also strategy-overridable; both appear in the template schema recording. Label details are in `retain.md` (not my slice).
- Per item: `RetainContent.entities` (user-provided entities) and `resolve_entities: false` (pass names yourself, skip fuzzy matching) — referenced from this page, specified in `api/retain.md` (not read).
- `HINDSIGHT_API_RETAIN_ENTITY_LOOKUP` (`trigram` | `full`, server): changes "which names can merge at all".
- Resolution, two stages: stage 1 candidates by trigram ≥ `HINDSIGHT_API_ENTITY_TRGM_SIMILARITY_THRESHOLD` (0.15), at most `..._ENTITY_RESOLUTION_MAX_CANDIDATES` (200); stage 2 score ≥ 0.6 from name similarity (SequenceMatcher, ≤ 0.5), co-occurring entities (≤ 0.3) and temporal proximity (≤ 0.2: "How close the fact's date is to the candidate's `last_seen`, decaying linearly to zero at 7 days"). Floor `HINDSIGHT_API_ENTITY_MERGE_MIN_SIMILARITY` 0.3; word-by-word agreement check for multi-word names; identical trigram sets reused outright; label entities "resolve by exact match only". In-batch fold `HINDSIGHT_API_ENTITY_INTRABATCH_MERGE_SIMILARITY` 0.5. All thresholds are server env (listed under the DB connection pool); the page does not say they are per bank.
- Implications for Atlas: filings retained months apart get no temporal-proximity score (7-day decay), so a name variant must win on name similarity + co-occurrence alone (max 0.8, needs 0.6). "Coherent" vs "Coherent Corp." vs "II-VI" will not merge on name; "Lumentum" vs "Lumentum Holdings Inc." likely will. Atlas already holds canonical company identities (CIK/LEI, slug); passing them as item `entities` or as labels would make the entity graph (which `link_expansion` traverses) follow Atlas's identity rather than fuzzy matching.

## 6. Links between facts

- `HINDSIGHT_API_RETAIN_EXTRACT_CAUSAL_LINKS` default `true`, server (not in the template schema). Graph retrieval: "`link_expansion` (default): Fast graph expansion from semantic seeds via entity co-occurrence, semantic kNN, and causal links."
- `HINDSIGHT_API_SEMANTIC_LINK_MIN_SIMILARITY` 0.7, server: "Minimum cosine similarity for creating semantic links during normal retain ... This directly controls semantic graph density." Not retroactive.
- Entity links come from entity resolution (above). Nothing here documents a supplier/customer typed relation between entities.

## 7. Temporal fields

- `HINDSIGHT_API_RETAIN_OPTIONAL_FACT_DIMENSIONS` (server, default `false`): facts carry `when`/`where`/`who`/`why`; off means the model must write something ("N/A" placeholder per the doc), and under strict schema "the nearest plausible one is a date the text stated about something else".
- `HINDSIGHT_API_LLM_SUPPORTS_STRING_PATTERN` (server, `false`): constrains `occurred_start`/`occurred_end` to ISO timestamps when the backend accepts `pattern`.
- Recording `upsert/09-get-document.json`: Atlas's `timestamp` is stored as `retain_params.event_date`. The meaning of `occurred_*` vs `mentioned_at` is in `retain.md` (not my slice).
- Recall-side but intake-relevant: `HINDSIGHT_API_RECENCY_DECAY_FUNCTION` `linear` over 365 days (server) ages memories by their date, so the timestamp Atlas sends shapes ranking of old filings.

## 8. Metadata routing of the extraction model

`HINDSIGHT_API_LLM_STRATEGY={"mode":"metadata","routes":[...]}` (server; per-operation via `HINDSIGHT_API_RETAIN_LLM_STRATEGY`): per item, first matching route wins, values compared as strings, "Nothing is stored ... changing the routes changes only future retains. Reprocessing a document replays its original metadata". Not a data boundary: "recall, reflect, consolidation, mental-model refresh and dry-run extraction all continue to use the primary LLM." Incompatible with `HINDSIGHT_API_RETAIN_BATCH_ENABLED=true` (provider Batch API, not Atlas's multi-item batches). `update_mode: "append"` routes on the append call's metadata. Per-operation chains exist for `CONSOLIDATION` too ("Each operation can define its own members + strategy with the `RETAIN` / `REFLECT` / `CONSOLIDATION` / `MENTAL_MODEL_REFRESH` prefix"), so consolidation could be moved off the primary independently. Atlas uses `extractor: minimax` (decisions.md, "What stays on the primary" already notes consolidation spends the primary's quota).

## 9. Deduplication

- Document level: content hash; re-retaining unchanged content dedups ("the chunk's content hash is still kept so incremental re-retain of the same document continues to deduplicate correctly"). Same `document_id` = destructive upsert (matrix).
- Entities: in-batch fold (0.5) and merge (above).
- Observations: `HINDSIGHT_API_CONSOLIDATION_DEDUP_THRESHOLD` 0.97 cosine → 1-by-1 LLM "merge or keep" (server; `1.0` disables).
- Facts: no fact-level dedup setting documented on this page (identical boilerplate in successive 10-Ks yields separate facts per document as far as this page says).

## 10. Consolidation into observations

| Setting | Default | Scope |
|---|---|---|
| `ENABLE_OBSERVATIONS` / `enable_observations` | `true` | server, bank |
| `ENABLE_AUTO_CONSOLIDATION` | `true` ("after retain, delete, and update operations") | server, bank |
| `OBSERVATIONS_MISSION` | unset; "Replaces the built-in consolidation rules" | server, bank |
| `CONSOLIDATION_LLM_BATCH_SIZE` | `8` facts per LLM call | server, bank |
| `CONSOLIDATION_MAX_MEMORIES_PER_ROUND` | `100`; "Mental model refreshes only run on the final round" | server, bank |
| `CONSOLIDATION_BATCH_SIZE` | `50` (load batch) | server |
| `CONSOLIDATION_MAX_TOKENS` | `1024` (recall for related observations) | server |
| `CONSOLIDATION_RECALL_BUDGET` | `low` | server |
| `CONSOLIDATION_SOURCE_FACTS_MAX_TOKENS` / `_PER_OBSERVATION` | `4096` / `256` | server, bank |
| `CONSOLIDATION_LLM_PARALLELISM` | `4` tag groups; mentions `per_tag` / `all_combinations` / explicit-list `observation_scopes` | server, bank |
| `MAX_OBSERVATIONS_PER_SCOPE` | `-1`; per tag scope; untagged not limited | server, bank |
| `OBSERVATION_SCOPE_LIMITS` | per-scope globs | server, bank |
| `CONSOLIDATION_RECONCILE_INTERVAL_SECONDS` | `300` | server |
| `ENABLE_OBSERVATION_HISTORY` / `_MAX_ENTRIES` | `true` / `50` | server |
| `LLM_TEMPERATURE_CONSOLIDATION` | `0.0` | server |

Key point: Atlas sets `observations_mission`, so the default definition ("durable, specific beliefs ... Contradictions are tracked with temporal markers rather than overwriting the prior belief") is **replaced entirely** by Atlas's one-sentence mission. Whether temporal markers on contradictions survive is then up to Atlas's wording. `observation_scopes` (how tags group consolidation) is only named here, not specified; recordings show `observation_scopes: null` on Atlas-shaped documents, i.e. the default scope applies (not documented here which that is).

## 11. Embeddings

- Provider, model, dims, prefixes are static server settings.
- Qwen3: "`Qwen/Qwen3-Embedding-*` ships one for searches only, which is what makes those models retrieve accurately." Applied automatically only by the `local` provider; for `openai`/`tei`/`litellm` "you supply the instructions yourself with `HINDSIGHT_API_EMBEDDINGS_QUERY_PREFIX`". Atlas's stack runs qwen3-embedding-0.6b through the `openai` provider with no prefix in `compose.yaml` → queries are embedded without the instruction the model was trained with. Search-side-only instructions "need no re-indexing", so this is a cheap server change (cluster env not verified).
- The five cosine gates (semantic 0.3, graph seed 0.3, temporal 0.1, semantic-link 0.7, observation dedup 0.97) were "calibrated for `BAAI/bge-small-en-v1.5`"; the doc says to "recalibrate all five values" after changing models. Atlas uses a different model.
- `HINDSIGHT_API_EMBEDDINGS_MAX_INPUT_TOKENS` 8192 (truncation).

## 12. Other intake-relevant switches

- `HINDSIGHT_API_FAIL_ON_EXTRACTION_ERRORS` (server, `false`): otherwise extraction errors leave a `completed` retain with silently dropped facts.
- `HINDSIGHT_API_STORE_DOCUMENT_TEXT` (`true`): needed for reflect's chunks and `expand` tool; doc contradicts itself on scope (see contradictions).
- `HINDSIGHT_API_LLM_TEMPERATURE_RETAIN` 0.1; `HINDSIGHT_API_LLM_STRICT_SCHEMA(_RETAIN)`; `HINDSIGHT_API_LLM_OUTPUT_LANGUAGE` (forces facts' language).
- `HINDSIGHT_API_DEFAULT_BANK_TEMPLATE`: template fields become per-bank overrides above env defaults.
- `HINDSIGHT_API_ENABLE_DRY_RUN_EXTRACT` (`true`): `POST .../memories/dry-run-extract` runs extraction without storing — a cheap way to compare modes/missions/strategies on real filing sections (uses the primary LLM, not metadata routes).
- Worker: consolidation reserves 2 slots (`WORKER_CONSOLIDATION_RESERVED_SLOTS`), matrix confirms ≥ 3 slots needed.

## 13. Which of these bear on Atlas's intake (SEC filings, exhibits, transcripts, section by section)

1. Query prefix for qwen3 embeddings (server) — affects every recall and every Scout pointer.
2. Entity identity: per-item `entities` / `resolve_entities: false` or bank `entity_labels` using Atlas's resolved companies — makes graph expansion follow real companies across filings retained months apart.
3. `observations_mission` replaces the default rules — review its wording (temporal markers, per-company grounding).
4. Retain strategies per document type (call-level `strategy`) — e.g. a transcript mission, a verbose mode for exhibits; test with dry-run extract.
5. `FAIL_ON_EXTRACTION_ERRORS=true` — no silent fact loss in long Items.
6. Re-calibrated similarity gates for the qwen3 model; semantic-link density at retain is not retroactive.
7. Consolidation chain per operation — move consolidation to the MiniMax member if quota matters.
8. Chunk size (3000) vs Atlas sections up to 12,000 chars (non-Item) or longer (Items): per-chunk extraction with only `context` as framing.
9. Causal links on by default (server) — feed graph retrieval.

## Contradictions noted

- `STORE_DOCUMENT_TEXT`: the Retain table row says "Hierarchical — overridable per bank via the [config API]", the "Skip storing raw document text" section says "This is a static, server-level setting and cannot be overridden per bank." The recordings show `store_document_text` in the resolved bank config and in the template schema, so per-bank appears to be real in 0.10.1 (setting it not exercised).
- Security Model lists "retrieval settings" among static fields, while the Recall budget mapping and Recall pipeline stages sections and the template schema make recall budgets and the four arms hierarchical per bank.
- AGENTS.md calls it "the shared Hindsight" for retains on MiniMax; `docs/decisions.md` line 8 speaks of a "dedicated Atlas Hindsight" distinct from the shared release. Not a docs-vs-matrix issue, but the lead should know which server's env the findings target.

## Not covered

- `retain.md`, `api/retain.md`, `api/memory-banks.md`: entity label format, `entities`/`resolve_entities` item fields, `observation_scopes` values and default, `update_mode`, temporal field semantics (`occurred_*`, `mentioned_at`), chunk boundary and overlap rules.
- The cluster's actual Hindsight env (home-ops) — only `compose.yaml` and the spike compose were read.
- `docs/research/extraction-bakeoff.md` (prior mode/model measurements) was not re-read.
