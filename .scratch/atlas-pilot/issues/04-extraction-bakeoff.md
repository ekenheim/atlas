# MiniMax extraction check on a Lumentum filing fixture (bake-off)

Type: task
Status: claimed
Blocked by: 02, 03

## Question

Run pinned Hindsight 0.10.1 in local Compose against MiniMax-M3 and MiniMax-M2.7 (the owner's choice; direct probes passed, see `docs/research/litellm-dev-probe.md`). Test reflect's forced tool calls too. Only if both MiniMax models fail inside Hindsight, add Ornith via `fast` as the fallback candidate. Retain the same small fixture: sections from one Lumentum 10-K plus one 8-K, with a handful of hand-listed expected facts. Record for each candidate:

- facts extracted vs expected
- structured-output errors
- zero-fact documents
- latency
- any spend visible in LiteLLM

**Pacing (owner, 2026-09-28):** MiniMax's flat plan returns 429 on cap-out, and the owner saw MiniMax billing-service retry errors (`openplatform-billing … UserResourcePackagePage`, code 1000) during the probe. Run the bake-off paced: low concurrency, async batch retain, and nothing parallel against MiniMax. Also establish:

- Hindsight 0.10.1's own LLM concurrency and retry settings (the knob that paces extraction)
- the MiniMax error classes observed (429 cap-out, code 1000 transient, others), and whether LiteLLM or Hindsight retries them
- sustained throughput at the chosen pace, to size the backfill

Output: a results table in `docs/research/extraction-bakeoff.md`. No decision is made here; ticket 05 decides.
