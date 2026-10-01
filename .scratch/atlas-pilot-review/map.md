# Map: the pilot review

Label: wayfinder:map

## Destination

The pilot's verdict, in two artifacts:
- **The pilot report** (`docs/pilot-report.md`; START_HERE step 8): the five pilot investigations reviewed against their cited spans, each compared with the archive-search baseline, the §15 demo shown on production, the evaluation results, and the exact test status.
- **A ready-for-agent spec for the next effort** (via `/to-spec`, then `/to-tickets`), chosen from what the report shows.

## Notes

- **Domain:** glossary `CONTEXT.md`; the product spec is authoritative; deviations go in `docs/decisions.md`. The questions and seeds are in `.scratch/pilot/pilot-plan.md`, the reviews in `.scratch/pilot/results.md`, the defects in `.scratch/atlas-pilot-fixes/issues/`.
- **Starting point (2026-10-01):** Phases 0–6a are built. Production runs 0.2.5 (pilot fixes 06–12). Investigation 1 has run three times (0.2.1: no output; 0.2.3: a card with 8 findings, precision 10/14; 0.2.5: 5 findings, precision 6/10, below the bar). Investigations 2–5 have not run. All their seed companies are ingested with as-of financials.
- **This map carries execution.** Its tickets are mostly tasks (run and review an investigation), because the verdict waits on their results.
- **Skills:** investigation tickets use `pilot-review`; the release ticket uses `release-atlas`; grilling tickets use `grilling` + `domain-modeling`.
- **Who decides:** the owner delegated planning and decisions to the lead (2026-10-01). The lead resolves grilling tickets and records the reasoning in the answer. The owner's own acts stay the owner's: merging the home-ops PR, approving or rejecting an edge, adjudicating a gold case.
- **Focus rule, as amended on 2026-10-01 (evening):** the owner asked whether Hindsight is used to the maximum, freed the MiniMax budget and told the lead to adjust during the dev cycle. Investigation 1's three runs showed structural, question-independent defects, and a recall probe showed Memory holds the missed answers when asked focused questions across the theme. So one build cycle comes before investigations 2–5: the spec `.scratch/atlas-memory-directed-reading/spec.md` (ticket 14). After its release the rule holds as first written: the five investigations run on that one version, and a defect waits for the verdict unless it is a blocker (no card, or an untrustworthy span).
- **Quota:** the MiniMax subscription is dedicated to Atlas (owner, 2026-10-01); production's budgets are 4,000,000 tokens per 5 h and 1,000,000 per investigation once home-ops PR #7174 is merged. Read `/queue` before a run; a `quota` pause means the budget is above what the subscription allows. The Codex budget of the shared Hindsight (40 operations per 5 h) is unchanged and is not the lead's to raise. Live suites that are not pilot runs still need the owner's go-ahead.
- **New work found on the way** goes under "Not yet specified", in the candidate list for the next effort, never into a log entry's "Next" line alone.

## Decisions so far

<!-- one line per closed ticket -->

- [The pilot's verdict criteria](issues/02-pilot-verdict-criteria.md): per investigation a trust gate and a six-part bar (Claim precision at least 80%, at least 3 saved-work findings, at least 50% baseline coverage, the roles ran, at most 200k tokens and 10 minutes); pass at 4 of 5 with pooled machine-reviewed precision at least 90%, partial at 2–3 (one fix round), fail at 0–1 (the workflow's design reopened).
- [The archive-search baseline](issues/03-archive-search-baseline.md): BM25 of the question's words over the seed companies' parsed filings of the last 18 months, untuned, plus recall alone beside it; run read-only by `scripts/pilot_baseline.py`; the reviewer judges at most 10 on-question hits and the card must cover half.
- [Release and deploy 0.2.5](issues/01-release-and-deploy-0-2-5.md): `v0.2.5` released and deployed on 2026-10-01 (home-ops PR #7152); the re-parse ran; the deploy also changed the SearXNG engines, and web leads are on topic since.
- [Investigation 1 on 0.2.5](issues/04-investigation-1-on-0-2-5.md): does not meet the bar on the stricter readings (precision 6 of 10, baseline coverage 2 of 10; 8 and 5 of 10 on the lenient ones, which would meet it; trust, saved work, roles, cost and latency met). The Skeptic and the Analyst now work and 8-Ks are read, but the allocation statement was lost to the equal passage share; eight new defects, none a blocker.
- Owner's direction, 2026-10-01 (evening): Hindsight was used in two narrow places (the Bottlenecks model's text for the Scout; one company-scoped recall per Investigator, its ranking discarded). The spec for memory-directed, multi-hop reading is `.scratch/atlas-memory-directed-reading/spec.md`; pilot-fix tickets 13–20 are superseded by its tickets.
- [Breadth runs of investigations 2 to 5 on 0.2.5](issues/16-breadth-runs-on-0-2-5.md): all four produced a card (10 to 31 accepted Claims, unreviewed); investigation 1's defects recur on every question; new: Investigators that propose almost nothing for systems and DSP companies, the allocation statement rejected for its object (spec ticket 09), filing leads crowding the kept leads.

