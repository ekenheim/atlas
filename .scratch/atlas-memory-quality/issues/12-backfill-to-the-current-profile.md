# 12: The corpus already in Memory, brought to the current standard

**What to build:** One job per company brings its retained sections to the current retain profile (context, entities, scopes, labels) and retries its failed ones, without fetching or parsing anything again, and then has Memory consolidate. The owner sees its progress and its end state in the health read.

Spec: `.scratch/atlas-memory-quality/spec.md` ("The backfill"). Ticket 01 says how a stored document takes a new profile (`reprocess`, or a retain under the same `document_id`); build to that answer. Ticket 15 says which embedding model the backfill runs under.

- `atlas memory backfill --company <slug>... | --theme <slug> [--max-sections N] [--key K]` enqueues a backfill-class job per company. It takes the sections whose profile is older than the current one, and the failed and cancelled ones, newest documents first, and re-retains them through the existing retain path (same document ID, so Hindsight replaces that document's memories), under the retain budget, in the backfill window, never using the interactive reserve. A rerun takes the next sections; an interrupted run resumes.
- The cancelled sections (the owner cancelled about 1,900 sections' retains early in the rollout; ticket 03 gives them their own state) are the larger part of the work: the job takes them like the failed ones. Its pace is set by what consolidation costs on the shared Codex subscription (ticket 01's measurement), not by extraction: `--max-sections` and the retain budget keep a night's run inside what the owner allows, and the runbook says how many sections that is.
- Sections triage skipped stay skipped. A section retained on demand stays retained.
- When a company's sections are done, the job asks for consolidation and records the operation.
- The job's artifacts and `GET /api/v1/memory/health` show, per company, sections at the current profile, below it, failed and pending.
- An Assertion, a reading pointer or a snapshot that named an older memory keeps its record: pointers are insert-only history, and provenance of a replaced memory reads as replaced, not broken (the resolver's states gain it if the fake shows a replaced memory disappears).
- `docs/runbooks.md`: "Memory backfill" (order, budget, how long, how to stop); `docs/decisions.md`: the rule for replaced memories.

Migration revision `0067` (down: main's head), only if a record needs it.

**Blocked by:** 03, 04, 05, 06, 15

**Status:** ready-for-agent

- [ ] Integration test at the CLI and worker seams: a company with sections at an old profile, at the current one and failed; the job re-retains the first and the last, leaves the second, and ends with a consolidation operation; a rerun does nothing.
- [ ] `--max-sections` bounds a run and a second run continues; a quota pause holds it and it resumes.
- [ ] A pointer recorded before the backfill still reads, with its memory's state.
- [ ] The health read shows the profile counts.
- [ ] Runbook and decision entries; `AGENTS.md` line.
