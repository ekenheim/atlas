# 33: Atlas finds and covers its own companies

Type: task (a standing loop, with small build parts as they are needed)
Status: in progress (the lead), opened 2026-10-18 at the owner's request
Blocked by: none. It runs beside ticket 29; its exclusions keep the scorecard clean.

## Why

The owner asked (2026-10-18) for Atlas to "start covering other companies, new thesis: actually do the work we set the project up for".

- **All 20 proven Beliefs are photonics, 15 of them AXT.** Atlas has evidenced one thesis (InP substrates), and the market priced it a year ago.
- **The universe was chosen for Atlas.** It is a config list the owner and the lead picked, so Atlas has never had to find a name. The goal review (map, "The find step") names that as the largest gap between what Atlas proves and what the owner needs: a constraint found before it is priced.
- **The closed-book arm** (`scorecard/closed-book.md`) showed the model already knows the famous 2025 winners. An edge, if there is one, will come from names that are less covered.

## The loop (each step dated and committed before the next reads its result)

1. **Scan.** Run a market-wide search of filings for supply-constraint language, by a phrase list fixed before the run, over every filer (not the universe). Two channels:
   - EDGAR full-text search, now;
   - Atlas's own `discover` job (Scout queries, EDGAR FTS and `propose_candidates`), nightly per theme, so the dated record lives in Atlas.
2. **Shortlist, by rule.** Deduplicate the hits by filer. Exclude the universe and the scorecard cases. Rank by the number of distinct constraint phrases and by recency. An Opus analyst reads each top filer's hit passages and classes it:
   - **holder:** the company controls the scarce thing;
   - **squeezed:** it buys the scarce thing; reported, not a thesis by itself (the Raspberry Pi lesson);
   - **noise:** risk-factor boilerplate, or a constraint that is the company's own failure.

   Each class comes with the quote. Prices are never looked at before a company is admitted.
3. **Admit.** A holder or a cluster (several names pointing at the same scarce input) enters the universe, either as a company in a theme (`configs/themes/`, the next release) or as a committed Candidate (`POST /candidates/{id}/commit`, which also enqueues its SEC ingest). Each admission is recorded with its date and the scan that named it. This date is the find step's measure (Amendment 2 of ticket 29).
4. **Ingest:** EDGAR and the TradingView catalog (call transcripts), as for any company.
5. **Research.**
   - A Researcher session per question, through the scheduled agents or the lead's sessions.
   - Beliefs, judged by the owner's rule.
   - A Hypothesis when a theme has proven Beliefs at every step.
   - Calls into the prospective record, which settles them against what followed.

## Pre-registered measures

- **The scan's precision@20:** of the shortlist's top 20 filers, the share a blind reviewer classes holder or squeezed. Reported per scan; no target before the first one.
- **First named:** for every company admitted, the date Atlas first named it (scan or Candidate) and the date it was admitted. Compared later with when the market priced it (never before admission).
- **Calls:** every Belief proven in a new theme makes a call. Its +1, +3 and +6 month checkpoints are the out-of-sample record. A theme is judged on its calls, not on its Fact precision.

## Exclusions (until ticket 29's runs are done)

- The scorecard cases (SanDisk, IREN, eToro, Snap, POET; Raspberry Pi) are on no shortlist and in no new theme, and no non-isolated session is seeded with them. No session at all is seeded with SanDisk (Amendment 1).
- Nothing under ticket 29's frozen surface changes. Discovery code, the theme configs and the scan's own scripts are outside it.

## Today (2026-10-18)

1. Commit the scan's phrase list and rule (`docs/research/bottleneck-scan-2026-10-18.md`, "Method") before the scan runs.
2. Run the EDGAR scan, and give the top filers' passages to the analyst (subagents; SEC calls with Atlas's UA at ≤ 5 per second; no browser).
3. Point the scheduled agents at the first new thesis Atlas can evidence: DRAM and HBM supply in `memory-packaging`, seeded with Micron and SK hynix. Its documents arrive with tonight's ingest. The change goes through a home-ops PR for the Researcher's question and seeds.
4. Write the owner a brief, "what's going on": what is evidenced, apart from what are leads.

## Known weakness

Filings miss what is said on calls and at conferences, where both case studies' key sentences were. A company's calls arrive only after it is admitted (its TradingView catalog). So the scan finds names; the calls make the case.
