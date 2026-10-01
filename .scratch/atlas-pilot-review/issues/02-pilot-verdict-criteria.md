# The pilot's verdict criteria

Type: grilling
Status: open
Blocked by: none

## Question

Decide, before any review on 0.2.4 is written, what the five investigations must show for the pilot to pass, so the verdict isn't fitted to the results:
- the measures per investigation (the `pilot-review` skill's labels: saved work, precision as accepted-and-right over accepted, machine-reviewed edges that are right, coverage as read over taken, missed evidence, cost and latency) and the threshold for each;
- how the comparison with the archive-search baseline counts (ticket 03 defines the baseline);
- how many of the five investigations must meet the thresholds, and what "useful to a researcher" means when they are met on numbers but the card is thin;
- the three outcomes and what each leads to: pass (the next effort builds on the workflow), partial (a named fix round, then a re-run), fail (the workflow's design is reopened);
- the shape of `docs/pilot-report.md`.

Resolved by the lead (the owner delegated the decision); the answer gives the reasoning for each threshold.
