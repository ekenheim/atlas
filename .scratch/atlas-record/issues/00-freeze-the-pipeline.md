# Freeze the research pipeline

Type: task
Status: open
Blocked by: none

## Why

The scheduled tasks now do the research (spec, "Why"). The pipeline's CronJobs and daily jobs still spend the MiniMax, Codex (Hindsight) and Claude subscription budgets on work nobody will read. Freezing them is configuration only and can be undone. Deleting the code is ticket 07.

## What

A home-ops PR on `kubernetes/apps/development/atlas/app/`. The owner merges it.

1. Set `suspend: true` on these CronJobs:
   - `atlas-agent-scout`
   - `atlas-agent-researcher`
   - `atlas-agent-skeptic`
   - `atlas-agent-scorecard`
   - `atlas-agent-watch-robotics`
   - `atlas-agent-watch-power-equipment`
   - `atlas-agent-watch-aerospace-defence`
   - `atlas-ingest-nightly`
2. Set these in the Atlas Deployment's env:
   - `ATLAS_CONSOLIDATION_ENABLED=false`
   - `ATLAS_MENTAL_MODEL_REFRESH_AT=""`
   - `ATLAS_RECONCILE_AT=""`
   - `ATLAS_SIGNAL_SCAN_AT=""`
   - `ATLAS_BULK_RETENTION=off`
3. Leave `ATLAS_SETTLE_CALLS_AT` as it is, so the calls already made keep settling.
4. Put no `${}` in the manifests. Flux substitution breaks on it (memory `home-ops-no-dollar-brace`).

## Done when

- [ ] The PR is open, says what is frozen and why, and the owner has merged it.
- [ ] A day after the deploy, `GET /api/v1/queue` shows no new pipeline jobs, and the CronJobs show `SUSPEND True`.
