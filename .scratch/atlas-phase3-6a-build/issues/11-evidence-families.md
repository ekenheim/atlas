# 11: Evidence Families

**What to build:** Syndicated copies of one announcement are grouped into one Evidence Family: exact duplicates by content hash, near-duplicates by 64-bit SimHash on normalized parse text (Hamming ≤ 3, recorded per family). One family counts as one witness.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Family assignment on new parsed Source Versions, with the threshold recorded
- [ ] Unit tests of SimHash grouping
- [ ] Gate test: syndicated fixture stories count as one Evidence Family
- [ ] Families are visible on the Source Version API
