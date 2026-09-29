# 28: Live extraction smoke test

**What to build:** A small, bounded, opt-in live check of the Investigator on real MiniMax output, done before the workflow, scenarios and snapshots are built on top of it. The risk it measures is that models count characters poorly, so the exact span check may reject most true Claims as `quote_mismatch`. The check runs `extract_claims` over 2–3 recorded Source Versions (a Lumentum 10-K section, an EX-99.1 release, one supplier-rich passage) and reports acceptance, the rejection reasons and the tokens used. If `quote_mismatch` dominates, the decision on quote location (search for a quote that occurs exactly once in its passage, recording the located offsets) is put to the owner, with numbers.

Spec: `.scratch/atlas-phase3-6a/spec.md`; ticket 10's open risk.

**Blocked by:** None (can start immediately; uses the merged ticket 10)

**Status:** done

- [x] An opt-in live test (the `live` marker and `ATLAS_LIVE_TESTS=1`) that makes at most ~10 MiniMax calls and records a report: Claims proposed, accepted, rejected by reason, and tokens.
- [x] Run once with the owner's go-ahead, with results in the implementation log (never claimed as more than it measured).
- [x] If quote mismatches exceed ~20% of otherwise valid Claims: a decision entry with the measured numbers and the proposed fix, for the owner.
