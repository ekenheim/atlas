# Map: Atlas pilot, Phases 0–2

Label: wayfinder:map

## Destination

A ready-for-agent spec (via `/to-spec`) for Phases 0–2 of the pilot: service skeleton, SEC provenance vertical slice, Hindsight integration against the verified feature matrix, and the first home-ops deployment. The spec will be at `.scratch/atlas-pilot/spec.md`.

## Notes

- **Domain:** evidence-driven investment research on Hindsight. Glossary: `CONTEXT.md`. The build plan (`hindsight_investment_research_build_plan.md` v1.1) is authoritative. Grilling fills its gaps; it doesn't relitigate it. Deviations go in `docs/decisions.md`.
- **Skills:** grilling tickets call `grilling` + `domain-modeling`. Research tickets call `research` and write to `docs/research/`.
- **Standing preferences:**
  - All LLM traffic goes through LiteLLM, including Atlas Hindsight's extraction and reflect. Never call providers directly.
  - Use what's already paid for (ChatGPT Plus, MiniMax Plus, Anthropic subscription, self-hosted models); flag anything that would need a new paid service.
  - Research that needs the cluster uses the canonical home-ops checkout at `/mnt/c/Users/ekenh/home-ops-upgrade` (not the `Documents/` duplicate).
- **Settled in the charting session (2026-09-28):**
  - Anchor companies: Lumentum (Phase 1) and Coherent (Phase 2 cross-company gate).
  - The SEC User-Agent contact is set in env, never committed.
  - The CI gate is one local entrypoint that GitHub Actions also calls; the remote `ekenheim/atlas-research` is added before Phase 2.
  - LLM budget: $25/month on the `atlas` key, $2 default per run.
  - The Hindsight feature check records real request/response pairs as CI fixtures and runs in local Compose on the pinned version.
  - Embeddings: reuse `qwen3-embedding-0.6b` via LiteLLM (1024 dims).
  - The LiteLLM key reaches `datasci` via a new `ClusterSecretStore` modeled on `crunchy-pgo-secrets`.
  - Pilot auth: private-CIDR Envoy SecurityPolicy with the actor identity from config.
  - Hindsight is pinned at 0.10.1 unless ticket 01 finds a reason to move.
  - The EDGAR adapter is written fresh; `trading-research` is reference only.

## Decisions so far

<!-- one line per closed ticket -->

## Not yet specified

- **Hindsight gateway surface details:** the exact shape of the typed gateway, provenance resolution (memory → document_id → source version → quote span) and operation polling. Hangs on the feature matrix.
- **The two curated mental models for Phase 2:** which two of the §6.5 standing questions, their refresh trigger, and whether knowledge pages are used at all (depends on the matrix).
- **CI Hindsight strategy:** whether a real Hindsight container with a fixture LLM is feasible in CI, beyond the recorded-response fake.
- **Home-ops rollout order:** the PR sequencing across the Crunchy users, the OpenTofu bucket, the LiteLLM key, the Hindsight release and the app release, given that PRs auto-merge.
- **Threat model and gold-fixture format:** Phase 0 deliverables. Their content likely comes straight from the spec, but may surface decisions once the Hindsight matrix exists.

## Out of scope

- Phases 3–6a (discovery, entity resolution, research workflow, financial scenarios, snapshots/replay): the next map, charted once this spec exists.
- Authentik forward-auth/OIDC on the internal gateway: ruled out for the pilot (Q16). No cluster pattern exists yet.
- Exa, Firecrawl, OpenBB and any market-data provider: optional or post-pilot per the spec.
- A broad local-model benchmark beyond the extraction bake-off in ticket 04.
