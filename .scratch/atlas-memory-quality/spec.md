# Spec: Memory quality: what Hindsight holds, and what Atlas asks of it

**Status:** ready-for-agent

Decided by the lead on 2026-10-02 under the owner's delegation, after the owner asked for a close study of how Hindsight works and for tickets from it. Evidence: `docs/research/hindsight-memory-use.md` (the study: seven findings, each marked observed, documented or open), production's counts on 2026-10-02 and one read-only recall.

## Problem Statement

Since 0.3.0 an investigation reads where Memory points. So what Memory holds, and how it is asked, now bounds every research card. The study shows Memory is under-fed and under-asked:

- **Most of the archive never reached it.** Production records 695 retained sections as completed, 22 with no fact and 1,907 as failed. A failed operation marks every section of its Source Version failed without checking what Hindsight stored, a timeout counts as permanent, and nothing retries.
- **What it consolidates stays inside one company and one form.** Atlas tags each retained section with company, theme, source, document type and form, and Hindsight's default builds observations only among memories with exactly the same tags. AXT's 8-K on its supply agreement with Coherent is never consolidated with AXT's 10-Q or with Coherent's statements.
- **It is told little about what it reads.** A transcript section is retained with the context "Q4 2026: chunk-004". Memories then say "Jordan Klein warned that…" with nothing to tell an analyst's question from the company's statement. Atlas knows the filer and the universe's names and passes neither, so Hindsight guesses which names are the same company, and its graph, which is what follows a supply chain from one company to the next, links facts only through the entities they share.
- **It is asked for the least it can give.** A recall sends the query, a middling search depth and the tags. The answer is capped near 45 memories, spends places on the same fact twice (an observation and the fact under it), is ranked for recency against today rather than the investigation's as-of time, and comes back with scores and entities that Atlas throws away. Reflect runs at its shallowest setting and cannot see Atlas's own mental models.
- **Nobody can see any of this.** There is no read of what the bank holds: how many sections per company are in Memory, which failed and why, which observation scopes exist, whether one company is one entity.

## Solution

A researcher's question reaches a Memory that holds the archive it should, knows whose statements it holds, connects companies, and is asked for everything a reading index needs:

1. **Measure first.** A memory-health read shows, per company and for the bank, what is retained, failed (grouped by error), empty, consolidated and how; a fixed set of probe recalls shows what the reading index returns. Both are run before and after this effort.
2. **Intake stops losing sections.** A section's outcome is decided from its own document in Hindsight, a timeout is retried, partial extraction is noticed, and the failed sections of the corpus are retained again.
3. **Each retained section says what it is.** The context names the company, the document, its period and who is speaking; the item names the companies Atlas knows are in it; the bank's missions say what to extract, what to ignore and what an observation is; the extractor labels each fact with its supply-chain layer.
4. **Observations consolidate across a company's documents and across the theme.**
5. **Recall is asked like a reading index:** more results, no duplicates, the as-of time, the sources of an observation in the same answer, scores and entities kept on each reading pointer.
6. **Two new ways to point:** the exact chunk a fact came from, and every fact in the theme that names a company (the company-to-company hop).
7. **Reflect and the mental models are grounded:** a real search depth, no model reading another, citations that resolve, and their cost counted.
8. **The corpus already in Memory is brought up to the same standard** by a backfill, and the five pilot investigations then run on that Memory.
9. **A conformance check says, behaviour by behaviour, that Memory works as Hindsight advertises and as this spec plans,** and it passes before anything is benchmarked.

Memory stays an index. Nothing here lets a memory's text be quoted, serve as a witness, or reach a role.

## User Stories

