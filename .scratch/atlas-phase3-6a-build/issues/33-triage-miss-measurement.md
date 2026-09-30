# 33: Measure what triage misses; overlapping windows

**What to build:** A measurement of retention triage's recall, as the Codex review (2026-09-30, item 3) asked, before any further tuning of triage cost. The measurement:
1. Samples sections that triage marked `skip`, stratified by form and section length, from real archived Source Versions.
2. Has each sample judged in full by a stronger, full-text reading: the same rubric, but the whole section, not its windows.
3. Reports the miss rate, meaning skipped sections the full reading would retain, by category and length band, with examples.

Also make triage windows overlap by a small margin, so a sentence at a window boundary is seen whole.

**Blocked by:** PR #1, "Measure the real system" (triage windows)

**Status:** done

- [x] `ATLAS_TRIAGE_WINDOW_OVERLAP_CHARS` (default 200). Windows overlap by that many characters, and unit tests cover the window boundaries.
- [x] `atlas triage audit [--sample N] [--company slug] [--seed S]` samples skipped sections deterministically (seeded), asks the full-section judge (a role call using the rubric with the whole text, chunked only when it exceeds the model context), and stores the results in an insert-only `triage_audit` table: section, triage decision and windows read, the judge's decision and reason, and agreement. It is paced under the `minimax` budget, and its summary (miss rate with a Wilson interval, by category and length) is printed and exposed at `GET /api/v1/triage/audits[/{id}]`.
- [x] Tests use the scripted LiteLLM fake: a skipped section whose key detail sits past the first windows is found by the judge and counted as a miss, and the sampling is deterministic.
- [x] Runbook (written, `docs/runbooks.md`, "Triage audit"; the live audit is not run yet): how to run the audit on the cluster archive or on a live-verify database, and how to read it. The first live audit (for example N=40 on Lumentum and Coherent) runs with the owner's go-ahead (given), and its numbers go in the implementation log.
