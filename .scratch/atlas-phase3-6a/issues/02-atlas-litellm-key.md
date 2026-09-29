# Create Atlas's LiteLLM key and make it reachable from development

Type: task
Status: claimed
Blocked by: none

## Question

Via a fresh home-ops clone (the root-owned objects block the original checkout), prepare a PR with:
- the `atlas` LiteLLMVirtualKey (maxBudget and budgetDuration, models MiniMax-M3 and qwen3-embedding-0.6b, maxParallelRequests 3)
- a ClusterSecretStore scoped to the key's Secret, restricted to `development` (not datasci, as the earlier prepared branch had)
- the Atlas ExternalSecret and ATLAS_LITELLM_* env

Reuse the uncommitted `atlas/litellm` patch where it applies. Validate (yamllint, flux-local, kubeconform); the owner merges. Resolved when readiness reports litellm ok and runs record routed models. Also fix: stamp the package version from the release tag (build_info still says 0.1.0).
