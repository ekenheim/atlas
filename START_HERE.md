# START HERE: engineering handoff for Atlas Research

You are the lead implementation agent. The complete, authoritative product and engineering specification is `hindsight_investment_research_build_plan.md` (v1.1). Read all of it before modifying code, including the "What changed in 1.1" table and **Appendix A** (the deployment target). Use this handoff to start implementing right away. To learn what has already been tried, how it was measured and what came of it (failures included), read `docs/experiments.md` first.

## Mission

Build a working Hindsight-centred investment research platform that runs locally (Compose) and in the owner's home Kubernetes cluster (`home-ops`, Flux GitOps). It should:

- discover emerging industry bottlenecks
- map companies and products using source-backed evidence
- investigate counterarguments
- model economic exposure
- freeze hypotheses for prospective evaluation

Deliver an end-to-end vertical slice in AI photonics before expanding to other themes. This is a research system, not a trade execution service.

## Critical architecture constraints

- **Hindsight is the only automatic long-term memory/graph core.** It already does entity/fact extraction and maintains its knowledge graph. No Neo4j, Graphiti, Cognee, FalkorDB or Qdrant in the MVP.
- **PostgreSQL is the system of record** for:
  - canonical companies and securities
  - immutable source-version metadata
  - individual claims
  - reviewed typed relationships
  - financial observations
  - hypotheses and audits
  - frozen snapshots
  - **job state** (the job queue is a Postgres table; no Prefect or Dagster)
- **Raw source bytes and parsed text versions go in filesystem/S3-compatible storage.** Derived memories and synthesized research never count as independent primary evidence.
- **One connected Hindsight research bank for the pilot.** Tagged retrieval uses explicitly chosen matching semantics. Retain/reflect/observations are configured through a versioned bank template, or the config API if the pinned version has no templates.
- **Respect Hindsight's document_id upsert semantics.** Retain each immutable source version under its own ID and never destructively replace an earlier version. Async retain operations must be idempotent and monitored for completion, error and zero-fact ingestion.
- **Hindsight `query_timestamp` and `temporal_window` are not hard historical filters.** Reproducibility comes from frozen snapshots that store what was retrieved. Isolated replay banks evaluate the pipeline, and the exclusion of future-dated sources must be tested.
- **Nothing is generated without a verified, available source.** That covers facts, supplier contracts, company exposures, valuation numbers and citations. When evidence is missing, show the unresolved questions instead.
- **LLM access goes through LiteLLM.** App-side LLM calls use the cluster LiteLLM proxy with a dedicated budgeted virtual key and per-role aliases from config. Hindsight's own extraction LLM must be non-streaming-capable and use a stable, dated model ID.
- **Commercial providers are optional adapters.** A fixture-only demo must work without paid keys. Use SEC/official IR sources first and respect source terms. SearXNG (self-hosted, no key) is the default live discovery provider, and Exa is optional.

## Before writing adapters: verify, don't assume

The spec describes Hindsight features from its docs, but the pinned server version (0.10.x in the cluster today) may differ. Phase 0 includes a live spike that produces `docs/hindsight-feature-matrix.md`. For each feature the spec relies on, record verified / behaves differently / absent:

- retain (sync/async/batch) and document_id upsert
- strict tags
- reflect JSON schema + provenance
- operations
- bank templates
- observations
- mental models
- knowledge pages
- export/import

Design against the matrix, not the prose.

## Execution order

1. **Phase 0.**
   - Inspect the repository and write an ADR recording reuse decisions.
   - Generate the skeleton: README.md, AGENTS.md, .env.example, compose.yaml, Dockerfile (a single image for api + worker + static frontend), migrations, and CI lint/type/test jobs (fixture-only).
   - Run the Hindsight spike and write the feature matrix.
2. **Phase 1: provenance vertical slice.** One SEC document goes through raw archive → parsed source version (with `available_at` from EDGAR `acceptanceDateTime`) → reviewable assertion → API + minimal source viewer. Include the idempotent re-fetch and 429-retry tests.
3. **Phase 2: Hindsight + first cluster deploy.**
   - Typed gateway, versioned bank config, source↔document↔fact linking, async operation status, grounded recall/reflect, evidence validation and two mental models.
   - Then deploy api + worker + a dedicated Hindsight to home-ops following Appendix A: Crunchy DBs with `sslmode=require` and migrations on the direct primary, a MinIO bucket via OpenTofu, ExternalSecrets from Bitwarden, a LiteLLM virtual key, and an internal-gateway HTTPRoute behind Authentik.
4. **Phase 3.**
   - Photonics seed theme (8–12 companies, config only).
   - SearXNG discovery plus a discovery fixture, with Exa optional.
   - Legal-entity resolution (mostly deterministic).
   - An evidence-backed typed relationship projection with a review workflow.
   - Theme/company views and an edge *table*. React Flow comes later.
5. **Phase 4.** Typed Scout, Investigator, Skeptical Reviewer and Financial Analyst tasks on the job table, with explicit budgets, stop states and independent counterevidence. Publish a reviewable hypothesis dossier and a JSON/Markdown export.
6. **Phase 5.** SEC XBRL normalization with as-of selection by filing availability and restatement linkage, plus transparent deterministic low/base/high scenario modeling. No PyMC until a likelihood/prior can be justified from available data.
7. **Phase 6a (inside the pilot).** Immutable published snapshots, a minimal isolated replay bank, and the intentional future-data leakage test.
8. **Pilot review.** Run the integrated scripted photonics demo (spec §15). Include a quality-evaluation report and the exact integration test status.
9. **Post-pilot only:** Phase 6b (scheduled monitoring, evidence inbox, the **market-data provider decision**, paper tracking) and Phase 7 (restore drill, hardening, React Flow map).

## Required demonstration and report

When complete, demonstrate:

- a fixture-only local boot
- the same flow running in the cluster
- provenance-resolved Hindsight recall
- a discovered company that wasn't seeded at startup
- a directed, reviewed, source-clickable company/product edge
- a thesis with both support and falsifiers
- a recomputing economic scenario
- a frozen research snapshot
- a later contradictory source that doesn't rewrite the original snapshot
- an as-of replay that excludes future sources

After each phase, record in `docs/implementation-log.md`:

- files created or changed
- acceptance tests run and their actual results
- open blockers
- provider credential dependencies
- version decisions (Hindsight version, concrete LLM models behind each alias)
- the next executable task

If a real API wasn't available, say its adapter has only been contract-tested against fixtures. Don't claim live validation.

## Deployment rules for the home-ops side

- The app code lives in its own repo and CI pushes images to GHCR. The home-ops repo only gets manifests under `kubernetes/apps/datasci/atlas/`.
- Home-ops PRs can auto-merge within minutes, so opening one is effectively deploying. Validate manifests (`flux-local`, `kubeconform`, `yamllint`) before opening it.
- Escape any literal `${...}` in manifests as `$${...}`. Flux substitution is strict and one stray placeholder fails the whole Kustomization.
- Never commit secrets. Use Bitwarden → external-secrets, and read optional fields with `{{ index . "FIELD" }}`.

Begin with repository inspection and Phase 0. Don't spend the first implementation cycle on an elaborate multi-agent orchestrator or a polished frontend. The evidence → retention → snapshot vertical slice has to work first.
