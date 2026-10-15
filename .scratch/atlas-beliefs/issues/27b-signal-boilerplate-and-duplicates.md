# 27b: Archive signals: supplier-dependence boilerplate and one sentence once per document

Type: build
Status: ready-for-agent
Blocked by: none

## Why

After ticket 27 the last quarter's top 20 holds 10 real cues of 20 (`docs/experiments.md`, "archive signals after ticket 27"): 10-K supplier-dependence boilerplate ("We purchase some of the critical materials ... from a single source or a limited number of suppliers", "We rely on sole-source suppliers for a number of critical materials", "Some of these materials are available from only one proven outside source") ranks 8, 15 and 19, and one Lumentum 10-K sentence ("This demand is outpacing our current supply which has required us to make decisions on supply allocation.") ranks 17 and 18.

## What to build

- In a filing (10-K, 10-Q, 20-F, 40-F; not a call), a few_suppliers sentence that states the company's reliance on single or limited sources with no named product, figure or present constraint ("rely on", "purchase ... from a single source", "available from only one", "limited number of suppliers") is multiplied down below the threshold, as Item 1A is; a sentence naming the input and a current shortage keeps its score. Tests both ways from the sentences above and new ones.
- One identical sentence (normalised) in one document counts once in the ranked reads and the replay.

## Acceptance criteria

- [ ] Unit tests both ways with literal scores.
- [ ] The precision replay of the last quarter: at least 12 of the top 20 real cues; the AXT replay's 31 July sentence still in the top five (the lead).
