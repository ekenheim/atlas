# 40: The conformance check recalls the way investigations do, and the recall cap is measured

**Status:** done (2026-10-07, integrate/fixes-1)

The known-answers half (`atlas.conformance.known_answers.run_known_answers`) posts `/memory/recall` with only a query and a scope: Hindsight's defaults, budget `mid` and 4,096 tokens. Investigations recall at budget `high`, `pointer_recall_max_tokens` (8,192), observations preferred, with source facts and chunks (`atlas.investigations.tasks._asker`). So the 2026-10-07 figure (recall at 10 0.08, at 50 0.12) measures a setup nothing uses. Measured that day with the plain recall: 4 of 17 answer sections reached at 4,096 tokens, 9 at 16,000, 10 at 16,000 with raw facts only (`.scratch/pilot/results.md`, "The verdict runs on 0.4.6").

**Acceptance:** the check recalls with the investigations' request (one shared builder, so the two can't drift); a run reports recall at 10 and 50 at 8,192 and at 16,000 tokens, read-only and with no LLM call, so the owner can decide `ATLAS_POINTER_RECALL_MAX_TOKENS` on numbers.

## Comments

**2026-10-07, the lead: measured live** (`scripts/memory-conformance.sh --only known-answers --recall-max-tokens 8192,16000`, read-only, no LLM call; report `.scratch/live-runs/20261007T151321Z-memory-conformance/`). Recalled as investigations do (budget high, observations preferred, source facts and chunks): recall at 10 and at 50 are **0.08 at 8,192 tokens and 0.08 at 16,000**. The cap is not the gap: the same day a plain recall of raw facts only (budget high, 16,000 tokens, types world and experience) reached 10 of 17 answer sections. Preferring observations replaces the facts that point at the filings' sections. Decision: `ATLAS_POINTER_RECALL_MAX_TOKENS` stays 8,192; the reading agent (bottleneck-argument ticket 03) searches the archive by term and recalls raw facts, not observations, for its pointers.
