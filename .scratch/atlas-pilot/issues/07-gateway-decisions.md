# Hindsight gateway and bank-policy decisions from the matrix

Type: grilling
Status: open
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
