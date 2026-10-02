# Hindsight 0.10.1 API surface vs Atlas's gateway

Reader: API-surface slice. Sources: `.agents/skills/hindsight-docs/references/openapi.json` (schemas read by script, not top to bottom),
`developer/api/{memory-banks,memories,documents,operations,main-methods}.md`, `docs/hindsight-feature-matrix.md`,
`spikes/hindsight/recordings/` (tags, temporal, reflect, observations, operations, upsert), and Atlas's
`backend/atlas/hindsight/{gateway,models}.py` plus the callers that matter (`research/service.py`, `research/provenance.py`,
`retention/service.py`, `investigations/pointers.py`, `investigations/tasks.py`, `configs/hindsight/bank-template.json`).

Note: the vendored `openapi.json` says `"version": "0.10.0"` in `info`, though the skill is pinned to 0.10.1. Treat schema details as
0.10.x; the feature matrix and recordings (taken against 0.10.1) win where they differ. In `openapi.json`, non-ASCII characters
(em dashes) are stored as `—` escapes, so the quotes below avoid them.

---

## 1. Endpoints Atlas calls (gateway.py), what it sends, what it keeps

| Gateway method | Endpoint | Sent | Kept (models.py) |
|---|---|---|---|
| `retain_batch` | `POST /memories` | `items[]` of `RetainItem` (`content`, `document_id`, `timestamp`, `context`, `metadata` (str→str), `tags`), `async: true` | `RetainSubmitted`: `bank_id`, `items_count`, `operation_id` (drops `operation_ids`, `usage`, `success`, `async`) |
| `operation` / `wait_for_operation` | `GET /operations/{id}` | none (no `include_payload`) | `operation_id`, `status`, `operation_type`, timestamps, `error_message`, `retry_count`, `next_retry_at`, `result_metadata`, `child_operations` (drops `progress`, `details`, `task_payload`) |
| `recall` | `POST /memories/recall` | `query`, `budget` (default `mid`), `tags` + `tags_match` (strict only), or nothing for the whole bank | `results[]` → `Memory`: `id`, `text`, `type`, `context`, `document_id`, `chunk_id`, `tags`, `metadata`, `occurred_start/end`, `mentioned_at`, `state`, `source_memory_ids` (absent on recall). **Drops** `entities` (per result and the response-level map with entity IDs), `scores`, `source_fact_ids`, `chunks`, `source_facts`, `trace`, `attachments`. |
| `reflect` | `POST /reflect` | `query`, tags scope, `include: {facts: {}}`, optional `response_schema` | `text`, `based_on.memories` (id, text, type, context, occurred_*), `based_on.mental_models`, `structured_output(_error)`, `usage`. Drops `based_on.directives`, `trace`. |
| `get_memory` | `GET /memories/{id}` | none | `Memory` incl. `source_memory_ids` and `source_memories`; **drops** `entities`, `observation_scopes`, `invalidation_reason`, `edited_at`, `history` |
| `list_observations` | `GET /memories/list?type=observation` | `type`, `limit`, `offset` | `items` (as `Memory`), `total`, `limit`, `offset`; drops `proof_count`, `consolidated_at`, `consolidation_failed_at`, `entities` |
| `document_memories` | `GET /memories/list?document_id=` | `document_id`, `limit`, `offset` | same |
| `get_document` | `GET /documents/{id}` | none | `id`, `bank_id`, `memory_unit_count`, `nodes_by_fact_type`, `tags`, `document_metadata`, `content_hash`, timestamps (drops `original_text`, `retain_params`, `observation_scopes`) |
| `knowledge_page_tree` | `GET /knowledge-base/tree` | none | `roots` as `KnowledgeNode` |
| `apply_bank_template` | `POST /import?dry_run=true`, then `POST /import` | the manifest | `TemplateImportResult` |
| `bank_config` | `GET /config` | none | `config`, `overrides` |
| `consolidate` | `POST /consolidate` | `{}` (no `observation_scopes`) | `operation_id`, `status` |
| `delete_bank` | `DELETE /banks/{id}` | replay banks only | `success`, `message`, `deleted_count` |
| mental models | `POST /mental-models`, `POST .../{id}/refresh`, `GET .../{id}`, `GET .../{id}/history` | `id`, `name`, `source_query`, `trigger` (`refresh_after_consolidation`, `min_refresh_interval_seconds`, `refresh_cron`), `tags`, `max_tokens` | content, `is_stale`, `last_refreshed_at`, `based_on` (flattened); drops `last_memory_seen_at`, `reflect_response.structured_output`, trace |
| server | `GET /health`, `GET /version` | none | status, `api_version`, `features` |
| LLM log | `GET /llm-requests/stats` | `period` | buckets |