1. As a researcher, I want the sections of a company's filings to be in Memory unless they were skipped on purpose, so that an investigation can be pointed at them.
2. As a researcher, I want a section that failed to be retained to be tried again by itself, so that one bad section doesn't hide a whole 10-K.
3. As the owner, I want to see how many sections per company are retained, failed, empty and pending, so that I know what Memory can and cannot point at.
4. As the owner, I want failed sections grouped by their error, so that I can tell a quota problem from a parser problem.
5. As the lead, I want a section whose extraction was partial to be told apart from one with nothing material in it, so that the first is retried and the second is left alone.
6. As a researcher, I want a memory from an earnings call to say whose call it was and whether management or an analyst said it, so that an analyst's worry isn't read as the company's statement.
7. As a researcher, I want a memory from a filing to carry the reporting period, so that a figure is tied to its period.
8. As a researcher, I want "Coherent", "Coherent Corp." and its ticker to be one company in Memory, so that a question about Coherent reaches everything said about it.
9. As a researcher, I want what AXT says about its agreement with Coherent and what Coherent says about its substrate supply to be found together, so that a bottleneck is seen from both sides.
10. As a researcher, I want Memory's consolidated statements about a company to draw on its 10-K, 10-Q, 8-Ks and transcripts together, so that a change over time is seen as one development.
11. As a researcher, I want consolidated statements about the theme that draw on several companies, so that an industry-wide constraint is one finding and not five.
12. As a researcher, I want each fact labelled with the supply-chain layer it concerns, so that a question about substrates can be pointed at substrate facts.
13. As a researcher, I want a pointer recall to return more distinct sections, so that more of the theme's companies and documents are considered.
14. As a researcher, I want a recall not to spend places on the same fact twice, so that the places go to other sections.
15. As a researcher running an as-of investigation or a replay, I want recency to be judged from the as-of time, so that the ranking is the one a researcher at that time would have had.
16. As a researcher, I want each reading pointer to carry how strongly Memory ranked it, so that the companies and passages read are chosen by relevance and not by position alone.
17. As a researcher, I want a pointer to lead to the passage the fact came from, so that the Investigator reads the right window of a long section.
18. As a researcher, I want an investigation to follow a company named in what it read to every other document in the theme that names it, so that a supplier or customer is found in other filers' documents.
19. As a researcher, I want the investigation page to say which way each pointer was found (a recall, a chunk, an entity), so that I can judge why something was read.
20. As a researcher, I want a reflect answer to search deeply and to cite memories that resolve to sections, so that I can check it.
21. As the owner, I want the Bottlenecks and Theme status models to rest on memories and never on each other, so that one wrong claim doesn't spread.
22. As the owner, I want every reflect and every mental-model refresh counted against the budget, so that the shared subscription's use is visible.
23. As the owner, I want the server-side settings that would help (the embedding model's query instruction, failing on extraction errors, a reranker that fails open) proposed to me with their effect on the other consumers of the shared server, so that I can decide.
24. As the lead, I want every Hindsight feature Atlas starts to use recorded against the cluster's version first, so that the fake and the tests rest on observed behaviour.
25. As the lead, I want the same probe recalls and the same health read before and after, so that the effort's effect is a number and not an impression.
26. As the owner, I want the corpus already retained brought to the new standard without re-fetching anything, so that the pilot runs on one Memory.
27. As the owner, I want one report that says whether each thing Hindsight promises (no lost sections, one entity per company, observations across documents, recall that finds known answers, citations that resolve) holds on our settings, so that a benchmark of Atlas is not a benchmark of a broken memory.
28. As the owner, I want the embedding model chosen from a measurement on our own material, so that retrieval is as good as the server can make it.
29. As a reviewer, I want Memory to remain an index: never quoted, never a witness, never sent to a role, so that every Claim still rests on archived text.

## Implementation Decisions

**The ground: Hindsight 0.10.2, recorded.**
- The cluster runs 0.10.2; the vendored docs and the feature matrix are 0.10.1. The matrix is extended on 0.10.2 with a recorded request and response for every feature this spec uses: explicit `observation_scopes` and the scopes listing; recall's `max_tokens`, `types`, `prefer_observations`, `include.source_facts`, `include.chunks`, `query_timestamp` and per-result `scores`; retain's `entities` with `resolve_entities`; `entity_labels` with `tag: true`; the memory listing by `entity_id`; `dry-run-extract`; reflect's `budget` and `exclude_mental_models`; a document's `reprocess`. The recordings extend the fake. The docs skill is re-vendored at the server's version.
- The same ticket settles the four open questions of the study: whether stored memories take a new scope, context, entities or labels by `reprocess` or need to be retained again; whether a chunk's text is a verbatim slice of the retained content; what consolidation costs per retained section; what changed in 0.10.2.

**Measuring.**
- A memory-health read (`GET /api/v1/memory/health`, and per company): sections by retain outcome, failed sections grouped by error text, zero-fact sections, pending; from Hindsight, the observation scopes with their counts and the entities of the universe's companies (how many entities carry each company's name). No LLM call.
- A probe set: a config file of fixed recall queries (the five pilot questions and their Scout-style queries), run through the scoped recall by a script, reporting per probe the memories returned, distinct sections, distinct companies, the share of observations, duplicates, and resolved citations. Reports go under `.scratch/live-runs/` and their summary into the implementation log.

