# 22: Atlas's records are reconciled with Memory every night

**What to build:** a nightly, read-only `reconcile_memory` job that compares what Atlas records about the research bank with what Hindsight holds, records every difference, and makes it visible (health read, metric, alert). No LLM call, no write to Hindsight.

Why (2026-10-03, production): three defects in one day were all Atlas's records diverging from Hindsight, each found by accident: a consolidation recorded `completed` after its first round of about 20 (ticket 20); one budget unit counted for those rounds (ticket 20); 58 sections recorded `pending` that Hindsight held in the old profile (ticket 21). As the bank grows, such drift accumulates silently and every measurement rests on it.

Decided by the lead:
- **Checks**, each a kind with a count and up to 20 sample IDs:
  1. `section_missing`: a section Atlas records `completed` or `zero_fact` whose Hindsight document does not exist.
  2. `document_unrecorded`: a Hindsight document of the bank (`srcv:` IDs) whose section Atlas records `pending`, `failed` or `cancelled` and not in flight (the stuck case of ticket 21), or does not know at all (an orphan).
  3. `profile_mismatch`: a section Atlas records at the current `RETAIN_PROFILE` whose Hindsight document was not retained with it: its `retain_params` lack the item's `observation_scopes` or its given entities (the document listing carries `retain_params`).
  4. `observation_scope_outside`: observations in any scope other than one theme's (`GET …/observations/scopes`).
  5. `config_drift`: a setting the bank template sets whose live value (`GET …/config`) differs.
  6. `consolidation_untracked`: a consolidation operation of the bank pending or processing that no `submitted` run of Atlas follows, or a `submitted` run whose last round is no longer pending or processing in Hindsight.
  7. `usage` (report only, never drift): Hindsight's traced LLM calls for the bank over the last 24 h (`GET …/llm-requests`, kept one day by default) by operation (retain, consolidation, reflect) with input and output tokens, beside what Atlas's budgets counted in the same window.
- **The record:** an insert-only `memory_reconciliation` row per run (migration revision `0076`, down `0075`): started/ended, the counts by kind, samples, the usage table, and `status` (`clean`, `drift`, `failed` with the error when a listing failed: never a partial result reported as clean).
- **Schedule:** the worker enqueues one a day from `ATLAS_RECONCILE_AT` (default 03:30 UTC, after the nightly backfill's start and before the 04:30 consolidation; empty: never); `atlas memory reconcile [--wait]` by hand. Not pausable on a quota (it calls no LLM), and runs while consolidation is off.
- **Visible:** `GET /api/v1/memory/health` → `reconciliation` (the last run: status, counts, when); `GET /api/v1/memory/reconciliations[/{id}]`; gauge `atlas_memory_drift{kind}` from the last run; a PrometheusRule in `configs/prometheus/atlas-alerts.yaml` firing when any drift kind is above 0 for a day or the last run is older than 36 h.

**Blocked by:** None.

**Status:** done

- [x] Integration tests at the worker seam against the Hindsight fake: a clean bank reconciles `clean`; each of kinds 1 to 6 seeded once (a completed section whose document the fake lacks; a stuck pending section and an orphan document; a document retained without scopes; a template setting changed live; a consolidation operation nobody follows) is found with its sample; a failed listing makes the run `failed`, not clean.
- [x] The usage table is read from `llm-requests` (the fake derives it) and never counts as drift.
- [x] The health read, the two routes, the gauge and the alert rule; the CLI (`--wait` prints the summary).
- [x] Decision note, runbook ("Memory reconciliation": what each kind means and what to do), `AGENTS.md` line, settings documented, API client regenerated.
