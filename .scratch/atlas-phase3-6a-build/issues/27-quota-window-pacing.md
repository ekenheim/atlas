# 27: Quota-window pacing and staged universe rollout

**What to build:** LLM-backed work is paced against the owner's subscription quotas instead of a single night window. ChatGPT/Codex (the shared Hindsight's retain, consolidation and mental models) and MiniMax (Atlas's roles via LiteLLM) are each rationed in **rolling 5-hour windows**. Backfill work runs at any time of day, up to a configurable budget per rolling 5 h per provider, so a large ingest spreads over several windows and never drains a quota in one go. The 429/outage pause stays as the backstop. The ten companies not yet ingested are rolled out through this pacing, one company at a time, not in one bootstrap. That incident spent ~1.27M Codex tokens, so the rollout must stay bounded.

Spec: `.scratch/atlas-phase3-6a/spec.md`. Owner direction (2026-09-29): "we have 5 hours windows on both chatgpt and minimax, we do not need to run everything at night, spread out the work in the windows".

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A rolling-window budget per provider (`codex` for Hindsight-backed job kinds, `minimax` for role calls). Settings: the window length (default 5 h), and the budget per window in submitted retain operations (Codex) and in LLM tokens (MiniMax, from recorded usage). A job kind that would exceed its provider's budget is held until the window rolls. This is visible in `GET /api/v1/queue`: per provider used/budget, and when capacity next frees.
- [ ] `ATLAS_BACKFILL_WINDOW` becomes optional (empty = any time) and accepts several ranges; the budgets apply whether or not a window is set.
- [ ] Interactive work (an owner's investigation) takes priority over backfill inside the same budget: backfill never uses the last configurable share (default 30%) of a window.
- [ ] Staged rollout: `atlas ingest --company X --backfill` for a company not yet ingested records an ingest plan (the discovered documents after lookback and 8-K selection, with a count and an estimated retain-op count) before anything is retained. A `--max-retains N` cap applies per company.
- [ ] Runbook: the rollout order for the ten remaining companies (one per window, largest last) and how to read the queue's budget view.
- [ ] Metrics: budget used per provider and window; jobs held by budget.
- [ ] Tests at the worker-pass seam with the injectable clock: a backfill that exceeds the budget spreads over two windows, interactive work runs while backfill is held, and a 429 still pauses.
