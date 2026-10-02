# 03: A section's outcome comes from its own document

**What to build:** When a retain operation fails, only the sections Hindsight did not store are failed; a section that was stored counts as retained. A timeout or a relayed server error is tried again instead of being final. A section whose extraction was partial is told apart from one with nothing material in it. The owner can re-enqueue failed sections by error class and by company.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Intake that doesn't lose sections"). Study: finding 1 (695 completed against 1,907 failed on production). The error grouping of ticket 02's health read, run by the lead on production, is attached to this ticket before it starts: build to the errors that are there.

- After an operation ends, whatever its state, each pending section's outcome is read from its own Hindsight document: stored with facts is completed, stored with none is zero-fact (the existing one reprocess first), absent is failed with the operation's error.
- A transient class for timeouts and relayed 5xx errors: the section stays pending and is resubmitted with the queue's backoff, at most a bounded number of times (a setting), then failed with the class recorded.
- The operation's `extraction_errors_count` is read: a completed section whose operation reported extraction errors is recorded as partial and retried once; the count is kept on the section's record.
- `atlas retention retry-failed` gains `--error-class` and `--company`, and enqueues as backfill class.
- If the error grouping shows long Items failing by size, say so in the log and stop there: splitting an Item changes section identity and is its own ticket (the spec's decision).
- `docs/decisions.md`: the outcome rule and the failure classes; `docs/runbooks.md`: retrying by class.

Migration revision `0061` (down: main's head).

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Integration test at the worker seam with the Hindsight fake: an operation of three sections ends failed with one document stored with facts, one stored empty and one absent; the three sections end completed, zero-fact (after one reprocess) and failed.
- [ ] A timeout error leaves its sections pending and resubmits them; after the bound they are failed with the class; a quota error still pauses the queue as today.
- [ ] A completed operation with extraction errors marks its sections partial and retries once.
- [ ] `retry-failed --error-class … --company …` re-enqueues only those sections, as backfill class (CLI test).
- [ ] The health read of ticket 02 shows partial and the classes (or the log says what to add when 02 merges first).
- [ ] Decision and runbook entries; `AGENTS.md` line.
