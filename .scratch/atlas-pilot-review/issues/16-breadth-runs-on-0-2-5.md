# Breadth runs of investigations 2 to 5 on 0.2.5

Type: task
Status: open
Blocked by: none

## Question

Investigations 2 to 5 have never run. Run each once on 0.2.5 while the new release is built, **without a span-by-span review**, to learn which of investigation 1's defects recur on other questions and seeds, and to have a before for each question. It costs MiniMax tokens only, which the owner freed on 2026-10-01.

For each run record, from the API and the baseline script alone: stop reason, tokens and time; Claims proposed and accepted and the rejection reasons by code; passages per document and how many documents got only administrative Items; the Skeptic's items by kind and whether its plan was empty; the Analyst's sourced inputs; edges by review state and their layers; Candidates proposed; the baseline's hits containing an accepted Claim's quote and the accepted Claims in no hit.

These runs are not counted for the verdict (the reviewed runs on the new release are). They need the raised budgets (home-ops PR #7174) or a free budget window. The answer is one table and the defects that recur, written into `.scratch/pilot/results.md` under "Breadth runs on 0.2.5".
