# 11: A plan limit is a quota failure, not an error

**Status:** done
**Type:** bug

**What happened:** on 2026-10-09 MiniMax's weekly plan limit was reached. LiteLLM relayed HTTP 402 with `{"type":"error","error":{"type":"insufficient_balance_error","message":"The Token Plan usage limit has been reached. ..."}}`. `RoleCaller` classified only 429 and 5xx by status, `budget_exceeded` by type, and read error text only for a 5xx, so the 402 raised `RoleCallFailed`. Each task burned its 3 attempts in seconds; investigations d85faae2 and 5e1088d7 stopped `needs_review` with their Readers cancelled (events at 11:19 UTC).

**What to build:** classify the error type and text for every non-success status, so this answer is a `quota` `TransientFailure` (the queue pauses with backoff, as for a 429). Genuine 4xx request errors stay `RoleCallFailed`.

**Acceptance:**
- [x] A 402 `insufficient_balance_error` pauses the queue (`quota`), requeues the job without an attempt and records no failed attempt. (`tests/integration/test_role_calls.py::test_a_quota_or_outage_failure_pauses_the_queue_and_requeues_the_job`)
- [x] A 400 with an unrelated message, and a 402 of another kind, are still `RoleCallFailed`. (`test_any_other_failure_is_an_ordinary_error_that_doesn_t_pause`, `test_a_4xx_without_quota_or_outage_text_stays_an_ordinary_error`)

**Answer (2026-10-12):** `docs/decisions.md`, "A MiniMax plan limit is a quota; a budget of 0 is a hold".
