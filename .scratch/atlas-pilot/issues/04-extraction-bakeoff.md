# MiniMax extraction check on a Lumentum filing fixture (bake-off)

Type: task
Status: open
Blocked by: 02, 03

## Question

Run pinned Hindsight 0.10.1 in local Compose against MiniMax-M3 and MiniMax-M2.7 (the owner's choice; direct probes passed, see `docs/research/litellm-dev-probe.md`). Test reflect's forced tool calls too. Only if both MiniMax models fail inside Hindsight, add Ornith via `fast` as the fallback candidate. Retain the same small fixture: sections from one Lumentum 10-K plus one 8-K, with a handful of hand-listed expected facts. Record for each candidate:

- facts extracted vs expected
- structured-output errors
- zero-fact documents
- latency
- any spend visible in LiteLLM

Output: a results table in `docs/research/extraction-bakeoff.md`. No decision is made here; ticket 05 decides.
