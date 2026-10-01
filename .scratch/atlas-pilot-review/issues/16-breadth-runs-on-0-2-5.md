# Breadth runs of investigations 2 to 5 on 0.2.5

Type: task
Status: resolved
Blocked by: none

## Question

Investigations 2 to 5 have never run. Run each once on 0.2.5 while the new release is built, **without a span-by-span review**, to learn which of investigation 1's defects recur on other questions and seeds, and to have a before for each question. It costs MiniMax tokens only, which the owner freed on 2026-10-01.

For each run record, from the API and the baseline script alone: stop reason, tokens and time; Claims proposed and accepted and the rejection reasons by code; passages per document and how many documents got only administrative Items; the Skeptic's items by kind and whether its plan was empty; the Analyst's sourced inputs; edges by review state and their layers; Candidates proposed; the baseline's hits containing an accepted Claim's quote and the accepted Claims in no hit.

These runs are not counted for the verdict (the reviewed runs on the new release are). They need the raised budgets (home-ops PR #7174) or a free budget window. The answer is one table and the defects that recur, written into `.scratch/pilot/results.md` under "Breadth runs on 0.2.5".

## Answer

Run on 2026-10-01 after the budgets were raised; the table and the findings are in `.scratch/pilot/results.md`, "Breadth runs on 0.2.5". All four stopped `needs_review` with a card: 28, 31, 10 and 22 accepted Claims; 368k to 594k tokens; 9 to 13 minutes.

- **Recurring on every question, already ticketed:** the party check (31 of 105 rejections), quote mismatches (19), the Skeptic reading only by fallback and attaching most of its items to no Claim, the layer following the question, and low coverage of what a term search finds.
- **New:** some Investigators propose almost nothing (Ciena 1 Claim from 72 passages, Marvell 5); the allocation statement was read and rejected for its object (ticket 09 of the memory-directed reading spec); private acquisition targets don't resolve; filing leads crowd the kept leads, one filer many times; the baseline repeats one paragraph across filings (ticket 10).
