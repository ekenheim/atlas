# Decisions and spec deviations

Deviations from `hindsight_investment_research_build_plan.md` v1.1, and decisions the spec left open. ADRs for hard-to-reverse architectural choices live in `docs/adr/`.

## 2026-09-28: charting session (`.scratch/atlas-pilot/map.md`)

- **Pilot auth (deviates from §11, §13.3, Appendix A).** The cluster has no Authentik forward-auth/OIDC pattern on internal routes. For the pilot, Atlas uses the cluster's standard private-CIDR Envoy `SecurityPolicy`, with the actor identity taken from config (as in local dev). Every mutation still records an actor and an audit event. Authentik is post-pilot.
- **All LLM traffic via LiteLLM, including Atlas Hindsight (tightens §6.1).** Unlike the shared `llm/hindsight` release, which calls `openai-codex` directly, the dedicated Atlas Hindsight's extraction and reflect models are LiteLLM routes. The extraction model is chosen by a bake-off among already-paid options (MiniMax, self-hosted, and the subscription routes if their terms allow it) rather than a new paid API.
- **The CI gate before the GitHub remote exists (§14 Phase 0).** One local entrypoint runs lint, types, migrations and fixture-only tests; the GitHub Actions workflow calls the same entrypoint. The remote `ekenheim/atlas-research` is added before Phase 2.
- **Embeddings (§6.1).** Reuse `qwen3-embedding-0.6b` via LiteLLM (1024 dims), the same as the shared Hindsight.
- **Release-driven deployment (refines §12, Appendix A).** The app lives in its own GitHub repo under `github.com/ekenheim`. Versioned releases publish images to GHCR, and the home-ops deployment pins a released version and is bumped per release, never tracking `main`. Home-ops holds only manifests.
- **Issue tracking.** Local markdown under `.scratch/`, permanently (see `docs/agents/issue-tracker.md`).

## 2026-09-28: Hindsight 0.10.1 feature matrix (`docs/hindsight-feature-matrix.md`)

- **Provenance resolution (refines §6.4):** reflect citations carry no `document_id`. Atlas resolves observations through `source_memory_ids` to world facts, then maps each world fact to its Source Version via `document_id` (`srcv:<sha256>`) and the preserved `metadata.source_version_id`. Content that reflect draws from raw chunks, with no memory ID, is unverified until matched to an archived span.
- **Bank configuration uses versioned templates (§6.2):** 0.10.1 supports template export, dry-run and import, so the config-API fallback isn't needed.
- **Response schemas avoid union types:** 0.10.1 returns 500 on `"type": [..., "null"]`.
- **Worker slots ≥ 3:** consolidation reserves 2; pacing uses `HINDSIGHT_API_LLM_MAX_CONCURRENT`.

## 2026-09-28: models, pacing and Hindsight integration (tickets 05 and 07)

- **LLM:** MiniMax-M3 with thinking disabled for both extraction and reflect, behind the LiteLLM aliases `atlas-extract` / `atlas-reflect`. There is no fallback model; on 429 or an outage the ingest queue pauses with backoff. Routed models are recorded per run from LiteLLM `/model/info`.
- **Pacing:** Hindsight runs 2 concurrent LLM calls with 4 worker slots, and the backfill runs in a nightly window.
- **Document IDs** are per Source Version UUID and section (ADR-0001), which deviates from the spec's `srcv:<sha256>` example.
- **Only strict tag matching** is allowed through the gateway.
- **Citation states:** resolved / unverified / broken. Only resolved citations count as Evidence.
- **Phase 2 mental models:** Theme status and Bottlenecks, refreshed on a daily cron (not after consolidation). No knowledge pages in Phase 2.

## 2026-09-28: archive durability (ticket 10)

- **Bucket provisioning by script, not OpenTofu (deviates from Appendix A):** OpenTofu isn't running, its state location is unknown, and most existing buckets are hand-made. A re-runnable minio-py script creates `atlas-archive` (object lock, Governance, 10-year default retention), a scoped `atlas` user without bypass rights, and prints the credentials for Bitwarden.
- **Off-cluster copy:** a nightly copy-only CronJob to R2 `atlas-archive-offsite`. Immutability is guaranteed on MinIO only.
- **Dev/CI S3:** MinIO images and binaries are no longer publicly distributed, so Compose/CI use another S3-compatible server (ticket 13). Dev defaults to the filesystem backend.
- **Cluster MinIO image:** it can't be re-pulled from quay. Spegel's peer-to-peer image cache mitigates this; the owner accepts the residual risk.
