# Consolidation: the model and the batch size, measured on quality, then the backlog finished

Type: research
Status: open
Blocked by: none

## Question

Which model or models should consolidate the research bank, at which `consolidation_llm_batch_size`, so the five verdict runs read observations that are good enough and arrive soon enough? Then: what infrastructure delivers that, and the backlog consolidated with it.

## Why now

Investigations 2–5 (tickets 05–08) read Memory after the memory-quality release, and that release exists to give observations that span the whole theme. On 2026-10-04 only 6,495 of 71,525 facts were consolidated. Consolidation runs one call after another within a round (one observation scope, `theme:photonics`, so `consolidation_llm_parallelism` does nothing), at about 12 minutes and ~30 calls per 100-memory round on `gpt-5.6-luna`. That is ~480 memories an hour, or 5½ days for the rest.

The owner's rule (2026-10-04): the objective comes first and infrastructure is fitted around it. So the choice is made on observation quality, and only then on speed and on which subscription pays. Observations stay in the bank: a weak model's observations would be read by every verdict run.

## State on 2026-10-04

- Live (home-ops #7218): consolidation on its own chain, weighted round-robin ChatGPT `gpt-5.6-luna` 3 : MiniMax-M3 7 (thinking off); a failed call falls through to the other. Atlas's round budget is 40 per 5 h. This applies to every bank's consolidation on the shared Hindsight.
- Held (home-ops #7220): the alias `hindsight-consolidation`, MiniMax-M3 with `local-pool-chat` (qwen3.8-flash-next, reasoning off) as LiteLLM's fallback. Held until this ticket measures qwen3.8.
- Quotas: ChatGPT 82% of the 5 h window, 73% of the weekly one (resets 10 Oct). MiniMax 98% weekly (resets in ~14 h from 11:40). On ChatGPT alone, one round cost about 4% of the 5 h window and 0.8% of the weekly one (yesterday: 1,261 calls, 15.1M input tokens, 42 rounds).
- qwen3.8-flash-next serving on worker4 (#7219): 2 slots of 262k context, about 23 tokens/s. The largest consolidation call is 9,000–20,000 input tokens and about 1,000 output tokens.

## How

The shared server can't choose a model per bank, so the measurement runs on the local Hindsight (`docker compose --profile hindsight`, 0.10.1) with `HINDSIGHT_API_CONSOLIDATION_LLM_*` set per arm. The facts are the same in every arm: the conformance fixtures (Lumentum, Coherent, the synthetic transcript) retained once, then consolidated per arm from a copy of that bank, or retained per arm with a fixed extractor.

Arms: qwen3.8-flash-next (via `local-pool-chat`) and MiniMax-M3 (after the MiniMax reset), each at batch size 8 and 16. Luna is the baseline: the LiteLLM `chatgpt` alias serves streaming callers only, so luna needs a Codex login on the local Hindsight (the owner's act) or production's own observations of the same documents as the reference.

Per arm: the known answers and the probe recalls of the conformance check, with observations allowed (recall at 10 and 50, observation share), a read of a sample of observations against their source facts (faithful, theme-spanning, figures kept), and seconds and tokens per 100 memories.

## Done when

- A table per arm, written to `docs/research/consolidation-models.md`, with a recommendation: model mix, weights, batch size.
- The infrastructure for it proposed as a home-ops PR (weights, the local fallback merged or closed, more ChatGPT capacity asked of the owner if luna is clearly better), and the batch size in a bank template release.
- The production backlog consolidated, and `GET /api/v1/memory/health` → `consolidation` completed before tickets 05–08 run.

## Comments

### 2026-10-04: measured; the 5090 consolidates the backlog

**The measurement.** 18 retain items rebuilt from production (windows of ~4,500 characters around the 25 known answers, plus AXT substrate windows; Lumentum, Coherent, AXT), extracted once by MiniMax-M3 into 152 facts, then consolidated per run from the same database snapshot on local Hindsight 0.10.1 with production's bank template (no mental models). Scripts and results in the session scratchpad (`t21/`: `prep.py`, `run.py`, `blind.py`, `results/`, `judge/`). Blind review: 30 observations per run, four reviewers, each scored 0–2 against its own source facts. "Real errors" excludes the date-only flags: the consolidator sees each fact's document date, which the reviewers did not (56 of M3's 75 dated observations use exactly their document's publication date).

| Run | faithful | specific | synthesis | useful | real errors | single-fact obs | spanning docs | answers at 10 | seconds |
|---|---|---|---|---|---|---|---|---|---|
| luna b8 | 1.87 | 1.77 | 0.43 | 1.13 | 3 | 58% | 17 | 24 | 751 |
| luna b16 | 1.77 | 1.80 | 0.33 | 1.03 | 4 | 70% | 16 | 23 | 630 |
| M3 b8 | 1.33 (dates) | 1.77 | 0.07 | 1.20 | 1 | 81% | 10 | 24 | 390 |
| M3 b16 | 1.70 (dates) | 1.97 | 0.27 | 1.23 | 2 | 73% | 12 | 21 | 330 |
| 5090 qwen3.8 27B b8 | 1.90 | 1.77 | 0.27 | 1.30 | 0 | 81% | 8 | 21 | 420 |
| 5090 b16 | 1.87 | 1.77 | 0.23 | 0.97 | 2 | 83% | 10 | 19 | 390 |

qwen3.8-flash on worker4 was stopped unscored: ~90 facts in 60 minutes per run, too slow for Hindsight (the owner, 2026-10-04).

**Findings.** (1) Every model is faithful; luna synthesises most, none much. (2) **The bigger problem is the consolidation setup, not the model:** 58–83% of observations are built from one fact, almost none spans companies; the theme-wide observations the memory-quality effort is for don't form. Check on production's observations before changing the setup (mission, scopes, facts per call). (3) Batch 16 saves 7–16% of the time and loses recall or synthesis on every model: keep 8.

**Decision (the owner, 2026-10-04).** Dev cycle: get the backlog through fast and free, then re-consolidate on a frontier model once the setup is stable. Home-ops #7222: Hindsight's consolidation uses LiteLLM's `hindsight-consolidation` alone (qwen3.8 27B on the owner's RTX 5090 via Ollama at 192.168.1.182, `num_ctx` 32768, thinking off; MiniMax-M3 as LiteLLM's fallback when the PC is off); ChatGPT is out of consolidation; Atlas's round budget is 100 per 5 h. Production consolidation restarted on it at 11:13 UTC (64,823 memories pending). The pilot report must say which model built the observations it read.

**Found on the way.**
- A Hindsight restart strands a running consolidation round in `processing` (the #7218 restart did, 09:29 UTC); Atlas follows it forever. Cancelling it marked the run failed, but the follow-up job never asks again, so nothing ran until a manual `atlas memory consolidate`. Atlas should cancel a round with no progress for ~30 minutes and request again, and a run ended `cancelled` should be requested again, not wait for the daily job.
- LiteLLM: `local-pool-chat` and `fast` sent `reasoning_effort: none`, which qwen3.8's template rejects (fixed in home-ops #7221); a non-streaming call to `chatgpt` is answered by a fallback model although the configmap lists none for it ("Fallbacks are configured for: chatgpt"): a DB-stored fallback, the owner's to check.

**Next.** Watch the backlog to completion (`GET /api/v1/memory/health` → `consolidation`); then test finding (2) on production's observations and specify the setup change.
