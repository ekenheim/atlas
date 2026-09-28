# Hindsight 0.10.1 feature check → feature matrix + recorded fixtures

Type: task
Status: open
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
