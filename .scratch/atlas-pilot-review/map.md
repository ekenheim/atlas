# Map: the pilot review

Label: wayfinder:map

## Destination

The pilot's verdict, in two artifacts:
- **The pilot report** (`docs/pilot-report.md`; START_HERE step 8): the five pilot investigations reviewed against their cited spans, each compared with the archive-search baseline, the §15 demo shown on production, the evaluation results, and the exact test status.
- **A ready-for-agent spec for the next effort** (via `/to-spec`, then `/to-tickets`), chosen from what the report shows.

## Notes

- **Domain:** glossary `CONTEXT.md`; the product spec is authoritative; deviations go in `docs/decisions.md`. The questions and seeds are in `.scratch/pilot/pilot-plan.md`, the reviews in `.scratch/pilot/results.md`, the defects in `.scratch/atlas-pilot-fixes/issues/`.
- **Starting point (2026-10-01):** Phases 0–6a are built. Production runs 0.2.3. Pilot fixes 06–12 are on main; their release is 0.2.5 (`v0.2.4` failed and published nothing). Investigation 1 has run twice (0.2.1: no output; 0.2.3: a card with 8 findings, precision 10/14). Investigations 2–5 have not run. All their seed companies are ingested with as-of financials.
- **This map carries execution.** Its tickets are mostly tasks (run and review an investigation), because the verdict waits on their results.
- **Skills:** investigation tickets use `pilot-review`; the release ticket uses `release-atlas`; grilling tickets use `grilling` + `domain-modeling`.
- **Who decides:** the owner delegated planning and decisions to the lead (2026-10-01). The lead resolves grilling tickets and records the reasoning in the answer. The owner's own acts stay the owner's: merging the home-ops PR, approving or rejecting an edge, adjudicating a gold case.
- **Focus rule:** after 0.2.5, investigations 1–5 all run on one version. A defect found in a review becomes a ticket in `.scratch/atlas-pilot-fixes/issues/` and waits for the verdict. The one exception is a **blocker**: an investigation that produces no card, or a defect that makes a cited span untrustworthy. Reason: twelve fixes came from one question; four more questions are needed to rank defects by how often they recur.
- **Quota:** an investigation spends about 100–150k MiniMax tokens of the 400k rolling 5 h budget, so run one at a time and read `/queue` first. Other live runs that spend quota (`atlas evaluate --live`, live suites) need the owner's go-ahead, as `AGENTS.md` says.
- **New work found on the way** goes under "Not yet specified", in the candidate list for the next effort, never into a log entry's "Next" line alone.

## Decisions so far

<!-- one line per closed ticket -->

- [The pilot's verdict criteria](issues/02-pilot-verdict-criteria.md): per investigation a trust gate and a six-part bar (Claim precision at least 80%, at least 3 saved-work findings, at least 50% baseline coverage, the roles ran, at most 200k tokens and 10 minutes); pass at 4 of 5 with pooled machine-reviewed precision at least 90%, partial at 2–3 (one fix round), fail at 0–1 (the workflow's design reopened).
- [The archive-search baseline](issues/03-archive-search-baseline.md): BM25 of the question's words over the seed companies' parsed filings of the last 18 months, untuned, plus recall alone beside it; run read-only by `scripts/pilot_baseline.py`; the reviewer judges at most 10 on-question hits and the card must cover half.

## Not yet specified

- **A third fix round before the verdict.** Whether one is needed depends on what investigations 2–5 show; the focus rule says no unless a blocker appears.
- **What Hindsight adds.** The baseline and the live evaluation both bear on whether recall and reflect improve a card over reading the archive directly; the question can't be phrased sharply until the baseline is defined.
- **Cost at scale.** Tokens per investigation against the MiniMax and Codex budgets when the universe and the number of questions grow; needs the five runs' numbers.
- **Candidates for the next effort**, swept from the implementation log's "Next" lines (2026-10-01). The verdict ticket ranks them; none is started before it.
  - Research quality: counterparty aliases (a short form of a legal name stays unresolved); a named subject outside the known companies; widening the `substitutes` cues; the Skeptic's independence by source origin; the follow-up's Skeptic targeting only the round's new Claims; ingesting an `ingestable` EDGAR filing on demand; retaining the re-parse (`reprocess`, designed in fix 11's decision entry).
  - Measurement: `object_name` and `filing_phrase` in the evaluation gold format and the live-verify rehearsal; a live re-audit of triage and the `ATLAS_TRIAGE_WINDOWS_PER_SECTION` decision; a live replay on the Compose Hindsight; a live replay of `investigator.v5` against v4.
  - Discovery: the SearXNG instance's engines (the owner's; `docs/runbooks.md`, "Discovery channels"); tuning `min_score` and the host lists from real leads.
  - Pages: the decisions-first landing page; lead scores and the scenario summary on the investigation page; a company's Hypotheses, proposed updates and a correction form on the dossiers; a proposed-updates metric.

## Parked (owner)

- The TradingView live check (build tickets 26 and 31: paused until it is deployed to the cluster).
- Home-ops releases (pilot-build ticket 21), centralising Hindsight's LLM traffic, LLM failover, a dedicated Atlas Hindsight (`.scratch/atlas-pilot/map.md`).

## Out of scope

- Phase 6b (scheduled monitoring, the evidence inbox, the market-data provider, paper tracking) and Phase 7 (hardening, the restore drill, the React Flow map), unless the verdict's spec chooses one.
- The derivation-graph and ontology work of the earlier ChatGPT review: the owner's direction is to measure the real system first (`docs/decisions.md`, "Measure the real system first").
