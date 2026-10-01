# 05: Passages are chosen by pointer and search rank, not dealt in equal shares

**What to build:** Inside the documents an Investigator takes, the passages it reads are the windows Memory pointed to and the windows that best match the question, best first. Evidence: pilot investigation 1 on 0.2.5 read 3 passages of Lumentum's 10-K and stopped 2,000 characters short of the allocation statement, while administrative 8-Ks each got a passage; the archive-search baseline's hits all lay in recalled sections the Investigator read other windows of (pilot-fix ticket 15, which this supersedes).

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("Passage selection", "The search code is shared").

- Candidate windows per document, each with a score and its selections:
  1. **pointer** windows: for each reading pointer into the document, the window of the pointed section that best matches the memory's text (term overlap), scored by the pointer's rank;
  2. **search** windows: the document's windows ranked by BM25 against the question and the Scout's queries;
  3. **entity**-tagged windows, as today;
  4. **lead** windows, as today, only for a document with none of the above.
- Passages are taken best first across the Investigator's documents, with a floor of one for each periodic report and results release that has a candidate and a ceiling per document (a setting, default one third of the passage budget). A window chosen by several selections is one passage recording all of them; the section-wide `recall` selection is retired.
- The tokenizer, passage scoring and BM25 of `atlas.evaluation.baseline` move to a module the extraction also uses; `scripts/pilot_baseline.py` and its unit tests behave as before.
- The standalone `extract_claims` job (no investigation, so no pointers) uses search, entity and lead selections.
- Each accepted Claim's passage selections are on the Claim read, so the pilot can count which selection found it; the card's `read` rows show selections per document.

**Blocked by:** 01 (Reading pointers)

**Status:** done

- [x] Integration test at the investigation seam on the recorded Lumentum filings: with a pointer whose memory paraphrases the allocation statement, the window holding "This demand is outpacing our current supply" is read (`pointer`), the EX-99.1 and the 10-Q each keep at least one passage, and an 8-K with only Items 5.02 and 9.01 gets none while other documents have unread candidates.
- [x] Without pointers, the search selection reads the window that best matches the question's terms; the ceiling stops one document taking more than its share.
- [x] Unit tests of the scoring and the dealing (floor, ceiling, ties, a window chosen twice).
- [x] The baseline's unit tests pass unchanged against the moved code.
- [x] Decision entry (replaces "The passage budget is spread over the documents"), settings, `AGENTS.md`.

## Resolution

Built as `atlas.claims.selection` (pure) over `atlas.research.search` (the baseline's tokenizer, passages and BM25, moved). Decision: `docs/decisions.md`, "Passage selection: pointers and search, alternately"; log: `docs/implementation-log.md`, "memory-directed reading ticket 05" (with its amendment).

- The order, as amended by the lead: pointer windows (by rank) and search and entity windows (by BM25 score) are taken alternately, so a document Memory doesn't hold yet (an unretained transcript) is still read; lead windows last. First built with every pointer window before any search window. The ceiling (`ATLAS_INVESTIGATOR_MAX_PASSAGE_SHARE_PER_DOCUMENT`, a third) yields when the budget would otherwise go unspent; lead windows of a document with no floor come after every other candidate.
- The floor of one passage covers periodic reports, results releases and, by the amendment, results-call transcripts (provider `tradingview`, document type "Call transcript"); conference transcripts have none.
- The Investigator's own recall is removed, in investigations and in the standalone job.
- The administrative 8-K of the acceptance test is a **hand-shaped stand-in** (a manual import with Items 5.02 and 9.01 in its text): the recorded Lumentum fixtures hold only the results 8-K, and adding a filing to them would change every test that ingests Lumentum. The rule that an 8-K without Item 2.02 has no floor is unit-tested on the form, document type and Items.
- No migration: `selected_by` is JSON, and the Claim read computes `passage_selected_by` from the extraction.
