# 34: The Editor's findings state agreements, plans and development as present fact

**Status:** needs-triage
**Hurt:** investigations 1, 2, 3 and 5 (the trust gate fails in each), verdict runs on 0.4.6.

The grounding check passes names, figures and phrases; it doesn't check tense, direction or merging (the card's `grounding_limit`). The failures, each with its quote:

- AXT's development-and-supply agreement with Coherent written as "supplies 6-inch InP" or "manufactures 6-inch InP" (inv 1 finding 2, inv 2 finding 1, inv 5 finding 1; `adcf1b4e`); "6-inch" carried over to Lumentum's agreement (inv 5).
- "one- to three-month" for "the next quarter, two to three months later" (inv 1 finding 3, `c86629a1`).
- A conditional ("if the customer would like us to do sub-assemblies…") as manufacture (inv 3 finding 1, `8a834754`); "qualification efforts continue" as "ramping in volume production" (inv 5 finding 3).
- Two items of a risk list merged into a stated dependency (inv 5 finding 4); "a limited number of suppliers" as "sole-sources" (inv 1 finding 2's limitations).

The misstated findings, with reasons: `.scratch/live-runs/pilot-0.4.6/inv-*/review/workflow-result.json` (`card.findings`). They are the evaluation cases for a semantic check of findings (the pilot-review map, "The next effort's likely shape", item 3). Waits for ticket 13: a fail reopens the design.
