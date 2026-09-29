# Claim → Assertion → Relationship: extraction, predicates and review

Type: grilling
Status: resolved
Blocked by: none

## Question

Decide:
- who proposes Claims (the Investigator via LiteLLM, and/or Hindsight reflect with a JSON schema)
- the predicate whitelist mapping (§5.5) and direction rules
- the photonics layer taxonomy (ticket 12)
- how Evidence Families (syndication) are detected in Phase 3
- the review UI and API for turning Assertions into Relationships
- the edge table
- the co-mention rejection fixture

## Answer

Grilled 2026-09-29; the owner accepted all, with a refinement to review.

- **Proposer:** the Investigator (MiniMax-M3 via LiteLLM, strict JSON schema) reads archived parsed text. Every Claim names a Source Version and an exact quote span, so it becomes an Assertion automatically. Hindsight recall only finds passages.
- **Predicates:** the §5.5 whitelist with explicit direction. `supplies`/`buys_from` are never inferred from each other; "works/partners with" maps to no predicate. Each edge carries a photonics **layer** (ticket 12 taxonomy).
- **Evidence Families:** exact duplicates by content hash; near-duplicates by SimHash on the normalized parse, above a threshold, as one family (one witness).
- **Review (owner refinement):** LLM-assisted by default. A separate reviewer role (the Skeptic model), plus deterministic checks (verbatim span in the archive; a Tier A source; explicitly directional language), marks a Relationship **machine-reviewed**, visible as such and usable in research. Rejected or uncertain proposals go to a **human exceptions queue**. Any Relationship a **published Hypothesis** depends on requires owner approval before publication (spec §7.3 step 11: humans approve *material* relationships). Plus an edge-table page and a co-mention rejection fixture.
