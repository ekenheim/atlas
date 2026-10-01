# 01: Reading pointers: the Scout's queries asked of Memory across the theme

**What to build:** After the Scout has written its queries, the investigation asks Memory each of them, and the question itself, with the theme's scope, and stores what comes back as reading pointers. A researcher opening the investigation sees, per query, the recalled facts with their company, document and section, labelled as Memory.

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("Reading pointer", "Pointers are stored", "The Scout task makes the recalls"). Evidence for the design: the recall probe in the spec's Problem Statement.

- One recall per Scout query plus one for the question, theme scope, through the existing scoped-recall service and provenance resolver. Only resolved citations become pointers; a Source Version available after the investigation's as-of time makes none.
- An insert-only pointer record per investigation and round: query (index and text), rank, memory id, type and text, Source Version, section anchor and offsets, company, citation state. Audited like the investigation's other records.
- `GET /api/v1/investigations/{id}` returns `pointers`; the Scout task's artifacts count recalls, memories and pointers by company. The investigation page lists them under the Scout, with the fact text marked as Memory, not Evidence.
- A recall that fails or returns nothing doesn't fail the Scout: the pointers are fewer, and the event log says so. An LLM-free Hindsight outage follows the existing pause rules.
- `CONTEXT.md` gains **Reading pointer**; `docs/decisions.md` gains "Memory as the reading index" (what it may do, what stays forbidden: Memory is never quoted, never a witness, never sent to a role as a statement).

Nothing reads the pointers yet in this ticket; tickets 05 to 07 do.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Integration test at the investigation seam: with memories derived from two companies' recorded filings (one a seed, one not), the Scout's two scripted queries produce pointers for both companies, each with its query, rank, section and memory text; the investigation read returns them; a version available after `as_of` gives none.
- [ ] A recall error on one query leaves the Scout succeeded with the other query's pointers and an event naming the failed query.
- [ ] The pointer table refuses UPDATE and DELETE; `atlas audit verify` passes.
- [ ] The investigation page shows the pointers (frontend unit test of the pure part; the API client regenerated).
- [ ] Glossary and decision entry; `AGENTS.md` line; migration with the revision the lead names.
