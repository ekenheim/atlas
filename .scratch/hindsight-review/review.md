# Atlas / Hindsight review — 3 October 2026

Reviewed Atlas `integrate/mdr` at `41f052e` (0.4.2), the 13:01 UTC conformance report, and the live research bank through GET requests. Production was not changed. No retain, reflect, consolidation, deletion, or live evaluation was requested. Offline diagnostics are intentionally failing reproducers, not application changes.

**Update, 4 October:** this is a historical review of 0.4.2, not the latest implementation. The integration log now records releases through 0.4.5, including consolidation-chain tracking/accounting, corrected conformance checks, pending-section backfill, nightly reconciliation, and pinned bank settings. These changes were read from the repository; this update is not a fresh live verification. The production root-cause assessment in finding 3 is corrected below.

**Assessment:** the report mixes genuine operational defects with faulty checks. “Six failed behaviours” is not a reliable count of broken Hindsight capabilities. Fix the completion/budget model and the checks before choosing a production rebuild.

## Live state and the 70/42404 counter

At approximately **13:49 UTC / 15:49 Stockholm**:

| Measure | Observed |
|---|---:|
| Hindsight documents | 2,228 |
| Extracted world + experience facts | 44,706 |
| Observations | 748 |
| Pending consolidation | 42,934 |
| Failed consolidation facts | 0 |
| Active consolidation operations | 1 |
| Theme-only observations | 71 |
| Company/form-scoped observations | 677 |
| Atlas sections still pending retention | 1,245 |

The operation with total **42,404** started at 13:35:11 UTC, finished at 13:48:50 after processing **100** facts, and immediately handed work to a new operation with **42,934** pending. Its results were 40 observation creates, 59 updates, and zero failed facts. The displayed numerator belongs to the current round; it is not a cumulative count across the whole backfill.

The eleven recent completed rounds each processed 100 facts and took 5.93–13.64 minutes. Their backlog totals grew from 40,184 to 42,404 while ingestion continued. At that throughput, the existing backlog alone represents roughly 2–4 days if no more facts arrive; this is a scale estimate, not a completion forecast. New ingestion was outpacing consolidation over this interval.

Evidence: [production details](C:/Users/ekenh/atlas/.scratch/hindsight-review/production-details.json), [earlier snapshot](C:/Users/ekenh/atlas/.scratch/hindsight-review/production-state.json).

## 1. P1 — Atlas mistakes a completed round for completed consolidation

`Consolidation._await` marks Atlas's record completed as soon as its one recorded Hindsight operation succeeds. Hindsight creates new operation IDs for subsequent rounds, even when `enable_auto_consolidation` is false. That setting prevents retain-triggered consolidation; it does not stop an already requested consolidation from draining its backlog.

This is observable in production: Atlas's health endpoint reports its last consolidation completed at **12:44:39 UTC**, while Hindsight is still processing successor operations at 13:49. The ADR's premise that Atlas's own operation record is complete is therefore false. The filtered operation listing also works on this deployment; I used `GET .../operations?type=consolidation&limit=12` successfully.

The same mistake occurs in the conformance harness: it waits only for the submitted operation before testing cross-company observations and reflect. A test can therefore judge a partially consolidated bank.

**Adjustment:** represent a consolidation run separately from a Hindsight round. Reconcile active/pending operations and the bank's pending/failed fact counts. Record the follow-on operations, show cumulative processed facts and incoming facts separately, and report completion only for a defined scope of work. With ongoing ingestion, define a captured cohort/cutoff or explicitly treat the run as a drain-until-idle run. Apply the same completion criterion to conformance. Require a fake-server regression where operation A completes, B is pending, and the bank still has unconsolidated facts.

