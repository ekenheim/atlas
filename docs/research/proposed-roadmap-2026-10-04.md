# Proposed Atlas TODO — 4 October 2026

**Proposal for the owner; not an adopted execution map.** Based on the current pilot-review map, its uncommitted 4 October updates, ticket 21's completed model comparison, the frozen verdict procedure, pilot-fix tickets, and the existing bottleneck-argument draft. Repository reference: integration checkout `28eb0f7`, release work through 0.4.5. No production changes or live model calls were made for this proposal.

**Handoff:** the owner asked on 4 October to commit this proposal so Claude can pick it up later. When planning resumes, compare it with the current pilot map and the latest results, then record accepted sequencing changes in that map and its tickets. This document preserves the recommendation and its rationale; it does not mark the proposed work completed or replace the frozen verdict procedure.

## The change I recommend

Keep the existing five-question pilot and its independent comparisons. Give product development a bounded path while consolidation runs, and make the next delivered product **one defensible bottleneck dossier that connects evidence, economic capture, uncertainty, and the next research action**.

The present TODO already contains the right ideas. Its main weakness is sequencing: memory release, backfill, model measurement, complete consolidation, verdict, and only then any product development. Each new memory issue can move the entire product further away. The proposed ordering preserves the official verdict's gates while allowing preparation and a small prototype to progress independently.

**Explicit changes to current policy:** permit the dossier prototype and scenario-correctness work before the verdict, isolated from the frozen benchmark version; begin fundamental prediction recording before the broader Phase 6b monitoring system. These are recommendations for adopting a revised map, not claims that the current map already authorizes them. Formal verdict runs still follow the existing readiness and conformance requirements. No trading, sizing, or execution is added.

## What is already in place — reuse it

- Pilot questions, acceptance criteria, blind Claim review, BM25 archive baseline, and a separate researcher's-hour baseline. Do not create another competing pilot.
- Source archive, Assertions, Evidence Families, scoped Memory, investigations, Hypotheses, scenarios, snapshots and proposed updates.
- A draft [bottleneck argument specification](../../.scratch/atlas-bottleneck-argument/spec.md) containing the core product direction.
- Released work on consolidation-chain tracking, corrected checks, stale pending sections, reconciliation and pinned settings. Verify the deployed behaviour needed by the pilot; do not relist these as wholly unbuilt features.
- A small consolidation-model comparison and the owner's development choice: the 5090, batch 8, with a recorded fallback. The small sample and local Hindsight 0.10.1 versus production 0.10.2 limit what that comparison establishes. It is sufficient to close the initial choice, not to claim universal quality or launch another model search.

## Proposed order

| Order | Deliverable | Completion criterion | Existing work to use |
|---|---|---|---|
| 1 | One current execution map and pilot readiness record | Current version/settings, dependencies and incomplete live checks are explicit; one place says what blocks the verdict | Pilot-review 17, 20, 21; memory-quality 22–23 |
| 2 | Consolidation completes and can recover from interruption | A stopped/restarted worker cannot leave an unattended run followed forever; current corpus reconciles; required conformance is recorded | Pilot-review 21 and its restart finding |
| In parallel with 2 | One bounded dossier prototype and a scenario-correctness patch | A reviewed case exposes unsupported premises and the economic assumptions; wrong financial metrics/periods are refused | Bottleneck-argument draft; pilot-fix 30 |
| 3 | The frozen five-case pilot verdict | All five cases, both baselines, reviews, demo and evaluation status are reported together under the existing criteria | Pilot-review 05–13; rerun case 1 explicitly |
| 4 | A complete bottleneck dossier in the product | The selected workflow produces a short, source-backed argument with meaningful challenge coverage and a bounded next action | Bottleneck-argument draft; pilot-fixes 23, 25 |
| 5 | Economic capture and market expectations | Incremental benefit is separated from the existing business; price comparisons use an appropriate valuation basis and dated inputs | Existing scenarios; spec §8.2 and §9.3 |
| 6 | A prospective research record | Supported, rejected and unresolved cases carry dated predictions and are settled without rewriting the original | Hypothesis versions, snapshots, proposed updates |
| 7 | One evidence-led universe expansion | One new company is researched with minimal intake and maintained thereafter | Existing Candidate workflow; Sivers item in the map |

Orders describe dependencies, not a commitment to fixed calendar dates. The final implementation scope after order 3 depends on the pilot's verdict.

## 1. Make the TODO describe today's system

- **Split pilot-review 21 into three independently closeable pieces:** the model/batch decision (measured and decided), completion/recovery of the backlog (running), and a bounded investigation of consolidation's contribution to useful research (later). Finishing the backlog should not silently open another mandatory mission/model experiment.
- **Narrow pilot-review 20 to its remaining acceptance work.** The releases already happened; list the missing live checks, conformance and before/after measures individually.
- **Recheck pilot-review 17's intake acceptance.** Its latest counts are from 2 October. Close it only on current evidence, or name the exact missing companies/documents. Missing coverage stays visible.
- **Make investigation 1's final rerun explicit.** Ticket 15 is a resolved before-measure, while the frozen procedure requires all five on the verdict configuration. Give the rerun its own checklist entry or ticket dependency.
- **Synchronize the map's summary with ticket 02.** The map still summarizes 200k tokens/10 minutes, while the criteria's later amendments specify 2M/20 minutes. Preserve the existing decisions and their dates; do not change thresholds after seeing results.
- **Make readiness a shared prerequisite.** Pilot-review 11 currently lists only the adjudicated gold ticket as a blocker; the evaluation methodology also requires conformance. The execution map should expose both.

