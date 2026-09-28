# Hindsight feature matrix: 0.10.1

Verified 2026-09-28 by live calls against `ghcr.io/vectorize-io/hindsight-api:0.10.1-slim` (the cluster's digest) in local Compose (`spikes/hindsight/`). The LLM was MiniMax-M3 with thinking disabled via LiteLLM; embeddings were `qwen3-embedding-0.6b` (1024 dims); the reranker was LiteLLM `rerank`. The documents were synthetic (fictional companies). Every claim links to a recorded request/response under `spikes/hindsight/recordings/`, which double as contract fixtures for Atlas's fake Hindsight. The harness is `feature_check.py` + `feature_followup.py`, with the evidence summary in `spikes/hindsight/results/feature-check.json`. The extraction-quality results are in `docs/research/extraction-bakeoff.md`.

The spec defers to this matrix. Differences that change Atlas's design are listed at the end and in `docs/decisions.md`.

| Feature (spec §6.1) | Verdict | What was observed | Recordings |
|---|---|---|---|
| Retain: sync | ✅ verified | `"async": false` returns 200 with `success`, `items_count`, `usage` once extraction completes | `retain/01-sync` |
| Retain: async + operations | ✅ verified | `"async": true` returns an `operation_id`; polling reaches `status: completed` | `retain/02-async*` |
| Retain: batch | ✅ verified | several `items` in one request → **one** operation for the batch | `retain/04-batch*` |
| `document_id` upsert | ✅ verified, **destructive** | re-retaining the same `document_id` removed v1's facts: after v2 there was 1 fact and the "40,000 wafers" fact was gone. Per-version IDs (`srcv:<hash>`) kept both versions intact | `upsert/*` |
| Recall: tags, `tags_match=any` | ✅ verified, **includes untagged** | filter `company:aurora` + `any` returned 10 Aurora + 2 untagged Cirrus results | `tags/01-tags-any` |
| Recall: strict tags | ✅ verified | `any_strict`, `all_strict` and `exact` returned only Aurora (untagged excluded) | `tags/02..04` |
| `query_timestamp` / `temporal_window` | ✅ verified, **not a hard filter** | a 2024 window still returned 7 of 14 results dated 2026, some ranked first | `temporal/01-window-2024` |
| Reflect: provenance | ⚠️ behaves differently | `include.facts` → `based_on.memories` has only `id, text, type, context, occurred_*`, **no `document_id`**. In this bank every citation was an **observation** (`document_id: null`). Tracing needs two hops: observation → `source_memory_ids` → world fact → `document_id` + `chunk_id` + Atlas's own `metadata` (preserved verbatim) | `reflect/01-provenance`, `reflect/02-resolve-memory`, `reflect/*resolve-observation*`, `reflect/*resolve-source-memory*` |
| Reflect: JSON Schema | ✅ verified, one bug | `response_schema` → `structured_output`, with `structured_output_error: null` on success. **Union types (`"type": [..., "null"]`) return HTTP 500** (`TypeError: unhashable type: 'list'`) | `reflect/03-structured`, `reflect/04-structured-union-type` |
| Operations API | ✅ verified | list shows `id, task_type, status, error_message, retry_count, next_retry_at, document_id, progress, …`; retry/delete endpoints exist (not exercised) | `operations/01-list` |
| Bank config API | ✅ verified | `PUT /banks/{id}` accepts `retain_mission`, `reflect_mission`, `disposition_*`; `GET …/config` returns `config` + `overrides` | `bank_config/*` |
| Bank templates | ✅ verified | `GET /v1/bank-template-schema`; `GET /banks/{id}/export` → manifest (`version, bank, mental_models, directives`); `POST /banks/{id}/import?dry_run=true` validates; a real import applied the config (mission present) and created the mental models, queuing their refresh operations | `bank_templates/*` |
| Observations | ✅ verified | consolidation ran (`POST …/consolidate` → completed) and produced 6 observations. They are listed via `GET …/memories/list?type=observation`; **`GET …/observations` returns 405** in 0.10.1 | `observations/*` |
| Mental models | ✅ verified | create (`id`, `name`, `source_query`, `trigger` incl. `refresh_after_consolidation`, `min_refresh_interval_seconds`) → an operation; `GET` gives the content; manual `refresh` works; `history` returned 2 entries with `previous_content` | `mental_models/*` |
| Knowledge pages | ✅ verified | `POST …/knowledge-base/pages` → 201, **backed by a mental model** (`mental_model_id`); listed via `GET …/knowledge-base/tree` (`GET …/pages` returns 405); a page has `markdown`/`body` | `knowledge_pages/*` |
| Document export / import | ✅ verified | `POST …/document-transfer/export?document_id=…` → operation → `result_metadata.storage_key` → ZIP via `GET /v1/default/files/download/{key}`; multipart `POST …/document-transfer` into a new bank imported 3 memories with **zero LLM requests** (a copy, not re-extraction) | `export_import/*` |
| Per-bank LLM request log | ✅ verified (bonus) | `GET …/llm-requests[/stats]`: operation, scope, provider, **alias** as model (not the LiteLLM deployment), tokens, duration, full prompt and output | `llm_requests/01-stats` |

Operational facts found along the way (details in `docs/research/extraction-bakeoff.md`):

- `HINDSIGHT_API_WORKER_MAX_SLOTS` ≤ 2 starves retain, because consolidation reserves 2 slots. Use ≥ 3 and pace with `HINDSIGHT_API_LLM_MAX_CONCURRENT`.
- MiniMax thinking is disabled only via `HINDSIGHT_API_LLM_EXTRA_BODY` when it sits behind `provider=openai`.
- Reflect can answer from raw chunks as well as facts (bake-off: a table figure absent from facts appeared in reflect output).
- Across this whole run, 31 LLM calls used 128k input / 12k output tokens, all successful.

## Differences that change Atlas's design

1. **Provenance resolution is two-hop, via metadata.** Atlas resolves every cited memory: if it's an observation, follow `source_memory_ids` to world facts; each world fact carries `document_id` and Atlas's `metadata.source_version_id`. Chunk-sourced reflect content (no memory ID) cannot be resolved this way, so it must be treated as unverified until matched to an archived span.
2. **No union types in response schemas.** Use explicit `*_known` booleans.
3. **Listing routes differ from the docs:** observations via `memories/list?type=observation`, knowledge pages via `knowledge-base/tree`.
4. **Templates exist**, so the bank template (not the config API fallback) is the versioned configuration mechanism.
5. **Document export/import copies memories without re-extraction.** That is useful for moving banks. Whether it can seed a replay bank without temporal leakage is a Phase 6a question, because extraction and entity resolution in the source bank may have seen later documents.

## Not verified here

- the retry and delete operation endpoints
- mental-model refresh loops (upstream issue #4532) and the slot hang (#4763), from ticket 01
- `refresh_after_consolidation` behavior
- bank deletion
- the MCP endpoints
- tenant API-key auth (the local spike runs without the tenant extension)
- behavior under sustained load
