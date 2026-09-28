# Home-ops wiring facts for the Atlas deploy

Type: research
Status: resolved
Blocked by: none

## Question

In `/mnt/c/Users/ekenh/home-ops-upgrade`, establish the facts the Phase 2 deploy decisions wait on:

1. Does `terraform/minio/modules/minio` support bucket versioning and object lock, and how are the existing buckets replicated off-cluster to R2?
2. What would a `ClusterSecretStore` for the `llm` namespace need (the kubernetes provider, RBAC, the ServiceAccount), modeled on `database/crunchy-postgres/clustersecretstore/`? Does `LiteLLMVirtualKey` support `max_budget` / budget duration fields?
3. How is `CREATE EXTENSION vector` handled for the existing `hindsight` database, and how would `atlas-hindsight` get the same treatment?
4. How is Renovate automerge configured per image (to disable it for the dedicated Hindsight image)?
5. How are the Gatus template line and the ServiceMonitor/PrometheusRule wired for an app in `datasci`?
6. Is the `ghcr-pull` secret present in `datasci`, and how are private GHCR images pulled?

Cite file paths for every claim.

## Context

Research in progress on branch `research/home-ops-wiring`; findings in `docs/research/home-ops-wiring.md` on that branch.

## Answer

All from the repo and the pinned tool sources; none of it reflects live cluster state.

1. **MinIO:** the module sets no versioning or object lock. Provider v3.43.0 supports both, so the module needs extending. **No bucket is replicated to R2 today:** pgBackRest and VolSync each write their own second copy straight to R2, and R2 can't take versioning, object lock or MinIO replication. OpenTofu is applied by hand (tofu-controller is commented out), and where its state lives isn't in the repo. This raises a new decision → ticket 10.
2. **Secret store for `llm`:** the Crunchy model means a ServiceAccount, RBAC and a `ClusterSecretStore` with `remoteNamespace`. Copied as-is, its RBAC can read Secrets in every namespace and any namespace could use the store. Scope it instead: a Role in `llm`, with store conditions limited to `datasci`. `LiteLLMVirtualKey` supports `maxBudget` (a string) and `budgetDuration`.
3. **`vector` extension:** it was a manual `kubectl exec` for `hindsight`. Immich's init-container pattern automates it, but it puts the superuser password in the app namespace.
4. **Renovate:** the dedicated Hindsight shares package names with `llm/hindsight`, so automerge must be disabled by file path, as the last rule. Atlas image bumps would currently **auto-merge, i.e. auto-deploy**.
5. **Gatus:** the `guarded` template only checks public DNS via 1.1.1.1, not app health. Add an in-cluster health endpoint check. Prometheus picks up ServiceMonitors and PrometheusRules in any namespace without labels.
6. **`ghcr-pull`:** nothing in Git creates it, so its presence in `datasci` can't be determined from the repo.

Full findings: `docs/research/home-ops-wiring.md` on branch `research/home-ops-wiring` (`6eb8c2b`).
