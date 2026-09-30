# 10: The passage budget is spent on one document

**What to build:** In pilot investigation 1's re-run (0.2.3), each Investigator was given 12–13 documents but sent only 24 passages, all from the company's 10-K (Coherent: Items 5, 1, 1A; Lumentum: Items 1, 1A). No 8-K press release (EX-99.1: the results calls, where capacity, allocation and lead-time statements are made) was opened, and the card's `read` shows `sections: []` for every other document. The document budget (fix 01) is no longer the binding limit; the passage selection is. Diagnose how the extraction picks its passages (entity-tagged windows plus recall hits, 24 in total?) and change it so the budget is spread across the documents taken: a per-document cap, newest-first across forms, with press releases and 10-Q MD&A getting a share; make the passage budget a setting (`ATLAS_INVESTIGATION_MAX_PASSAGES`) and record per document how many passages were sent (`read` already lists sections). Measure on the recorded Coherent and Lumentum fixtures how the selection changes.

**Blocked by:** None

**Status:** done

- [x] The recorded run's selection is explained in the ticket (why only the 10-K).
- [x] With the Lumentum EDGAR fixtures (10-K, 10-Q, 8-K with EX-99.1), an Investigator's passages come from at least three documents; integration test at the investigation seam with the fakes.
- [x] The card's `read` shows passages per document.

## Why only the 10-K (diagnosis)

`ClaimExtractor._select` (atlas.claims.extraction) built two lists over **all** the documents, in the order the Investigator task gave them (newest first): every window naming a known company other than the filer (entity-tagged), then every window of a section a recall for the question resolved to (recall-only). It kept the first `investigator_max_passages` (24) of tagged-then-recalled. The 10-K is the newest long filing, with dozens of windows naming other universe companies (competitors, customers, the peer group in Item 5), and its Items 1 and 1A are where recall resolves; so its tagged windows, then its recall hits, filled all 24 before any other document was reached. Press releases (EX-99.1) and 10-Qs rarely name another universe company (the recorded Lumentum filings name none), so they could enter only as recall-only windows, after the 10-K's. The document budget was not binding: 12–13 documents were taken, and the passage cap was spent on the first one. Coherent's cards show Items 5, 1, 1A (tagged Item 5 peer-group windows first); Lumentum's Items 1, 1A.

## Result

`ATLAS_INVESTIGATION_MAX_PASSAGES` (24) is the Investigator's budget, dealt one passage per document per round, newest first, tagged then recalled windows first within a document, and lead windows (results sections first) for a document with neither. Recorded Lumentum fixtures: 10-K 8, 8-K 3, EX-99.1 8, 10-Q 5 passages (before: 24 of the 10-K). Coherent: 10-K 21, 10-Q 3 (before: 24 and 0). Decision: `docs/decisions.md`, "The passage budget is spread over the documents (pilot fix 10)".
