# The AXT replay: would Atlas have made the early call as of mid-2025?

Type: task
Status: resolved
Blocked by: none

## Why

The owner's aim is early calls like Serenity's AXT (`docs/research/early-signal-case-studies.md`): AXT said on its Q2 2025 call that InP demand was "too fast to be adequately serviced by just two players", months before the price moved. Nothing yet asks whether Atlas, given only what was public then, surfaces that statement and builds the argument around it. The five pilot questions are asked as of today, where the answer is already in every filing. This is the one measurement that connects to why Atlas exists.

Approved by the owner on 2026-10-12 (this session).

## What to run

1. **Check the archive holds the period:** AXT's Q2 2025 call transcript (TradingView) and its 2025 10-Qs, Coherent's and Lumentum's filings and calls to 2025-08-31, each with `available_at` before the cutoff. List what is missing; ingest nothing new unless the owner agrees (a backfill ingest records `available_at` from EDGAR, so later ingestion of an older filing is fine).
2. **Leakage check before trusting a result:** with `as_of` = 2025-08-31, confirm the archive search, the Reader's recall and the pointers return nothing available after the cutoff (the pointers filter by `as_of`; `query_timestamp` is not a hard filter in Hindsight, so read the recall results' Source Versions). Any later-dated section reaching a Reader is a defect ticket, and the run does not count.
3. **The run:** `POST /api/v1/investigations` with the argument plan, `as_of` 2025-08-31, question "Is indium phosphide substrate supply a bottleneck for datacom lasers, and who controls it?", seeds Coherent and Lumentum only (AXT must be reached by the hop or the search, not given). A second run seeded with AXT if the first does not reach it, reported separately.
4. **The comparison:** the researcher's hour under the same cutoff, archive-only (web search cannot be as-of): the same question, the seeds' filings and calls before the cutoff through `scripts/pilot_baseline.py`'s search.
5. **Scoring:** does the card's constraint step cite AXT's "two players" statement or its equivalent, with the right status and period; what the card says about relief, control and capture as of then; the researcher's hour beside it; the usual blind review of the Facts.

## Done when

- [x] Steps 1 and 2 recorded (the archive holds the period; no leakage in either run).
- [x] The cards and reviews in `.scratch/pilot/results.md`, "The proof sessions"; the experiment in `docs/experiments.md`.
- [x] The map's Decisions carry the paragraph.

## Comments

**2026-10-12, step 1 read on production (read-only, `GET /api/v1/companies/{id}/sources`, `/sources/{id}/versions`, `/archive-search`):**
- AXT: 16 of its 44 Source Versions are available before 2025-09-01, among them the Q2 2025 call transcript (TradingView, `available_at` 2025-07-31T20:30Z, version `c91733c3-…`), the Q4 2024 and Q1 2025 calls, the Needham conference of 2025-01-14, the 10-K of 2025-03-14 and the 10-Qs of May and August 2025. The earliest AXT version is 2024-10-31.
- `archive-search?q=adequately serviced by just two players&company_id=<axt>&as_of=2025-08-31` returns the Q2 2025 call as its first hit (score 26.6), so the statement is in the archive and the as-of search reaches it.
- Coherent: 193 versions before the cutoff (SEC only: 10-K, 10-Q, 8-K; no transcript before the cutoff in the first 201 of 355 documents). Lumentum: 174 (SEC only, of 226 documents). Both have their FY2025 10-Ks (2025-08-15, 2025-08-19) and the quarters before the cutoff.
- So step 1 needs no new ingest for the first run. Step 2 (leakage) still has to be checked on the run itself.

## Answer

Run twice on 2026-10-12, both seeded with Coherent and Lumentum as of 2025-08-31: a Claude session with the `atlas-research` skill and the pipeline's argument plan (investigation `da618842`). Both reached AXT. The session recorded AXT's export-control hold, permits, backlog, share and competitors, and stated in substance that the other players could not keep up (the 1 May 2025 call), though not the 31 July sentence, and under a step it marked disputed; its Facts were 93% right, its statements 24 of 26 through the trust gate. The pipeline did not state the point; its Facts were 75% right, 22 of 29 statements through the gate, at eleven times the tokens. Neither run read anything after the cutoff. The researcher's-hour comparison was run on question 2 instead (19 of 32 facts on the session's card against the pipeline's 8). Detail: `.scratch/pilot/results.md`, "The proof sessions".
