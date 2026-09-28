# Phase 2 deploy shape and PR sequencing

Type: grilling
Status: resolved
Blocked by: 03, 05, 08, 10

## Question

Decide:

- the concrete home-ops layout for `kubernetes/apps/datasci/atlas/`
- resources for api, worker and the dedicated Hindsight
- the hostnames
- the secret layout (which Bitwarden item, and one ExternalSecret per target Secret)
- the order of home-ops PRs (Crunchy users → OpenTofu bucket → LiteLLM key + ClusterSecretStore → Hindsight → app), given that each PR auto-merges
- whether Atlas release bumps auto-merge (i.e. auto-deploy) or need a manual merge (ticket 08 §4)
- how the `vector` extension is created in `atlas-hindsight`: a one-off manual step vs an init container holding the superuser credential (ticket 08 §3)
- the scoping of the `llm` secret store: a Role in `llm`, restricted to `datasci` (ticket 08 §2)
- how `ghcr-pull` in `datasci` is confirmed, or whether images are public (ticket 08 §6)
- amending the LiteLLM configmap's PRIVACY comment to record Atlas's exception (Q22); note that a configmap edit restarts LiteLLM via reloader
- LiteLLM aliases `atlas-extract` / `atlas-reflect` → MiniMax-M3, and a parallel-request cap of 3 on the `atlas` key, if `LiteLLMVirtualKey` supports it (ticket 05)
- running the MinIO provisioning script (ticket 10): bucket `atlas-archive` with Governance lock for 10 y, the `atlas` user and policy, credentials into Bitwarden
- the nightly R2 copy CronJob, the R2 bucket `atlas-archive-offsite` and its token
- how validation (`flux-local`, `kubeconform`, `yamllint`) is run before each PR is opened

## Answer

Grilled 2026-09-28; all recommendations accepted, and Q29 chose public images.

21. **Layout:** `kubernetes/apps/datasci/atlas/`, containing:
    - `ks.yaml` with two Kustomizations: `atlas-hindsight`, and `atlas`, which depends on it plus crunchy and external-secrets
    - `hindsight/`: the dedicated HelmRelease, same chart and digest as `llm/hindsight`
    - `app/`: app-template 5.2.1 with the `api` and `worker` controllers, the R2 copy CronJob, the ExternalSecrets and the HTTPRoute
22. **Routes:**
    - `atlas.<domain>` on envoy-internal, behind a private-CIDR SecurityPolicy
    - the Hindsight API has no route (in-cluster only)
    - the control-plane UI is internal at `atlas-hindsight.<domain>`
23. **Resources:**
    - api: 100m / 256Mi, limit 1Gi
    - worker: 100m / 512Mi, limit 2Gi
    - Hindsight: 250m / 1Gi, limit 4Gi
    - no TEI sidecar (rerank via LiteLLM)
    - the Hindsight env matches the spike: `LLM_MAX_CONCURRENT=2`, `WORKER_MAX_SLOTS=4`, thinking off, the aliases `atlas-extract` / `atlas-reflect`
24. **Secrets:**
    - Bitwarden item `atlas`: `SEC_USER_AGENT`, `HINDSIGHT_API_KEY`, `S3_*`, `R2_*`
    - DB credentials via `crunchy-pgo-secrets`
    - the LiteLLM key via a new `llm` store scoped to `datasci`
    - one ExternalSecret per target Secret; optional fields via `{{ index . "X" }}`
25. **`vector`:** a one-off `CREATE EXTENSION vector` by the owner as superuser before the first boot, documented in a runbook.
26. **PR order:**
    1. Crunchy users `atlas` and `atlas-hindsight`, then the `vector` step
    2. LiteLLM: aliases, the `atlas` key (maxBudget 25 / 30d, plus a parallel cap if supported), the scoped `llm` secret store, the privacy-comment amendment
    3. Renovate: automerge off for the dedicated Hindsight and for Atlas images
    4. the `atlas-hindsight` release
    5. outside Git: the MinIO provisioning script, the R2 bucket and token, credentials into Bitwarden
    6. the `atlas` app release once the first image is on GHCR
27. **Release bumps:** Renovate opens a PR per Atlas release tag with automerge off; the owner's merge is the deploy.
28. **Home-ops changes:** prepared and validated (flux-local, kubeconform, yamllint) on local branches in `home-ops-upgrade`. The owner reviews, pushes and opens the PRs.
29. **Images:** public GHCR images for now, so no `ghcr-pull` is needed. They can go private later.
30. **CI:** it replays only the recorded Hindsight fixtures. A real Hindsight runs in the local spike and in a manually triggered live test, never in CI (no MiniMax from CI).
