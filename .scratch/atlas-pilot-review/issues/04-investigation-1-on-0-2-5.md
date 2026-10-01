# Investigation 1 on 0.2.5: the before and after of fixes 06–12

Type: task
Status: open
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
