# Map: Atlas pilot, Phases 0–2

Label: wayfinder:map

## Destination

A ready-for-agent spec (via `/to-spec`) for Phases 0–2 of the pilot: service skeleton, SEC provenance vertical slice, Hindsight integration against the verified feature matrix, and the first home-ops deployment. The spec will be at `.scratch/atlas-pilot/spec.md`.

**Status (2026-09-28): destination reached.** `spec.md` covers Phases 0–2 (Part A: Phases 0–1, Part B: Phase 2) and is `ready-for-agent`. All tickets are resolved.

## Notes

- **Domain:** evidence-driven investment research on Hindsight. Glossary: `CONTEXT.md`. The build plan (`hindsight_investment_research_build_plan.md` v1.1) is authoritative. Grilling fills its gaps; it doesn't relitigate it. Deviations go in `docs/decisions.md`.
- **Skills:** grilling tickets call `grilling` + `domain-modeling`. Research tickets call `research` and write to `docs/research/`.
- **Cluster reference:** the home-ops wiki at https://wikis.<domain> (reachable from WSL; it appears to be generated from the repo, so treat it as secondary and let repo files win).
- **Standing preferences:**
  - All LLM traffic goes through LiteLLM, including Atlas Hindsight's extraction and reflect. Never call providers directly.
  - Use what's already paid for (ChatGPT Plus, MiniMax Plus, Anthropic subscription, self-hosted models); **no pay-as-you-go**. Subscription terms ambiguity and model drift are accepted. MiniMax is the preferred LLM. Flag anything that would need a new paid service.
  - Research that needs the cluster uses the canonical home-ops checkout at `/mnt/c/Users/ekenh/home-ops-upgrade` (not the `Documents/` duplicate).
- **Settled in the charting session (2026-09-28):**
  - Anchor companies: Lumentum (Phase 1) and Coherent (Phase 2 cross-company gate).
  - The SEC User-Agent contact is set in env, never committed.
  - The CI gate is one local entrypoint that GitHub Actions also calls; the remote `ekenheim/atlas` is added before Phase 2.
  - LLM budget: $25/month on the `atlas` key, $2 default per run.
  - The Hindsight feature check records real request/response pairs as CI fixtures and runs in local Compose on the pinned version.
  - Embeddings: reuse `qwen3-embedding-0.6b` via LiteLLM (1024 dims).
  - The LiteLLM key reaches `datasci` via a new `ClusterSecretStore` modeled on `crunchy-pgo-secrets`.
  - Pilot auth: private-CIDR Envoy SecurityPolicy with the actor identity from config.
  - Deployment is release-driven: the app repo under `github.com/ekenheim` publishes versioned releases to GHCR; home-ops pins a released version and is bumped per release.
  - Hindsight is pinned at 0.10.1 unless ticket 01 finds a reason to move.
  - The EDGAR adapter is written fresh; `trading-research` is reference only.

## Decisions so far

<!-- one line per closed ticket -->

