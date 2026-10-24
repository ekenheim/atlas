# Atlas archived

On 2026-10-24 the owner archived Atlas: "I think we archive this project as we're now running this entirely from Claude app instead." The research, and keeping its record, now happen in the owner's claude.ai scheduled tasks. Atlas is stopped, and nothing is deleted.

This supersedes ADR 0004's plan to keep the record in Atlas, and its deletion plan (`.scratch/atlas-record/issues/07-retire-the-pipeline.md`). The code is kept rather than deleted, because an archived repository costs nothing and a deletion cannot be undone.

## Decision

- **The repository** `github.com/ekenheim/atlas` is archived on GitHub, which makes it read-only. The last release is `v0.6.22` (commit `616cbad`), live from 2026-10-20 until the stop.
- **The cluster** (home-ops):
  - The Deployment is at `replicas: 0`. The api and worker share its one pod, so the worker's daily schedules stop too: reconciliation, signal scan, call settlement and consolidation.
  - The PrometheusRule and the gatus check are removed, so a stopped Atlas pages no one.
  - The CI runner scale set `gha-runner-scale-set-atlas` is commented out.
  - The Flux Kustomization stays (`prune: true`), and so do the PVC, the ExternalSecret, the Service, the HTTPRoute and the suspended CronJobs. Removing the Kustomization, or the PVC from it, would make Flux delete the source archive.
- **No data is deleted.** See below for where it is.

## Where everything is

| What | Where | Note |
|---|---|---|
| Database | `atlas` (user `atlas`) in the Crunchy cluster `database/crunchy-postgres` | Keep the user and database in the cluster spec, as for bandit. pgBackRest keeps full backups 14 days (repo1), so a dropped database is gone within a month. |
| Source archive | PVC `development/atlas-archive`, 10Gi `ceph-block`, filesystem backend (`ATLAS_ARCHIVE_ROOT=/data/archive`) | The only copy of the raw bytes and parses: no other backup exists. |
| Images | `ghcr.io/ekenheim/atlas:0.6.22`, `ghcr.io/ekenheim/atlas-agent:0.6.22` | |
| Memory | The shared Hindsight (`llm/hindsight`): banks `atlas-ai-infrastructure` (research), `atlas-beliefs` (conclusions) and `atlas-dev` (development memory) | Idle: the templates turn automatic consolidation off. |
| The 2026-10-19 editions | `tests/fixtures/artifacts/2026-10-19/` (eight pages, manifest with sha256), and the stopped database (`ledger_edition`, 31 `ledger_prediction` rows) | The only week Atlas recorded. |
| Unmerged work | Branch `ui/round-one` (UI rounds 1 and 2 follow-ups, `8a6f5a2`) | Never released. |
| The lead's local scratch | Branch `archive/local-scratch` | Untracked `.scratch/` files from the owner's PC, kept as they were. |

These stay in the cluster and are inert while Atlas is stopped: the LiteLLM key `litellm-key-atlas` and its ClusterSecretStore RBAC, and Hindsight's Atlas-only MiniMax extractor block. They are left in place because they cost nothing and are tedious to recreate.

## What is lost by stopping

Each scheduled task republishes its artifact in place every week. With Atlas stopped, nothing keeps last week's edition, compares the two or settles a prediction, unless the tasks are told to keep their own history (append, never replace).

## Reviving it

1. Unarchive the repository (GitHub, Settings → Unarchive).
2. In home-ops:
   - set the Deployment back to `replicas: 1`;
   - restore `./prometheusrule.yaml` and the gatus template in the app's `kustomization.yaml`;
   - uncomment `gha-runner-scale-set-atlas`.
3. The pipeline is still frozen by configuration (ADR 0004, ticket 00): its CronJobs are suspended, `ATLAS_BULK_RETENTION=off` and `ATLAS_MENTAL_MODEL_REFRESH_AT=""`. Unfreeze only what the new effort needs.
4. Start at `.scratch/atlas-record/map.md`, which says where the record effort stopped.