How Atlas uses recall (verified in code):
- `research/service.py`: scope is `company:<id>` and `theme:<slug>` tags combined with `SCOPE_MATCH: TagMatch = "any_strict"`; the
  list is built as `tags = [f"company:{c}" for c in company_ids] + [f"theme:{t}" for t in theme_ids]`, so a company+theme scope is
  an OR (union), never an AND.
- `investigations/tasks.py` `_theme_recall`: the Scout's pointer recall is theme-only, default budget `mid`, no `max_tokens`.
- `investigations/pointers.py`: the pointer rank is the list position: `for rank, memory in enumerate(response.memories, start=1):`.
- `research/provenance.py`: observations are resolved by `get_memory` on the observation, then `get_memory` on each source
  (comment: `# A recall result carries no source IDs; the memory lookup does.`). That is 1 + N HTTP calls per observation.

How Atlas retains (verified in code, `retention/service.py`): each section is one item with `content`, per-version
`document_id`, `timestamp=version.available_at`, `context=f"{title}: {heading}"`, metadata (`source_version_id`, `section_anchor`,
`char_start`, `char_end`, `available_at`, optional `extractor`), and tags `company:`, `theme:` (each theme), `source:`, `doctype:`,
`form:`. No `entities`, no `observation_scopes`, no `strategy`, no `operation_id`.

---

## 2. Parameters not sent and fields dropped on the endpoints Atlas calls

### 2.1 Recall request (RecallRequest)

| Field | Schema default | What it gives a reading index over filings |
|---|---|---|
| `max_tokens` | 4096 | Caps how much the result list may hold. Atlas never sends it, so every pointer recall is capped at ~4096 tokens of memories; the recordings show 10 to 14 results per recall at `mid`. A larger value (main-methods shows `max_tokens=8192,  # Return more context`) is the cheapest way to get more pointers per query; recall makes no LLM call. |
| `budget` | `mid` | Atlas uses `mid` always. Budget maps to a per-arm retrieval limit (`fixed` default: "Defaults: `100` / `300` / `1000`"). `high` widens graph traversal (more multi-hop candidates) at latency cost only. |
| `types` | all | Atlas gets world + experience + observation mixed. `types=["world"]` returns only facts that carry `document_id` + Atlas `metadata` inline: a pointer straight to a Source Version section, no extra hop. Observations need the two-hop resolution. |
| `prefer_observations` | false | "When recalling raw facts ('world'/'experience') together with 'observation', drop any raw fact that an observation in the results was consolidated from" and backfill. For a reading index it frees slots that would be duplicates of an observation's sources. |
| `include.entities` | `{max_tokens: 500}` (on by default) | Already returned (the recordings have a 17 to 21 entry map with `entity_id`), but Atlas drops it. These IDs are the handle for `GET /memories/list?entity_id=` (exhaustive per-entity evidence). Entity `observations` are empty (entity observations are deprecated: "This endpoint is deprecated. Entity observations have been replaced by mental models."). |
| `include.chunks` | off | "Include raw chunks. Set to {} to enable, null to disable (default: disabled)." Returns `chunks` "keyed by chunk_id" with `text`, `chunk_index`. Gives the exact retained chunk (≤ `retain_chunk_size`, 3000 chars default) a fact came from: a finer pointer than the whole section. |
| `include.source_facts` | off | "Source facts for observation-type results, keyed by fact ID"; values are `RecallResult` (so they carry `document_id`, `metadata`, `chunk_id`). Plus `source_fact_ids` per observation, and `source_facts_truncated` ("Whether the source_facts map was cut short by the token budget."). This would replace Atlas's 1 + N `get_memory` calls per observation with zero extra calls. **Not exercised in any recording**: in the recordings `source_fact_ids` is `null` on observations when not requested. |
| `query_timestamp` | none | "Used as the query-time anchor for relative temporal expressions and recency scoring." Investigations have an `as_of`; sending it makes recency scoring relative to the as-of time instead of now. |
| `temporal_window` | none | "**This ranks, it does not filter**". Feature matrix: "a 2024 window still returned 7 of 14 results dated 2026, some ranked first". Not an as-of filter. |
| `tag_groups` | none | "Compound tag filter using boolean groups. Groups in the list are AND-ed. Each group is a leaf {tags, match} or compound {and: [...]}, {or: [...]}, {not: ...}." Lets Atlas express company AND theme, theme AND form:10-K, NOT source:tradingview, or exclude later availability periods if Atlas tagged them. Atlas's union-only scope cannot. Leaves may use `resolve='fuzzy'` (Atlas should not: strictness). |
| `min_scores` | none | Retrieval floors per arm (semantic, keyword) and post-ranking floors (`reranker`, `final`): "post-ranking filters applied to every scored result, so those floors *are* guaranteed by each result returned". Lets a pointer recall abstain rather than return weak hits. Caveat in the schema: "the reranker's absolute scores are not calibrated across queries". |
| `trace` | false | Untyped `trace` object; debug only. Shape not documented. |

