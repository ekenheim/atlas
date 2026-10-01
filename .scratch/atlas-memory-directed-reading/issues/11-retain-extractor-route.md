# 11: Atlas marks its retains for the MiniMax extractor

**What to build:** With one setting, every section Atlas retains is extracted by MiniMax on the shared Hindsight instead of by the ChatGPT subscription, and the queue budgets it accordingly. Evidence and design: `.scratch/atlas-pilot-review/issues/18-retains-on-minimax-by-metadata-routing.md` (Hindsight's `metadata` routing strategy, verified on 0.10.2: an item whose metadata says `extractor: minimax` goes to the second chain member; everything else stays on the primary; a routed item that fails does not fall back, its retain operation fails). The cluster side is home-ops PR #7180.

- **Setting** `ATLAS_RETAIN_EXTRACTOR` (unset by default; the only value today is `minimax`). When set, every retain item Atlas builds carries `extractor: <value>` in its metadata, beside the provenance keys it already sends. Unset, nothing changes. Replay banks and evaluation banks follow the same setting (they run on whatever Hindsight they are pointed at; a server without the route ignores the key).
- **What was asked is recorded:** the memory-document record of a retained section gains the extractor Atlas requested (null for the primary), since Hindsight stores nothing about the route. `GET /api/v1/source-versions/{id}/memory` shows it per section. A section retained again (reprocess) records the extractor of that attempt.
- **Budgets:** with the extractor set, `retain`, `poll_operation` and `reprocess` no longer count against the `codex` budget. They count against a new provider budget, in operations per rolling window: `ATLAS_RETAIN_BUDGET_OPERATIONS` (default 200), shown in `GET /api/v1/queue` like the others, with the same interactive reserve and backfill rules. The `codex` budget then covers `reflect`, `refresh_mental_model` and `replay` only. Unset, the kinds stay under `codex` as today. Metrics follow the provider name.
- **Failures:** a routed retain whose operation fails with a provider error (a 429 or an outage relayed by LiteLLM in the operation's error) pauses the Hindsight job kinds exactly as a Codex quota error does today; check the failure classification on the error text the prototype saw (`litellm.BadRequestError`, `RateLimitError`) and extend it if needed. A zero-fact or failed section is retried and reported as today.
- Docs: decision entry "Atlas's retains on MiniMax by metadata routing" (why metadata routing and not failover or round-robin; what stays on the primary: recall, reflect, consolidation, mental-model refresh; the bank holds facts from two extractors), `docs/runbooks.md` ("Universe rollout and quota budgets": the new budget, how to switch the setting on and back), `.env.example`, `AGENTS.md`.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Integration test at the retention seam with the recorded Hindsight fake: with the setting, the retain request's items carry `extractor: minimax` in metadata and the section's memory record shows it; without it, the request is byte-for-byte what it is today.
- [x] With the setting, a retain is held by the new budget and not by `codex`; `GET /api/v1/queue` shows both providers; a `reflect` job is still held by `codex`.
- [x] An operation that failed with a relayed rate-limit error pauses the queue with the `quota` class.
- [x] Decision entry, runbook, `.env.example`, `AGENTS.md`, migration with the revision the lead names.

## Comments

**2026-10-01, the implementer: built** (`docs/implementation-log.md`, "memory-directed reading ticket 11"; `docs/decisions.md`, "Atlas's retains on MiniMax by metadata routing"). The provider is `hindsight_minimax`; migration `0060` (down `0055`). Tested against the recorded fake only: nothing here shows that the shared Hindsight routes the key (home-ops PR #7180 is not merged), and the unset request is checked field by field and key by key in order, with no `"extractor"` in the raw body, not against a stored byte copy.
