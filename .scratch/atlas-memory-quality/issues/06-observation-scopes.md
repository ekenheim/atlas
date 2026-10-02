# 06: Observations consolidate across each theme

**What to build:** What Memory consolidates about a company draws on all of that company's documents, and what it consolidates about a theme draws on all the theme's companies. Today an observation exists only among memories with exactly the same tags, so nothing crosses a form, a source or a company.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Observation scopes"). Study: finding 2 (observed on production). Recordings: ticket 01 (`observation_scopes`, `GET …/observations/scopes`, and whether stored memories can change scope).

- **Decided by the lead after ticket 01's measurement (2026-10-02): one scope per theme, no company scope.** Consolidation costs one LLM request per scope a run touches, on the shared Codex subscription, and a theme's scope already draws on every document of every company in it. So a company-and-theme pair would double the cost for nothing a theme scope lacks; one scope per theme costs what today's default costs. Each retain item sends explicit `observation_scopes`: one scope with each of its theme tags. The company, source, document type and form tags stay on the item for filtering.
- What it gives up, stated in the decision entry: a recall scoped to a company alone returns that company's facts and no observation (a theme observation carries no company tag). Investigations and the Skeptic recall across the theme, so nothing built today loses by it.
- The provenance resolver and the recall scope keep working for an observation tagged with a theme alone: a theme-scoped recall returns it; a company-scoped recall returns facts only (the recordings `observation_scopes/` and `tags/` show what `any_strict` matches).
- An observation resolves to sections through its source facts as today; a theme observation's sources may lie in several companies' documents, and every source is listed.
- Replay banks and evaluation banks send the same scopes.
- The health read (ticket 02) lists the scopes; this ticket adds nothing there beyond a test that the new scopes show.
- `docs/decisions.md`: "Observation scopes: one per theme" with the cost ticket 01 measured and what a company-scoped recall no longer returns.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Integration test at the worker seam: the retain request for a section of a company in one theme carries that one scope; a company in two themes carries two.
- [ ] With the fake deriving observations per scope: a theme-scoped recall returns an observation whose sources are sections of two companies, each resolved; a company-scoped recall returns that company's facts and no observation.
- [ ] Replay and evaluation retains carry the scopes.
- [ ] Decision entry; `AGENTS.md` line.