### 2.2 Recall response fields dropped

- `results[].scores` (`final`, `reranker`, `semantic`, `keyword`): "``final`` is the value results are ranked by." Atlas weighs
  pointed companies by 1/rank; `final` and `reranker` would let it weight by relevance and tell a strong rank-5 from a weak rank-1.
- `results[].entities` (names) and response `entities` (name → `entity_id`, `canonical_name`).
- `source_fact_ids`, `source_facts`, `chunks`, `trace`.
- `chunk_id` is parsed (`chunk_id: str | None = None` in `Memory`) but no caller uses it.

### 2.3 Retain request (RetainRequest / MemoryItem)

| Field | What it would give |
|---|---|
| `entities` (`EntityInput{text, type}`) + `resolve_entities` | "Optional entities to combine with auto-extracted entities." With `resolve_entities: false`: "False takes your names literally ... any other name creates a new entity". Atlas knows the filer and its universe/counterparty names; supplying the filer's canonical name (and Atlas-resolved company names) would give one stable entity per company. The recording shows the extractor splitting one company: `"canonical_name": "Aurora Optics",` and `"canonical_name": "Aurora Optics Inc.",` are two entities with different IDs in the same recall. |
| `observation_scopes` | `'per_tag'`, `'combined'` (default), `'shared'`, or explicit tag lists. "'combined' (default) runs a single pass with all tags together." and an observation scope is "an exact tag set". Atlas's tag set per item is {company, every theme, source, doctype, form}, so under the default observations are consolidated only among memories with that exact set: a company's 10-K facts and its 10-Q or transcript facts land in different scopes. Explicit scopes such as `[["company:x"], ["theme:photonics"]]` would give per-company and per-theme observations across forms and sources. `GET /observations/scopes` shows how fragmented the bank is today. (Exact consolidation semantics are the observations page's; the lead reads it.) |
| `strategy` | "Named retain strategy for this item. Overrides the bank's default strategy for this item only." Defined in bank config `retain_strategies` (not documented in my pages beyond that). Caveat: mixed strategies in one async batch return several operations, "Operation IDs when items were submitted as multiple strategy groups (async=true with mixed per-item strategies)." Atlas keeps only `operation_id` and would poll only the first group. |
| `operation_id` (request-level) | "Re-submitting with the same operation_id returns the original operation and creates no new work, so retrying after a lost or timed-out acknowledgement will not enqueue a duplicate." Atlas's retain job retry after a lost ack re-submits and pays extraction twice (the per-version `document_id` upsert makes it harmless for content but not for quota). |
| `update_mode` | `replace` (default) or `append`. Not relevant (per-version IDs). |
| `timestamp` | Sent (availability time). Accepts `"unset"`; not relevant. |
| `document_tags` | Deprecated. |

Retain response dropped: `operation_ids` (above), `usage` (sync only).

### 2.4 Reflect request

Atlas sends no `budget` (schema default `low`), no `max_tokens` (default 4096), no `fact_types`, no `exclude_mental_models` /
`exclude_mental_model_ids`, no `tag_groups`, no `apply_all_directives`, no `include.tool_calls`, no
`reflect_search_observations_max_tokens` / `_include_entities`. Notes:
- `budget` is left at the server default `low` for every research reflect and replay reflect.
- Reflect may answer from Atlas's own mental models (Theme status, Bottlenecks): "If true, exclude all mental models from the
  reflect loop (skip search_mental_models tool)." Atlas resolves only `based_on.memories`; a mental-model-sourced claim is cited
  via `based_on.mental_models`, which the provenance resolver does not follow.
- `ReflectFact` carries no `document_id` (matrix row "Reflect: provenance").
- `include.tool_calls` returns `trace.tool_calls`/`llm_calls`: which recalls reflect made. Useful for debugging empty answers.

### 2.5 Other endpoints Atlas calls

- `GET /memories/{id}`: response untyped in the OpenAPI (`schema: {}`); the recording has `entities` (list of names),
  `observation_scopes`, `state`, `invalidation_reason`, `edited_at`, `history: []`, `source_memory_ids`, `source_memories`.
  Atlas drops `entities`.
- `GET /memories/list`: Atlas uses `type` and `document_id` only. Unused filters: `q` (full-text over text and context),
  `entity_id`, `tags`/`tags_match`, `state`, `consolidation_state`, `time_field` + `start_date`/`end_date` (a real filter: "This
  filters, unlike recall's `temporal_window`, which only ranks"). Row field `entities` is "Comma-separated canonical entity names";
  in the recording observation rows have `"entities": "",` while the same observation's `GET /memories/{id}` lists 9 entities.
- `GET /operations/{id}`: drops `progress` (stage, processed/total, `detail` such as `facts_committed`) and typed `details`
  for mental-model refreshes.
- `POST /consolidate`: accepts `observation_scopes` (list of tag lists) to consolidate only matching memories; Atlas sends `{}`.
- `GET /documents/{id}`: Atlas drops `original_text` and `retain_params` (the recording shows `retain_params.event_date` = the
  item `timestamp`, and the context and metadata as sent).

---

## 3. Endpoints Atlas never calls that bear on research

### 3.1 Entities

- `GET /entities` ("List all entities (people, organizations, etc.) known by the bank, ordered by mention count. Supports
  pagination."): `id`, `canonical_name`, `mention_count`, `first_seen`, `last_seen`, `metadata`. No tag filter: bank-wide.
  Use: find which product/company entities the bank knows, find duplicates of a company (fragmentation check).
- `GET /entities/{id}`: same plus `observations` (deprecated; empty in recordings).
- `GET /entities/graph?limit&min_count`: "Return a graph of entities (nodes) and their co-occurrences (edges) for
  visualization." Edges have `weight` (co-occurrence count) and `lastCooccurred`. Bank-wide, no tags. Use: candidate
  company↔company and company↔product pairs to read next (a co-occurrence is a reading pointer, never an edge; Atlas's rule
  that co-mention forms no edge still holds).
- `POST /entities/{id}/regenerate`: deprecated.

**Biggest single opportunity in this slice**: `GET /memories/list?entity_id=<id>` ("The `entity_id` filter is an exact reverse
lookup over stored entity links"), combinable with `type`, `tags`, `time_field`/`start_date`/`end_date`. Starting from a
company named in one filing, it lists every fact that mentions that company in *any* filing (including other companies'
filings: a supplier named in a customer's 10-K), with `document_id` + Atlas metadata, so each is a pointer to a section. That is
a deterministic company-to-company hop, exhaustive and as-of filterable, which theme-scoped recall (top-k, ranked, no date
filter) is not. It depends on stable entities (retain `entities` above) and the entity IDs recall already returns.

### 3.2 Memory graph

- `GET /graph?type&limit&q&tags&tags_match(all_strict default)&document_id&chunk_id`: "Retrieve graph data for visualization,
  optionally filtered by type (world/experience/observation)." Nodes = memory units; edges with `linkType` ('entity',
  'semantic', 'temporal', ...), `weight`, `entityName`; `table_rows` with `document_id`, `chunk_id`, `proof_count`, entities.
  Use: from a document (or chunk) Atlas has read, list the memories linked to it through shared entities or semantic links:
  the neighbours graph retrieval would walk. The full set of link types is not documented ("...").

### 3.3 Tags

- `GET /tags?q=company:*&source=memories`: "List all unique tags in a memory bank with usage counts. Supports wildcard search
  using '*'". Use: memory counts per company/form/source tag, a cheap coverage check (which universe companies have few
  memories) for the Theme explorer's coverage gaps and before an investigation.

### 3.4 Bank stats and series

- `GET /stats`: `nodes_by_fact_type`, `links_by_link_type`, `pending_consolidation`, `failed_consolidation` ("Number of source
  memories (world/experience) whose consolidation permanently failed and can be retried via the consolidation recovery
  endpoint."), `total_observations`, `last_consolidated_at`, `last_memory_write_at`. Use: know when observations are behind
  (pointers via observations are missing for unconsolidated facts), alert on failed consolidation, and recover with
  `POST /consolidation/recover`.
- `GET /stats/memories-timeseries?time_field=mentioned_at|occurred_start`: memories by event time; low value.

### 3.5 Observations

- `GET /observations/scopes`: "Each observation lives under a scope: the exact set of tags it was consolidated with." Use: measure
  scope fragmentation under Atlas's five-family tag sets.
- `GET /memories/{id}/history`: "Get the full history of an observation, with each change's source facts resolved to their
  text." Response untyped in the OpenAPI and not recorded. Use: how the bank's view of a company changed and from which facts:
  candidate contradictions for the Skeptic to read (pointers only).
- `DELETE /memories/{id}/observations`, `DELETE /observations`: re-consolidation tools; operational.

### 3.6 Chunks and documents

- `GET /documents/{id}/chunks`, `GET /chunks/{chunk_id}` (`chunk_text`, `chunk_index`, `document_id`): map a fact's `chunk_id` to
  the exact chunk. Whether `chunk_text` is a verbatim substring of the retained content (so Atlas could locate its offsets) is
  not documented.
- `GET /documents?tags&tags_match&time_field&start_date&end_date&q`: list retained documents by tag and time; Atlas has its own
  ledger (`memory_document`), so low value.
- `PATCH /documents/{id}` (tags only): replaces tags and "Observations derived from those units are invalidated and queued for
  re-consolidation under the new tags." Costly; only relevant if Atlas wanted a mutable tag such as `latest`.
- `POST /documents/{id}/reprocess`: re-extract under a new config (resets curation).

### 3.7 Curation and extraction preview

- `PATCH /memories/{id}` (edit or `state: invalidated`, reversible, audited): "Only raw **world** and **experience** facts can be
  curated." Atlas treats memory as an index and never curates; an option for a fact Atlas has proven misextracted.
- `POST /memories/dry-run-extract`: "Preview what the retain step would extract from text WITHOUT changing the bank", with
  overrides for `retain_mission`, extraction mode, chunk size, `entity_labels`, `strategy`. Returns facts with raw entities
  and chunks. Use: A/B the retain mission or entity labels on a real 10-K section before changing the template (costs one
  extraction LLM call; nothing stored).
- `POST /prompts/preview`: the exact retain/consolidation/reflect prompt for the bank; no LLM call.

### 3.8 Directives, bank, operations

- Directives (`GET/POST/PATCH/DELETE /directives`): Atlas sets five via the template; tagged directives apply only to reflects with
  matching tags. Low.
- `GET /operations?status&type&exclude_parents`: list failed retains/consolidations bank-wide. Low (Atlas polls its own).
- Bank transfer and clone: "Move a bank ... between banks and instances **without re-running the LLM**" (paraphrased around an
  em dash). A document-subset export could seed a replay bank without re-extraction, but the matrix leaves open whether that leaks
  later knowledge (entities resolved in the source bank). Low for research.

---

## 4. Contradictions found

1. `main-methods.md` says recall chunks are "keyed by memory ID" (`# Check chunk details (chunks are on response level, keyed by
   memory ID)`); the OpenAPI says "Chunks for facts, keyed by chunk_id".
2. `operations.md` names the parent batch operation `retain_batch`; the recording `operations/01-list.json` shows
   `"task_type": "batch_retain",`.
3. The OpenAPI `type` filter on `GET /operations` lists "retain, consolidation, refresh_mental_model, file_convert_retain,
   webhook_delivery"; `operations.md` also lists `graph_maintenance`.
4. The OpenAPI `info.version` is `0.10.0` while the skill is pinned to 0.10.1.
5. `memories/list` row `entities` is documented as comma-separated canonical names, but observation rows in the recording have
   `"entities": "",` although `GET /memories/{id}` for the same observation lists entities.
6. Atlas's `RetainSubmitted` keeps a single `operation_id`; the API returns `operation_ids` when per-item strategies differ (only a
   problem if Atlas adopts `strategy`).

## 5. Not covered / not settled

- Did not read `recall.md`, `retain.md`, `reflect.md`, `mental-models.md`, `observations.mdx`, `configuration.md` (lead's or other
  readers' slices). So the exact semantics of observation scope `combined` beyond the schema text, retain strategies, and whether
  `include.source_facts` / `source_fact_ids` behave as documented in 0.10.1 are unverified here.
- `GET /memories/{id}` and `/history` responses are untyped in the OpenAPI; history was never recorded.
- No recording exercises `include.chunks`, `include.source_facts`, `entity_id` listing, `/entities`, `/entities/graph`, `/graph`,
  `/tags`, `/stats`, `/observations/scopes`, `tag_groups`, `min_scores`, `types`, `max_tokens`, retain `entities`,
  `observation_scopes` or `operation_id`. All of section 3 is documented-only for 0.10.1.
- Webhooks and knowledge pages were not read.
