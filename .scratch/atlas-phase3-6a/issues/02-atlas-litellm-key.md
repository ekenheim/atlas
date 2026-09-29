# Create Atlas's LiteLLM key and make it reachable from development

Type: task
Status: resolved
Blocked by: none

## Question

Via a fresh home-ops clone (the root-owned objects block the original checkout), prepare a PR with:
- the `atlas` LiteLLMVirtualKey (maxBudget and budgetDuration, models MiniMax-M3 and qwen3-embedding-0.6b, maxParallelRequests 3)
- a ClusterSecretStore scoped to the key's Secret, restricted to `development` (not datasci, as the earlier prepared branch had)
- the Atlas ExternalSecret and ATLAS_LITELLM_* env

Reuse the uncommitted `atlas/litellm` patch where it applies. Validate (yamllint, flux-local, kubeconform); the owner merges. Resolved when readiness reports litellm ok and runs record routed models. Also fix: stamp the package version from the release tag (build_info still says 0.1.0).

## Answer

- **Home-ops PR [#7086](https://github.com/ekenheim/home-ops-upgrade/pull/7086)** (`atlas/litellm-key`, not merged; the owner merges):
  - the `atlas` LiteLLMVirtualKey: MiniMax-M3, qwen3-embedding-0.6b and rerank; maxBudget "25" per 30d; maxParallelRequests 3 (the CRD supports it)
  - a ClusterSecretStore that admits only `development`
  - the Atlas `atlas-litellm` ExternalSecret, plus `ATLAS_LITELLM_URL` and both alias envs set to MiniMax-M3
  - Atlas's Flux Kustomization now depends on `litellm-stores` and `litellm-keys`
  - no LiteLLM configmap change, so no restart
  - validated: yamllint on 9 files; flux-local 184 passed; kubeconform -strict 20/20
- **Atlas:** the release passes the tag's version as build arg `ATLAS_VERSION` → `atlas_build_info`, and the release smoke test asserts it matches the tag. `__version__` comes from `importlib.metadata`. It takes effect from the next release.
- **After merge:** `/health/ready` should report litellm `ok`, and runs record routed models.
