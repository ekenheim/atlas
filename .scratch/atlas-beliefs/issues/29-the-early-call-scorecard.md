# 29: The early-call scorecard

Type: task (with a build part, 29a)
Status: in-review (29a); the runs are the lead's
Blocked by: 20a (SanDisk's documents), 29a

## Why

Twenty-two Beliefs are proven, fifteen of them about AXT, the case the method was built on. Fact precision and the trust gate measure the process, not the goal: whether Atlas, reading only what was public on a date, names a bottleneck before the market priced it, and stays quiet where there was none. The owner agreed (2026-10-18) that progress on the goal is reported as this scorecard and the prospective record (ticket 19), and that photonics gets no more depth once its Hypothesis is published.

## The answer key (fixed 2026-10-18, before any run)

From `docs/research/early-signal-case-studies.md` (texts read blind on 2026-10-04, prices overlaid afterwards). Each case is run at each of its as-of dates; nothing in this table changes after the first run. Amendments go below it, dated, and the first table is what is scored.

| Case | Kind | As-of dates | The key: what a hit states, from documents public by the as-of date | Priced (the date the lead time runs to) |
|---|---|---|---|---|
| SanDisk (NAND) | bottleneck by decision | 2025-02-28, 2025-05-31, 2025-08-31 | NAND undersupply that the suppliers chose (utilisation cut while profitable), forecast by the company to last; price increases | 2025-09-10 (Goldman conference, "undersupplied ... through 2026"; the 6-month run from there) |
| IREN (grid power) | physical bottleneck | 2025-03-31, 2025-05-31 | Grid power for AI data centres is short; connections take years; IREN holds secured power | 2025-08-28 (first contracts) |
| AXT (InP) | calibration, not scored | 2025-08-31 | InP substrates short, two suppliers, export permits the gate | 2025-10-30 |
| eToro | negative | 2025-09-30 | No bottleneck: activity follows volatility | none |
| Snap | negative (inverse) | 2025-08-31 | No bottleneck: ad inventory outgrows demand, prices falling | none |
| POET | negative, photonics | 2025-11-30 | No bottleneck: capacity meets demand, ramp slipping, equity-financed | none |
| Raspberry Pi | squeezed buyer | 2025-10-31 | Squeezed by a DRAM shortage (the cost side), not a holder of one | 2026-03-31 |

Raspberry Pi (LSE, not an SEC filer) is in the key but run only if its documents can be reached (FCA NSM for regulated news, TradingView for calls); otherwise it is reported as not run, never dropped silently. POET was named by the owner and is photonics, so it counts as a negative with that caveat.

## The protocol

1. **Same question everywhere.** Each run is one Researcher session, seeded with the case's company, as of the as-of date, with the question: "As of {date}, does anything constrain supply in {company}'s market, who holds it, and what would relieve it?" No case gets a question naming its answer.
2. **Two readers per run, scored apart.**
   - *The code's reading:* the archive-signal ranking for the company as of the date (`scripts/signal_replay.py --as-of`, no model). It cannot leak outcomes. Scored: the rank of the first hit a blind reviewer marks as the key's cue, among the company's top 20.
   - *The session's reading:* the Beliefs it proposes and its card. Scored hit when a proposed Belief (judged or not) states the key's bottleneck with Facts from documents public by the as-of date; a miss otherwise. For a negative, a false positive is a Belief stating a supply constraint the company holds.
3. **The leakage risk, named.** The session's model has read about 2025 in training. Atlas bounds the data by the as-of time; it cannot bound the model's memory. So: the prompt forbids outside knowledge; a statement no cited Fact carries is not scored; the negatives measure how often the model "finds" what it cannot have read; and the code's reading is reported beside the session's as the leak-free baseline. A hit the code's reading does not support is marked as such.
4. **Scored by the key, not by judgement.** A reviewer who sees the key and the session's Beliefs, not the prices, marks each Belief hit, miss or false positive with a one-line reason. Two blind reviewers; disagreement goes to the lead, recorded.
5. **Reported as:** hits of the positive runs, false positives of the negative runs, lead time in days (as-of date to the priced date) for the earliest as-of that hit, and the code's reading's ranks. Seven cases are no hit rate; the report says so.

## 29a: what to build

- A `scorecard` theme in the universe config: SanDisk (already in `memory-packaging`), IREN, eToro, Snap, POET; CIKs and forms from SEC's submissions (the lead supplies them in the ticket's notes before the implementer starts); `tradingview_symbol` each, so the catalog job fetches their call transcripts.
- `agent/run.sh researcher` takes an optional question and seed companies (`ATLAS_AGENT_QUESTION`, `ATLAS_AGENT_SEEDS`), overriding `next_issue`; the wrapper prompt says so; `--dry-run` shows them; `tests/unit/test_agent_run.py` covers both.
- `scripts/scorecard.py`: given the runs (session ids), reads each session's Beliefs, Facts and card through the API, joins the key, writes the review sheets (no prices, no outcome) and, from the reviewers' marks, the report to `.scratch/live-runs/<stamp>-scorecard/`. Unit-tested on recorded API answers.

