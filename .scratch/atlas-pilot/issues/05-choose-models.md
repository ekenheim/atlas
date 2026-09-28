# Choose and pin the extraction and reflect models

Type: grilling
Status: resolved
Blocked by: 04

## Question

Given the bake-off results, which model serves Atlas Hindsight extraction, and which serves reflect? What is the exact pinned identifier (and, for self-hosted, the weights/quant)? What LiteLLM aliases does Atlas define (`atlas-extract`, `atlas-reflect`, and the per-role aliases for later phases)? What happens when the chosen model is unavailable: fail closed, or a named fallback that is recorded per run?

Inputs from ticket 02 that need the owner:

- pinning Ornith's weights by checksum, and dedicated no-fallback Atlas routes in LiteLLM
- whether MiniMax's name-plus-date counts as a stable identifier
- MiniMax's grey terms for batch use and the quota it shares with coding use (pay-as-you-go would be a new cost)
- whether an Anthropic API key (a new cost) is worth it

**Owner direction (2026-09-28), which supersedes the ticket 02 inputs above:**

- Use the subscriptions already paid for; no pay-as-you-go.
- MiniMax is preferred, if the bake-off shows it works.
- Model drift and terms ambiguity are accepted.

What remains to decide: M3 vs M2.7 for each of extraction and reflect, the alias names, the fallback behavior, and how the concrete routed model is recorded per run (the `x-litellm-model-id` header or the spend logs).

**Pacing to decide here:**

- per-key `rpm` / `tpm` / max-parallel limits on the `atlas` and `atlas-dev` LiteLLM keys (check whether `LiteLLMVirtualKey` exposes them; the counters persist via Dragonfly)
- Hindsight's LLM concurrency
- how Atlas treats a 429 cap-out: pause the queue until the window resets, rather than failing jobs
- whether the backfill is spread over nightly batches

**Privacy (Q22):** MiniMax is allowed for all Atlas traffic, both extraction and reflect; see `docs/decisions.md`.

**Bake-off result (ticket 04):** MiniMax-M3 with thinking disabled beat M2.7 on every measure (facts, speed, verbatim quotes, observations); see `docs/research/extraction-bakeoff.md`. The obvious candidate for both extraction and reflect, pending this ticket's grilling.

## Answer

Grilled 2026-09-28, all recommendations accepted:

1. **Extraction:** MiniMax-M3, with thinking disabled (`HINDSIGHT_API_LLM_EXTRA_BODY={"thinking":{"type":"disabled"}}`).
2. **Reflect:** the same model and setting. Thinking-on reflect is a later experiment, measured on the same fixture.
3. **Aliases:** the LiteLLM aliases `atlas-extract` and `atlas-reflect` both point at MiniMax-M3, so a model change is a home-ops commit (→ ticket 09).
4. **When MiniMax is unavailable or capped (429):** no fallback model. Atlas pauses its ingest queue with backoff (capped at 1 h) and shows the pause.
5. **Pacing:**
   - Hindsight: `LLM_MAX_CONCURRENT=2`, `WORKER_MAX_SLOTS=4`
   - LiteLLM: a parallel-request cap of 3 on the `atlas` key, if the CRD supports it (→ ticket 09)
   - the backfill runs in a nightly window (e.g. 01:00–07:00)
6. **Model recording:** at the start of each run, Atlas reads LiteLLM `/model/info` with its own key and records what its aliases resolve to. Per-call tokens come from Hindsight's `/llm-requests`.
