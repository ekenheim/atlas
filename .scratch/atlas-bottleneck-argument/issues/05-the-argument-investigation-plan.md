# 05: The argument investigation plan

**Status:** ready-for-agent (after 03 and 04)
**Type:** task
**Blocked by:** 03, 04

**What to build:** a second investigation plan, `argument`, chosen in the request (`{"plan": "argument"}`; the current plan stays the default until the argument plan beats it): Scout (leads, unchanged) → one Reader per argument step, in parallel (ticket 03) → Skeptic (it reads the Facts of every step and searches for counterevidence the same way, with ticket 01's search) ∥ Financial Analyst → Editor, which writes the card **as the argument**: each step with its status (`supported`, `disputed`, `unknown`), a statement, the Facts behind it (with their quantities, periods and status shown), the counterevidence, and what remains unchecked; every statement through ticket 04's judge. The research card keeps its current fields for the workbench, with the steps added.

**Acceptance:**
- [ ] The plan selectable by request; recorded on the investigation; the read side and the workbench show the steps (the frontend's research card shows steps when present; no new page).
- [ ] Tests: an argument investigation end to end with the scripted fakes (Readers, Skeptic, Analyst, Editor, judge) on the fixture filings, as the current plan's end-to-end test does.
- [ ] `docs/decisions.md`: "The argument plan" (why, what it replaces later, how it is compared).
