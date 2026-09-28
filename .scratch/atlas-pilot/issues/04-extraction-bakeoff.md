# Extraction LLM bake-off on a Lumentum filing fixture

Type: task
Status: open
Blocked by: 02, 03

## Question

Run pinned Hindsight 0.10.1 in local Compose against each candidate that ticket 02 found viable: MiniMax-M3, MiniMax-M2.7, Ornith via `fast`, and Gemma 3 via `translate` (extraction only). Test reflect's forced tool calls separately for the first three. Retain the same small fixture: sections from one Lumentum 10-K plus one 8-K, with a handful of hand-listed expected facts. Record for each candidate:

- facts extracted vs expected
- structured-output errors
- zero-fact documents
- latency
- any spend visible in LiteLLM

Output: a results table in `docs/research/extraction-bakeoff.md`. No decision is made here; ticket 05 decides.
