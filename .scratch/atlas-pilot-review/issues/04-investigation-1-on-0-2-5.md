# Investigation 1 on 0.2.5: the before and after of fixes 06–12

Type: task
Status: resolved
Blocked by: 01, 02, 03

## Question

Run pilot investigation 1 a third time (the plan's question; seeds Lumentum and Coherent) on 0.2.5 and review it with the `pilot-review` skill. It is the first run on the new version, on the one question with a known result, so a defect points at the release and not at the question.

What do fixes 06–12 change against the 0.2.3 run (`4620f8c2-709c-465a-b0ca-ee0486f3e1b2`)?
- the Skeptic: documents and passages read, chosen by its plan or by the fallback; counterevidence;
- the Financial Analyst: sourced inputs from the as-of XBRL figures;
- the Investigators: passages per document (8-Ks and exhibits read, not only the 10-K); the Lumentum `capacity_constrained` quote recovered through the `text-v3` re-parse;
- Claim precision: the VCSEL neighbouring-clause Claim and the generic `sole_sources` Claims rejected;
- leads: `edgar_fts` leads kept; Candidates proposed from filers outside the universe;
- tokens and wall time.

The answer points at the results section and lists the new defect tickets.

## Answer

Run on 2026-10-01 as `ead2b86e-3556-42ba-9f3e-08660a938f98`; the review is in `.scratch/pilot/results.md`, "Investigation 1, third run".

**It does not meet the bar.** Trust gate held (10 of 10 quotes at their spans). Claim precision 6 of 10 (bar 80%); saved work 4 findings (bar 3); baseline coverage 2 of 10 (bar 50%); every role ran; 158,842 tokens; 5 min 29 s. `machine_reviewed` edges: 2 of 4 right. The result rests on the two stricter readings recorded in the criteria ticket's comment: counting a wrong layer as right and a hit covered in substance as covered, precision is 8 of 10 and coverage 5 of 10, and the investigation would meet the bar.

**What fixes 06–12 changed:**
- The Skeptic reads (4 documents, 24 passages, all through the fallback; its v3 plan was empty) and the Financial Analyst has sourced figures: both fixed.
- Every document gets passages, so 8-Ks, exhibits and 10-Qs are read, and they hold the run's new facts: NVIDIA's $2 billion investments in Coherent and Lumentum, and Coherent's "industry-wide shortage" of InP capacity.
- The same spread starved Lumentum's 10-K, and the allocation statement, the 0.2.3 run's best finding, was not read.
- Fix 09's two cases held (the VCSEL clause, the generic `sole_sources`); the web leads are on topic for the first time; production has its first Candidates (16, about 5 on the theme).

**New defects** (`.scratch/atlas-pilot-fixes/issues/`, 13–20, none a blocker): the party check and the filer's impersonal sentences; a typographic hyphen; the equal passage share; Skeptic context recorded as contradictions; the empty Skeptic plan; layers the quote doesn't name; a constraint cue and the direction of `owns`; one-word filing phrases.
