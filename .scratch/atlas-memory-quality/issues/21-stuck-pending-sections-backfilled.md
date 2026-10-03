# 21: A section stuck pending in an old profile is backfilled

**What to build:** the memory backfill also takes a section that Atlas records `pending` under an older retain profile when no retain of it is in flight, deletes its Hindsight document (a 404 is fine: nothing was stored) and retains it again, like the sections it takes today.

Evidence (production, 2026-10-03, read by the lead):
- 58 sections of three source versions have been `pending` with `retain_profile` `retain-v1` since 2026-09-30 01:00 UTC: Coherent's 10-K filed 2026-08-14 (`de8239e5-…`, 24 sections), Lumentum's 10-K filed 2025-08-19 (`f4cd3b1d-…`, 24) and Lumentum's 10-Q filed 2025-05-07 (`c027dd1d-…`, 10). They are the health read's "pending, 1 to 7 days" group.
- Hindsight holds all 58 documents (created 2026-09-30 01:39 to 02:xx), retained under the old profile: no `observation_scopes`, no entities, the old context; 1,587 facts. They are the only documents of the bank's 2,666 without `observation_scopes`.
- The backfill (ticket 12) takes `failed`, `cancelled`, and `completed`/`zero_fact` sections below the profile (`_BELOW` in `backend/atlas/retention/backfill.py`), never a `pending` one, so these were never replaced. Their facts are the oldest in the bank, so a consolidation takes them first and forms observations scoped by company, form, source and document type: every such observation on production on 2026-10-03 came from these three documents.
- A plain retain would not fix them: a retain of unchanged content under the same document ID re-extracts nothing (ticket 01, `docs/hindsight-feature-matrix.md`), so Atlas would record the old facts as the current profile. The document must be deleted first, as the backfill does.

Decided by the lead:
- **Stuck:** `retain_state = 'pending'`, `retain_profile IS DISTINCT FROM` the current profile, the row not updated for `ATLAS_BACKFILL_STUCK_AFTER_HOURS` (default 24), and no `retain`, `poll_operation` or `reprocess` job queued or running for its source version. Such a section is a backfill candidate, ordered with the failed and cancelled ones (first).
- Everything else of the backfill is unchanged: delete, reset to `pending` under the current profile, record the replaced memories (`memory_replacement`), enqueue the backfill-class retain, follow, consolidate.
- The health read counts them: `stuck` per company and for the bank (pending in an older profile, not in flight).

**Blocked by:** None.

**Status:** done

- [x] Integration test at the worker seam: a section left `pending` under `retain-v1` with its document in the fake (retained, no job in flight, older than the threshold) is taken by `atlas memory backfill`: its document is deleted, it is retained again and completes under the current profile; a `pending` section with a retain in flight, or updated within the threshold, is not taken.
- [x] The health read shows `stuck` per company and for the bank.
- [x] Decision note ("A backfill replaces a section's document": the stuck case), runbook ("Memory backfill"), `AGENTS.md`, the setting documented; API client regenerated if the schema changed.
