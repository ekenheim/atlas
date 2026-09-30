# 10: The passage budget is spent on one document

**What to build:** In pilot investigation 1's re-run (0.2.3), each Investigator was given 12–13 documents but sent only 24 passages, all from the company's 10-K (Coherent: Items 5, 1, 1A; Lumentum: Items 1, 1A). No 8-K press release (EX-99.1: the results calls, where capacity, allocation and lead-time statements are made) was opened, and the card's `read` shows `sections: []` for every other document. The document budget (fix 01) is no longer the binding limit; the passage selection is. Diagnose how the extraction picks its passages (entity-tagged windows plus recall hits, 24 in total?) and change it so the budget is spread across the documents taken: a per-document cap, newest-first across forms, with press releases and 10-Q MD&A getting a share; make the passage budget a setting (`ATLAS_INVESTIGATION_MAX_PASSAGES`) and record per document how many passages were sent (`read` already lists sections). Measure on the recorded Coherent and Lumentum fixtures how the selection changes.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] The recorded run's selection is explained in the ticket (why only the 10-K).
- [ ] With the Lumentum EDGAR fixtures (10-K, 10-Q, 8-K with EX-99.1), an Investigator's passages come from at least three documents; integration test at the investigation seam with the fakes.
- [ ] The card's `read` shows passages per document.
