## What

**Atlas 0.3.0** (`ghcr.io/ekenheim/atlas:0.3.0`): memory-directed, multi-hop reading, and Atlas's retains extracted on MiniMax.

- **Reading follows Memory.** Each of the Scout's queries is also asked of Hindsight across the theme; the facts that come back are stored as reading pointers (never quoted, never sent to a role). The companies they name get an Investigator, up to six a round, not only the seeds. Inside a document, passages are taken alternately from the pointers and from a term search, at most a third of the budget from one document.
- **The Skeptic** asks Memory about each bear-checklist item and reads where it points; its findings are either a contradiction of a named Claim or bear context.
- **Claim checks:** the filer's own impersonal sentences and slide bullets are quotable; typographic hyphens and quotes no longer break a quote; `capacity_constrained` needs constraint language and may be company-level; `owns` runs from the holder to the issuer; an edge carries a layer only when its quote supports one.
- **Discovery:** EDGAR phrases must be specific, and a filer needs a kept hit to become a Candidate.
- **Retains on MiniMax:** with `ATLAS_RETAIN_EXTRACTOR=minimax`, every retain item is marked for the second extraction model of the shared Hindsight (home-ops PR #7180, merged and verified on 2026-10-01), under its own budget of operations.

## Manifest changes

- The image is already `0.3.0`: Renovate's #7190 bumped `deployment.yaml` and `ingest.yaml` on 2026-10-02, and production reports `atlas_build_info{version="0.3.0"}` with every readiness check `ok`. This PR adds the settings the release was built to run with; until it merges, 0.3.0 runs with the 0.2.5 budgets and its retains wait on the Codex budget (104 queued on 2026-10-02 07:32 UTC).
- `ATLAS_MINIMAX_BUDGET_TOKENS` 4,000,000 → 8,000,000 per rolling 5 h. The owner's plan allows about 1.7 billion M3 tokens a month (about 11.8M per window on average) and 3–4 concurrent agents.
- `ATLAS_RUN_TOKEN_BUDGET` 1,000,000 → 2,000,000: an investigation may now run up to six Investigators.
- `ATLAS_RETAIN_EXTRACTOR=minimax` (new). Atlas's retains then count against `ATLAS_RETAIN_BUDGET_OPERATIONS` (default 200 per window) instead of the Codex budget, which is left for reflect and mental-model refresh.
- No new secret.

## Provenance for `ghcr.io/ekenheim/atlas:0.3.0`

- **Source:** tag `v0.3.0` at commit `419d8a1` on `ekenheim/atlas` main.
- **Release build:** https://github.com/ekenheim/atlas/actions/runs/36939346940 (success: `ci` 25m44s on the self-hosted runners, `publish` 1m33s).
- **CI on the same commit:** https://github.com/ekenheim/atlas/actions/runs/36936870302 (success: 1,402 tests passed, the frontend gates, the API client check, the e2e 10 passed).
- **Migrations:** nine, chained `0050 → 0051 → 0052 → 0053 → 0054 → 0055 → 0057 → 0058 → 0059 → 0060` (there is no `0056`), none destructive:
  - `0051` the insert-only `reading_pointer` table;
  - `0052` `claim.party_basis`, and `folded` as an offset source;
  - `0053` the counterevidence kind (existing rows: `contradiction` when they name a Claim, else `bear_context`);
  - `0054` a `skipped` status and reason on `edgar_search`;
  - `0055` nullable layer on `claim` and `relationship`, the edge identity index (existing duplicates by layer are marked, none removed);
  - `0057` `claim.company_level` and the relationship object checks;
  - `0058` `investigation.max_companies` (backfilled 6);
  - `0059` the Skeptic's pointer columns on `reading_pointer`;
  - `0060` `extractor` on `memory_document` and `hindsight_operation`, and the `hindsight_minimax` budget provider.
- **Why 0.3.0:** a feature release after 0.2.5; no version was skipped.

## Load on the shared Hindsight and on MiniMax

- Atlas's new retains are extracted by MiniMax-M3 through LiteLLM (Hindsight's existing key), at most two concurrent extractions (Hindsight's setting), at most 200 retain operations per 5 h. Codex still does this bank's consolidation, reflect and mental-model refresh.
- An investigation makes more recalls than before (one per Scout query, and up to 36 for the Skeptic). Recall makes no LLM call.
- Atlas's worker makes one MiniMax role call at a time; with Hindsight's two that is three concurrent at peak, inside the plan's 3–4.

## How to check after merge

`GET /api/v1/queue` lists a `hindsight_minimax` budget and a `minimax` budget of 8,000,000, and the queued retains start to drain. After the first retain: `GET /api/v1/source-versions/{id}/memory` shows `extractor: minimax`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
