# 35: Hedged, conditional and development language becomes a positive Claim

**Status:** done (2026-10-07, integrate/fixes-1)
**Hurt:** investigations 1, 2, 3 and 5, verdict runs on 0.4.6.

Accepted Claims whose predicate the quote doesn't support:

- `sole_sources` from hedged risk language, "may only be available from a single or limited number of suppliers" (`417642df`, `e6e8e2b1`). (An unhedged "We depend on a limited number of suppliers for …" is right: the predicate reads "a single supplier or a limited number of suppliers".)
- `manufactures` from development: "making significant investments in", "in our tool chest … good progress", "development of our six-inch … capability" (`e41817db`, `884d539f`, `21b1ab6c`, `53dbb627`).
- `qualified_for` from "customers may require qualification", "asked by customers to qualify", "qualification efforts continue" (`4ee77ec1`, `bfd97c03`, `90f3c158`, `57c4d1e6`).
- `capacity_constrained` from a market-wide remark or one that downplays a constraint (`38896e24`, `050b6e17`, `0e1b82ef`, `07dcf257`, `acdba88c`).
- `expands_capacity_for` from a revenue ramp, a demand forecast, a reservation or spare capacity (`eeddeee4`, `4f8df503`, `79c51b8b`, `cc79b65f`, `51c04dc6`).

Reasons and right readings: `.scratch/live-runs/pilot-0.4.6/inv-*/review/final-verdicts.json` and `workflow-result.json`. Waits for ticket 13.
