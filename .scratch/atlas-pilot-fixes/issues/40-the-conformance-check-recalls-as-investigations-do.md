# 40: The conformance check recalls the way investigations do, and the recall cap is measured

**Status:** done (2026-10-07, integrate/fixes-1)

The known-answers half (`atlas.conformance.known_answers.run_known_answers`) posts `/memory/recall` with only a query and a scope: Hindsight's defaults, budget `mid` and 4,096 tokens. Investigations recall at budget `high`, `pointer_recall_max_tokens` (8,192), observations preferred, with source facts and chunks (`atlas.investigations.tasks._asker`). So the 2026-10-07 figure (recall at 10 0.08, at 50 0.12) measures a setup nothing uses. Measured that day with the plain recall: 4 of 17 answer sections reached at 4,096 tokens, 9 at 16,000, 10 at 16,000 with raw facts only (`.scratch/pilot/results.md`, "The verdict runs on 0.4.6").

**Acceptance:** the check recalls with the investigations' request (one shared builder, so the two can't drift); a run reports recall at 10 and 50 at 8,192 and at 16,000 tokens, read-only and with no LLM call, so the owner can decide `ATLAS_POINTER_RECALL_MAX_TOKENS` on numbers.
