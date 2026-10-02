# 15: The embedding model and the reranker, measured and decided

**What to build:** The owner gets a recommendation, with numbers, on which embedding model Memory should run on and with which thresholds: keep the current one as it is, keep it with its query instruction, or change it. The owner offered a different model on 2026-10-02.

Type: research (a measurement; no Atlas behaviour changes). The lead runs the live part.

Study: `docs/research/hindsight-memory-use.md`, finding 7. What is known: the cluster embeds with Qwen3-Embedding-0.6B (1,024 dimensions) through the `openai` provider with no query instruction, though the model expects one on queries and the pinned docs have `HINDSIGHT_API_EMBEDDINGS_QUERY_PREFIX` for it; five similarity thresholds are at defaults calibrated for `BAAI/bge-small-en-v1.5`; the vector dimension is fixed for the whole server once its tables hold rows (the manifest's "one-way door"), and the server is shared with other consumers.

- On the local Hindsight (ticket 01's Compose, the cluster's version), retain the same recorded fixtures under each candidate and run the known answers and the recall behaviours of the conformance check (ticket 14) against each:
  1. the current model as served today;
  2. the current model with its documented query instruction as the query prefix;
  3. the model Hindsight's thresholds are calibrated for, served locally (a text-embeddings-inference container);
  4. at most two further candidates the owner's embedding service could serve at 1,024 dimensions or fewer, chosen from published English retrieval results and named with the reason.
- Per candidate: recall at 10 and at 50 on the known answers; the distribution of cosine similarity between queries and the facts that answer them, and between facts, against the five thresholds (how many right answers each gate would cut, how dense the semantic links become); retain and recall latency.
- **The reranker, measured the same way** (added 2026-10-02, the owner pointed at Hindsight's post "Adding Jev reranker: what we learned"). The reranker decides which of the ~300 fused candidates survive into the ~45 memories a recall returns, which is where the known answers are lost (the before-measure: 12 of 23 not pointed at). The cluster runs `ms-marco-MiniLM` in a TEI sidecar, a small web-search cross-encoder. Hindsight 0.10.2 has `HINDSIGHT_API_RERANKER_PROVIDER=typesafe` (Jev, listwise, `jev-latest`) as a setting; Hindsight's own benchmark reports recall@1 0.783 against MiniLM's 0.583 at 240 candidates, at 63 ms a query, on its data, not ours. Measure on the local Hindsight: the current embedding with MiniLM, and with Jev (`PRUNE_CANDIDATES` off: with it on, recall returns at most twelve results), on the known answers and the probe set; Jev needs the owner's TypeSafe API key (early access). Say plainly in the recommendation: the reranker is server-wide on the shared Hindsight, and Jev sends the candidate text of every bank's recalls to TypeSafe's hosted API, the owner's other banks included; it needs a fallback chain ending in `rrf` (ticket 11) so an outage degrades the order instead of failing recall. **Measure a self-hosted reranker beside it**, which keeps every bank's text on the cluster and plugs into the TEI sidecar the cluster already runs (`HINDSIGHT_API_RERANKER_TEI_URL`; or LiteLLM's rerank route): a current open cross-encoder reranker (for example Qwen3-Reranker-0.6B, the family of the cluster's embedding model, or bge-reranker-v2-m3), chosen from published retrieval results and named with the reason. Not Cloudflare's Clef (the owner asked, 2026-10-02): it is an open, self-hostable decision model, but a classifier, not a reranker, and Hindsight has no provider for it, so using it would mean writing a reranker extension for the shared server.
- State the cost of each change plainly: a query prefix re-embeds nothing; a model of the same dimension makes every bank's stored vectors stale until re-embedded; another dimension needs an empty store, so a new server or a wipe, for every consumer.
- Recommend one, with thresholds, and say what the recommendation does not cover (the fixtures are a few filings, not the production corpus). The owner decides; ticket 11 carries the decision into home-ops, and the backfill (ticket 12) runs after it.

Output: `docs/research/embedding-model.md`, the raw numbers under `.scratch/live-runs/`.

**Blocked by:** 01, 14

**Status:** ready-for-agent

- [ ] The note has the table per candidate, the threshold analysis, the cost of each change and one recommendation.
- [ ] Every number says what it was measured on and what was live.
- [ ] The owner's decision is recorded in `docs/decisions.md` and in ticket 11.
