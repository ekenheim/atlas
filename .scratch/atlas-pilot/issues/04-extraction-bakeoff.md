# MiniMax extraction check on a Lumentum filing fixture (bake-off)

Type: task
Status: resolved
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

## Answer

Run 2026-09-28; full write-up in `docs/research/extraction-bakeoff.md`, harness and raw results in `spikes/hindsight/`.

- **MiniMax-M3 with thinking disabled** (`HINDSIGHT_API_LLM_EXTRA_BODY={"thinking":{"type":"disabled"}}`):
  - 16/17 expected facts, 60 memories (including 8 observations)
  - retain 54 s + 33 s
  - reflect 18 s; structured reflect OK; 4/5 quotes verbatim
- **MiniMax-M2.7:** 15/17 facts, 40 memories, 2–4× slower, 0/4 verbatim quotes.
- No 429s or MiniMax billing errors at 2 concurrent calls. Throughput is ~13k source chars/min (≈40 min per full 10-K, extrapolated).
- **Traps found:**
  - `WORKER_MAX_SLOTS ≤ 2` starves retain, because consolidation reserves 2 slots
  - JSON-Schema union types in `response_schema` return a 500
  - reflect answers from raw chunks as well as facts
  - Hindsight logs only the alias, not the LiteLLM deployment

Ornith wasn't needed. The decision is left to ticket 05.
