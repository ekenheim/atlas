# 21: Contradiction proposes an update

**What to build:** A later contradictory Source Version or Assertion flags the Hypothesis (or Candidate) with a proposed update and never changes the frozen snapshot.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 20 (Publish gate and Research Snapshot)

**Status:** ready-for-agent

- [ ] Contradiction detection on new Assertions against published versions' dependencies
- [ ] Proposed-update flag visible in the API
- [ ] Gate test: a later contradictory source leaves the snapshot untouched
