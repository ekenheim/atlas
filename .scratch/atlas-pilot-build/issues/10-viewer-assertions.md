# 10: Assertions in the viewer

**What to build:** The researcher can select a passage in the viewer to create an Assertion, and review Assertions there, completing the provenance slice without API tooling. Spec Part A: story 49.

**Blocked by:** 08 (Assertions and review), 09 (Source viewer (read-only))

**Status:** ready-for-agent

- [ ] Selection-to-Assertion submits the exact span and anchor, and a rejected span shows the reason
- [ ] Review actions update the state and are reflected in the list
- [ ] The Playwright test creates and reviews an Assertion