**Intake that doesn't lose sections.**
- A section's outcome is read from its own Hindsight document whatever the operation's end state: stored with facts is completed, stored with none is zero-fact, absent is failed.
- The failure classes gain a transient class for timeouts and relayed server errors; a transient failure leaves the section pending and resubmitted with the queue's backoff, a bounded number of times.
- The operation's `extraction_errors_count` is read: a completed section with extraction errors is recorded as partial and retried once.
- Whether a long Item should be retained in bounded parts is decided from the health read's error grouping, not assumed: it would change section identity, which triage, provenance and the pointers all key on. If the failed sections are mostly long Items failing by size, the split becomes its own ticket; otherwise it is not built.
- `atlas retention retry-failed` (the existing owner command) is extended to re-enqueue by error class and company, as backfill class.

**What a retained section says.**
- Context is built by one function from the Source Version: company display name, document kind and form, the period it reports on, its availability date, the section's heading, and a speaker line by source type: "The filer is speaking" for a company's own filing; for a call transcript, that management and analysts speak and an analyst's question is not the company's statement.
- The item's `entities` are the filer's canonical name and the names of universe companies and counterparties the section's text names (the matcher passage selection already uses), sent with `resolve_entities` false so they are taken as written.
- Metadata keeps the provenance keys and gains display keys the extractor can use (company name, form, period).
- The retain record stores the context and entities sent, so a later backfill can tell which sections are at the current standard (a `retain_profile` version on the memory document).

