# 10: The archive-search baseline drops near-duplicate passages

**What to build:** The baseline's top hits are different findings, not one paragraph five times. In the breadth run of investigation 2 its top five hits are the same export-permit paragraph from five AXT filings, each worded slightly differently, so exact-duplicate dropping (the same normalized text) doesn't catch them and the reviewer would judge one fact five times (`.scratch/pilot/results.md`, "Breadth runs on 0.2.5").

- A passage is dropped when it is a near-duplicate of a better-ranked or newer one: token-set overlap (Jaccard over the passage's terms, or word shingles) at or above a threshold chosen on the AXT example and recorded in the module's docstring. The newest document's passage is kept.
- The search module's other behaviour and the script's interface are unchanged; the kept hit lists the documents its dropped duplicates came from, so the reviewer sees how often the statement is repeated.

**Blocked by:** 05 (Passage selection), which moves the search code

**Status:** done

- [x] Unit test: a paragraph repeated in three filings with small edits (a date, a figure, one added sentence) is one hit from the newest filing, naming the other two; two different paragraphs on the same subject stay two hits.
- [x] The existing baseline tests pass.

## Resolution

Built in `atlas.evaluation.baseline.search` only (its docstring records the measure, the threshold and the reasoning); log: `docs/implementation-log.md`, "memory-directed reading ticket 10".

- **Measure and threshold:** Jaccard over the two passages' sets of stemmed terms (stopwords included), at least `NEAR_DUPLICATE` = 0.75. On the 80 saved hits of the four breadth baselines the repeated paragraphs are at 0.79 to 1.00 and the pairs that say different things at 0.68 and below, with no pair between.
- **Which wording is the hit:** the newest document's, unless that document has already shown its `--per-document` hits; then the newest with a hit to spare, and the newer document is named in `also_in`. A dropped wording uses none of its document's share.
- **`Hit.also_in`:** the other documents' source version ids, newest first, word-for-word copies included; `results.json` has them with company, title and time, `summary.md` as "Also in N other documents: …".
- **Not dropped: one filing repeating itself, and a filing and its exhibits.** Only documents available at different times are compared. The existing test "one document gives at most its share of the hits" requires it: its six passages of one 10-K and the one of an 8-K of the same time differ by two words (overlap 0.90 to 0.95) and must stay separate hits. In an offline rehearsal on the cached parses (only the documents the saved hits came from) this leaves one such pair in investigation 3's list (two passages of one EX-99.2, overlap 0.97) and one in investigation 5's (two of one 10-K, 0.97). Comparing within a filing too is one condition in `_near_duplicates`, and needs that test's passages reshaped into different statements: the lead's decision.
