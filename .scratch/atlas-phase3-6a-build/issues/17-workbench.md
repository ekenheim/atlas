# 17: Research workbench page (D) and follow-up round

**What to build:** The researcher follows an investigation (plan, events, Evidence tray, contradictions, open questions) in a workbench page and launches one bounded follow-up round on an open question.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 15 (Skeptic); 16 (Hypotheses)

**Status:** done

- [x] `POST investigations/{id}/follow-up` limited to one round within budget
- [x] Workbench page; API client regenerated
- [x] Playwright test: open an investigation, see its events and Evidence, launch a follow-up
