# Hindsight gateway and bank-policy decisions from the matrix

Type: grilling
Status: claimed
Blocked by: 06

## Question

With the matrix in hand, decide:

- the document_id scheme per Source Version
- the tag vocabulary, and strict-matching usage
- the bank configuration mechanism (template import vs the config API)
- how the returned facts are mapped to Source Versions, and what happens when that mapping is unavailable
- the retain granularity (whole parse vs bounded sections with anchors)
- operation polling and zero-fact handling
- which two mental models ship in Phase 2

Inputs from ticket 01 to weigh:

- reflect citations need a per-memory lookup to reach `document_id`
- structured output is loosely enforced
- the mental-model refresh-loop risk (#4532)
- the worker-slot hang (#4763)

Record spec deviations in `docs/decisions.md`.

**Inputs from ticket 06 (`docs/hindsight-feature-matrix.md`):**

- two-hop provenance via `source_memory_ids` and preserved `metadata.source_version_id`
- chunk-sourced reflect content can't be resolved to a memory
- templates exist (so use a versioned template, not the config API)
- strict tag modes work
- one operation per batch retain
- the alternative listing routes
- no union types in schemas

**Input from ticket 12:** the candidate glossary term *Bottleneck* (a constrained input with no qualified second source or substitute in the relevant timeframe, where the owner has pricing power), and the proposed wording for the Bottlenecks mental model. Both are in `docs/research/serenity-skills-alignment.md`.