Each open item should name an outcome, a dependency, a proof of completion, and what is deliberately left out. Keep closed engineering history linked below the active queue.

## 2. Finish memory work with a bounded operational objective

Keep the 5090 decision for the development pass. Record the actual model/fallback used, template, server version, corpus/profile and consolidation generation in evaluation artifacts. A local PC going offline must not silently turn a supposedly single-model experiment into another one.

The newly observed restart problem deserves a focused reliability item: a consolidation can remain `processing` without progress after a restart, and a cancelled run may not be requested again until the daily schedule. Implement bounded detection and recovery based on progress and worker state, respecting owner-initiated cancellation and existing budgets. A time threshold alone must not indiscriminately cancel legitimate slow work. Prove restart recovery and the absence of duplicate active runs at the worker/gateway seam.

Readiness for the **official verdict** remains the existing conformance/coverage gate, plus completion of the intended consolidation and a reconciled bank. Freeze the research configuration and bank/corpus state for comparison, or disclose any unavoidable change and rerun affected cases under the frozen procedure. Archive the observations/retrieval outputs actually used.

While that happens, work on reviewed examples, UI/data contracts, deterministic scenario checks, and evaluation preparation. Exploratory runs against an incomplete or changing bank are development observations, not the official benchmark. This proposal does not authorize additional paid/live runs or alter their existing approval requirements.

Do not make the count of observations spanning companies the sole success target. The end-to-end question is whether Atlas finds the relevant primary passages and builds a supported argument across them. Distinguish a conformance defect from a hypothesis that more precomputed synthesis would improve retrieval. Measure the latter on a fixed corpus before another rebuild.

## 3. Close the five-case pilot and make a decision

Use the existing questions: laser chips, InP substrates, module assembly, DSP/drivers, and coherent optics/systems. Keep the existing BM25 and researcher's-hour comparisons; the latter already implements the simple model-plus-sources baseline discussed in our conversation.

Report the preregistered measures without dilution: Claim accuracy, supported findings, baseline coverage, useful saved work, role execution/challenge coverage, cost and latency. Also report the observed human correction effort as a descriptive measure, without retroactively adding a pass/fail threshold.

The output is pilot-review 13's verdict and `docs/pilot-report.md`, including 09's edge review, 11's live evaluation status and 12's end-to-end demonstration. Respect the existing handling of unavailable live checks and say what was shown only with fixtures.

Choose a concrete consequence:

- **Pass:** build the dossier around the workflow that actually worked.
- **Partial:** one named, bounded correction round focused on the failures shown by several cases; rerun under the declared procedure.
- **Fail:** simplify or redesign the weak workflow, using the simpler baseline as the reference. Do not respond automatically with more agents, more ingestion or a stronger consolidation model.

Set an actual review date when this proposal is adopted. At that checkpoint, write either the verdict or a readiness report with the exact remaining blocker. Do not silently rename the next infrastructure cycle as progress toward a verdict.

## 4. Deliver the bottleneck dossier in two small increments

**First, one human-reviewed example and a prototype.** Reuse an existing research case; do not present it as a fresh investment recommendation. Start from the current Hypothesis and source-viewing components. This prototype can proceed during consolidation under the proposed policy change, on an isolated branch or static artifact, without changing the pilot deployment.

**Then, after the verdict, implement the selected workflow.** For each premise, show its claim, company/product, period, supporting Evidence, contrary Evidence, status and uncertainty. Preserve the distinction between a management plan and an achieved result. An inference must name its premises. Unknown or disputed steps remain visible even if surrounding steps are supported.

The owner should be able to answer from the dossier:

1. What is constrained, and what establishes demand relative to qualified supply?
2. How long might it last; what new capacity, supplier or substitute changes it?
3. Which company controls the scarce capability and can capture the economics?
4. Which material premises have actually been challenged?
5. What would invalidate the case, and what should be researched next?

Bring pilot-fix 23's semantic errors and the remainder of 25's Skeptic coverage into this milestone, narrowed by the verdict. Reuse existing wrong-Claim/finding examples and add unseen cases; lexical matching alone cannot establish preserved meaning. Challenge the material premises with an explicit reading allowance so the supporting investigation cannot consume all the documents.

Choose one bounded next action by a simple rule: prioritize an unresolved premise whose outcome would most change the case. Record why it matters, what source could resolve it, and its stopping condition. No new general-purpose autonomous planner is needed.

## 5. Make the economics usable before adding price conclusions

**Promote pilot-fix 30.** It is currently deferred until the verdict, but its deterministic metric/period checks can be implemented without waiting for memory quality or altering the frozen research version. Debt must include the appropriate components from one balance date. Prevent a cash observation from sourcing revenue and a quarter from silently sourcing an annual flow.

