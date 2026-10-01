# 10: The archive-search baseline drops near-duplicate passages

**What to build:** The baseline's top hits are different findings, not one paragraph five times. In the breadth run of investigation 2 its top five hits are the same export-permit paragraph from five AXT filings, each worded slightly differently, so exact-duplicate dropping (the same normalized text) doesn't catch them and the reviewer would judge one fact five times (`.scratch/pilot/results.md`, "Breadth runs on 0.2.5").

- A passage is dropped when it is a near-duplicate of a better-ranked or newer one: token-set overlap (Jaccard over the passage's terms, or word shingles) at or above a threshold chosen on the AXT example and recorded in the module's docstring. The newest document's passage is kept.
- The search module's other behaviour and the script's interface are unchanged; the kept hit lists the documents its dropped duplicates came from, so the reviewer sees how often the statement is repeated.

**Blocked by:** 05 (Passage selection), which moves the search code

**Status:** ready-for-agent

- [ ] Unit test: a paragraph repeated in three filings with small edits (a date, a figure, one added sentence) is one hit from the newest filing, naming the other two; two different paragraphs on the same subject stay two hits.
- [ ] The existing baseline tests pass.
