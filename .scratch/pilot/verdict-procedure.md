# The verdict runs: the frozen procedure

Written by the lead on 2026-10-03, before any verdict run. It fixes how the five pilot investigations are run and reviewed for the verdict (pilot-review tickets 05 to 08 and 13, with investigation 1 run again), so that all five are measured the same way. The measures and thresholds are ticket 02's (`.scratch/atlas-pilot-review/issues/02-pilot-verdict-criteria.md`, with its comments); the review rubric is the `pilot-review` skill's. Nothing here changes between the first and the fifth run. A defect found on the way becomes a ticket, not a fix, unless it fails the trust gate (then: fix, release, and re-run that investigation on the new version, and say so).

## 1. One version, its preconditions

- **All five on one version,** investigation 1 included (its 0.3.1 run is the before-measure, not a verdict run). No deploy, template import or setting change between the first run and the last; a change forced by a blocker re-runs every investigation already run.
- **Before the first run,** recorded in the results with the time:
  - production's version (`atlas_build_info`) and `/health/ready`;
  - Memory: `GET /api/v1/memory/health`: no section `stuck`, the seeds' sections at profile, `pending` sections listed by company; Hindsight's `pending_consolidation` (bank stats) and the last consolidation run;
  - the last reconciliation (memory-quality ticket 22, if released): its status and counts;
  - the memory conformance report (`scripts/memory-conformance.sh --strict`), passed or not. Whether the runs may start on a failed report is the owner's (the map: "a fixed verdict date"); the report is attached either way, and the verdict says which.
  - `GET /api/v1/queue`: no pause, the `minimax` window with room for one investigation (2,000,000 tokens).

## 2. Running

- **One at a time, in order 1 to 5,** each alone on production, so its latency is its own. Nothing else is run meanwhile (no discovery, no other investigation, no live suite).
- `uv run --no-sync python .scratch/tools/pilot_runs.py <n> pilot-<version>` (the plan's question verbatim, its seeds, a 2,000,000-token budget); it waits out a budget pause, saves everything the review reads and runs the archive-search baseline. Output: `.scratch/live-runs/pilot-<version>/inv-<n>/` (not in git).
- `uv run --no-sync python .scratch/tools/pilot_review_pack.py <n> pilot-<version>` cuts the saved run into the reviewers' files (`review/`).

## 3. Reviewing (Opus reviewers; the lead adjudicates and audits)

- **Claims, twice, blind.** Each chunk of accepted Claims (`claims-<k>.json`) goes to two reviewers who do not see each other's verdicts. Rubric: the skill's section 2 (the verb belongs to the object; the layer is in the quote; boilerplate is not evidence; on the question; counterparties), and ticket 02's clarifications: a Claim is right when subject, predicate, object and direction match the quote and its layer is not *wrong*; an *unconfirmed* layer counts as right and is counted apart. Each verdict: `right`, `wrong` (with the reason and the right reading) or `off-question`, with the quote. The lead adjudicates every disagreement, confirms every Claim both call wrong, and checks a random 10% of those both call right; Cohen's kappa is reported.
- **The card, once:** each finding against the Claims it cites (the trust gate: it says only what they say), saved work (correct, primary span, on a clause of the question, not boilerplate; product catalogs one per company), the thin-card test, the open questions.
- **The baseline, once:** the top 20 hits in order, stop at the tenth on-question one, covered or not at the hit's level of detail (ticket 02's magnitude rule; "covered in substance" listed apart).
- **The run, once:** the roles ran (the Skeptic read a document with passages; the Financial Analyst has a sourced input per seed with as-of figures; the Editor wrote open questions), what was searched and read, cost (tokens in and out, role calls), latency (wall time minus budget pauses).
- **A researcher's hour** (ticket 02, 2026-10-02): one agent, with web search and the archive's term search (`scripts/pilot_baseline.py`'s search over the seeds' filings) and no access to Atlas's Memory, Claims, cards or results, a budget of one hour and 200,000 tokens, gets the question verbatim and the seeds, and writes the best answer it can, every fact cited (URL or filing and passage). Prompt, fixed: "You are an equity research analyst with one hour. Answer this question as well as you can from primary sources (company filings, call transcripts, company releases) and reputable industry sources, citing each fact to its source: <question>. Start from these companies: <seeds>. Say what you could not establish." A reviewer then marks each of its on-question, true, cited facts as on the card or not, and each saved-work finding of the card as in the answer or not.
- **The write-up:** the skill's section 4, in its order and labels, under the investigation's heading in `.scratch/pilot/results.md`; `wrong-claims.md` and the card's misstatements kept in `review/` (the evaluation cases for the meaning check).
- **Edges:** after each review, ticket 09's rule (every Evidence Claim right: approve; every one wrong: reject; else left, with a note), applied with the review's `edge-plan.json`.

## 4. After the fifth

- Pooled machine-reviewed edge precision; the per-investigation table; the verdict by ticket 02 (pass, partial, fail).
- The held-out answer key (ticket 02, 2026-10-03): the owner lists Serenity's flagged names and dates; found, missed and "found before" per item, with replays where the budget allows.
- `docs/pilot-report.md`, in ticket 02's order; then ticket 13 (the verdict and the next effort).
