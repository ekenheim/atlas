# 28: Smaller defects of investigation 1's fifth run

**What to build:** Five things the review found that each need a look before a ticket of their own. Evidence for all: production 0.3.1, investigation `452c3b9d-2e2f-4cc6-bc54-5130155b9aac` (pilot investigation 1, fifth run; reviewed in `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs"); the run reviewer's notes in `.scratch/live-runs/pilot-0.3.1/inv-1/review/run-review.md` (not in git).

- **Financial Analyst.** `addressable_units` and `company_share` were rejected for both seeds on a Decimal type error and became `missing`; its first call (`247a2afd-b08f-4333-a827-9a97c24fc9e3`) was quarantined (invalid JSON, then an extra `data_gaps` field: ticket 26's rule would have kept it); Coherent's `total_debt` value (3,222,224,000) disagrees with its stated basis ("3,222.4M"; the parts sum to 3,222.3M).
- **Kept leads repeat one story.** Six of the ten kept leads are the AXT and Lumentum agreement of 2026-07-29 syndicated on six sites; no EDGAR lead is in the ten. Lead ranking has no near-duplicate rule (the baseline has one).
- **The `search` selection tag says nothing.** Every passage of every reading task carries it (72 of 72 for each Investigator, 48 of 48 for the Skeptic), so which channel found a Claim cannot be told: pointer 236 tags, search 182, entity 58 over 182 Claims.
- **Two Skeptic items rejected with document-scale offsets** (`quote_outside_passage` at [244497, 244732) and [149350, 149573) in 3,000-character passages); the second is AXT's export-permit backlog sentence, which the card therefore lacks.
- **IQE's epiwafer products tagged `chip-laser`** because the quote says "laser and detector products" (2 Claims): the layer rule reads the word, not what the company makes.

**Blocked by:** None

**Status:** needs-triage

- [ ] Each item is either a ticket of its own with its evidence, or closed with the reason.
