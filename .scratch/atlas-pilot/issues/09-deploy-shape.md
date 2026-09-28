# Phase 2 deploy shape and PR sequencing

Type: grilling
Status: open
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
