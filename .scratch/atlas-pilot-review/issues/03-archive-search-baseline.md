# The archive-search baseline

Type: grilling
Status: resolved
Blocked by: none

## Question

The Codex review (2026-09-30) asked that the pilot compare each investigation with an archived-document-search baseline; nothing in the repo defines it. Decide:
- what the baseline is: a plain search of the archived parsed Source Versions of the seed companies for the question's terms, with no research role; or scoped recall alone (`POST /api/v1/memory/recall`); or both, since they answer different questions (what the pipeline adds over search; what memory adds over the archive);
- how it is run reproducibly against production, read-only, and at what cost (no MiniMax tokens if possible);
- what is compared: the passages the baseline surfaces against the card's findings and the review's "missed evidence";
- where the result is recorded in each `.scratch/pilot/results.md` section.

If it needs a script, the answer specifies it; building it is part of this ticket only if it is small (a read-only script under `scripts/`).

## Answer

Decided and built by the lead on 2026-10-01.

**Two baselines, both without a model, both read-only; the threshold applies to the first.**
- **Archive search** answers "what does the pipeline add over searching the archive?". The question's content words (lowercased, stopwords and question words out, plural endings dropped, no synonyms) are searched with BM25 over passages of the seed companies' parsed, English filing documents available in the 18 months before the investigation's as-of time (the window its EDGAR search uses). Passages are about 300 to 1,500 characters with code-point offsets; a passage repeated in an older filing is dropped; one document gives at most 3 of the top 20. It is deliberately untuned: a term list or a synonym table fitted to a question would make the baseline a second pipeline.
- **Recall alone** answers "what does memory surface without a research role?". One `POST /api/v1/memory/recall` with the question, scoped to the seed companies and the theme. It is reported beside the first (how many archive hits lie in a section recall resolved to), not thresholded: recall's sections are whole Items or chunks, so "in a recalled section" is a coarse measure.

**How it is run.** `uv run python scripts/pilot_baseline.py --company <slug>... --question "..." --investigation <id> --as-of <the investigation's created_at>` against production: GETs and the one recall, no MiniMax token, no Codex operation. Parsed texts are cached under `.scratch/live-runs/baseline-cache/`. The search is `atlas.evaluation.baseline` (unit-tested).

**What is compared, and where it is recorded.** The script marks each hit with the accepted Claims whose quote it contains. The reviewer reads the top 20, marks each on-question or not, and stops at 10 on-question hits. Baseline coverage (verdict criteria) is the share of those the card covers: a hit counts as covered when a finding or an accepted Claim states its fact, whether or not the quote is the same sentence. Each on-question hit the card doesn't cover is listed under **Missed evidence** in the investigation's section of `.scratch/pilot/results.md`, and the section gains one line, **Baseline**: hits judged, on-question, covered, and the recall figure.

**First run** (the 0.2.3 run of investigation 1, as a check of the script; not a review): 69 documents (Lumentum 33, Coherent 36), 145 requests. 2 of the 20 hits contain an accepted Claim's quote, 11 of the 14 accepted Claims are in no hit, and all 20 hits lie in sections recall resolved to. The top hits are Coherent's investor-presentation slides (EX-99.2: "3X InP capacity increase", the laser portfolio) and press-release highlights (EX-99.1), documents that run never read. Ticket 04 judges them against the 0.2.5 run.