Atlas code: [completion branch](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/retention/consolidation.py:309), [conformance wait](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/tests/live/conformance.py:275). Pinned upstream proof: [round rescheduling regression](https://github.com/vectorize-io/hindsight/blob/5fc4ce20917b916240cef27c212c387a177f115b/hindsight-api-slim/tests/test_consolidation_reschedule_after_round.py), [rescheduling implementation](https://github.com/vectorize-io/hindsight/blob/5fc4ce20917b916240cef27c212c387a177f115b/hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py#L2234).

## 2. P1 — Admission budgets do not bound downstream LLM work

Atlas counts one operation for submitting consolidation. Server-created rounds and their LLM calls bypass that admission counter. Backfill-window checks likewise cannot stop server work already admitted. The conformance report makes the distinction concrete: it records **2 reflect/consolidation API operations**, but Hindsight reports **145 successful LLM requests and 709,825 total tokens** for the whole test bank, including extraction. The former is not a cap on the latter.

**Adjustment:** name API submissions and provider usage separately; record actual calls/tokens, throughput, retries, and workload class. If the budget is intended to protect subscription capacity, enforce it where provider calls occur, or provide a genuinely bounded server execution mechanism. Atlas-side scheduling alone cannot enforce a hard cap after submitting an unbounded chain. Add backpressure between retention and consolidation so the pending count cannot grow indefinitely unnoticed.

Evidence: [budget contract](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/jobs/budget.py:8), [test request counters](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/tests/live/conformance.py:71), original conformance `usage.bank_llm_requests`.

## 3. P1 — Scope migration remains incomplete; a template change cannot repair old observations

**Root-cause correction, 4 October:** the lead's subsequent investigation, recorded in memory-quality ticket 20 at 19:55 UTC on 3 October, traced the company/form observations to **58 old-profile documents holding 1,587 facts**. Atlas recorded their sections as pending, and the backfill did not select pending sections, so those documents had never been re-retained with the new scopes. The old-scope observations reappeared even after the owner cleared observations. Thus the tag-matching mechanism discussed below was not established as the cause of the production incident; I gave that explanation too much weight. The immediate repair is to replace/reconcile the stale source documents (ticket 21), then validate consolidation. Clearing observations alone cannot fix old source scopes. The following paragraphs preserve the original inspection and reasoning for context.

The live bank still has 677 observations with company/form tags and only 71 carrying exactly `theme:photonics`. The configuration has the new mission, theme-oriented workflow, and automatic retain-triggered consolidation disabled. That is configuration success, not evidence that existing observations migrated.

The pinned consolidator retrieves related observations with `all_strict`: every requested tag must be present, but extra tags are allowed. A theme pass can therefore retrieve a company/form observation that also has the theme tag. Updates union the old and new tags, preserving the old scope. This supports the report's mechanism: replaying facts with theme-only scopes need not move observations into a theme-only scope. It does **not** establish that no cross-company synthesis is possible; that needs a provenance check after consolidation settles.

**Adjustment:** treat a scope change as an explicit data migration. First validate a small clean-bank example with complementary facts from two companies, complete consolidation, and inspect source provenance. Before any production reset, settle or safely stop active writers, verify source scope assignments, preserve the existing bank/history, and plan refreshes of derived models. A replacement bank permits comparison before switching readers. A bank-wide observation clear is a rebuild, not a harmless cleanup: the pinned implementation also clears observation history and resets consolidation markers on source facts.

Sources: [related-observation filtering](https://github.com/vectorize-io/hindsight/blob/5fc4ce20917b916240cef27c212c387a177f115b/hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py#L3215), [tag union on update](https://github.com/vectorize-io/hindsight/blob/5fc4ce20917b916240cef27c212c387a177f115b/hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py#L3006), [clear semantics](https://github.com/vectorize-io/hindsight/blob/5fc4ce20917b916240cef27c212c387a177f115b/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L11778).

## 4. P2 — Entity and entity-hop checks count submissions instead of unique documents

The proxy records every retain request, including repeats. `_company_items` preserves those repeats. Check 2 then sums the same document's facts again. Check 8 compares a list with duplicates against a deduplicated set of returned document IDs.

The actual report lists the same Coherent Item 5 document twice as expected and once as found. The reported missing entity-hop section was found. A minimal offline replay of the real check functions passes with unique submissions and fails after resubmitting the identical document, without changing any stored facts or entity links.

**Adjustment:** reconcile successfully retained current documents by `document_id` and content/version identity before counting; distinguish request history from bank contents. Compare unique document sets and unique fact IDs. Recheck the real 50/55 and 205/208 entity counts afterward; this repro does not prove that every count discrepancy disappears.

Code: [grouping](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/conformance/behaviours.py:237), [counts](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/conformance/behaviours.py:283), [entity hop](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/conformance/behaviours.py:541).

## 5. P2 — Attribution and layer checks have incorrect acceptance rules

**Attribution:** any fact containing “largest customer” fails unless it also contains “analyst”, “asked”, or “question”. The reported offender explicitly attributes an answer to Casey Placeholder, the synthetic CFO. The source transcript confirms that the CFO declines to break out demand and describes a broad backlog. This is a false rejection of a management answer, not proof that an analyst question became a company claim.

**Layers:** the check lowercases both text and acronyms and uses substring matching over the whole source section. “An initial quarterly report” matches `TIA` inside “initial”; `EMS` can match “items” or “systems”. A correctly unlabelled cover section can fail the test. The offline replay proves a valid layer check becomes a failure merely by adding the neutral cover text. Separately, a layer term in a section does not guarantee an extracted fact about that layer.

**Adjustment:** use annotated speaker turns and expected propositions for attribution, with negative cases for questions misrepresented as assertions. Use reviewed fact-level layer examples, the production vocabulary's word/acronym boundaries, and separate extraction coverage from label accuracy. Do not weaken the extraction prompt to satisfy these incorrect checks.

Code: [attribution predicate](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/conformance/behaviours.py:340), [layer predicate](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/conformance/behaviours.py:370).

## 6. P2 — The remaining checks need better evidence and actual execution

- **Cross-company synthesis:** three recall queries are a retrieval sample, not an exhaustive audit of observations. Absence from their results cannot establish absence from the bank. Combined with the incomplete-consolidation wait, the reported failure is inconclusive. Use a controlled pair of complementary company facts, inspect resulting observation source IDs after the full run, and score retrieval separately.
- **Mental-model refresh:** both models have zero citations and timestamps around 13:01:14, shortly after test setup. The test only rejects citations of another model; it does not assert a fresh successful refresh or any grounded citations. The template's 12-hour minimum refresh interval can skip the requested refresh. The reported two counted LLM API operations are also consistent with consolidation plus reflect, with no actual model refresh. Assert the refresh decision/outcome, an advanced timestamp, and meaningful evidence after retention.
- **Reflect:** the unverified quote among 75 citations remains an unresolved quality finding. The saved evidence drops its text, memory/source IDs, and verification reason, retaining only `state` and `kind`; the throwaway bank is then deleted. Preserve a redacted diagnostic bundle containing the answer, unresolved citation, source passage, and resolver reason before cleanup. “Unverified” is not enough to diagnose either fabrication or a resolver defect.

Code: [sampled observation check](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/conformance/behaviours.py:411), [refresh and citation evidence](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/backend/atlas/conformance/behaviours.py:603), [refresh interval](C:/Users/ekenh/worktrees/atlas/oval-tide/atlas/configs/hindsight/bank-template.json:65).

## Reproduction and recommended order

Run from PowerShell:

```powershell
wsl.exe -d Ubuntu --exec /mnt/c/Users/ekenh/atlas/.venv/bin/python /mnt/c/Users/ekenh/atlas/.scratch/hindsight-review/reproduce_checks.py
```

Observed exit code **1**, intentionally: checks 2 and 8 falsely fail on identical resubmission; check 3 falsely fails a correctly attributed CFO answer; check 4 falsely fails a neutral cover. Positive controls pass. The harness invokes the actual conformance checks, with in-memory API results and no network calls. [Reproducer](C:/Users/ekenh/atlas/.scratch/hindsight-review/reproduce_checks.py), [recorded results](C:/Users/ekenh/atlas/.scratch/hindsight-review/offline-results.json).

Recommended order:

1. Correct full-run completion, progress, provider accounting, and retention/consolidation backpressure.
2. Repair the conformance predicates and preserve diagnostic evidence. Add round-handoff and skipped-refresh regressions.
3. Validate a small clean-bank synthesis case under a real bounded quota, then decide whether a controlled production rebuild is warranted.
4. Refresh models and rerun representative research questions only after the intended corpus is ready. Compare source coverage, useful reading pointers, and supported findings; observation count alone is not the quality target.

The project direction remains sound: archived sources and verified Assertions are the durable evidence, and Hindsight is a derived research index. The immediate weakness is reliable measurement and operational control of that index. Scaling ingestion before those controls are correct compounds work without establishing better research quality.
