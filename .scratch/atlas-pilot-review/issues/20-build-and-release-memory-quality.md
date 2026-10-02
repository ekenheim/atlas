# Build and release the memory-quality effort

Type: task
Status: claimed
Blocked by: 19

## Question

Build the spec `.scratch/atlas-memory-quality/spec.md` (sixteen tickets in `.scratch/atlas-memory-quality/issues/`), integrate and release it with the `release-atlas` skill, deploy it, run the backfill for the pilot's companies and show the conformance check passing strict.

- Wave 1 (no blockers): 01 Hindsight 0.10.2 recorded, 02 Memory health and the probe set.
- Out of band, at once: 16 The Editor's card fits a multi-hop investigation. A blocker (investigation 1 on 0.3.0 ended with no card), released by itself as 0.3.1 so investigation 1 can be run again.
- Wave 2: 03 A section's outcome (after 02); 04 What a retained section says, 05 The bank template, 06 Observation scopes, 07 Recall as a reading index, 10 Reflect and the models (after 01); 14 The conformance check (after 01, 02).
- Wave 3: 08 Chunk-exact pointers (after 07), 09 The entity hop (after 04, 07), 15 The embedding model (after 01, 14).
- Wave 4: 11 The owner's server settings (after 02, 15; the lead's, the owner merges), 12 The backfill (after 03 to 06, 15).
- Wave 5: 13 Layer-aware pointer recall (after 05, 07, 12).

Each ticket goes to one Opus implementer in its own worktree (`docs/agents/implementer-brief.md`); the lead names the migration revisions, checks each implementer's artifacts against its ticket before merging, integrates, runs the runners and releases. Before the build: the health read and the probe set run on production as the before-measure. After the deploy and the backfill: both again, and `scripts/memory-conformance.sh --strict`.

The answer records the release, the deploy, the before and after numbers, the conformance report and how each implementer's work held up against its ticket.
