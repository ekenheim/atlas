# The pilot's verdict criteria

Type: grilling
Status: resolved
Blocked by: none

## Question

Decide, before any review on 0.2.5 is written, what the five investigations must show for the pilot to pass, so the verdict isn't fitted to the results:
- the measures per investigation (the `pilot-review` skill's labels: saved work, precision as accepted-and-right over accepted, machine-reviewed edges that are right, coverage as read over taken, missed evidence, cost and latency) and the threshold for each;
- how the comparison with the archive-search baseline counts (ticket 03 defines the baseline);
- how many of the five investigations must meet the thresholds, and what "useful to a researcher" means when they are met on numbers but the card is thin;
- the three outcomes and what each leads to: pass (the next effort builds on the workflow), partial (a named fix round, then a re-run), fail (the workflow's design is reopened);
- the shape of `docs/pilot-report.md`.

Resolved by the lead (the owner delegated the decision); the answer gives the reasoning for each threshold.

## Answer

Decided by the lead on 2026-10-01, before any 0.2.5 run was read. The only results known when these were set are investigation 1's two earlier runs (0.2.1: nothing; 0.2.3: precision 10/14, machine-reviewed edges 7/8 right).

**Who judges.** The lead reviews each accepted Claim with the `pilot-review` skill and writes the verdict with the quoted span and the reason, so the owner can audit any of them. The owner's own edge decisions (ticket 09) are the independent check: the report states where they disagree with the lead's verdicts.

**The trust gate (per investigation, no threshold).** Every accepted Claim's quote occurs verbatim in its cited span, and every finding on the card cites Claims that say what the finding says. A failure is a blocker under the map's focus rule: fixed at once and that investigation re-run. The verdict cannot be "pass" with one open.

**The bar (per investigation; the latest run of each question on 0.2.5).** An investigation meets the bar when all six hold:

| Measure | Threshold | Why this number |
|---|---|---|
| Claim precision: accepted and right over accepted | at least 80%, with at least 5 accepted | Below four in five, checking each Claim costs the researcher about as much as reading the source. With fewer than 5 accepted the ratio means nothing and the investigation fails on saved work anyway. |
| Saved work: findings that are correct, cited to a primary span, on a clause of the question, and not boilerplate | at least 3 | Three is the least that makes a card worth opening. A company's product-catalog facts (`manufactures`) count as one finding per company, so a list of what a company makes cannot meet the bar alone. |
| Baseline coverage: of the on-question passages the archive-search baseline surfaces (the reviewer judges at most 10), the share the card's findings or Evidence cover | at least 50% | The pipeline must at least find half of what a plain search finds; what it adds beyond search (typed edges, counterevidence, a scenario) is reported, not thresholded. Ticket 03 defines the baseline. |
| The roles ran | the Skeptic read at least one document with passages; the Financial Analyst has at least one sourced input for each seed company that has as-of figures; the Editor wrote a card with open questions | Each was empty in an earlier run; an empty role is a pipeline defect, whatever the Claims look like. Counterevidence itself has no threshold: none may exist. |
| Cost | at most 200k MiniMax tokens, no Codex operation beyond recall | Two investigations fit one 5 h window of the 400k budget with the interactive reserve left. |
| Latency | at most 10 minutes wall time, pauses for a budget excluded | The 0.2.3 run took 2 minutes; ten leaves room for three seeds and the Skeptic's reading. |

**Across the five investigations:**
- Machine-reviewed edge precision, pooled over all five (single runs have too few edges): at least 90%, and no investigation with more than one wrong `machine_reviewed` edge. These edges reach the edge table without a person, so the bar is higher than for Claims.

**The verdict:**
- **Pass:** at least 4 of 5 investigations meet the bar, the trust gate holds in all five, and pooled machine-reviewed precision is at least 90%. The next effort builds on the workflow as it is.
- **Partial:** 2 or 3 meet the bar, or 4 do but the pooled machine-reviewed precision is under 90%. One named fix round follows, limited to defects that hurt at least two investigations, then only the failing questions are re-run.
- **Fail:** at most 1 meets the bar. No fix round: the research workflow's design is reopened (a grilling ticket on what the Claim model and the roles can express) before anything else is built.

**A thin card.** If an investigation meets the numbers but its saved-work findings answer no clause of the question with a named company, product or figure, it does not meet the bar; the review says which clause went unanswered. This is the "would the card have saved a researcher work" test made checkable.

**The report** (`docs/pilot-report.md`), in this order: the verdict and the reason in one paragraph; method (version, questions, these criteria, the baseline); one table with the measures per investigation; saved work, with the spans; what was unsupported or wrong; missed evidence and the baseline comparison; the roles (Skeptic, Financial Analyst, Editor); cost and latency; the §15 demo, item by item with production IDs or "fixtures only"; the evaluation results (scripted and, if run, live); the exact test status (the CI run and its counts); the defects ranked by how many investigations each hurt; the next effort and why the others wait.

## Comments

**2026-10-01, the lead: two clarifications, made while reviewing investigation 1 on 0.2.5 and before investigations 2–5 ran.** Both take the stricter reading, and together they decide investigation 1's result: under the lenient readings its precision would be 8 of 10 and its coverage 5 of 10, each exactly at its threshold, and it would meet the bar. They were chosen after that run's results were known, which is the weakness the criteria were written to avoid; the reasons are that a `machine_reviewed` edge in the wrong layer misleads on the question asked, and that a capacity hit's magnitude is its content. The owner may overrule either; the reviews report both counts so the verdict can be recomputed.
- **A Claim is right** when subject, predicate, object and direction match the quote **and its layer is not wrong**. A layer is *wrong* when the archive shows the object belongs to another layer (Coherent's InP device capacity tagged `substrate`). A layer the quote merely doesn't name (the question's layer on an ownership edge) is *unconfirmed*: the Claim counts as right, and the count of unconfirmed layers is reported beside the precision.
- **A baseline hit is covered** when the card states its fact at the hit's level of detail. A hit whose point is a magnitude or a date ("3X InP capacity increase", "double internal InP output by year-end") is not covered by a finding that only says capacity is expanding; such hits are listed as covered in substance.
