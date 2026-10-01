# Release and deploy 0.2.5

Type: task
Status: resolved
Blocked by: none

## Question

Get pilot fixes 06–12 onto production, following the `release-atlas` skill. `v0.2.4` (main at `9371319`) published nothing: its release run failed on a Docker Hub 502, and the re-run of the failed job failed on two tests whose fixed clock the real time had passed (`docs/implementation-log.md`, 2026-10-01). The release is `v0.2.5`, on the commit that fixes them:
- `main`'s `ci` run is green, then the `release v0.2.5` run's `publish` job succeeds;
- the home-ops PR (image bump, the `normalize-financials` and `reparse` init containers, `ATLAS_SEARXNG_ENGINES`; the pushed branch `atlas-0.2.4` renamed for 0.2.5) is open with its provenance and green checks;
- the owner merges it;
- production reports `atlas_build_info{version="0.2.5"}`, every readiness check is `ok`, and the `reparse` job has run.

The answer records the release run, the PR, and what the two init containers did.

## Answer

Done on 2026-10-01.
- **Release:** `v0.2.5` at `a7661c6`; `ci` run 36879512373 on main and release run 36884437413 both passed (1,131 tests); the image is `ghcr.io/ekenheim/atlas:0.2.5`.
- **Deploy:** home-ops PR #7152, merged by the owner. Production reported `atlas_build_info{version="0.2.5"}` at 16:45 UTC with every readiness check `ok`. The PR's one red check, "AI PR Review", fails on every home-ops PR for a missing `ai-base-url` input.
- **The init containers:** `reparse` ran with no failed job, and Lumentum's 10-K (`e256983e-142b-4427-a17a-2f64cc221b6f`) now has a `text-v3` parse beside its recorded `html-text-v1`. `normalize-financials`: 9 normalizations succeeded, none failed (`atlas_financial_normalizations_total`); the seed companies already had figures from the nightly ingest.
- **Also in the deploy:** `ATLAS_SEARXNG_ENGINES=duckduckgo,google,startpage,mojeek`. The first discovery after it kept 10 on-topic web leads.
