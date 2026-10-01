# Release and deploy 0.2.5

Type: task
Status: claimed
Blocked by: none

## Question

Get pilot fixes 06–12 onto production, following the `release-atlas` skill. `v0.2.4` (main at `9371319`) published nothing: its release run failed on a Docker Hub 502, and the re-run of the failed job failed on two tests whose fixed clock the real time had passed (`docs/implementation-log.md`, 2026-10-01). The release is `v0.2.5`, on the commit that fixes them:
- `main`'s `ci` run is green, then the `release v0.2.5` run's `publish` job succeeds;
- the home-ops PR (image bump, the `normalize-financials` and `reparse` init containers, `ATLAS_SEARXNG_ENGINES`; the pushed branch `atlas-0.2.4` renamed for 0.2.5) is open with its provenance and green checks;
- the owner merges it;
- production reports `atlas_build_info{version="0.2.5"}`, every readiness check is `ok`, and the `reparse` job has run.

The answer records the release run, the PR, and what the two init containers did.
