# 06: Observations consolidate per company and per theme

**What to build:** What Memory consolidates about a company draws on all of that company's documents, and what it consolidates about a theme draws on all the theme's companies. Today an observation exists only among memories with exactly the same tags, so nothing crosses a form, a source or a company.

Spec: `.scratch/atlas-memory-quality/spec.md` ("Observation scopes"). Study: finding 2 (observed on production). Recordings: ticket 01 (`observation_scopes`, `GET …/observations/scopes`, and whether stored memories can change scope).

- Each retain item sends explicit `observation_scopes`: one scope with its company tag, one with each of its theme tags. The source, document type and form tags stay on the item for filtering.
- The provenance resolver and the recall scope keep working for an observation tagged with a company alone or a theme alone: a theme-scoped recall returns theme observations and the theme's company observations; a company-scoped recall returns that company's observations and not another's. Whether a theme-scoped observation may be returned by a company-scoped recall is decided here and written down (the recordings show what `any_strict` matches).
- An observation resolves to sections through its source facts as today; a theme observation's sources may lie in several companies' documents, and every source is listed.
- Replay banks and evaluation banks send the same scopes.
- The health read (ticket 02) lists the scopes; this ticket adds nothing there beyond a test that the new scopes show.
- `docs/decisions.md`: "Observation scopes: a company, a theme" with the cost ticket 01 measured.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Integration test at the worker seam: the retain request for a section of a company in one theme carries the two scopes; a company in two themes carries three.
- [ ] With the fake deriving observations per scope: a theme-scoped recall returns an observation whose sources are sections of two companies, each resolved; a company-scoped recall for a third company returns neither that company-scoped observation of another company nor its sources.
- [ ] Replay and evaluation retains carry the scopes.
- [ ] Decision entry; `AGENTS.md` line.
