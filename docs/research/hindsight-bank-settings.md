# The research bank's settings, reviewed (2026-10-03)

Read live from `GET /v1/default/banks/atlas-ai-infrastructure/config` (Hindsight 0.10.2), against the pinned docs (`.agents/skills/hindsight-docs`). The bank has 51 settings: 14 overridden on the bank, 37 taken from the server's defaults, which the owner or a Hindsight upgrade can change without Atlas knowing. **Correction (memory-quality ticket 23):** of the 14, only 10 were set by Atlas's bank template (`configs/hindsight/bank-template.json`, 1.4.0); 4 had been set on the bank directly, outside it: `consolidation_llm_batch_size` (8), `consolidation_source_facts_max_tokens` (4096), `consolidation_source_facts_max_tokens_per_observation` (256) and `max_observations_per_scope` (-1).

**Since template 1.5.0 (memory-quality ticket 23) the template owns all 14 and pins nine of the defaults besides:** the four overrides above at those values, and `enable_temporal_retrieval`, `enable_graph_retrieval`, `enable_text_search`, `enable_reranking`, `store_document_text`, `entities_allow_free_form` (all true), `retain_extraction_mode` (`concise`), `retain_chunk_size` (3000) and `consolidation_max_memories_per_round` (100), each at the value in the table below. `BankTemplate.load` refuses a template that leaves one of these 13 out or nulls it (`docs/decisions.md`, "The bank template pins what Atlas relies on"). The rows below marked **Pinned** are the nine defaults.

## The 14 Atlas sets

(Four of them, the consolidation batch size, the two source-fact limits and `max_observations_per_scope`, were set on the bank outside the template until 1.5.0; see the correction above.)

`retain_mission`, `observations_mission`, `reflect_mission`, `entity_labels` (the `layer` group), `enable_observations`, `enable_auto_consolidation` (false), `max_observations_per_scope` (-1), `consolidation_llm_batch_size` (8), `consolidation_source_facts_max_tokens` (4096) and `…_per_observation` (256), `reflect_source_facts_max_tokens` (4096), `recall_include_chunks`, `disposition_skepticism`, `disposition_literalism`. Reviewed with their tickets (memory-quality 05, 06, 10, 19).

## The server defaults that matter to Atlas

| Setting | Value | What it does (docs) | For Atlas |
|---|---|---|---|
| `enable_temporal_retrieval` | true | The temporal recall arm and the date-aware query analysis that feeds it | **Keep on. Pinned (1.5.0).** Atlas's content is dated and every retain item carries a timestamp (`event_date` = the version's `available_at`, checked on one document); pointer recalls send `query_timestamp`. Without a timestamp, temporal ranking is off entirely (best practices). |
| `enable_graph_retrieval`, `enable_text_search`, `enable_reranking` | true | The graph, keyword and rerank stages of recall | Keep on: recall as a reading index (ticket 07) was measured with all of them. **Pinned (1.5.0).** |
| `retain_extraction_mode` | `concise` | "Selective: only facts worth remembering long-term"; `verbose` captures more detail per fact, slower and more tokens | **Open question; pinned at `concise` (1.5.0)** until measured. Concise may drop figures and terms an analyst needs. Changing it re-extracts the whole bank, so measure first: `verbose` against `concise` on the conformance bank's sections and the known answers. |
| `retain_chunk_size` | 3000 | Characters per extraction chunk | Unmeasured; filings' sections run to 80,000 characters. Measure with the extraction mode, never alone. **Pinned (1.5.0).** |
| `consolidation_max_memories_per_round` | 100 | A round's size; the job then re-queues itself for fairness | Explains the chained rounds (memory-quality ticket 20). Raising it gives fewer, longer rounds, not less work. **Pinned (1.5.0).** |
| `consolidation_llm_parallelism` | 4 | **Tag groups** consolidated at once | **Pinned at 1 (1.6.0).** Believed on 2026-10-03 to have no effect (one scope, so one tag group, serial); wrong for 0.10.2 (checked 2026-10-08 in `consolidator.py`): with one tag group the fair fetch takes ceil(50 / parallelism) facts per fetch, so at 4 the batches are 8, 5, then 3, 2, 1, 1, 1, 1 in a 100-fact round (about 20 calls, mean about 5 facts, not 8). At 1 each call gets the full `consolidation_llm_batch_size` (Atlas's 8; 9,000 to 20,000 input tokens a call). Measure 16 on the conformance bank. |
| `entities_allow_free_form` | true | Entities beyond the given ones are extracted | Keep: counterparties and products come from it. **Pinned (1.5.0).** |
| `store_document_text` | true | The document's text is stored | Required: chunk-exact pointers (ticket 08) read it. **Pinned (1.5.0).** |
| `recall_max_tokens` (2048), `recall_chunks_max_tokens` (1000), `recall_budget_*` | | The recall **reflect's agent** runs internally (and a model's refresh) | Atlas's own recalls set their budgets per request (8192 for pointer recalls). Reflect's internal recall gets a quarter of that; consider raising it if a reflect answer looks under-read. |
| `mental_model_min_refresh_interval_seconds` | 0 | Server-wide floor | The template's models carry their own interval (ticket 10). |
| `memory_defense` | null | Sensitive-data screening of retained content | Not needed: Atlas retains public filings and transcripts. |
| `audit_log_enabled` | false | Hindsight's own audit log | Atlas audits its own acts. |
| `retain_strategies`, `consolidation_strategies`, `retain_custom_instructions`, `knowledge_page_default_trigger`, `reflect_default_options` | null | Per-call or per-scope overrides | Unused. A transcript strategy (other chunking) is a candidate later. |

## Found on the way

- **Hindsight traces every LLM call per bank** (`GET …/banks/{bank}/llm-requests`, on by default, kept 1 day): operation, model, input/output/cached tokens, duration, status. 15,749 calls in the last day; a consolidation call is 9,000 to 20,000 input tokens on `gpt-5.6-luna`. This is the measurement the parked fix needs (retains budgeted by the tokens Hindsight spends, not operations: map, "The retain budget counts operations"), and the reconciliation check can read it.
- **Pin what Atlas depends on.** The 37 defaults can change under Atlas. The template should set the ones above it relies on (temporal, graph, text, rerank, `store_document_text`, the extraction mode, the chunk size, the round size) explicitly, so a server change cannot change Atlas's memory silently, and the reconciliation check should compare the live config with the template's. **Done in template 1.5.0** (memory-quality ticket 23, with `entities_allow_free_form` too, and the four overrides set on the bank outside the template); the comparison is the reconciliation's `config_drift` (ticket 22).