**The bank template (a new template version).**
- `retain_mission` gains an ignore list (boilerplate legal language, safe-harbor statements, officer certifications, exhibit lists) and says to attribute each statement to who made it.
- `observations_mission` is rewritten to stand alone, since it replaces the built-in rules: durable, specific statements per company and for the industry; changes recorded with their dates and periods; figures with unit and period; who supplies whom; contradictions kept, not overwritten; never a count of repetitions as corroboration.
- `entity_labels`: one group for the supply-chain layer (the Claim layer taxonomy's values, several per fact allowed, optional, `tag: true`). A second group for the statement kind is left out until the first is measured.
- Mental-model triggers gain `exclude_mental_models: true` and `keep_trace: true`; reflect's own recall is set to return no raw chunks and to include the facts behind observations.

**Observation scopes.**
- Each retain item sends explicit scopes: one for its company, one for each of its themes. Source, document type and form stay as tags for filtering and are no longer consolidation boundaries.
- The health read shows the scopes; the backfill ticket re-consolidates what is stored.

**Recall as a reading index.**
- The gateway's recall takes `max_tokens`, `types`, `prefer_observations`, `query_timestamp` and the include options, and returns scores, entities, chunk IDs and, for observations, the source facts of the same answer. The provenance resolver uses those source facts instead of one request per observation.
- Pointer recalls (the Scout's and the Skeptic's) use a larger `max_tokens` (a setting, default 8,192), `budget` high, `prefer_observations`, and `query_timestamp` equal to the investigation's as-of time. The public recall endpoint keeps today's defaults and accepts the new fields.
- A reading pointer stores the recall's final score and the entity names of its memory (a migration; insert-only as before). Pointed companies are still ranked by reciprocal rank; the score is recorded for the review to judge before any weighting changes.

**Chunk-exact pointers.**
- When a memory's chunk is a verbatim slice of the retained section, the pointer's window is that chunk's span; otherwise the existing best-match window stands. The pointer records which rule placed it.

**The entity hop.**
- After the Scout's recalls, for each company the pointers name (seeds first, within a bound), Atlas lists the theme's facts that carry that company's entity and come from another company's documents, available by the as-of time. Each resolved fact becomes a reading pointer of a new kind (`entity`), which names the company whose document it is. These pointers join the ranking of pointed companies and passage selection under their own share, so they cannot crowd out recall pointers.
- Co-mention stays what it is: a reason to read, never an edge and never Evidence.

**Layer-aware recall.**
- A Scout query that carries a layer is also recalled with the theme's scope and the layer's label tag, once labelled facts exist; both recalls' pointers are kept, each naming its scope.

**Reflect and the mental models.**
- Reflect sends `budget` (a request field, default `mid`) and `exclude_mental_models` when citations must resolve.
- The two models are tagged with their theme, so a refresh reads the theme's memories and a theme-scoped reflect may see them; Atlas reports a citation of a model as such instead of dropping it.
- Each reflect and each refresh Atlas submits adds one unit to the `codex` budget. Atlas's daily job becomes the only scheduler: today the template gives Hindsight its own cron (06:00), half an hour before Atlas's job (06:30), and Atlas's job skips a model refreshed inside its minimum interval, so by the configuration a refresh is done by Hindsight and never counted (to confirm from the refresh records). The template keeps its rule that no model may run away; how Hindsight's cron is kept from firing (a schedule that never comes, or the rule changed to allow no cron when `refresh_after_consolidation` is false) is the ticket's to settle against the recorded schema.

**The owner's server settings.**
- One home-ops PR drafted by the lead, each setting with its effect on the server's other banks: the Qwen3 query instruction as the embeddings query prefix; failing a retain on extraction errors; a reranker chain that ends in rank fusion. Two more are proposed with a measurement and left to the owner: recalibrated similarity thresholds, and a consolidation model of its own.

**Memory works as advertised: the conformance check.**
- The owner's requirement (2026-10-02): Hindsight is used as its documentation describes, and before the system is benchmarked we know the memory under it works as planned. One command reports a pass or a fail per promised behaviour, with the evidence: known answers recalled on the live bank (read-only), and the behaviours this spec builds checked on a throwaway bank retained through Atlas's real path. It is the precondition of a pilot or benchmark run, and the release runs it strict.

**The embedding model.**
- The owner offered a different embedding model (2026-10-02). The choice is measured, not assumed: the current model as served, the same with its query instruction, the model Hindsight's thresholds are calibrated for, and at most two further candidates, each on the known answers and against the five similarity thresholds, with the cost of each change stated (a query prefix re-embeds nothing; a new model re-embeds every bank; another dimension needs an empty store). The owner decides; the backfill runs after the decision.

**The backfill.**
- A backfill-class job per company re-retains the sections whose retain profile is older than the current one (same document ID, so Hindsight replaces the document's memories), re-enqueues failed sections, and then asks for consolidation. It runs under the retain budget on the MiniMax extractor and in the backfill window, newest documents first, resumable.
- Its completion criterion is the health read: every non-skipped section of the pilot's companies completed, zero-fact or failed with a recorded reason, at the current profile.

## Testing Decisions

- Behaviour is tested at the existing seams: the HTTP API (the health read, recall, the investigation read with its pointers), the CLI (`retry-failed`, the backfill job through `atlas jobs enqueue` and `atlas worker --once`), and migrations. No test reaches into the gateway's internals.
- The recorded Hindsight fake is the stand-in. Every new request field and response field it serves comes from a recording made in the first ticket; a derivation the fake needs beyond the recordings is listed in `docs/decisions.md` as its earlier ones are.
- Prior art: the retention tests (`hold_retains`, `report_zero_facts`, `derive_retains`), the pointer tests of memory-directed reading tickets 01 and 05 to 07, the bank-template tests (a template that could run away is invalid), and the budget tests for the `hindsight_minimax` provider.
- A good test here states an outcome a researcher or the owner can see: a section failed alone and was retried; two companies' facts share an observation scope; a pointer carries its score; an investigation read a company it reached by the entity hop; a reflect counted against the budget.
- Live effect is measured, not unit-tested: the probe set and the health read before and after on production, and the feature recordings on a local Hindsight. Live runs keep the two locks of the live suite; the lead runs them.

## Out of Scope

- Any use of a memory's text as Evidence, as a quote or as input to a role.
- Per-company and per-layer mental models, and a reflect-written prior-knowledge brief for the Scout: they wait until the two existing models are grounded and counted (the map's "More of Hindsight").
- Retain strategies per document type and the `verbose` or `verbatim` extraction modes: the first ticket's dry-run comparison says whether they are worth a ticket; none is built here.
- Changing the reranker model or Hindsight's version. (The embedding model is in scope as a measured decision.)
- A dedicated Hindsight for Atlas (parked with the owner).
- New Claim predicates or role prompts.

## Further Notes

- **Order against the pilot.** Investigation 1 is reviewed on 0.3.0 as the before-measure. Investigations 2 to 5 run after this effort's release and backfill (the pilot-review map's focus rule, amended 2026-10-02).
- **Cost.** Recall-side changes cost no LLM call. Explicit observation scopes add consolidation passes on the shared Codex subscription; the first ticket measures how many, and the backfill is paced by the retain budget. The owner's quota is not the lead's to raise.
- **What the study could not see** is listed in `docs/research/hindsight-memory-use.md`, "Not settled"; each item is assigned to a ticket.
