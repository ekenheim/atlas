# 13: Edge table page (C)

**What to build:** The researcher audits the graph in a sortable, filterable table (subject, predicate, object, layer, review state, Evidence and family counts) where every edge opens its source span.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 12 (Relationships and review)

**Status:** done

- [x] API list with sorting and filtering by layer and review state
- [x] Frontend page, accessible like the viewer; API client regenerated
- [x] Playwright test: filter, open an edge, land on its highlighted span
