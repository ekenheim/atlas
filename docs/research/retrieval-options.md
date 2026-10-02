# Retrieval options: the reranker and the embedding query instruction, measured offline

Memory-quality ticket 15 (the reranker and query-prefix part). Measured 2026-10-02 on the local spike Hindsight 0.10.2 and this machine's CPU (24 logical cores, no GPU). Harness: `spikes/hindsight/retrieval_options_*.py`. Raw results: `.scratch/live-runs/20261002-retrieval-options/` (not in git).

**Read this first: what the numbers cannot show.** The live candidate pool the task asked for was **not obtained**. The throwaway bank's first (and only) full pass retained the facts correctly, but every `trace: true` recall answered HTTP 500, and the bank was deleted by the harness before I saw it; the LLM budget (117 of 120 requests) did not allow a second retain. So the rerankers were compared on pools **rebuilt offline** from the bank's 407 retained facts (below), not on the pool Hindsight's four arms produce. The result is a small, noisy, best-effort comparison (11 answers), not a decision-grade benchmark. The ordering of rerankers here should be treated as a hint, and the recommendation below rests more on cost, risk and the server-wide effects than on these numbers.

## What was live

| item | count |
|---|---|
| LLM requests (Hindsight's request log of the bank; extraction of Coherent's 10-K, 10-Q, Lumentum's 8-K, 10-Q and the synthetic transcript through Atlas's real retain path; MiniMax-M3) | 115 |
| plus an earlier aborted attempt (a Windows archive bug made ingest fail; only the transcript retained) | 2 |
| **Total (cap 120)** | **117** |
| Retain operations through the counting proxy | 6 (the run's last pass) |
| Facts in the bank | 407, all `world` facts (consolidation was switched off on the bank mid-run to stay under the cap, so no observations) |
| Recalls | 25 (5 questions x question + 4 queries), `budget: high`, `max_tokens: 8192`, `trace: true`; **all 25 failed (500)** |

Everything else (embeddings, rerankers) ran locally; no call to production Atlas or the cluster's Hindsight; Jev not measured (no TypeSafe key).

### The 500s are a finding in themselves

The recall error was `HTTP 413 from <LiteLLM>/rerank ... batch size 300 > maximum allowed batch size 256`. The spike (like the cluster's LiteLLM `rerank` alias) fronts a TEI server whose maximum batch is 256, while Hindsight sends the whole pre-filtered pool, up to `HINDSIGHT_API_RERANKER_MAX_CANDIDATES` = 300 candidates, in one request on the `litellm` reranker provider. **Any recall whose pool exceeds 256 candidates fails outright on that path.** The 6-fact bank of the first attempt stayed under it. This matters for the cluster: check which reranker provider and batch limit it runs (the docs say the native `tei` provider batches 128), and either use that provider, or set `HINDSIGHT_API_RERANKER_MAX_CANDIDATES` to 256 or lower, or raise the TEI `--max-client-batch-size`. This is separate from the quality question and should be checked before the corpus grows.

## Method

1. **Bank.** Spike Hindsight 0.10.2 (same image digest as the cluster), the research bank template, the conformance driver's retain path (`tests/live/conformance.py`) with triage off. Windows needed two harness changes: the archive on Silo instead of the filesystem (the read-only temp file cannot be unlinked), and an `os.fchmod` shim. The fixtures hold Coherent's 10-K and 10-Q but Lumentum only as an 8-K and 10-Q, so **13 of the 25 known answers resolve** (all in Coherent's 10-K, 5 sections: Item 1, 1A and 7), 12 do not (Lumentum's 10-K is not in the fixtures). 11 of the 13 have a usable answer fact (below). Questions covered: laser-chips 6, inp-substrates 2, module-assembly 3, dsp-drivers 1, coherent-demand 1.
2. **Answer facts.** The bank keeps no span per fact, so an answer's facts are the up-to-two facts of its section whose Qwen3 embedding is closest to the answer sentence (cosine >= 0.6; 0.63 to 0.85 in practice). Approximate, and **biased toward embedding-friendly rankings**, because the same model picks the labels and is one arm of the pool.
3. **Pools.** For each of the 25 queries: a semantic arm (today's Qwen3-Embedding-0.6B weights, fp32, no prefix), a BM25 arm, each 200 deep, RRF (k=60), cut to 300: 202 to 271 candidates. The graph and temporal arms are not rebuilt. The bank holds 407 facts, so a pool is most of the bank, and recall at 45 is a much easier test than on the production corpus (the before-measure there: 12 of 23 answers not pointed at).
4. **Rerankers** on those pools, per-query CPU scoring of the whole pool: `rrf` (the fused order), `cross-encoder/ms-marco-MiniLM-L-6-v2`, `BAAI/bge-reranker-v2-m3`, `Qwen/Qwen3-Reranker-0.6B` (model card prompt, yes/no probability, default instruction). Query text only, fact text only (no context field).
5. **Metrics.** Per answer, the rank of the first memory in the answer's section (`section`) or of its answer fact (`fact`), taking the best over the five recalls of its question; found-at-10 and found-at-45 over the 11 answers. Atlas's merged-section ranking at 10 and 50 was also computed.
6. **Embedding instruction.** Qwen3-Embedding-0.6B locally, the rank of each answer fact among all 407 facts for each of the 25 queries, with no prefix (today), with Qwen3's documented web-search instruction (`Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:` + query), and with a task instruction (`... research question about the optical and AI-infrastructure supply chain, retrieve passages from company filings that answer it`). 55 (query, answer) pairs per variant.

## Results: rerankers (11 answers, pools of 202 to 271 candidates)

| reranker | section found @10 | @45 | answer fact found @10 | @45 | median best fact rank | MRR (fact) | worst fact rank | CPU wall s / query | CPU-seconds / query |
|---|---|---|---|---|---|---|---|---|---|
| rrf (fused order) | 1.00 | 1.00 | 0.73 | 0.91 | 3 | 0.48 | 49 | 0 | 0 |
| MiniLM-L-6 (today's) | 1.00 | 1.00 | 0.91 | 1.00 | 5 | 0.33 | 36 | 2.3 | 24 |
| bge-reranker-v2-m3 | 1.00 | 1.00 | 0.91 | 1.00 | 3 | 0.38 | 16 | 42 | 475 |
| Qwen3-Reranker-0.6B | 1.00 | 1.00 | 0.82 | 1.00 | 3 | 0.37 | 19 | 151 | 1,739 |

Sorted best fact ranks: rrf 1,1,1,1,2,3,6,7,20,20,49; MiniLM 1,1,3,3,5,5,6,6,9,9,36; bge 1,1,3,3,3,3,4,4,5,9,16; Qwen3 1,2,2,2,3,3,3,5,5,12,19.

By question (fact @10 / @45): laser-chips (5) rrf 0.8/0.8, MiniLM 0.8/1, bge 0.8/1, Qwen3 0.6/1; inp-substrates (2) 0.5/1, 1/1, 1/1, 1/1; the single-answer questions all reach 1 at 45 with every reranker except `rrf` on dsp-drivers (rank 20).

Latency: 24 logical cores, fp32, batch 16 to 32, about 238 pairs per query. MiniLM is about 10 ms a pair; bge-reranker-v2-m3 about 0.18 s a pair; Qwen3-Reranker-0.6B about 0.64 s a pair. The two larger models are far too slow for a recall on CPU (42 s and 151 s per recall); they need a GPU, or a much smaller candidate cut (for example the top 40 of the fused pool), or a quantised runtime, which I did not try.

What these numbers show and do not:

- **Section-level recall is saturated** (all 1.0): five large sections, any pool contains them. It does not discriminate and says nothing about the production before-measure.
- **Fact-level, n = 11:** the differences between the three cross-encoders are one answer at most at @10 (10 of 11 versus 9 of 11), well inside noise. What is consistent is the **tail**: the fused order alone leaves three answers at ranks 20, 20 and 49, while every cross-encoder keeps all 11 within 36 (MiniLM), 19 (Qwen3) or 16 (bge). The fused order wins on the top ranks (MRR), which is partly an artefact: the labels and one pool arm both come from the same embedding model. MiniLM has the worst top-of-list placement among the three (median 5) and the worst tail.
- Not measured: Jev (no key), Kev (below), anything on the graph or temporal arms, Hindsight's own score combination (recency, temporal, proof) after reranking, or the real production pool.

**Kev** (github.com/jaredpalmer/kev): skipped. Its README documents GPU (CUDA, ROCm) and Apple MLX backends and PyTorch checkpoints, with no CPU path, no GGUF, ONNX or vLLM; it serves `POST /v1/systemone` with `yes/no`, `choice` and `score` question types and says it is not designed as a reranker. I did not verify that Hindsight's listwise `choice` request is one it answers (that needs the server running; no TypeSafe key to compare). Cheapest check for the lead: run its smallest model on a GPU and point `HINDSIGHT_API_RERANKER_TYPESAFE_BASE_URL` at it; its accuracy figures are its own.

## Results: the embedding query instruction (local Qwen3-Embedding-0.6B, 55 pairs)

| query format | median answer-fact rank among 407 | p25 / p75 | answer fact in top 10 | in top 45 | MRR | paired vs today (better / worse) |
|---|---|---|---|---|---|---|
| none (today) | 19 | 7 / 52 | 0.36 | 0.73 | 0.138 | |
| web-search instruction | 19 | 6 / 39 | 0.36 | 0.78 | 0.132 | 23 / 26 |
| task instruction | 15 | 5 / 40.5 | 0.44 | 0.78 | 0.122 | 31 / 22 |

The web-search instruction is a wash. The task-specific instruction moves the median rank from 19 to 15 and the top-10 rate from 0.36 to 0.44, better in 31 pairs and worse in 22: a small, plausible gain (the model was trained with instructions), not a significant one at this sample size; MRR is flat to slightly lower. The effect is confined to the queries: **a prefix re-embeds nothing, but it applies to every bank on the server**, including the owner's other banks, whose queries would all gain the same instruction (a task-specific one suits a research bank, not necessarily a chat-memory bank; the documented generic one is the safe choice and it measured as neutral here). `HINDSIGHT_API_EMBEDDINGS_QUERY_PREFIX` is a literal string; Qwen3's format is `Instruct: <task>\nQuery:` (no space after `Query:`).

## Recommendation

For the server (all settings are server-wide on the shared Hindsight; the owner decides):

1. **Reranker: do not change on this evidence alone. If a change is made, take `BAAI/bge-reranker-v2-m3` served on a GPU (or a TEI image that serves it), not Jev.** It had the best tail, the best median with MiniLM's recall, and keeps every bank's text on the cluster; Jev would send every bank's candidate text to a hosted third-party API, including the owner's other banks, and is untested here. bge costs 0.18 s a pair on this CPU, so it only makes sense on a GPU or with a small candidate cut; Qwen3-Reranker-0.6B is 3.5 times slower on CPU for no measured gain. Today's MiniLM is cheap and, on this bank, not clearly worse at the top 10 than the alternatives; its weakness is the ordering of mid-rank answers (median 5, tail 36), which the real corpus (more candidates than here) would magnify, and that is what the production before-measure suggests. A proper decision needs the live-pool run (below).
2. **Query prefix: leave unset for now** (neutral to slightly positive, one bank-wide setting that changes all consumers' queries); if the owner wants to try it, use the documented `Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:` (no measured gain) or the task instruction (a small measured gain, specific to research banks). No bank needs re-embedding either way.
3. **`PRUNE_CANDIDATES` off** (with it on, recall returns at most 12 results): yes if the pointer ranking is meant to see about 45 memories; it changes only result counts for every bank (other banks' recalls would return up to the `max_tokens` budget instead of 12).
4. **Fallback chain ending in `rrf`** (ticket 11): yes; an outage or a 413 then degrades to the fused order (which here is not worse than MiniLM at the top, only in the tail) instead of failing recall. This protects every bank.
5. **Fix the 256 batch limit** (above) before anything else: it is the only measured way recall fails today.

## What is needed to make this decision-grade

A rerun of step 1 with the spike started as `ATLAS_RERANKER_PROVIDER=rrf` (the recall then cannot fail on the TEI batch limit, and `trace.rrf_merged` is the real pool), a retain budget of roughly 140 LLM requests (the 19-section corpus used 115 plus consolidation), then the unchanged offline steps on the real pools. `retrieval_options_collect.py` is written for that (its recall step now stops loudly on a non-200). The real pool also needs answers outside Coherent's 10-K (the fixtures lack Lumentum's 10-K).

## Files

- `spikes/hindsight/retrieval_options_collect.py`: the live step (retain, pools, dumps, bank deleted).
- `spikes/hindsight/retrieval_options_embed.py`, `retrieval_options_rerank.py`, `retrieval_options_summary.py`, `retrieval_options_common.py`: the offline steps (a scratch environment with torch, sentence-transformers and transformers; not in `pyproject.toml`).
- `.scratch/live-runs/20261002-retrieval-options/`: `memories.json` (the 407 facts), `answers.json`, `answer-facts.json`, `rerank-scores.json`, `rerank-results.json`, `embedding-instruction-rows.json`, logs. `recalls.json` holds the 25 failed answers.
