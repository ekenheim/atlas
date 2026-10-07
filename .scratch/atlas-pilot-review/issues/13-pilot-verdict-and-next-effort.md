# The pilot's verdict and the next effort

Type: grilling
Status: open
Blocked by: 05, 06, 07, 08, 11, 12, 15

## Question

With the five reviews, the baseline comparisons, the live evaluation and the demo in hand:
- apply the verdict criteria (ticket 02) and write `docs/pilot-report.md`;
- rank the open defects in `.scratch/atlas-pilot-fixes/issues/` by how many investigations each one hurt;
- choose the next effort from the map's candidates and the phases still unbuilt (6b, 7), and say why the others wait;
- hand off: `/to-spec` for the chosen effort, then `/to-tickets`.

The live evaluation (ticket 11) waits on the owner's adjudication; if that is still open when the investigations are done, the verdict is written without it and says so.

**2026-10-02, the lead:** the candidate next effort is drafted in `.scratch/atlas-bottleneck-argument/spec.md` (the bottleneck argument, from the owner's outcome and two Codex reviews). This ticket confirms, narrows or replaces it, and then finishes it with `/to-spec` and `/to-tickets`.

**2026-10-03, the lead: the procedure is frozen** in `.scratch/pilot/verdict-procedure.md` (one version for all five, investigation 1 run again on it; preconditions recorded; one run at a time; Claims judged twice blind; the card, baseline, run and a researcher's hour reviewed once each). Run this investigation by it.

## Comments

**2026-10-07, the lead: the five verdict runs on 0.4.6 are run and reviewed; the verdict is fail.** No investigation meets the bar; the trust gate fails in four of five; pooled precision 62%, baseline coverage 22%, machine-reviewed edge precision 57%; a researcher's hour found 144 true, cited facts and the cards had 16. Written up in `docs/pilot-report.md` and `.scratch/pilot/results.md` ("The verdict runs on 0.4.6"); the defects are pilot fixes 33 to 40, ranked in the report; the edges are applied by ticket 09's rule. Left for this ticket, with the owner: the next effort (the report's proposal: reading by an agent with web access, trust by the ledger with a Claim model that holds figures and regulatory status, Hindsight as memory over time; first test, the researchers' cited sources through the archive and the span check), and the held-out answer key (the owner's list of Serenity's flagged names and dates). Tickets 11 (live evaluation) and 12 (the §15 demo) are still open; the report says so.
