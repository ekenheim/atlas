# How Atlas uses Hindsight today (from the code)

Reader slice: Atlas's own use of Hindsight 0.10.1. Sources: the Atlas code and `docs/decisions.md` named below, `docs/hindsight-feature-matrix.md`, `spikes/hindsight/recordings/`, and (only to say what Atlas does *not* send) the pinned `openapi.json` and `developer/api/retain.md`, `developer/observations.md` under `.agents/skills/hindsight-docs/references/`. Every quote is verbatim from the file named.

Note: the pinned `openapi.json` reports `"version": "0.10.0"` in its `info` block although the skill says it is vendored from v0.10.1 (see Contradictions).

---

## 1. The HTTP client (`backend/atlas/hindsight/gateway.py`, `models.py`)

- One gateway per bank; every call is bank-scoped under `/v1/default/banks/{bank}`. Request timeout 300 s.
- Strict tag matching only: `models.py` `STRICT_TAG_MATCHES: frozenset[str] = frozenset({"any_strict", "all_strict"})`. `tag_groups`, `exact`, `any`, `all` are refused before a call.
- Union types in response schemas refused (`check_response_schema`).
- Results parse with `extra="ignore"`: every field Atlas does not model is silently dropped.

Endpoints used: `POST /memories` (retain, async), `GET /operations/{id}`, `POST /memories/recall`, `POST /reflect`, `GET /memories/{id}`, `GET /memories/list?type=observation`, `GET /memories/list?document_id=`, `GET /documents/{id}`, `GET /knowledge-base/tree`, `POST /import[?dry_run=true]`, `GET /config`, `POST /consolidate`, `DELETE /banks/{id}` (replay banks only), mental models create/refresh/get/history, `/health`, `/version`, `/llm-requests/stats`.

Not used: `documents/{id}/reprocess`, `operations` list/retry/delete, `observations/scopes`, document export/import, entity endpoints.

---

## 2. Retain: what one item carries

`backend/atlas/retention/service.py`, `retain_item(...)`:

```
metadata = {
    "source_version_id": str(version.id),
    "section_anchor": anchor,
    "char_start": str(start),
    "char_end": str(end),
    "available_at": version.available_at.isoformat(),
}
if extractor is not None:
    metadata[EXTRACTOR_METADATA_KEY] = extractor
return RetainItem(
    content=parsed[start:end],
    document_id=document_id,
    timestamp=version.available_at,
    context=f"{version.title}: {heading or anchor}",
    metadata=metadata,
    tags=tags,
)
```