## Not yet specified

- **A third fix round before the verdict.** Whether one is needed depends on what investigations 2–5 show; the focus rule says no unless a blocker appears.
- **What Hindsight adds.** The baseline and the live evaluation both bear on whether recall and reflect improve a card over reading the archive directly; the question can't be phrased sharply until the baseline is defined.
- **Cost at scale.** Tokens per investigation against the MiniMax and Codex budgets when the universe and the number of questions grow; needs the five runs' numbers.
- **More of Hindsight, after the pointers can be measured.** Reflect for a prior-knowledge brief (it spends the shared Hindsight's Codex budget); a pointer's fact text as a hint to the Investigator; per-theme mental models and the Theme status model in a role; a theme-wide term index over the archive; how much of each company's archive is retained, which bounds what recall can point to.
- **Why 1,907 retained-section outcomes are recorded as failed** (production metrics, 2026-10-01, against 473 completed): not diagnosed. It bounds what recall can point to, and matters more once retains run on MiniMax.
- **From the 0.3.0 build.** Whether the Skeptic should read transcripts (Tier B) its pointers lead to; a cap on kept leads per filer; the extraction smoke test's rehearsal check, which may be stale; a setting that sends no bearer header to the TradingView proxy.
- **From the breadth runs.** A cap on kept leads per filer (eight POET 6-Ks in one run); resolving private acquisition targets as counterparties (Celestial AI, XConn); whether the predicates fit a systems or DSP company once the passages are chosen by relevance (Ciena, Marvell); "provide" as a `supplies` cue.
- **TradingView beyond transcripts.** Quotes, fundamentals, analyst consensus and the earnings calendar as `estimated` scenario inputs and for scheduling (the spec's price-provider gate, §9.3); a setting that sends no bearer header, replacing the placeholder token; whether a management statement in a transcript (Tier B) may make a `machine_reviewed` edge.
- **Candidates for the next effort**, swept from the implementation log's "Next" lines (2026-10-01). The verdict ticket ranks them; none is started before it.
  - Research quality: counterparty aliases (a short form of a legal name stays unresolved); a named subject outside the known companies; widening the `substitutes` cues; the Skeptic's independence by source origin; the follow-up's Skeptic targeting only the round's new Claims; ingesting an `ingestable` EDGAR filing on demand; retaining the re-parse (`reprocess`, designed in fix 11's decision entry).
  - Measurement: `object_name` and `filing_phrase` in the evaluation gold format and the live-verify rehearsal; a live re-audit of triage and the `ATLAS_TRIAGE_WINDOWS_PER_SECTION` decision; a live replay on the Compose Hindsight; a live replay of `investigator.v5` against v4.
  - Financials: the Analyst's `total_debt` for Coherent cited an observation that is only the current portion (`LongTermDebtCurrent`), so the input was refused; the canonical debt metric needs both parts.
  - Discovery: the SearXNG instance's engines (the owner's; `docs/runbooks.md`, "Discovery channels"); tuning `min_score` and the host lists from real leads.
  - Pages: the decisions-first landing page; lead scores and the scenario summary on the investigation page; a company's Hypotheses, proposed updates and a correction form on the dossiers; a proposed-updates metric.

## Parked (owner)

- (Unparked on 2026-10-01: TradingView is in the cluster behind the owner's MCP proxy; ticket 17.)
- Home-ops releases (pilot-build ticket 21), centralising Hindsight's LLM traffic, LLM failover, a dedicated Atlas Hindsight (`.scratch/atlas-pilot/map.md`).
- (2026-10-01: the owner asked about alternating Hindsight between ChatGPT and MiniMax. Ticket 18 prototypes Hindsight's metadata routing, which sends only Atlas's retains to MiniMax on the shared server and may make the dedicated Hindsight unnecessary for intake.)

## Out of scope

- Phase 6b (scheduled monitoring, the evidence inbox, the market-data provider, paper tracking) and Phase 7 (hardening, the restore drill, the React Flow map), unless the verdict's spec chooses one.
- The derivation-graph and ontology work of the earlier ChatGPT review: the owner's direction is to measure the real system first (`docs/decisions.md`, "Measure the real system first").
