# 23: Theme explorer (A) and Company dossier (B)

**What to build:** The researcher browses the theme by layer (companies, Relationships, Bottleneck gaps) and opens a company dossier (identity, sources, Relationships, financial observations).

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 02 (Entity resolution and identity review); 12 (Relationships and review); 18 (XBRL normalization)

**Status:** ready-for-agent

- [ ] `themes`, `themes/{id}/map` API
- [ ] Two frontend pages; API client regenerated
- [ ] Playwright test: theme → company → a source span
