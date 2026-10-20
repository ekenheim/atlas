# Freeze the research pipeline

Type: task
Status: ready-for-human
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
2. Set `ATLAS_MENTAL_MODEL_REFRESH_AT=""` in the Atlas Deployment's env, so the mental models' daily refresh no longer spends the Codex budget.
3. Leave these as they are:
   - `ATLAS_CONSOLIDATION_ENABLED` stays `true`. `ATLAS_BULK_RETENTION=off` already holds the daily consolidation try, and turning consolidation off would also stop the follow-ups that cancel a running chain of rounds.
   - Reconciliation and the signal scan keep running. Neither calls an LLM, and a stopped reconciliation would fire `AtlasMemoryReconciliationStale`.
   - `ATLAS_SETTLE_CALLS_AT` keeps its value, so the calls already made keep settling.
4. Put no `${}` in the manifests. Flux substitution breaks on it (memory `home-ops-no-dollar-brace`).

## Done when

- [ ] The PR is open, says what is frozen and why, and the owner has merged it.
- [ ] A day after the deploy, `GET /api/v1/queue` shows no new pipeline jobs, and the CronJobs show `SUSPEND True`.

## Comments

- 2026-10-20, the lead: home-ops PR https://github.com/ekenheim/home-ops-upgrade/pull/7842 is open for the owner to merge.
