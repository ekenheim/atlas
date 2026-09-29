# 17: Live test suite

**What to build:** The Phase 2 gate scenarios can be re-run end to end against real Hindsight 0.10.1 and MiniMax through LiteLLM, on demand, never in CI. Spec Part B: Testing Decisions (live tests).

**Blocked by:** 15 (Recall and reflect with resolved citations)

**Status:** done (live run 2026-09-29, small profile: 7 passed, 1 skipped; see the implementation log)

- [x] An opt-in marker runs the gate scenarios against the local spike-style stack (run live 2026-09-29 against the Compose `hindsight` profile with MiniMax-M3)
- [x] The suite is excluded from CI and refuses to run without explicit opt-in
- [x] Results are recorded in the implementation log, stating clearly which paths were live-tested
