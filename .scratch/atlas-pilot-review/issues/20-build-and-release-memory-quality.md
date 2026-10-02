# Build and release the memory-quality effort

Type: task
Status: claimed
Blocked by: 19

## Question

Build the spec `.scratch/atlas-memory-quality/spec.md` (sixteen tickets to build, in `.scratch/atlas-memory-quality/issues/`), integrate and release it with the `release-atlas` skill, deploy it, run the backfill for the pilot's companies and show the conformance check passing strict.

- Wave 1 (no blockers): 01 Hindsight 0.10.2 recorded, 02 Memory health and the probe set.
- Out of band, at once: 16 The Editor's card fits a multi-hop investigation. A blocker (investigation 1 on 0.3.0 ended with no card), released by itself as 0.3.1 so investigation 1 can be run again.
- Added from the cluster's consolidation log (2026-10-02): 19 Atlas decides when Memory consolidates (no blockers).
- With this release, from investigation 1's review: pilot-fix tickets 21 (a finding says only what its Claims say), 22 (an analyst's words), 24 (a seed's filings are read) and 26 (the Investigator's answers fit the schema), in `.scratch/atlas-pilot-fixes/issues/`.
- Not built: 17 and 18 (news stories through TradingView). Written on the owner's suggestion and dropped with the owner the same day: a news story makes no Claim and no edge.
- Wave 2: 03 A section's outcome (no blocker since the cancellations were confirmed); 04 What a retained section says, 05 The bank template, 06 Observation scopes, 07 Recall as a reading index, 10 Reflect and the models (after 01); 14 The conformance check (after 01, 02).
- Wave 3: 08 Chunk-exact pointers (after 07), 09 The entity hop (after 04, 07), 15 The embedding model (after 01, 14).
- Wave 4: 11 The owner's server settings (after 02, 15; the lead's, the owner merges), 12 The backfill (after 03 to 06, 15).
- Wave 5: 13 Layer-aware pointer recall (after 05, 07, 12).

Each ticket goes to one Opus implementer in its own worktree (`docs/agents/implementer-brief.md`); the lead names the migration revisions, checks each implementer's artifacts against its ticket before merging, integrates, runs the runners and releases. Before the build: the health read and the probe set run on production as the before-measure. After the deploy and the backfill: both again, and `scripts/memory-conformance.sh --strict`.

The answer records the release, the deploy, the before and after numbers, the conformance report and how each implementer's work held up against its ticket.

## Comments

**2026-10-02, the lead: the before-measure of recall** (`.scratch/tools/probe_before.py`, production 0.3.0, 08:10 to 08:40 UTC, read-only, no LLM call; raw answers in `.scratch/live-runs/20261002-memory-probe-before/`, not in git). 91 theme-scoped recalls as Atlas sends them today: the five pilot questions, and 86 Scout queries of investigation 1 on 0.3.0 and of the breadth runs on 0.2.5. None failed.

| | Pilot questions (5) | Scout queries (86) |
|---|---|---|
| Memories per recall, median (range) | 46 (37 to 49) | 42 (34 to 54) |
| Of them observations, median | 15 | 13 |
| Distinct sections pointed at, median | 63 | 50.5 |
| Distinct companies pointed at, median | 3 | 3 |
| Citations resolved / unverified / broken | 224 / 1 / 0 | 3,561 / 42 / 0 |

- Of the 3,828 memories returned in all, 1,313 (34%) are facts returned beside an observation that was built from them: places a recall with `prefer_observations` would give to other sections (ticket 07).
- Every recall is capped near 45 memories by the default `max_tokens` (ticket 07).
- 11 companies are pointed at over the 91 recalls, two of them far more than the rest (3,953 and 3,886 source sections, then 1,793 and 983; three companies under 12). Memory holds little of most companies: about 1,900 sections' retains were cancelled early in the rollout (ticket 12 brings them in).
- The same recalls are run again after the release and the backfill, through ticket 02's probe script, whose report can also be computed from these raw answers.

**2026-10-02 (09:40 UTC), the lead: the before-measure in the probe set's own format** (`scripts/memory_probe.py`, ticket 02; `configs/memory/probes.yaml` version 1: the five pilot questions and four Scout-style queries each, 25 theme-scoped recalls; production 0.3.0; report in `.scratch/live-runs/20261002-memory-probe-before-official/`). This is the table the after-measure is compared with.

| Probe | Memories | Resolved | Sections | Companies | Observations | Superseded |
|---|---|---|---|---|---|---|
| laser-chips | 210 | 209 | 148 | 8 | 21% | 54 |
| inp-substrates | 215 | 215 | 136 | 5 | 21% | 47 |
| module-assembly | 242 | 241 | 179 | 8 | 13% | 17 |
| dsp-drivers | 233 | 223 | 208 | 9 | 16% | 16 |
| coherent-demand | 249 | 248 | 149 | 7 | 22% | 61 |
| total | 1,149 | 1,136 | 405 | 10 | 19% | 195 |

- "Superseded" is a fact returned beside an observation of the same answer that was built from it: 195 of 1,149 places (17%). The lead added the measure after the script's first run: its "repeats" only saw identical text and read 0. (The 34% above came from 91 other queries, most of them investigation 1's.)
- Pointer weight by company over the 25 recalls: Coherent 90.2, Lumentum 78.1, Applied Optoelectronics 27.3, AXT 22.9, MACOM 6.9, Marvell 3.9, Ciena 3.4, Fabrinet 3.2, IQE 0.3, STMicroelectronics 0.02; Soitec and Innolight none. The dsp-drivers and coherent-demand questions are seeded with Marvell, MACOM and Ciena.
- The memory-health read is not on production until this effort is deployed; its before-numbers are the metric's (695 completed, 22 zero-fact, 1,907 recorded failed of which the sampled ones are all the owner's cancellations, 59 pending, at 07:53 UTC).
