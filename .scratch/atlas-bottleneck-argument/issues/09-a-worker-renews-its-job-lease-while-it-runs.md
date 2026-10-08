# 09: A worker renews its job lease while it runs

**Status:** done (8 October; awaiting CI and release)
**Type:** bug

**What happened:** a worker claims a job for `job_lease_seconds` (300 s) and never renews the lease while the job runs (`atlas.jobs.queue.claim`, `atlas.jobs.worker`). Once a lease expires, another worker may claim the job. On the 0.5.5 pilot (2026-10-08), every argument Editor ran past 5 minutes because of the two judge votes per statement and the rewrites. Each was started a second time while the first attempt was still running: questions 1, 2 and 3 (events: two `task_started editor`). The first attempt to finish wrote the card; the second then failed with `RoleCallFailed: no unfinished run` and left the task `queued` on a stopped investigation. On 0.5.4, question 1, three Readers ran twice. The cost is duplicate MiniMax calls and inflated token counts. Mitigated in configuration: `ATLAS_JOB_LEASE_SECONDS=1800` (home-ops #7367).

**What to build:**
- While a job runs, the worker extends its lease every `job_lease_seconds / 3`, in a background heartbeat that stops when the job finishes. The extension is `UPDATE job SET lease_expires_at = now() + lease WHERE id = :id AND lease_owner = :owner AND status = 'running'`; a lost lease stops the heartbeat and is logged.
- A task whose investigation has stopped finishes as done (`skipped`, with a reason), not `queued`.
- The lease can then return to a few minutes, so a crashed worker's job is reclaimed quickly.

**Acceptance:**
- [x] An integration test: a job that runs longer than its lease, with the heartbeat on, is not claimed by a second worker.
- [x] A crashed worker's job (no heartbeat) is reclaimed after the lease.
- [x] A task finishing after its investigation stopped is not left `queued`.
