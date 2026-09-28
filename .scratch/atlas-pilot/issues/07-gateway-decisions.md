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

Record spec deviations in `docs/decisions.md`.