| Field | What Atlas sends | Where |
|---|---|---|
| `content` | the exact slice of the version's **recorded** parsed text for the section: `content=parsed[start:end],` (plain string, never content blocks) | `retention/service.py` |
| section size | SEC primary 10-K/10-Q/8-K: one Item = one document, **unbounded** (decisions: "a 140k-character Risk Factors section is one Hindsight document, and Hindsight chunks it internally"). Everything else (exhibits, press releases, transcripts, non-SEC): chunks of at most `MAX_CHUNK_CHARS = 12_000`, cut at a line break. Text before the first Item is a `cover` section, retained too | `retention/sections.py` |
| `document_id` | `srcv:<source_version_uuid>:<section-anchor>` (`return f"srcv:{source_version_id}:{section.anchor}"`), per version, never reused (ADR-0001) | `retention/service.py` |
| `timestamp` | `timestamp=version.available_at,`: the Source Version's availability (EDGAR acceptance/dissemination time, or the observed revision time), not the reporting period | `retention/service.py` |
| `context` | `f"{version.title}: {heading or anchor}"`; for SEC the title is `f"{filing.company_name} {filing.form} filed {filing.filing_date.isoformat()}"` (plus `, <document_type>` for an exhibit). For a chunk the "heading" is `chunk-003`, for the cover `cover` | `retention/service.py`, `sources/edgar.py` |
| `metadata` | `source_version_id`, `section_anchor`, `char_start`, `char_end`, `available_at` (all strings; the model is `dict[str, str]`), plus `extractor: minimax` when `ATLAS_RETAIN_EXTRACTOR=minimax` | `retention/service.py` |
| `tags` | `company:<uuid>`, `theme:<slug>` for every theme containing the company, `source:<provider>`, `doctype:<source_type>`, `form:<form_type>` (an exhibit carries its filing's form) | `retention/service.py` `version_tags` |
| `entities`, `resolve_entities`, `observation_scopes`, `strategy`, `update_mode` | **never sent**: `RetainItem` has only `content, document_id, timestamp, context, metadata, tags` and `model_config = ConfigDict(extra="forbid", frozen=True)` | `hindsight/models.py` |
| request level | `"async": True` always; one batch = all to-be-submitted sections of one Source Version; no client `operation_id`; no `document_tags` | `hindsight/gateway.py` `retain_batch` |

What is retained at all:
- English parses only (`RETAINABLE_LANGUAGES = ("en",)`), parse status `parsed` or `incomplete`.
- A version byte-identical to an already-retained one is **linked**, not retained: "The linked copy's own tags (for example a different company) are not in memory; the retained twin's are." (decisions, retention entry).
- With triage on (default `auto`), only sections whose effective triage decision is `retain` are recorded and submitted. Decisions come from: inheritance by section SHA-256 from the predecessor version; boilerplate rules on Item headings (`triage-rules-v2`); the Triage role reading up to 10 windows of 1,500 chars (overlap 200) per section, 15 windows per call; a section is `retain` if any window says so. Skipped sections stay archived and citable, retrievable on demand (`POST .../sections/{anchor}/retain`).
- Replay banks bypass triage and retain every section, through the same `retain_item`.

What Atlas does with the answer (`retain_batch` returns `RetainSubmitted`: `bank_id`, `items_count`, `operation_id`; `operation_ids` and `usage` in the response are ignored). It inserts a `hindsight_operation` row, points every section row at it, and enqueues `poll_operation`.

---

## 3. Retain outcome: how a section ends `completed`, `zero_fact`, `failed` or stuck `pending`

`retention/service.py` `poll`:

1. `wait_for_operation` polls `GET /operations/{id}` until `status` is terminal (`completed`, `failed`, `cancelled`, `not_found`), timeout `retain_poll_timeout_seconds` 240 s, interval 5 s. `OperationTimeout` re-raises: the attempt fails, the job is retried up to `retain_poll_attempts` (5). Sections stay `pending` meanwhile.
2. **Not succeeded** → `operation_error_class(operation)` reads the operation's `error_message` and every child's `error_message`:
   - `quota` / `unavailable` → `_record_terminal` then `TransientFailure` (queue pause; the sections stay `pending`; the next poll attempt resubmits them as a new batch under the same IDs).
   - anything else, **including a failure with no message**, is `permanent` → **every pending section of the operation** is set `"retain_state = 'failed', error = :error",`. No `GET /documents/{id}` is made on this path, so a section whose sub-batch did produce facts is still marked failed.
   - Classification regexes (`jobs/pacing.py`): quota `\b429\b|rate[ _-]?limit|too many requests|insufficient…quota…`; unavailable `\b50[234]\b|service[ _-]?unavailable|bad gateway|gateway[ _-]?time-?out|connection (refused|reset|error|aborted)|APIConnectionError|\boverloaded\b|no healthy deployments|no deployments available`. A relayed 500, a plain "timeout"/"timed out" from the LLM, a context-length error, or a JSON/parse error from extraction do **not** match, so they are `permanent`.
3. **Completed** → for each section, `GET /documents/{id}`; `memory_unit_count` is the fact count. 404 → `failed` ("document … not found in Hindsight after its operation completed"). `> 0` → `completed`, and the memory IDs are listed by `GET /memories/list?document_id=` and stored. `0` and never reprocessed → stays `pending` and a `reprocess` job re-retains all such sections of the operation as one batch under the same IDs (once). `0` after the reprocess → `zero_fact`.
4. `result_metadata` (e.g. `extraction_errors_count`, `num_sub_batches`, `total_tokens`) is stored on the operation row but never read to decide anything.
5. `failed` is final: "Failed sections are not retried automatically." (decisions). `atlas … retry_failed` (`run_retry_failed` in `cli.py`) resets failed rows to `pending` and enqueues retains.
6. The metric `atlas_retained_sections_total{outcome}` is a `count(*)` of `memory_document` rows by current `retain_state` (`_FINAL_SECTION_STATES = ("completed", "zero_fact", "failed", "linked")`), so it is a snapshot of rows, not a count of events.

What could explain many more `failed` than `completed` sections, **from the code only**:
- (a) One operation per Source Version, so a permanent failure of the batch (or of any sub-batch, whose error is folded into the classification) marks every section of that version failed at once: the failure count scales with sections per version.
- (b) Any error text not matching the two regexes is permanent, including a missing message; before ticket 11 "no healthy deployments" was permanent too (decisions: "it was `permanent` and is now `unavailable`"), so rows failed under the old rule remain `failed` until `retry_failed` is run.
- (c) Unbounded Item sections (a whole Risk Factors or MD&A) make large items, and Hindsight chunks them internally; decisions quotes the routed failure form "`RuntimeError: Fact extraction failed: 1/1 chunks failed. First failures: chunk 0: …`". Whether one failed chunk fails the whole operation is not documented in my slice.
- (d) A routed MiniMax item does not fall back (decisions: "when the routed member fails, the item's extraction fails after its retries and its retain operation ends `failed`").
- Not a cause of `failed`: poll timeouts (they leave `pending`), zero facts (they become `zero_fact`).
- I could not see production data; the above are code paths, not a diagnosis.

---

## 4. Recall

Gateway (`gateway.py`):
```
body: dict[str, JsonValue] = {"query": query, "budget": budget, **_scope_fields(scope)}
```
with `_scope_fields` = `{"tags": list(scope.tags), "tags_match": scope.match}`.

| Request field | Atlas | Server default (pinned OpenAPI) |
|---|---|---|
| `query` | the question / Scout query / bear-checklist query text, truncated to 4,000 chars | — |
| `budget` | `mid` (API default; Scout and Skeptic use the default) | `mid` |
| `tags` + `tags_match` | `company:<uuid>` / `theme:<slug>`, `any_strict` (`SCOPE_MATCH: TagMatch = "any_strict"`). Investigations: theme only (`scope = ResearchScope(theme_ids=[theme_id])`) | `any` |
| `types` | not sent (all of world, experience, observation) | all |
| `max_tokens` | not sent | 4096 |
| `include` (`entities`, `chunks`, `source_facts`) | not sent (entities are on by default server-side, then dropped by Atlas) | entities on |
| `prefer_observations` | not sent | false |
| `query_timestamp`, `temporal_window` | not sent | — |
| `trace`, `min_scores`, `tag_groups` | not sent | — |

Response: `RecallResult` keeps only `memories: list[Memory] = Field(validation_alias="results")`. Top-level `trace`, `entities`, `chunks`, `source_facts`, `source_facts_truncated` are dropped. Per memory, `Memory` keeps `id, text, type, context, document_id, chunk_id, tags, metadata, occurred_start, occurred_end, mentioned_at, state, source_memory_ids`; it drops `entities`, `scores` (final/reranker/semantic/keyword), `attachments`, and `source_fact_ids` (the recall's name for an observation's sources; the recording shows it `null` without `include.source_facts`). So the resolver makes one `GET /memories/{id}` per recalled observation: "# A recall result carries no source IDs; the memory lookup does."

`research/service.py` `recall` returns each memory as `RecalledMemory` (`memory_id, type, text, context, tags, occurred_start, occurred_end, mentioned_at, provenance`), dropping `document_id`, `chunk_id`, `metadata`. Every memory returned is kept (no cut-off); recall is synchronous and not stored except as reading pointers.

---

## 5. Provenance resolution (`research/provenance.py`)

- World/experience fact: `document_id` must start `srcv:`; the `memory_document` row with that ID in this bank is looked up; the fact's `metadata.source_version_id` must equal the row's version and `metadata.section_anchor` (if present) its anchor. → `resolved` with the section (version, anchor, heading, char span, company, form, `available_at`).
- Observation: follow `source_memory_ids` (from a `GET /memories/{id}` lookup), each source resolved recursively, at most `MAX_HOPS = 3`; the observation takes its worst hop's state.
- `unverified`: no memory ID (reflect chunk content), `not_an_atlas_document`, `unknown_document` (no ledger row), `metadata_mismatch`, `no_source_memories`, `too_many_hops`, `quote_mismatch`.
- `broken`: the memory or a source memory answers 404.
- Quotes in a reflect answer: every double-quoted passage must occur (whitespace and typographic quotes normalized) in the archived parsed text of a section a resolved citation leads to.

---

## 6. Reading pointers (`investigations/pointers.py`, `companies.py`, `claims/selection.py`)

- Scout: one recall for the round's question (`query_index` 0) and one per Scout query, theme-scoped `any_strict`, budget `mid` (≤ 11 a round). Skeptic: one recall per bear-checklist item × each of up to 6 companies the Claims name (≤ 36), query text built deterministically (`bear_query`), theme-scoped.
- Rank = the memory's position in the recall's results, counting unresolved ones: `for rank, memory in enumerate(response.memories, start=1):`.
- A pointer is stored per **resolved** memory per distinct section it leads to, dropping sections available after the investigation's `as_of`. Kept columns: query index/text/kind, `rank`, `memory_id`, `memory_type`, `memory_text`, the section (version, anchor, heading, offsets), `company_id`, `available_at`, citation state. Not kept: scores, entities, occurred/mentioned dates, chunk ID, the recall's own ordering signals beyond rank.
- Company ranking: sum of `1/rank` over the round's Scout pointers naming the company (researched only), ties by best rank then slug; Investigators added while `max_companies` (6) has room.
- Passage choice: each pointer chooses, within its section of the document being read (re-split by the selection), the window whose words overlap most with the pointer's memory text: `best = _best_window(query_terms(pointer.memory_text), words[index], within)`. Pointer windows and BM25 search windows are dealt alternately.
- The memory text is never sent to a role.

---

## 7. Reflect

`gateway.py`: `body: dict[str, Any] = {"query": query, **_scope_fields(scope)}`; `include` = `{"facts": {}}`; optional `response_schema`. **Not sent:** `budget` (server default `low`), `max_tokens` (default 4096), `fact_types`, `exclude_mental_models`, `include.tool_calls`, `tag_groups`, `apply_all_directives`, the `reflect_search_observations_*` knobs.

Response kept: `text`, `based_on.memories` (as `CitedMemory`: `id?, text, type, context, occurred_start, occurred_end`; no `document_id`), `based_on.mental_models`, `structured_output`, `structured_output_error`, `usage`. Dropped: `based_on.directives`, `trace`.

Stored (`research_answer`): `answer_text`, `structured_output`, `structured_output_error` (Hindsight's, or Atlas's own JSON-Schema check), `raw_citations` (the `CitedMemory` dumps), `citations` (resolved), `quote_rule`, `run_id` with input/output tokens. Only resolved citations become Evidence. Reflect is used by the API (`POST /memory/reflect`) and replays; investigations do not call reflect.

---

## 8. Mental models (`mental_models/refresh.py`, `bank_template.py`, `configs/hindsight/bank-template.json`)

- Template 1.1.0: missions (`retain_mission`, `observations_mission`, `reflect_mission`), `enable_observations: true`, `disposition_skepticism: 4`, `disposition_literalism: 4`, five directives, two mental models (`theme-status`, `bottlenecks`), each `max_tokens` 2048, **no tags**, trigger `refresh_after_consolidation: false`, `refresh_cron: "0 6 * * *"`, `min_refresh_interval_seconds: 43200`. No `retain_strategies`, no entity labels, no other bank config.
- Applied via `POST /import?dry_run=true` then `POST /import`, recorded with version and manifest SHA-256.
- Daily job (06:30 UTC): `GET /mental-models/{id}`; skip if inside the minimum interval (later of Atlas's last request and Hindsight's `last_refreshed_at`) or `is_stale is False`; else `POST …/refresh`, poll the operation (240 s), then `GET` the model and store `content`, its SHA-256, `raw_citations` (the `reflect_response.based_on` memories flattened across fact types; directives and mental-models keys excluded), `refreshed_at`, operation `result_metadata`. Citations are resolved on read, not stored resolved.
- Mental-model content reaches the Scout (the Bottlenecks content as its open gaps) per AGENTS.md; not verified in my slice's code.

---

## 9. Replay (`replay/service.py`)

- Retain: per Source Version, every section (triage bypassed), same `retain_item`/`version_tags`, one batch, waited on synchronously in the step; zero-fact sections not reprocessed; fact count from `GET /documents/{id}` (404 counts 0). Ledger: `replay_document`.
- Consolidation asked explicitly (`POST /consolidate`), waited on, bounded.
- Questions: `gateway.recall(question, scope=tag_scope)` (budget default `mid`) and `gateway.reflect(question, scope=tag_scope, include_facts=True)`; no `query_timestamp`.

---

## 10. What Atlas visibly does not pass or keep

Retain item: `entities` (Atlas knows company names, CIKs, products), `observation_scopes` (default `combined`), `strategy`, `update_mode`; request-level `operation_id` (idempotent resubmission).
Recall: `types`, `max_tokens`, `include.chunks`, `include.source_facts`, `prefer_observations`, `query_timestamp`, `temporal_window`, `min_scores`, `tag_groups`, `trace`. Kept nowhere: `scores`, `entities`, `chunks`, `source_facts`, `attachments`; `document_id`/`chunk_id`/`metadata` are used for resolution but not returned by Atlas's recall API.
Reflect: `budget` (so `low`), `max_tokens`, `fact_types`, `exclude_mental_models`, `include.tool_calls`; dropped `trace`, `based_on.directives`.
Operations: `result_metadata.extraction_errors_count` not read; `child_operations` read only for error classification, not per-section outcome; `operation_ids` in the retain answer ignored.
Observation scopes listing (`GET …/observations/scopes`) never called.

---

## 11. The observation-scope interaction (cross-slice, high importance)

`developer/api/retain.md`: "During consolidation, Hindsight uses `all_strict` matching to find existing observations to update — only observations whose tags exactly match the current scope are considered." and "#### combined *(default)*" / "One consolidation pass using all tags together. The resulting observation is tagged with the full set." `developer/observations.md`: "By default, observations are scoped to all of a memory's tags combined."

Atlas sends no `observation_scopes`, and its tag set per item is `{company, every theme of the company, source, doctype, form}`. Read together, observations would consolidate only among facts with the identical tag set: one company's 10-K facts apart from its 10-Q and 8-K facts, SEC filings apart from transcripts (`source:tradingview`), and never across companies. That would limit observations to single-company, single-form syntheses, which matters for a supply-chain memory where the value is cross-document and cross-company. This is my reading of the docs, not observed behaviour; the lead's observations slice and a look at `GET …/observations/scopes` on production would settle it.

---

## Not covered / unsettled

- Whether one failed chunk or sub-batch fails the whole retain operation (Hindsight side).
- How the job queue handles a `poll_operation` that failed after its attempts (whether `_enqueue_polls` can re-enqueue the same `poll:<op>` key); sections would stay `pending` with an operation ID and are not resubmitted by `retain` (it only submits rows with `operation_id IS NULL`).
- Production numbers (I made no network call).
- `atlas.research.quotes`, `atlas.research.search`, the investigation task runner beyond the recall call sites, the Scout's use of mental-model content.
- Hindsight's retain/recall/observations concept pages beyond the lines quoted (lead's slice).
