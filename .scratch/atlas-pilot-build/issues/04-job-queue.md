# 04: Job queue and single-pass worker

**What to build:** Work runs through a Postgres job table with deterministic IDs from idempotency keys, leases, bounded retries and recorded failures. The worker runs continuously or in single-pass mode for tests. Job status is visible via the API, and jobs can be enqueued by CLI. Spec Part A: Jobs module, stories 23–24.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] Two concurrent workers never claim the same job (`FOR UPDATE SKIP LOCKED`)
- [x] Re-enqueuing with the same idempotency key does not create a second job
- [x] An expired lease is reclaimed, and retries stop at the bound with the failure recorded
- [x] `GET /api/v1/jobs/{id}` shows status, attempts, failures and produced artifacts
