# 20: Home-ops prerequisites (PRs 1–3)

**What to build:** Prepared and validated local branches in the home-ops checkout for the owner to open in order: Crunchy users `atlas` and `atlas-hindsight` (plus the `vector` runbook); LiteLLM aliases `atlas-extract`/`atlas-reflect`, the `atlas` virtual key, the `llm` ClusterSecretStore restricted to `datasci`, and the amended PRIVACY comment; Renovate rules with automerge off for Atlas and the dedicated Hindsight. Spec Part B: Deployment; map ticket 09.

**Blocked by:** None (can start immediately)

**Status:** done (the `atlas/litellm` commit is waiting on an owner fix to home-ops' object store; see `docs/implementation-log.md`)

- [x] Each branch passes flux-local, kubeconform and yamllint locally; literal `${…}` is escaped as `$${…}`
- [x] No secrets are in Git; optional ExternalSecret fields use `{{ index . "X" }}`
- [x] The branches are not pushed; the owner opens the PRs
