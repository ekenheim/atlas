# Phase 2 deploy shape and PR sequencing

Type: grilling
Status: open
Blocked by: 03, 05, 08

## Question

Decide:

- the concrete home-ops layout for `kubernetes/apps/datasci/atlas/`
- resources for api, worker and the dedicated Hindsight
- the hostnames
- the secret layout (which Bitwarden item, and one ExternalSecret per target Secret)
- the order of home-ops PRs (Crunchy users → OpenTofu bucket → LiteLLM key + ClusterSecretStore → Hindsight → app), given that each PR auto-merges
- how validation (`flux-local`, `kubeconform`, `yamllint`) is run before each PR is opened
