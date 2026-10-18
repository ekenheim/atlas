# 29: The early-call scorecard

Type: task (with a build part, 29a)
Status: ready-for-agent (29a); the runs are the lead's
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
