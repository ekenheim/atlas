# 18: XBRL normalization

**What to build:** XBRL companyfacts become as-of financial observations: each fact's `available_at` is its filing's availability (`filing_availability`), selection is the latest filing available at the as-of date per (concept, period, unit), never `frame`. Tag precedence per concept, restatements linked not overwritten, a suspect flag, derived Q4 (FY − 9M) with 52/53-week years, `us-gaap` and `ifrs-full`, no currency mixing without a stated FX basis. Research: branch `research/xbrl-normalization`.

Spec: `.scratch/atlas-phase3-6a/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `financial_observation` table with source accession/version, `available_at`, currency, FX basis, restatement link
- [ ] Companyfacts fixtures re-trimmed (current revenue tag, capex, debt, diluted shares) plus an IFRS sample
- [ ] Worked examples as tests: Lumentum Q4 = $1,006.3M; the Nokia FY2023 restatement
- [ ] Gate tests: a fixture reconciles to filed values, units and periods; restatement and currency tests
- [ ] Every figure exposes accession, concept, period, unit and `available_at` via the API
