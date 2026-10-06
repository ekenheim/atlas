# Every parsed Source Version reaches Memory, and a gap shows

Type: build + ops
Status: open
Blocked by: none
Blocks: 05–08 (the verdict runs read the bank this fixes)

## Why

The owner asked on 2026-10-06 why the bank looks unbalanced. Read on production (0.4.5) that day, through the API only:

- **89 English, parsed Source Versions were never offered to Memory:** STMicroelectronics 67 (its FY2024 20-F among them), Applied Optoelectronics 17 (its FY2024 10-K and a 10-Q), Marvell 5 (a 10-Q). No triage decision, no section, no queued job. The first ingests of the ten new companies ran with `--max-retains 5` ("a rerun takes the next 5"), and the reruns stopped before these.
- **9 more failed triage and were never retried:** eight of Soitec's nine call transcripts and IQE's H2 2025 call (`atlas_triage_failed_jobs` = 9). Every attempt failed on MiniMax's `HTTP 529 … overloaded_error … (2064)`. That is an outage, but `atlas.jobs.pacing` did not classify it: `classify_status` knows 502/503/504 only, and `_UNAVAILABLE`'s `\boverloaded\b` cannot match `overloaded_error` (`_` is a word character). So each job spent its three attempts in minutes as ordinary failures instead of pausing the queue with backoff.
- **Nothing showed either gap.** `GET /api/v1/memory/health` counts recorded sections only (0 failed, 0 pending), and the day's reconciliation was `clean`; neither looks at a version with no section. The memory probe ranked STMicro at 0.03 and Soitec absent.

Under the scope rule this is a blocker for the verdict runs: a pointer can only lead to what Memory holds, so four companies are under-read by accident, not by relevance.

## What to build

1. **An overloaded provider is an outage.** HTTP 529 classifies as `unavailable` (status and text), and the outage text matches `overloaded` inside a longer token (`overloaded_error`). Test at the seam that exists for it: a role call (the triage job, through the worker's single pass) answered 529 with MiniMax's body pauses the queue and does not consume a failed attempt; the same for a retain operation whose error text carries it. Keep the rule that arbitrary exception text never pauses the queue.
2. **Memory health counts versions, not only sections.** Per company and for the bank, a `versions` block: parsed versions Memory should hold (English, a retainable kind; companyfacts and non-English excluded), split into `in_memory` (a memory document, or linked), `all_skipped` (every section's effective triage decision is `skip`), `triage_failed` (its triage job failed after its attempts), `in_flight` (a `triage`, `retain`, `poll_operation` or `reprocess` of it queued or running) and `not_submitted` (none of these). Samples (up to 20 version IDs with title and `available_at`) for the last two.
3. **Reconciliation reports it.** A new kind `version_not_in_memory` (count + up to 20 samples, `not_submitted` and `triage_failed` together, each sample naming which). A non-zero count makes the run `drift`.
4. **Metric and alert.** `atlas_versions_not_in_memory{company,reason}` (reason `not_submitted` | `triage_failed`) and an alert `AtlasVersionsNotInMemory` when it stays above 0 for 24 h, in `configs/prometheus/atlas-alerts.yaml` next to the memory alerts.
5. **One command takes them.** `atlas memory backfill` also takes `not_submitted` versions of the companies it runs for (enqueue their backfill-class `retain`, which triages first), and `triage_failed` ones (re-enqueue their triage, as `atlas triage retry` does), counted in the job's artifacts. `--max-sections` still bounds it (count a version's sections once it is triaged; before that count it as one).

Rules go in `docs/decisions.md` ("Every parsed version reaches Memory"), the operator's steps in `docs/runbooks.md` ("Memory backfill").

## Ops (the lead, after the owner's go-ahead for `kubectl exec` on production)

Can run before the release, with the commands that exist on 0.4.5:

```
atlas triage retry --failed                                   # the 9 (MiniMax; small)
atlas ingest --company stmicroelectronics --backfill --max-retains 100
atlas ingest --company applied-optoelectronics --backfill --max-retains 100
atlas ingest --company marvell --backfill --max-retains 100
```

Then the API sweep again (`scratchpad/sweep.py`-style: every English parsed version is `in_memory` or `all_skipped`), and the memory probe.

## Done when

- [ ] 529 / `overloaded_error` pauses the queue (tests above), released.
- [ ] Memory health's `versions` block, the reconciliation kind, the metric and the alert, released.
- [ ] On production: 0 versions `not_submitted` or `triage_failed` (health, and the reconciliation `clean`).
- [ ] The memory probe rerun; STMicro, Soitec and IQE's pointer weight recorded here before and after.
