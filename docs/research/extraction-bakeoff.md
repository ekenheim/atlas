# Extraction bake-off: MiniMax in Hindsight 0.10.1 (ticket 04)

Run 2026-09-28 on local Compose (`spikes/hindsight/`): Hindsight `0.10.1-slim` (the same digest as the cluster), pgvector pg18, and all LLM, embedding and rerank calls through `litellm.<domain>` with the `atlas-dev` key. Paced at 2 concurrent LLM calls, one document at a time.

**Fixture** (`spikes/hindsight/fixtures/lumentum/`): 13.8k chars of Lumentum's FY2026 10-K Item 1 (accession 0001628280-26-057358) plus 5.8k chars of the Q4 FY2026 earnings release, 8-K EX-99.1 (0001628280-26-055726). Each document is retained under `srcv:<sha256>` with `timestamp` = EDGAR `acceptanceDateTime`. There are 17 hand-listed expected facts, matched by keyword.

**Harness:** `bakeoff.py` (retain, then score, then log LLM requests, then free-text reflect) and `structured_reflect.py` (reflect with `response_schema`). Raw results are in `spikes/hindsight/results/*.json`.

## Results

| | **MiniMax-M3, thinking disabled** | MiniMax-M2.7 (default) |
|---|---|---|
| Retain 10-K excerpt / 8-K excerpt | **54 s / 33 s** | 147 s / 54 s |
| Operations | 2/2 completed, 0 errors | 2/2 completed, 0 errors |
| LLM calls (retain) | 10, all success | 9, all success |
| Tokens (input / output / cached) | 39.9k / 9.8k / 23.5k | 32.7k / 11.1k / 25.0k |
| Memories | **60** (52 world + 8 observations) | 40 (40 world, no observations yet) |
| Expected facts found | **16/17** (miss: B7, a table figure) | 15/17 (misses: A1 HQ, B7) |
| Free-text reflect | 17.8 s, 24 facts cited, accurate quotes | 63.9 s, 14 facts cited |
| Structured reflect (JSON Schema) | 18.5 s, shape OK, no `structured_output_error` | 56.4 s, shape OK, no error |
| Evidence quotes verbatim in source | **4/5** | 0/4 (paraphrased, yet marked `explicit_in_source: true`) |

**MiniMax errors observed:** none. There were no 429s and no code-1000 billing errors during these runs; all 19 retain calls and every reflect call succeeded.

**Throughput at this pace (M3):** ~19.6k chars in ~87 s of retain, i.e. ~13k chars/min. About 2 input tokens per source char once prompt overhead is included (much of it cached). *Estimate:* a full 10-K (~500k chars) is ~40 min and ~1M input tokens. A two-company, three-year backfill is a few overnight hours. This is an extrapolation from two small documents, not a measurement.

## Findings for later tickets

1. **Worker-slot trap (ticket 06/09):** consolidation reserves 2 worker slots. With `HINDSIGHT_API_WORKER_MAX_SLOTS ≤ 2` the shared pool is 0 and retain tasks never get claimed; they sit pending with no error. Use ≥ 3 (the spike uses 4) and pace with `LLM_MAX_CONCURRENT` instead.
2. **JSON Schema union types crash reflect (ticket 06/07):** `"type": ["number", "null"]` in `response_schema` returns HTTP 500 (`TypeError: unhashable type: 'list'` in request validation) before any LLM call. Atlas schemas must avoid union types (use a separate `*_known` boolean).
3. **Reflect reads raw chunks, not only facts (ticket 07):** both models answered Components revenue = $649.4M even though extraction stored no such fact. Provenance resolution must handle chunk-sourced answers, not only memory IDs.
4. **Quotes must be validated (ticket 07):** even with "verbatim" instructions, M2.7 paraphrased every quote while flagging it explicit. M3 was mostly exact. Atlas's span validation against the archive is required, as the spec says.
5. **Table numbers are under-extracted:** narrative facts come through; the release's revenue-by-product table did not. Financial figures should come from XBRL (Phase 5), not memory.
6. **Model attribution:** Hindsight's `/llm-requests` log records provider `openai`, the alias `MiniMax-M3`, tokens, duration, and the full prompt/response. It does not record the LiteLLM deployment. The concrete routed model must come from LiteLLM's side (fog item on the map).
7. **Thinking:** behind `provider=openai`, Hindsight doesn't disable MiniMax thinking itself. `HINDSIGHT_API_LLM_EXTRA_BODY={"thinking":{"type":"disabled"}}` worked for M3. M3 with thinking on was not tested.

## Not tested

M3 with thinking enabled; Ornith (not needed, because MiniMax passed); sustained load against the Plus quota; consolidation/observations timing; mental models.
