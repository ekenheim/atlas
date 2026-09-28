# Decisions and spec deviations

Deviations from `hindsight_investment_research_build_plan.md` v1.1, and decisions the spec left open. ADRs for hard-to-reverse architectural choices live in `docs/adr/`.

## 2026-09-28: charting session (`.scratch/atlas-pilot/map.md`)

- **Pilot auth (deviates from §11, §13.3, Appendix A).** The cluster has no Authentik forward-auth/OIDC pattern on internal routes. For the pilot, Atlas uses the cluster's standard private-CIDR Envoy `SecurityPolicy`, with the actor identity taken from config (as in local dev). Every mutation still records an actor and an audit event. Authentik is post-pilot.
- **All LLM traffic via LiteLLM, including Atlas Hindsight (tightens §6.1).** Unlike the shared `llm/hindsight` release, which calls `openai-codex` directly, the dedicated Atlas Hindsight's extraction and reflect models are LiteLLM routes. The extraction model is chosen by a bake-off among already-paid options (MiniMax, self-hosted, and the subscription routes if their terms allow it) rather than a new paid API.
- **The CI gate before the GitHub remote exists (§14 Phase 0).** One local entrypoint runs lint, types, migrations and fixture-only tests; the GitHub Actions workflow calls the same entrypoint. The remote `ekenheim/atlas-research` is added before Phase 2.
- **Embeddings (§6.1).** Reuse `qwen3-embedding-0.6b` via LiteLLM (1024 dims), the same as the shared Hindsight.
- **Release-driven deployment (refines §12, Appendix A).** The app lives in its own GitHub repo under `github.com/ekenheim`. Versioned releases publish images to GHCR, and the home-ops deployment pins a released version and is bumped per release, never tracking `main`. Home-ops holds only manifests.
- **Issue tracking.** Local markdown under `.scratch/`, permanently (see `docs/agents/issue-tracker.md`).
