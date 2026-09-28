# Home-ops wiring facts for the Atlas deploy

Type: research
Status: open
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
