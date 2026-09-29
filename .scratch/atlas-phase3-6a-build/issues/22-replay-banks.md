# 22: Replay banks

**What to build:** A replay job evaluates the pipeline as of a cutoff in an isolated `atlas-replay-<id>` bank on the local Hindsight: it re-retains only Source Versions with `available_at ≤ cutoff` in order, waits for consolidation, runs the fixed question set, records results and deletes the bank.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 20 (Publish gate and Research Snapshot)

**Status:** ready-for-agent

- [ ] `replay-jobs` API and job
- [ ] Runs against the recorded fake in CI; live run on the local Compose Hindsight is opt-in
- [ ] Gate test: a synthetic future-dated fixture is accepted 0 times (absent from recall and resolved citations)
- [ ] Replay banks are always deleted, also on failure
