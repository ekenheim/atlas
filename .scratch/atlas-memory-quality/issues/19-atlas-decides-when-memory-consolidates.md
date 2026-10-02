# 19: Atlas decides when Memory consolidates

**What to build:** Consolidation of Atlas's bank runs when Atlas asks for it: once after a batch of retains, at night, counted against the budget and pausable. Today Hindsight consolidates by itself after every retain operation, on the owner's shared ChatGPT subscription, uncounted and at the worst time: while a backfill is still retaining.

Evidence (the owner's cluster, 2026-10-02, read by the home-ops assistant from Hindsight's own log): a consolidation backlog of 6,709 memories in Atlas's bank at about 10 seconds a memory, 18 to 20 hours, with the consolidation LLM call (`gpt-5.6-luna`) 75 to 85% of each memory's time and **one memory per LLM call** (`1 memories, 1 llm calls`), though the batch size is 8. The likely cause, not yet confirmed on the cluster: by the pinned docs (`developer/configuration.md`, "Observations") a consolidation run loads 50 memories at a time and works tag group by tag group, up to 4 at once, and by the home-ops assistant's reading of the consolidator it splits a load by tag group before it applies the batch size. Atlas's items carry company, theme, source, document type and form tags and no explicit scope, so the bank has dozens of tag groups (the same finding as the study's "observations never cross a company, a form or a source"), and a load of 50 would leave one or two memories in each. The other possible cause is a batch answer the model got wrong, which Hindsight splits into smaller batches; the cluster's log would show that. Ticket 06 (one scope per theme) makes Atlas's memories one group, so batches fill; this ticket decides when the run happens. Ticket 01 measured the cost side: one consolidation request per scope touched.

It is also waste today: the memories being consolidated were retained under the old profile, and the backfill (ticket 12) re-extracts them.

- **The bank template turns auto-consolidation off** for the research bank (`enable_auto_consolidation: false`, a per-bank field of the recorded template schema). Template version `1.4.0`; tickets 05 and 10 edit the same file as `1.2.0` and `1.3.0`: touch only this field.
- **A `consolidate` job** (pausable; provider `codex`, one unit per request Atlas submits): asks Hindsight to consolidate the research bank, records the operation, and polls it to its end like the replay's consolidate step, bounded. A run that is still going at the bound leaves the operation recorded as running and the next job picks it up instead of submitting another.
- **When it runs:** the worker enqueues one a day at `ATLAS_CONSOLIDATE_AT` (default 04:30 UTC, before the mental models' 06:30 refresh), as backfill class so it stays in the backfill window and off the interactive reserve; it is skipped when no section was retained since the last completed consolidation and when a retain, a poll or a reprocess of the bank is queued or running (consolidating half a filing is the waste this ticket ends; it tries again an hour later, a bounded number of times). `atlas memory consolidate [--key K]` asks for one by hand; the backfill (ticket 12) asks for one per company when its sections are done.
- **The record:** `GET /api/v1/memory/health` (ticket 02) gains `consolidation`: the last requested and last completed run, their operation IDs, and how many sections were retained since. A metric `atlas_consolidations_total{outcome}`.
- Replay banks and evaluation banks are unchanged (they already consolidate explicitly).
- `docs/decisions.md`: "Atlas decides when Memory consolidates" (why off, the daily run, the skip rule, what a day's delay costs: recall still returns the raw facts, reflect checks unconsolidated facts itself); `docs/runbooks.md`: how to ask for one, how to stop one (`DELETE …/operations/{id}` on Hindsight is the owner's), what the bank's setting must be.

Migration revision `0069` (down: the head in your base), only if the record needs a table; the `hindsight_operation` row may be enough.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] The template validates against the recorded schema and imports through the fake with `enable_auto_consolidation` false; a template without the field for the research bank is refused by a test.
- [x] Integration test at the worker seam: after an ingest's retains complete, no consolidation is requested until the `consolidate` job runs; the job submits one request, records and polls the operation, adds one `codex` unit, and is held by a spent window like the other `codex` kinds.
- [x] The daily job is skipped when nothing was retained since the last completed consolidation, and waits when a retain of the bank is queued or running (the clock of the harness moves it).
- [x] `atlas memory consolidate` enqueues one (CLI test); a second while one is running does not submit another request.
- [x] The health read shows the consolidation record; the metric counts outcomes.
- [x] Decision and runbook entries; `AGENTS.md` line; the API client regenerated.

## Comments

**2026-10-02, the lead: the owner stopped the waste by hand.** After the lead's review of the cluster's consolidation log, the owner set `enable_auto_consolidation` to false on the research bank, cancelled the running consolidation operation and deleted its log entry (said 2026-10-02). So from now until this ticket ships, nothing consolidates in Atlas's bank: recall returns the raw facts, and the observations that exist stay as they are. Two things follow for the release:
- The template of the release must carry `enable_auto_consolidation: false` (this ticket), so the next template import keeps what the owner set. Tickets 05 and 10 also change the template; the three go out together, never 05 or 10 without this one.
- The first `consolidate` job after the deploy has the whole unconsolidated backlog to do. It should run after the backfill has re-extracted a company, not before: the release's runbook step says so.
