# Hindsight 0.10.1 feature check → feature matrix + recorded fixtures

Type: task
Status: resolved
Blocked by: 01, 04

## Question

Against the pinned version in Compose, using a model that worked in the bake-off, verify each §6.1 feature live and mark it verified / behaves differently / absent:

- retain sync/async/batch and document_id upsert
- strict tags
- reflect JSON Schema + provenance
- operations
- bank templates
- observations
- mental models
- knowledge pages
- export/import

Save each request/response pair as a versioned fixture (Q11). Output: `docs/hindsight-feature-matrix.md`, with every row linking its recordings, plus the fixture directory. Explicitly test that re-retaining the same document_id deletes the earlier extraction, and that `query_timestamp`/`temporal_window` are not hard filters.

Inputs from ticket 04:

- Reuse `spikes/hindsight/` (compose, `run.sh`, fixture, harness).
- Known so far:
  - `WORKER_MAX_SLOTS` must be ≥ 3
  - union types in `response_schema` return a 500
  - `/llm-requests` gives a per-bank LLM log
  - reflect includes raw chunks
  - async retain + operation polling works (`status: completed`)

## Answer

Done 2026-09-28: `docs/hindsight-feature-matrix.md`, with 58 recordings in `spikes/hindsight/recordings/` (the CI contract fixtures).

- **Verified:**
  - retain: sync, async and batch (one operation per batch)
  - the operations API and the bank config API
  - strict tags (`any_strict`, `all_strict`, `exact`)
  - bank templates, including export, dry-run and import
  - observations, mental models (create, refresh, history), knowledge pages
  - document export/import (copies memories with no LLM calls)
  - the per-bank LLM log
- **Confirmed as the spec warned:**
  - `document_id` upsert destroys the earlier version's facts, so per-version IDs are required
  - `tags_match=any` includes untagged memories
  - a 2024 `temporal_window` still returned 7/14 results dated 2026, so it's not a filter
- **Behaves differently:**
  - reflect citations carry no `document_id` (they were all observations). Provenance is two hops: observation → `source_memory_ids` → world fact → `document_id` + Atlas `metadata`
  - union types in `response_schema` return a 500
  - observations are listed via `memories/list?type=observation`, and knowledge pages via `knowledge-base/tree` (the documented list routes return 405)
- **Not verified:** the retry/delete endpoints, mental-model refresh loops, `refresh_after_consolidation`, tenant auth, sustained load.
