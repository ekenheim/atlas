# Memory holds the intake window: retire Coherent's and Lumentum's pre-window sections

Type: build + ops
Status: done
Blocked by: none
Blocks: 05–08 (the verdict runs read the bank this fixes)

## Why

Intake is a rolling window (`ATLAS_INGEST_LOOKBACK_DAYS`, 730; `docs/decisions.md`, "ingest lookback", spec §3 "a rolling two to three years"). Only Coherent and Lumentum hold more: their first cluster ingest ran before the lookback existed (the 2026-09-29 incident), and their sections were later retained in full. On production, 2026-10-06:

| | in the window (since 2024-10-06) | before it (2018–2024) |
|---|---|---|
| Coherent | 347 sections, 5.8k facts | 1,131 sections, 15.9k facts (814 from 8-Ks) |
| Lumentum | 310 sections, 7.0k facts | 681 sections, 15.1k facts |

Every other company starts in late 2024. In the memory probe (25 recalls, 2026-10-06), 22% of all pointers and **82% of Coherent's** led to pre-window documents: memory sends an Investigator to II-VI-era 8-Ks. The depth was an accident, not a choice, and the objective (early bottleneck calls across the universe) wants every company read at the same depth unless a reason says otherwise.

Decided (the lead, 2026-10-06, with the owner's agreement): the research bank holds what intake holds. Pre-window sections leave Memory; their Source Versions stay in the ledger and the archive, citable, and an Assertion on them is unaffected.

## What to build

`atlas memory retire --before <date> [--company <slug>...] [--max-sections N] [--key K]` (`--max-sections 0`: count only, delete nothing): a `memory_retire` job (backfill class, not pausable by an LLM outage: it calls no LLM; a Hindsight outage pauses it like the backfill), modelled on `atlas memory backfill`'s delete path (`docs/decisions.md`, "A backfill replaces a section's document"):

- Takes the sections of Source Versions whose `available_at` (effective) is before `--before`, newest first within a company, in any state but `linked` (a linked version is retired with the version it links to).
- For each: `DELETE …/documents/{id}` (404 is no error), then in one transaction set the section's state to a new `retired` and record its memories in an insert-only `memory_retirement` row (migration `0077`; like `memory_replacement`, with the date bound and the job).
- The provenance resolver reads a retired memory as `unverified` with the reason `memory_retired` (not `broken`), as it does `memory_replaced`.
- Nothing takes a retired section back: retain, `retention retry-failed`, the backfill, the stuck rule and triage skip it; a later Source Version of the same document is new and is retained as usual.
- Memory health counts `retired` per company and for the bank; the reconciliation counts a retired section's Hindsight document as `document_unrecorded` only if it still exists (a delete that did not take).
- Records, per document, Hindsight's `memory_units_deleted`, and in the job's artifacts the bank's `pending_consolidation` before and after.
- Ends by enqueueing a `consolidate`, under the existing round budget.

**What a delete does in Hindsight 0.10.x** (the owner pointed at the API docs, 2026-10-06; pinned copy `.agents/skills/hindsight-docs/references/developer/api/documents.md` and `operations.md`): `DELETE …/documents/{id}` removes the document and every memory extracted from it, permanently, and answers with `memory_units_deleted`. There is no bulk or filtered delete: one call per section document (about 1,800 here). Each delete queues a `graph_maintenance` operation (link top-up and entity prune; no LLM; bank-deduped, resumable). **An observation that cites a deleted fact is invalidated, not trimmed**, and is regenerated from its surviving co-source facts by the next consolidation; with `enable_auto_consolidation: false` (template 1.4.0) that happens only when Atlas consolidates. Observations span companies within `theme:photonics`, so retiring Coherent's and Lumentum's old facts invalidates observations across the theme until that consolidation runs: a burst of rounds on the consolidation quota (see `consolidation-chatgpt-quota`). Hence the order in Ops below.

Not now (after the verdict): retiring on a schedule as the window rolls. Record it under "Not yet specified" when this ships.

Rules: `docs/decisions.md`, "Memory holds the intake window"; runbook: "Retiring pre-window sections".

## Ops (the lead, after the release and the owner's go-ahead for `kubectl exec`)

```
atlas memory retire --before 2024-10-06 --company coherent --company lumentum
```

Order: first a dry count (`--max-sections 0` reports what it would take), then a small run (`--max-sections 50`) to read the invalidated observations and `pending_consolidation` it causes, then the rest. Run it as soon as it is released: the consolidation running since 2026-10-04 is still working through retained sections, and every round spent on a fact this ticket deletes is wasted. The rebuild of invalidated observations must finish before the verdict runs (05–08) read the bank.

## Done when

- [x] Tests at the seams: the CLI enqueues; a worker pass deletes the documents (the fake's `forget`), sets `retired`, records the retirement; the resolver's `memory_retired`; retain/backfill/retry skip a retired section; health counts it. Released.
- [x] On production: Coherent and Lumentum hold only in-window sections (health), the reconciliation is `clean`, and the memory probe's pre-window pointer share is 0, recorded here.

## Comments

### 2026-10-06: done on production (0.4.6)

- Count: Coherent 1,131, Lumentum 681 sections before 2024-10-06. Trial of 50 (Coherent): 1,105 memory units deleted, observations 16,674 → 16,022, pending consolidation +1,079. Then the rest: Coherent 1,081 (two attempts; the first stopped on a Hindsight `DELETE` answering HTTP 500 "deadlock detected", most likely against the running consolidation; the retry resumed), Lumentum 681. 0 documents absent.
- After: 1,812 sections `retired`; bank facts 74,849 → 44,973; observations 8,478 (being rebuilt from the surviving co-source facts; the owner agreed to the rebuild, 2026-10-06). Pending consolidation went down overall (28,161 → 23,761 over Coherent's run, 24,779 after Lumentum's): the deleted facts were largely still pending themselves. Coherent 347 sections / 5,800 facts, Lumentum 310 / 7,045. The reconciliation `clean`; the probe's pre-window share 0% (ticket 22's after-measure).
- **Known gaps, for after the verdict:** a Hindsight 5xx such as a deadlock on `DELETE` costs the job an attempt instead of being retried within it; a `linked` section is not retired with the version it links to (none on production); retiring on a schedule as the window rolls (map, "Not yet specified").

### 2026-10-06, 13:00 UTC: the consolidation after the retirement, checked

- **Correct:** 681 observations recalled by ten queries aimed at the retired material (II-VI/Finisar, NeoPhotonics, Coherent FY2022): all resolved, 0 of their 2,387 sources pre-window, so an invalidated observation is not served. The retire runs' three `consolidate` jobs joined the run in progress (no second request) and left it processing (rounds 331 → 335); observations 8,532 → 8,564 in seven minutes. The reconciliation clean.
- **Not yet in line:** about 24,800 memories pending at about 1,200 an hour (12 rounds of 100), so the rebuild ends around 2026-10-07 09:00 UTC. Fewer observations than the 16,674 before are expected: the bank has 40% fewer facts.
- **The mental models describe the morning's bank** (refreshed 06:30 UTC, before the retirement). Current citations: Theme status 232 (204 resolved, 10 `memory_retired`, 18 deleted observations reading `broken`), Bottlenecks 218 (202, 9, 7). The scheduled refresh of 2026-10-07 06:30 runs before the rebuild ends. **Next (lead):** once the run completes, refresh both models by hand (`atlas jobs enqueue refresh_mental_model`, 2 Codex units), then the probe and the reconciliation again, recorded here.
- **Gap:** a retirement records the facts' IDs, not the observations Hindsight invalidates with them, so a model's citation of such an observation reads `broken` (`memory_not_found`) instead of `memory_retired` (the same gap as the backfill's, `docs/decisions.md`, "A backfill replaces a section's document"). Parked with the rolling retirement in the map.
