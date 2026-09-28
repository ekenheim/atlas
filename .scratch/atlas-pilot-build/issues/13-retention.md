# 13: Retain Source Versions into memory

**What to build:** Every new Source Version is retained section by section into the research bank, tracked until done, and mapped back to the ledger. Zero-fact and failed sections are visible. Coherent is ingested alongside Lumentum. Spec Part B: Retention service, Schema; ADR-0001; stories 1–11.

**Blocked by:** 07 (Ingest a Lumentum filing end to end), 12 (Hindsight in Compose and bank template)

**Status:** ready-for-agent

- [ ] Document IDs follow ADR-0001; tags and metadata as specified; a Source Version whose raw hash is already retained is linked, not re-retained
- [ ] One batch per Source Version, operation-polled; the memory-document mapping records state and fact counts
- [ ] A zero-fact section is reprocessed once, then shows `zero_fact`; failed operations are visible
- [ ] A replayed identical retain does no duplicate work; a revised source gets new documents while the old ones stay auditable
- [ ] `GET /api/v1/source-versions/{id}/memory` shows section documents, states and counts
