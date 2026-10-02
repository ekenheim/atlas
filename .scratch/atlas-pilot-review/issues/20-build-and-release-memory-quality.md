# Build and release the memory-quality effort

Type: task
Status: claimed
Blocked by: 19

## Question

Build the spec `.scratch/atlas-memory-quality/spec.md` (eighteen tickets in `.scratch/atlas-memory-quality/issues/`), integrate and release it with the `release-atlas` skill, deploy it, run the backfill for the pilot's companies and show the conformance check passing strict.

- Wave 1 (no blockers): 01 Hindsight 0.10.2 recorded, 02 Memory health and the probe set.
- Out of band, at once: 16 The Editor's card fits a multi-hop investigation. A blocker (investigation 1 on 0.3.0 ended with no card), released by itself as 0.3.1 so investigation 1 can be run again.
- Added on the owner's word (2026-10-02, news through TradingView): 17 News stories in the ledger (no blockers), 18 News in Memory as leads (after 04, 06, 07, 17).
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
