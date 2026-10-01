# Build and release memory-directed reading

Type: task
Status: claimed
Blocked by: none

## Question

Build the spec `.scratch/atlas-memory-directed-reading/spec.md` (eleven tickets in `.scratch/atlas-memory-directed-reading/issues/`), integrate and release it with the `release-atlas` skill, and deploy it.

- Wave 1 (no blockers): 01 Reading pointers, 02 Claim checks, 03 Contradiction or bear context, 04 Specific filing phrases.
- Wave 2: 05 Passage selection (after 01), 08 Layer supported or absent (after 02).
- Wave 3: 06 Multi-hop Investigators (after 01, 05), 07 The Skeptic reads by pointers (after 01, 03, 05).
- Added after the breadth runs: 09 A company-level constraint (after 08), 10 The baseline drops near-duplicates (after 05).
- Added with pilot-review ticket 18: 11 Atlas marks its retains for the MiniMax extractor (no blockers).

Each ticket goes to one implementer agent in its own worktree (`docs/agents/implementer-brief.md`); the lead names the migration revisions, integrates, runs the runners and releases. The answer records the release, the deploy and what each ticket's tests showed.

## Comments

**2026-10-02, the lead: built, integrated and tagged.** All eleven tickets are merged on main at `419d8a1` (runners: 1,402 tests, the frontend gates, the e2e) and tagged `v0.3.0`; details in `docs/implementation-log.md`, "memory-directed reading integrated; release 0.3.0". Open for this ticket: the release run's image, the home-ops PR (image, `ATLAS_RUN_TOKEN_BUDGET` 2,000,000, `ATLAS_RETAIN_EXTRACTOR=minimax`), the owner's merge, and production reporting 0.3.0.
