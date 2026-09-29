# 17: Live test suite

**What to build:** The Phase 2 gate scenarios can be re-run end to end against real Hindsight 0.10.1 and MiniMax through LiteLLM, on demand, never in CI. Spec Part B: Testing Decisions (live tests).

**Blocked by:** 15 (Recall and reflect with resolved citations)

**Status:** ready-for-human (built and rehearsed against the recorded fakes; the live run awaits the owner's go-ahead, because it spends MiniMax quota: `scripts/live-tests.sh`, see `docs/runbooks.md`)

- [ ] An opt-in marker runs the gate scenarios against the local spike-style stack (built, and rehearsed end to end against the recorded fakes; **not yet run against the real stack**)
- [x] The suite is excluded from CI and refuses to run without explicit opt-in
- [ ] Results are recorded in the implementation log, stating clearly which paths were live-tested (the log records that nothing ran live yet; a live run's `summary.md` is the input for this)
