"""The prospective record (atlas-beliefs ticket 19): calls and predictions, dated and settled.

The owner's aim is early calls, and a replay of a known winner cannot show them. So Atlas keeps
a dated record of what it says, made now and read against what follows:

- `model`: what a call is (a Belief judged `proven`, a published Hypothesis version, an archive
  signal a Scout session escalated to a question Issue), the horizons (+1, +3 and +6 months),
  the due dates and the arithmetic of a checkpoint; `record`: making a call, in the transaction
  of the event that makes it, dated by that event and never earlier, and the backfill of the
  Beliefs proven before this existed; `settle`: the daily `settle_calls` job that appends the
  checkpoints; `reads`: `GET /api/v1/calls`.
- A published Hypothesis's measurable predictions as rows with their settlements:
  `atlas.hypotheses.predictions`.

Every table is insert-only. Closes are used only to score; they are never a Belief's evidence.
Rules in `docs/decisions.md`, "The prospective record"; `docs/runbooks.md`, "Calls".
"""
