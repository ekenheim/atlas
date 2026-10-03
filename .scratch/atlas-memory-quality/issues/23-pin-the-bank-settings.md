# 23: The bank template pins the settings Atlas relies on

**What to build:** bank template `1.5.0` sets explicitly the server-default settings Atlas's memory depends on, at today's values, so that a change of the server's defaults (by the owner or a Hindsight upgrade) cannot change Atlas's memory silently. No behaviour changes: every value is what the bank runs with today.

Evidence: `docs/research/hindsight-bank-settings.md` (the lead's review of the bank's 51 settings, 2026-10-03): 14 are set by the template, 37 come from the server's defaults.

Decided by the lead:
- **Pinned** (live values on 2026-10-03): `enable_temporal_retrieval: true`, `enable_graph_retrieval: true`, `enable_text_search: true`, `enable_reranking: true`, `store_document_text: true`, `entities_allow_free_form: true`, `retain_extraction_mode: "concise"`, `retain_chunk_size: 3000`, `consolidation_max_memories_per_round: 100`.
- Each must be a field the recorded template schema accepts (`spikes/hindsight/recordings/bank_templates/01-schema`); one it doesn't accept is left out and named in the log, not forced.
- `BankTemplate.load` refuses a research template that leaves out a pinned field, as it refuses one without `enable_auto_consolidation: false` (template 1.4.0). Replay and evaluation banks keep taking the template as today.
- The applied template's version is recorded as today (`atlas hindsight apply-template --if-changed`); the deploy's own apply imports it.

**Blocked by:** None.

**Status:** done

- [x] The template validates against the recorded schema and imports through the fake with the pinned values; a research template missing any pinned field is refused by a test.
- [x] Decision note ("The bank template pins what Atlas relies on"), `AGENTS.md` (the template line), and `docs/research/hindsight-bank-settings.md` updated to say they are pinned.