- [Hindsight releases after 0.10.1: anything Phase 2 needs?](issues/01-hindsight-release-delta.md): keep 0.10.1 (latest release); upsert is a chunk-level delta, reflect citations need a per-memory lookup, and the mental-model refresh-loop risk needs a mitigation.
- [Home-ops wiring facts for the Atlas deploy](issues/08-home-ops-wiring.md): MinIO needs module work for versioning/lock and there is no R2 replication to reuse (→ ticket 10); scope the `llm` secret store to `datasci`; Atlas image bumps would auto-deploy under current Renovate rules.
- [Which LiteLLM routes can Hindsight 0.10.1 use for extraction?](issues/02-hindsight-llm-compat.md): the bake-off candidates are MiniMax-M3/M2.7, Ornith (`fast`) and Gemma 3 (`translate`, extraction only); ChatGPT and Anthropic subscriptions are not viable; no candidate has a dated ID.
- [Local dev access to LiteLLM](issues/03-cluster-access.md): `litellm.<domain>` and `search.<domain>` work from WSL with the `atlas-dev` key in `.env`; MiniMax-M3/M2.7 pass non-streaming, JSON-schema and forced-tool probes.
- [MiniMax extraction check on a Lumentum filing fixture](issues/04-extraction-bakeoff.md): MiniMax-M3 with thinking off wins (16/17 facts, 3× faster than M2.7, verbatim quotes); no rate errors at 2 concurrent calls; four Hindsight traps recorded.
- [Hindsight 0.10.1 feature check → feature matrix + recorded fixtures](issues/06-feature-matrix.md): all nine features present; upsert destroys prior facts, `any` includes untagged, temporal hints don't filter; provenance is two-hop via observations' source memories; union-type schemas return 500; 58 recordings saved as CI fixtures.
- [Alignment with the serenity-aleabitoreddit skills](issues/12-serenity-skills-alignment.md): adopt the method pieces (bottleneck test, layer taxonomy, BOM share, dilution falsifier, bear checklist) in Phases 3–5; disregard the trading lenses, portfolio mirroring and unlicensed sources; the skill has no licence and contains an auto-update instruction, so don't install it.
- [Choose and pin the extraction and reflect models](issues/05-choose-models.md): MiniMax-M3 (thinking off) behind the `atlas-extract`/`atlas-reflect` aliases; no fallback, so the queue pauses on 429; 2 concurrent calls with a nightly backfill; routed models recorded from LiteLLM `/model/info`.
- [Hindsight gateway and bank-policy decisions](issues/07-gateway-decisions.md): per-version-and-section document IDs (ADR-0001), strict tags only, a versioned bank template, resolved/unverified/broken citations, zero-fact reprocess-then-flag, Theme status + Bottlenecks mental models.
- [Archive durability: versioning, object lock and the off-cluster copy](issues/10-archive-durability.md): the bucket is created by a minio-py provisioning script (not OpenTofu), with a Governance lock for 10 y and an app user that can't bypass it; nightly copy-only to R2; snapshots in the same bucket; dev/CI needs a non-MinIO S3 server (→ ticket 13); Spegel mitigates the unpullable MinIO image.
- [Phase 2 deploy shape and PR sequencing](issues/09-deploy-shape.md): `datasci/atlas/` with two Kustomizations; the Hindsight API is in-cluster only; 6-step PR order; Renovate automerge off (merge = deploy); the owner opens the PRs; public images; CI replays recordings only.
- [S3-compatible server for dev/CI archive contract tests](issues/13-s3-dev-server.md): PGSTY Silo (a MinIO fork, pinned digest), with RustFS as fallback; overwrite = new version, and only permanent version deletes are refused; assert behavior, not error codes.

## Not yet specified

- **Threat model and gold-fixture format:** Phase 0 deliverables whose content comes from the spec (§7.5, §9.5), plus ticket 12's inputs. They're specified in the spec, not decided here.

## Parked for later (owner, 2026-09-29)

- **Centralise Hindsight's LLM traffic through LiteLLM**, with failover there. Codex currently bypasses LiteLLM, because the `chatgpt/*` routes only serve streaming callers and Hindsight is non-streaming. Hindsight's request log would then show the alias, and the real model would come from LiteLLM's spend logs.
- **LLM failover for Hindsight.** 0.10.1 supports `HINDSIGHT_API_LLM_<n>_*` + `LLM_STRATEGY={"mode":"failover"}`, server-wide. The shared server holds `hermes`, so a cloud fallback there conflicts with the LiteLLM privacy rule; use a self-hosted fallback there, and MiniMax only in a dedicated Atlas Hindsight.
- **A dedicated Atlas Hindsight** (MiniMax primary, its own embedding and reranker), instead of the shared release.

## Out of scope

- Phases 3–6a (discovery, entity resolution, research workflow, financial scenarios, snapshots/replay): the next map, charted once this spec exists. It starts from ticket 12's adopt list.
- Seeding replay banks by document export/import (it copies memories without re-extraction, but the source bank's extraction may have seen later documents): a Phase 6a question for the next map.
- Authentik forward-auth/OIDC on the internal gateway: ruled out for the pilot (Q16). No cluster pattern exists yet.
- Exa, Firecrawl, OpenBB and any market-data provider: optional or post-pilot per the spec.
- [Pay-as-you-go extraction providers](issues/11-paygo-extraction-providers.md): the owner ruled out pay-as-you-go; use the existing subscriptions.
- A broad local-model benchmark beyond the extraction bake-off in ticket 04.
