# 12: A budget of 0 holds a provider

**Status:** done
**Type:** bug

**What happened:** the owner tried to hold MiniMax with `ATLAS_MINIMAX_BUDGET_TOKENS=1` (0 was refused: `ge=1`). The check admits a job while `used < budget`, and `used` is 0 at the start of each rolling window, so one task still ran per 5 h window (about 850k tokens on 2026-10-09; investigations d85faae2 and 5e1088d7).

**What to build:** allow 0 for the provider budgets and make it mean held: nothing claimed (interactive or backfill), `GET /api/v1/queue` shows `budget` 0 with both holds true, the queue unpaused. Document that 1 does not hold.

**Acceptance:**
- [x] A budget of 0 claims nothing and the queue read says so; a budget of 1 still admits the first call. (`tests/integration/test_quota_pacing.py::test_a_minimax_budget_of_zero_holds_the_provider_and_one_does_not`)
- [x] Runbook "Holding a provider" in `docs/runbooks.md`.

**Answer (2026-10-12):** `docs/decisions.md`, "A MiniMax plan limit is a quota; a budget of 0 is a hold".
