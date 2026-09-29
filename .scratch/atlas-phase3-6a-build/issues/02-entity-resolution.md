# 02: Entity resolution and identity review

**What to build:** Each company resolves to its legal entity, LEI, CIK and listings through a deterministic four-tier pipeline (exact, corroborated, candidate, conflict). Only exact and corroborated commit automatically; the rest wait in a review queue. The owner confirms CIK↔LEI once per company. Securities are effective-dated with ADR links, operating vs segment MIC, FIGI level and currency. Research: branch `research/identity-apis`.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** 01 (Photonics universe)

**Status:** ready-for-agent

- [ ] Transport-injectable clients for SEC `company_tickers*.json`, GLEIF (never `fuzzycompletions`) and OpenFIGI (keyless, jobs of 10, segment MICs such as `XNGS`), each with its rate limit and recorded fixtures
- [ ] Migration extends `security` and adds alias and identity-mapping tables with provenance (source, observed_at) and review state; uniqueness per (MIC, ticker, validity)
- [ ] Unit tests of the tiers from recorded fixtures, including the XNGS/XNAS, lapsed-LEI and ADR cases
- [ ] API lists pending mappings and lets the owner confirm or reject one (audited); CIK↔LEI is never auto-committed
- [ ] An `atlas companies resolve` (or equivalent) command resolves the universe; no live calls in CI
