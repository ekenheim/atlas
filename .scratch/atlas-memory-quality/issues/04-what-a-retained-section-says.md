# 04: What a retained section says: context, speaker, period and the companies in it

**What to build:** A section goes to Memory with a context that says whose document it is, what kind, for which period and who is speaking, and with the names of the companies Atlas knows are in it. A memory from an earnings call can then be told apart as management's statement or an analyst's question, and one company is one entity in Memory.

Spec: `.scratch/atlas-memory-quality/spec.md` ("What a retained section says"). Study: findings 4 and 5 (production context "Q4 2026: chunk-004"; no `entities` sent). Recordings: ticket 01 (`retain/entities`, and whether a stored document can take new context by `reprocess`).

- One function builds the context from the Source Version and the section: company display name, document kind and form, the period it reports on when known, the availability date, the section heading, and a speaker line by source type (a company's own filing: the filer is speaking; a call transcript: management and analysts speak, and an analyst's question is not the company's statement; a manual import: the publisher). Short, plain sentences; no identifier a reader could not use.
- `entities` on the retain item: the filer's canonical name, and the universe companies and counterparties the section's text names (the matcher passage selection uses for entity windows), each as written in the universe, with `resolve_entities` false.
- Metadata keeps the provenance keys unchanged and gains display keys (company name, form, period). The provenance resolver ignores the new keys.
- A `retain_profile` version on each memory document, with the context and entities sent, so the backfill (ticket 12) can find sections below the current profile. A section's memory read (`GET /api/v1/source-versions/{id}/memory`) shows them.
- Replay banks and evaluation banks send the same context and entities.
- `docs/decisions.md`: "What a retained section says" (the context's parts, why names are sent unresolved, what stays out).

Migration revision `0062` (down: main's head).

**From ticket 01 (the matrix's answer (a); recordings `reprocess/`):** a new context or new entities reach stored facts only through a new extraction. Retaining the same content again under the same `document_id` re-extracts nothing (Hindsight skips unchanged chunks) and `reprocess` replays the stored parameters. So this ticket changes what new retains send and records the profile; bringing stored sections to it is the backfill's work (ticket 12), which must delete and retain.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Unit tests of the context for a 10-K Item, an 8-K exhibit, a call transcript and a manual import: the expected text, exactly.
- [ ] Integration test at the worker seam: the retain request for a section that names another universe company carries the filer and that company as entities with `resolve_entities` false, the display metadata, and the context; the memory read shows the profile.
- [ ] A section retained before this ticket reads as an older profile.
- [ ] Replay and evaluation retains carry the same fields (their existing tests extended).
- [ ] Decision entry; `AGENTS.md` line.
