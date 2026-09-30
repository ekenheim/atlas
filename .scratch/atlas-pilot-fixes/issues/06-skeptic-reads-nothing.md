# 06: The Skeptic searched but read nothing

**What to build:** In pilot investigation 1's re-run (0.2.3), the Skeptic ran its 10 SearXNG queries (59 new leads) but read 0 archived documents and 0 passages, so it proposed no counterevidence and the card has no `contradictions`. Diagnose from the recorded run (`skeptic_search_id` `887c7bd9-c629-4654-8234-42b7cc10966f`, plan role call `b1948992-b116-4fb1-9e86-65de9e033f24`) why its plan chose no archived Source Versions: does the plan only name documents it found through search (which are leads, never fetched), or does it pick from the archive and found nothing that matched? Then make the bear checklist read the archive: the seed companies' other filings (older 10-Ks, 10-Qs, 8-K press releases) and the theme's other companies, within the document budget. A Skeptic that reads nothing must at least say so on the card.

**Blocked by:** None

**Status:** needs-triage

- [ ] The recorded run's Skeptic plan is explained in the ticket (what it asked for, what the archive had).
- [ ] With the pilot's seeds and archive, the Skeptic reads at least one archived Source Version per seed company; integration test at the investigation seam with the fakes.
- [ ] The card states what the Skeptic read (or that it read nothing), like `read` does for the Investigators.