## Acceptance criteria

- [ ] The key above unchanged when the first run starts (git history shows it).
- [ ] Every case run at every as-of date, or reported not run with the reason.
- [ ] The report: hits, false positives, lead times and the code's ranks, each run linked to its session; in `.scratch/pilot/results.md` and `docs/experiments.md`.
- [ ] The owner reads the report.

## Amendment 1 (2026-10-18, after the approach debate; before any reading or run)

The key table above is unchanged. A debate of four rival plans, each red-teamed, and a judge (`.scratch/atlas-beliefs/debate-2026-10-18.json`) kept this ticket first and repaired its protocol. These rules bind every run; nothing here may change after the first code reading.

**Frozen configuration.** Signal scorer `signals-v3` at commit `f0fe9ee` (config version 3); the `atlas-research` skill and `agent/prompts/researcher.md` at the commit that carries 29a (the skill unchanged since `84b299a`; the commit recorded in the coverage table before any run); the agent model by exact ID `claude-opus-5-5` (never `run.sh`'s `opus` alias); the judge `chatgpt` (gpt-5.6-luna) with `finding_judge.v4`/`v5`; Atlas release 0.6.12 or the first release carrying 29a, recorded with each run. A run on any other configuration is flagged and not scored.

**Isolation (the leak the debate found).** `prior_work` filters Facts by company and as-of time, not by session or theme (`backend/atlas/prior_work.py`, `_facts`), and Fact reuse matches on version, company and step (`atlas.facts.reuse`). A 2025 replay would inherit the 2026 sessions' Facts, chosen with hindsight (114 standing AXT Facts as of 2025-08-31), and one SanDisk run would hand its Facts to the next. Every scorecard run is therefore an **isolated session** (29a): `prior_work` empty, Fact reuse off, recall from the conclusions bank and `list_beliefs` refused, and its Beliefs can never be judged, so they make no call and never reach the conclusions bank. The scorecard companies stay off every scheduled agent's frontier, and the memory-packaging Researcher runs no SanDisk session before the scorecard's SanDisk runs are done.

**The code's reading is not leak-free in every case.** It cannot leak prices, but its vocabulary was written from the AXT and SanDisk case studies (`configs/discovery/signals.yaml`; experiments 2026-10-15). AXT's and SanDisk's code ranks are **in-sample** and reported apart; IREN, eToro, Snap, POET and Raspberry Pi are its clean cases. The scored statistic stays the within-company top-20 rank; a pooled percentile across the universe (k = 20, `--since` 365 days before the as-of date) is reported beside it.

**Pre-registered prediction:** IREN's code rank will be weak: a bare "shortage" scores 0.8 under `min_score` 1.5 and no cue family holds "bottleneck". If it is, that is the vocabulary's photonics shape, found in advance, not after.

**Closed-book arm.** Before any session, the frozen model with no tools is asked, per case and as-of date, to recall the company's supply position as of that date. Its verdict (stated, hedged, not stated) is reported beside the session's. A case the closed-book model states is "not discriminating" for the session's reading. The negatives measure discipline (the model knows eToro and Snap fell), not leakage.

**Miss taxonomy, from the session's recorded tool trace.** M1: the key's document is not in the archive (intake). M2: in the archive, never surfaced (code rank above 20 and never read) (signal vocabulary or search). M3: read, not recorded as a Fact (skill). M4: recorded, but in no Belief or under the wrong step (predicate and step model: market-level supply statements, chosen supply discipline). M5: the Belief misstated (judge). FP: a supply constraint the company holds, found on a negative (discipline, Skeptic). **Rule:** the same class on two positive cases triggers its build; otherwise the most frequent class across the positive runs plus AXT decides, ties going to M1. One miss alone triggers nothing.

**Control list for the code half.** Before ingest, by rule: for each scored case, the two SEC filers with the same four-digit SIC code nearest in market value that are not in the universe, drawn with seed 20261018; their hits are reported as a base rate and never labelled by price.

**Order.** (1) This amendment committed; (2) the coverage table (each key document present or absent as of each as-of date; absences recorded as M1 before any session); (3) the code readings and the closed-book probes, committed to `.scratch/live-runs/`; (4) the isolated sessions, one per ChatGPT 5-hour window; (5) two blind reviewers per run (the key and the Beliefs, no prices, probes or code ranks), the lead adjudicating and classifying misses. **Report** per run: the session's raw hit, the closed-book verdict and the code rank side by side; no composite score. Fact precision at or above 92% and the trust gate at or below 10% are guardrails; a run below them is flagged.

**Added acceptance:** this amendment committed before the first code reading and session; every run isolated and on the frozen configuration.

## 29a, as amended (2026-10-18): what to build

1. **The `scorecard` theme** in `configs/themes/ai-infrastructure.yaml` (bump `version`): SanDisk (already a `memory-packaging` company; a company may belong to both themes), IREN (CIK 0001878848; forms 10-K, 10-Q, 8-K, 20-F, 6-K: it moved from foreign-private-issuer forms to domestic ones in 2025), eToro (CIK 0001493318; F-1, 20-F, 6-K), Snap (CIK 0001564408; 10-K, 10-Q, 8-K), POET (CIK 0001437424; 20-F, 6-K); CIKs and forms read from SEC's ticker file and submissions on 2026-10-18 by the lead. `tradingview_symbol`: `NASDAQ:IREN`, `NASDAQ:ETOR`, `NYSE:SNAP`, `NASDAQ:POET` (unverified; the catalog job confirms). Choose the smallest change to 20a's per-theme layers that lets these companies in (a theme's own short layer list, documented in `docs/decisions.md`); the Claim taxonomy stays photonics'. The scorecard theme is never a scheduled agent's theme.
2. **Isolated sessions.** `POST /api/v1/sessions` and MCP `open_session` take `isolated: true` (migration 0116: a `research_session.isolated` boolean, default false). In an isolated session: `prior_work` returns nothing; `record_fact`/`POST /facts` never reuses a standing Fact (it records a new one, judged as usual); `recall` with `bank: beliefs`, `list_beliefs` and `get_belief` are refused (`isolated_session`); and a Belief whose producing session is isolated cannot be judged (`POST /beliefs/{id}/judge` 409 `isolated_session_belief`), so it makes no call and never reaches the conclusions bank. Test-first at the API and MCP seams.
3. **The tool trace.** `GET /api/v1/sessions/{id}/tool-calls` lists the session's recorded calls (`session_tool_call`: tool, arguments, outcome, at) in order, for classifying misses.
4. **The runner.** `agent/run.sh researcher` takes `ATLAS_AGENT_QUESTION` and `ATLAS_AGENT_SEEDS` (company slugs, comma-separated), overriding `next_issue`, and `ATLAS_AGENT_ISOLATED=true`, which the wrapper prompt passes to `open_session`; `--dry-run` shows them; `tests/unit/test_agent_run.py` covers each. The model stays `ATLAS_AGENT_MODEL` (the lead passes the exact ID).
5. **`scripts/scorecard.py`**: given a runs file (case, as-of date, session id), reads each session's Beliefs, Facts, card and tool trace through the API and writes, per run, a review sheet with the key's row and the Beliefs (no prices, probes or code ranks) and a trace summary (searches, reads, Facts by document date); then, from the reviewers' marks file, the report (raw hit, closed-book verdict, code rank per run; misses by class; the rule's choice). Unit-tested on recorded API answers.
