# 14: Queue pause and pacing

**What to build:** Quota and outage failures pause the ingest queue with backoff instead of failing jobs or switching models, and backfills run only in the nightly window. Both are visible to the owner. Spec Part B: Job queue extensions; stories 12–14 and 34–35.

**Blocked by:** 13 (Retain Source Versions into memory)

**Status:** ready-for-agent

- [ ] A 429- or outage-classified operation failure pauses the queue with backoff capped at 1 h, then resumes
- [ ] `GET /api/v1/queue` shows the pause state, backoff and pending jobs by kind
- [ ] Backfill-class jobs run only inside the configured nightly window
- [ ] Metrics exist for pauses, retains, zero-fact sections and operation outcomes, with alert rules for repeated failures and long pauses
