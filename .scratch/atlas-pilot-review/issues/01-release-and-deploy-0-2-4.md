# Release and deploy 0.2.4

Type: task
Status: claimed
Blocked by: none

## Question

Get pilot fixes 06–12 (main at `9371319`, tag `v0.2.4`) onto production, following the `release-atlas` skill:
- the `release v0.2.4` run's `publish` job succeeds (the first attempt failed on a Docker Hub 502 pulling `postgres:17`; the failed job was re-run on the same tag on 2026-10-01);
- the home-ops PR from the pushed branch `atlas-0.2.4` (image bump, the `normalize-financials` and `reparse` init containers, `ATLAS_SEARXNG_ENGINES`) is open with its provenance and green checks;
- the owner merges it;
- production reports `atlas_build_info{version="0.2.4"}`, every readiness check is `ok`, and the `reparse` job has run.

The answer records the release run, the PR, and what the two init containers did.
