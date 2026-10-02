# 03: A section's outcome comes from its own document

**What to build:** When a retain operation fails, only the sections Hindsight did not store are failed; a section that was stored counts as retained. A timeout or a relayed server error is tried again instead of being final. A section whose extraction was partial is told apart from one with nothing material in it. The owner can re-enqueue failed sections by error class and by company.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Intake that doesn't lose sections"). Study: finding 1.

**The evidence this ticket builds to (the lead, 2026-10-02):** production's 1,907 failed sections are not failures: the owner cancelled those retain operations early in the rollout (said 2026-10-02). A sample on the same day agrees: of the latest 425 Source Versions across the 12 universe companies, all 386 failed sections carry the one error "Hindsight reported the operation cancelled with no error message", from 78 cancelled operations; no other error text occurs. So the first thing to build is the cancelled state; the rest of the ticket hardens code paths that are weak by reading and have not been seen to fail on production.

- **Cancelled is not failed.** An operation Hindsight reports as cancelled leaves its sections in a `cancelled` state of their own; the metric (`atlas_retained_sections_total`), the memory read and the health read show it apart; `retry-failed` and the backfill enqueue cancelled sections again. A migration moves the sections recorded as failed with the error "Hindsight reported the operation cancelled with no error message" to `cancelled`.

- After an operation ends, whatever its state, each pending section's outcome is read from its own Hindsight document: stored with facts is completed, stored with none is zero-fact (the existing one reprocess first), absent is failed with the operation's error.
- A transient class for timeouts and relayed 5xx errors: the section stays pending and is resubmitted with the queue's backoff, at most a bounded number of times (a setting), then failed with the class recorded.
- The operation's `extraction_errors_count` is read: a completed section whose operation reported extraction errors is recorded as partial and retried once; the count is kept on the section's record.
- `atlas retention retry-failed` gains `--error-class` and `--company`, and enqueues as backfill class.
- If the error grouping shows long Items failing by size, say so in the log and stop there: splitting an Item changes section identity and is its own ticket (the spec's decision).
- `docs/decisions.md`: the outcome rule and the failure classes; `docs/runbooks.md`: retrying by class.

Migration revision `0061` (down: main's head).

**Blocked by:** None (can start immediately; the error grouping it waited for is above)

**Status:** ready-for-agent

- [ ] An operation that ends cancelled leaves its sections `cancelled`; the metric and the memory read show them apart from failed; `retry-failed` enqueues them; the migration moves the existing rows (migration test).
- [ ] Integration test at the worker seam with the Hindsight fake: an operation of three sections ends failed with one document stored with facts, one stored empty and one absent; the three sections end completed, zero-fact (after one reprocess) and failed.
- [ ] A timeout error leaves its sections pending and resubmits them; after the bound they are failed with the class; a quota error still pauses the queue as today.
- [ ] A completed operation with extraction errors marks its sections partial and retries once.
- [ ] `retry-failed --error-class … --company …` re-enqueues only those sections, as backfill class (CLI test).
- [ ] The health read of ticket 02 shows partial and the classes (or the log says what to add when 02 merges first).
- [ ] Decision and runbook entries; `AGENTS.md` line.