Then complete an economic-capture example using the existing scenario engine: contracts and pricing, realistic share, margin, capital expenditure, financing/dilution, and the duration of the benefit. Mark estimates and missing inputs explicitly.

Add an explicit valuation-basis check before any price comparison. The current scenario model values `incremental_contribution` and subtracts total net debt; that does not, by itself, model the value of the whole existing business. Distinguish incremental exposure, a segment valuation, and whole-company equity value. Reuse the arithmetic, but do not turn an exposure illustration into an unsupported price target.

The first market-expectations feature should answer what operating assumptions would be needed to justify a stated, dated price, and how those assumptions compare with the evidence. Use a manually recorded, permitted data snapshot for an initial reviewed example; select a licensed provider before automated price/consensus intake or return measurement. Handle missing market data openly. A complete market-data platform is not a prerequisite for documenting the causal economics.

## 6. Start learning from dated predictions

Use existing Hypothesis versions and frozen snapshots to record a metric, expected range or event probability where appropriate, deadline, settling source and falsifier. Include rejected and unresolved cases as well as promising ones. Resolve outcomes with an appended assessment, preserving the original forecast.

Start with fundamental outcomes: qualification, capacity coming online, lead times, margins, financing. A manual review cycle is sufficient initially. An automated inbox and broad monitoring come after several real updates reveal what needs automating. Return measurement waits for suitable licensed, point-in-time market data; early cases cannot establish persistent investment outperformance.

## 7. Expand the universe one thesis at a time

Keep the formal pilot universe fixed. Afterward, use the existing owner-suggested Sivers case to exercise Candidate → limited source intake → hypothesis → maintain/reject. Preserve its owner-sourced attribution and exclude it from the held-out discovery score.

Start with the relevant reports and calls through the permitted/manual path. Deepen history only to answer a research question. Before promoting a Candidate into ongoing coverage, fix the nightly loop to include the stored universe; subsequently add inactive coverage when a real case needs it. Do not begin a Swedish adapter project merely because one candidate exists.

## Keep parked

- A wholesale frontier-model re-consolidation until a fixed representative evaluation identifies the gain worth paying for; preserve generations when comparing it.
- More embedding/reranker/model bake-offs without a measured, material retrieval failure.
- General ontology/derivation-graph work, another graph core, and React Flow polish.
- Additional themes, mass universe expansion and broad new source adapters.
- Concurrent Investigators until there is a measured latency need **and pilot-fix 31 fences expired attempts**; 31 remains a prerequisite to 27.
- Decision-model vendor integrations, broad news ingestion, and a full market-data platform before their specific workflow needs are demonstrated.
- Automated portfolio sizing and trade execution; these remain outside the current product scope.

## Exact disposition of the current tickets

| Current item | Proposed disposition |
|---|---|
| Pilot-review 20 | Close out remaining live acceptance work; no new open-ended memory programme inside this ticket |
| Pilot-review 21 | Separate completed model choice, backlog/recovery, and later consolidation-quality experiment |
| Pilot-review 05–08 plus case 1 rerun | Preserve frozen verdict; expose shared readiness prerequisite |
| Pilot-review 09, 11, 12, 13 | Keep as one pilot completion package; refresh stale version/dependency references |
| Pilot-review 17 | Reconcile current coverage and close or name the precise residual gap |
| Bottleneck-argument draft | Promote as the next product direction; permit one bounded pre-verdict prototype if this proposal is adopted |
| Pilot-fix 30 and debt-normalization issue | Move into near-term deterministic correctness; complete before decision-facing valuation |
| Pilot-fix 23 and remaining 25 | Prioritize in the post-verdict dossier milestone according to observed failures |
| Pilot-fix 31 → 27 | Preserve hard prerequisite; performance work only after measured need |
| Phase 6b | Split: fundamental prediction record early; automated monitoring and licensed return data later |
| Sivers / dynamic universe | First controlled expansion after the fixed pilot |

The next development cycle should leave the owner with a usable dossier, a bounded set of uncertainties, and an honest comparison with simpler research. Infrastructure work earns priority when it is necessary to deliver or trust those outputs.

## Sources within the project

- [Current pilot-review map](../../.scratch/atlas-pilot-review/map.md)
- Consolidation measurement and 5090 decision: `.scratch/atlas-pilot-review/issues/21-consolidation-model-and-batch-measured.md` (read from the lead's uncommitted work on 4 October; this commit preserves the proposal, not that separate ticket). The relevant decision is summarized above.
- [Frozen verdict procedure](../../.scratch/pilot/verdict-procedure.md)
- [Pilot verdict criteria and amendments](../../.scratch/atlas-pilot-review/issues/02-pilot-verdict-criteria.md)
- [Bottleneck argument draft](../../.scratch/atlas-bottleneck-argument/spec.md)
- [Scenario source correctness](../../.scratch/atlas-pilot-fixes/issues/30-a-scenario-input-matches-its-metric-and-period.md)
- [Existing scenario model](../../backend/atlas/scenarios/model.py)
- [Authoritative product specification](../../hindsight_investment_research_build_plan.md)
