# 12: The corpus already in Memory, brought to the current standard

**What to build:** One job per company brings its retained sections to the current retain profile (context, entities, scopes, labels) and retries its failed ones, without fetching or parsing anything again, and then has Memory consolidate. The owner sees its progress and its end state in the health read.

Spec: `.scratch/atlas-memory-quality/spec.md` ("The backfill"). Ticket 01 says how a stored document takes a new profile (`reprocess`, or a retain under the same `document_id`); build to that answer. Ticket 15 says which embedding model the backfill runs under.

- `atlas memory backfill --company <slug>... | --theme <slug> [--max-sections N] [--key K]` enqueues a backfill-class job per company. It takes the sections whose profile is older than the current one, and the failed and cancelled ones, newest documents first, and re-extracts them: for a section already in Hindsight it deletes the Hindsight document and then retains it through the existing retain path under the same document ID (ticket 01 showed that a retain of unchanged content under the same ID re-extracts nothing, and that `reprocess` keeps the old context). The delete-then-retain path is not recorded yet: the first thing this ticket does is have the lead record it on the local Hindsight for one document (the facts, their observations and the document's row before and after), and build to that, under the retain budget, in the backfill window, never using the interactive reserve. A rerun takes the next sections; an interrupted run resumes.
- The cancelled sections (the owner cancelled about 1,900 sections' retains early in the rollout; ticket 03 gives them their own state) are the larger part of the work: the job takes them like the failed ones. Its pace is set by what consolidation costs on the shared Codex subscription (ticket 01's measurement), not by extraction: `--max-sections` and the retain budget keep a night's run inside what the owner allows, and the runbook says how many sections that is.
- **Order within a company:** the cancelled and failed sections first (they add what Memory lacks), then call transcripts (where the new context changes most: who is speaking), then the rest.
- **Order across companies:** the seed companies of the pilot's investigations first, thinnest in Memory first. The before-measure (pilot-review ticket 20) shows why: over 91 recalls Memory pointed at 144 distinct sections of Lumentum and 124 of Coherent, and at 12 of MACOM, 8 of Marvell and 4 of Ciena, which are the seeds of investigations 4 and 5. `--theme` enqueues in that order unless `--company` names one.
- Sections triage skipped stay skipped. A section retained on demand stays retained.
- When a company's sections are done, the job asks for consolidation and records the operation.
- The job's artifacts and `GET /api/v1/memory/health` show, per company, sections at the current profile, below it, failed and pending.
- An Assertion, a reading pointer or a snapshot that named an older memory keeps its record: pointers are insert-only history, and provenance of a replaced memory reads as replaced, not broken (the resolver's states gain it if the fake shows a replaced memory disappears).
- `docs/runbooks.md`: "Memory backfill" (order, budget, how long, how to stop); `docs/decisions.md`: the rule for replaced memories.

Migration revision `0067` (down: main's head), only if a record needs it.

**Blocked by:** 03, 04, 05, 06, 15

**Status:** done

- [x] Integration test at the CLI and worker seams: a company with sections at an old profile, at the current one and failed; the job re-retains the first and the last, leaves the second, and ends with a consolidation operation; a rerun does nothing.
- [x] `--max-sections` bounds a run and a second run continues; a quota pause holds it and it resumes.
- [ ] A pointer recorded before the backfill still reads, with its memory's state.
- [x] The health read shows the profile counts.
- [x] Runbook and decision entries; `AGENTS.md` line.

## Implementer's note

- The pointer box is left unticked on purpose: `test_a_memory_the_backfill_replaced_reads_replaced_not_broken` shows an observation consolidated from a replaced fact reading `unverified` / `memory_replaced` (not `broken`) through the recall API, and `reading_pointer` is insert-only and the backfill never touches it, but no test creates a pointer row through an investigation and reads it after a backfill. An observation Hindsight deleted with its facts is not known to Atlas by ID, so looked up alone it still reads `broken` (`docs/decisions.md`, "A backfill replaces a section's document").
- Recorded first: `spikes/hindsight/recordings/delete_and_retain/` (4 LLM requests of the cap of 8). The delete removes the document, its facts and the observations built only from them; the second retain extracts again and the new context, tags and entities reach the new facts, which have new IDs.
