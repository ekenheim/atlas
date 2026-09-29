# 28: Live extraction smoke test

**What to build:** A small, bounded, opt-in live check of the Investigator on real MiniMax output, done before the workflow, scenarios and snapshots are built on top of it. The risk it measures is that models count characters poorly, so the exact span check may reject most true Claims as `quote_mismatch`. The check runs `extract_claims` over 2–3 recorded Source Versions (a Lumentum 10-K section, an EX-99.1 release, one supplier-rich passage) and reports acceptance, the rejection reasons and the tokens used. If `quote_mismatch` dominates, the decision on quote location (search for a quote that occurs exactly once in its passage, recording the located offsets) is put to the owner, with numbers.

Spec: `.scratch/atlas-phase3-6a/spec.md`; ticket 10's open risk.

**Blocked by:** None (can start immediately; uses the merged ticket 10)

**Status:** done

- [ ] An opt-in live test (the `live` marker and `ATLAS_LIVE_TESTS=1`) that makes at most ~10 MiniMax calls and records a report: Claims proposed, accepted, rejected by reason, and tokens. *(The smoke run was made (4 calls) and reported, but no such test is committed on the branch this closes from; see the implementation log.)*
- [x] Run once with the owner's go-ahead, with results in the implementation log (never claimed as more than it measured).
- [x] If quote mismatches exceed ~20% of otherwise valid Claims: a decision entry with the measured numbers and the proposed fix, for the owner.

**Outcome (2026-09-29):** 3 Claims proposed, 3 rejected `quote_mismatch` (2 quotes exactly once in their passage, 1 paraphrase). Owner decided to locate quotes: `docs/decisions.md`, "Claim quotes are located, not trusted"; implemented with `claim.offset_source` and `quote_ambiguous` (migration 0024).
