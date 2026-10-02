# 15: The embedding model, measured and decided

**What to build:** The owner gets a recommendation, with numbers, on which embedding model Memory should run on and with which thresholds: keep the current one as it is, keep it with its query instruction, or change it. The owner offered a different model on 2026-10-02.

Type: research (a measurement; no Atlas behaviour changes). The lead runs the live part.

Study: `docs/research/hindsight-memory-use.md`, finding 7. What is known: the cluster embeds with Qwen3-Embedding-0.6B (1,024 dimensions) through the `openai` provider with no query instruction, though the model expects one on queries and the pinned docs have `HINDSIGHT_API_EMBEDDINGS_QUERY_PREFIX` for it; five similarity thresholds are at defaults calibrated for `BAAI/bge-small-en-v1.5`; the vector dimension is fixed for the whole server once its tables hold rows (the manifest's "one-way door"), and the server is shared with other consumers.

- On the local Hindsight (ticket 01's Compose, the cluster's version), retain the same recorded fixtures under each candidate and run the known answers and the recall behaviours of the conformance check (ticket 14) against each:
  1. the current model as served today;
  2. the current model with its documented query instruction as the query prefix;
  3. the model Hindsight's thresholds are calibrated for, served locally (a text-embeddings-inference container);
  4. at most two further candidates the owner's embedding service could serve at 1,024 dimensions or fewer, chosen from published English retrieval results and named with the reason.
- Per candidate: recall at 10 and at 50 on the known answers; the distribution of cosine similarity between queries and the facts that answer them, and between facts, against the five thresholds (how many right answers each gate would cut, how dense the semantic links become); retain and recall latency.
- State the cost of each change plainly: a query prefix re-embeds nothing; a model of the same dimension makes every bank's stored vectors stale until re-embedded; another dimension needs an empty store, so a new server or a wipe, for every consumer.
- Recommend one, with thresholds, and say what the recommendation does not cover (the fixtures are a few filings, not the production corpus). The owner decides; ticket 11 carries the decision into home-ops, and the backfill (ticket 12) runs after it.

Output: `docs/research/embedding-model.md`, the raw numbers under `.scratch/live-runs/`.

**Blocked by:** 01, 14

**Status:** ready-for-agent

- [ ] The note has the table per candidate, the threshold analysis, the cost of each change and one recommendation.
- [ ] Every number says what it was measured on and what was live.
- [ ] The owner's decision is recorded in `docs/decisions.md` and in ticket 11.
