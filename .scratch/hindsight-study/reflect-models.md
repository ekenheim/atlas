# Reflect, mental models, knowledge pages, directives, bank templates (Hindsight 0.10.1)

Reader's slice for the Hindsight study. Sources: the pinned docs under
`.agents/skills/hindsight-docs/references/developer/` (reflect.md, api/reflect.md,
mental-models.md, api/mental-models.md, knowledge-pages.md, api/knowledge-pages.md,
api/bank-templates.md, api/memory-banks.md sections on missions, dispositions and directives),
`docs/hindsight-feature-matrix.md`, `spikes/hindsight/recordings/{reflect,mental_models,
knowledge_pages,bank_templates}/`, and Atlas's `configs/hindsight/bank-template.json`,
`backend/atlas/mental_models/refresh.py`, `backend/atlas/research/service.py`, plus the lines of
`backend/atlas/hindsight/{gateway,models}.py`, `backend/atlas/jobs/budget.py`,
`backend/atlas/discovery/service.py`, `backend/atlas/bank_template.py`,
`backend/atlas/retention/service.py` and `docs/decisions.md` needed to check claims. Every quote
below is verbatim from the named file.

## 1. How reflect works, step by step

1. **Scope is resolved first.** `tags`/`tags_match`/`tag_groups` filter raw facts, observations
   *and* mental models the agent may retrieve, and select which tagged directives are injected
   (api/reflect.md, "tags"). A `tag_groups` fuzzy leaf is resolved once before the loop.
2. **Directives and disposition go into the prompt.** Untagged directives always; tagged ones only
   when the request's tags match (or `apply_all_directives: true`). `reflect_mission` is placed in
   the *system* prompt ("Only `reflect` puts its mission in the system prompt", memory-banks.md,
   Previewing Prompts). Disposition traits (skepticism, literalism, empathy, 1-5) are soft.
3. **Agentic loop, up to 10 iterations** (reflect.md: "**Runs up to 10 iterations** to find
   relevant information"). Tools: `search_mental_models` (checked first), `search_observations`,
   `recall` (raw facts, "ground truth", fallback), `expand` (more context for a memory: its chunk
   or document), `done`. reflect.md: "2. **Uses hierarchical retrieval** — Checks mental models
   first, then observations, then raw facts". A fresh model that covers the question can
   short-circuit; a stale one "no longer short-circuits retrieval" (mental-models.md). A stale
   observation is "automatically" verified against current facts.
   - Guardrail: it "**Must gather evidence** before answering".
   - Citations are validated: "only IDs that were actually retrieved can be cited".
   - Observation evidence size: `reflect_search_observations_max_tokens` (default 5000) and
     `reflect_search_observations_include_entities` (default true); per bank via
     `reflect_default_options`, per model via the trigger.
   - Grounding facts behind observations are only returned by `search_observations` when
     `HINDSIGHT_API_REFLECT_SOURCE_FACTS_MAX_TOKENS` is enabled, "off by default"
     (api/knowledge-pages.md); the template schema shows a per-bank
     `reflect_source_facts_max_tokens` ("Max tokens of source facts per reflect call").
   - Feature matrix (observed): "Reflect can answer from raw chunks as well as facts"; chunk
     content carries no memory ID, so it can't be cited/resolved.
4. **budget** (`low` default, `mid`, `high`): "At `low`, the agent does a shallow search optimized
   for speed. At `mid`, it checks multiple sources when the question warrants it. At `high`, it
   performs deep exploration across all knowledge levels and may use multiple query variations to
   find indirect connections." The docs give no numbers (iterations or tokens) per level.
5. **max_tokens** (default 4096) limits only the final answer: "This does not affect how much the
   agent can retrieve during the agentic loop — only the final answer length."
6. **Final synthesis**, then, if `response_schema` is set, a **second pass** extracts the prose
   answer into JSON: "the agent reasons to its answer, then a second pass extracts that answer into
   JSON matching your schema." `structured_output` is a projection of `text`. On failure: 200,
   prose, no `structured_output`, a `structured_output_error`. Feature matrix: union types → 500.
7. **Response**: `text`; `based_on` (only with `include.facts`) = `memories` (world, experience,
   observation: `id, text, type, context, occurred_start, occurred_end`), `mental_models`
   (`id, text, context`), `directives` (`id, name, content`); `usage` (all LLM calls of the loop);
   `trace` (only with `include.tool_calls`). Feature matrix: no `document_id` in `based_on`; in the
   spike every citation was an observation; resolution is two-hop through `source_memory_ids`.
8. **Failure semantics**: any retrieval tool raising → 500 (not an empty answer); empty `done` →
   500; provider error retried once then 500. Context overflow is *not* a failure: it synthesizes
   from what it has. An empty successful retrieval is answered as "nothing on this".

Observed cost (recording `reflect/01-provenance.json`, a tiny synthetic bank, untagged, default
budget): 27.56 s, `input_tokens` 10600, `output_tokens` 1936.

## 2. What a mental model is

- "Mental models are **saved reflect responses** that you curate for your memory bank. When you
  create a mental model, Hindsight runs a reflect operation with your source query and stores the
  result." (api/mental-models.md). Content is always markdown; `max_tokens` 256-8192, default 2048
  (4096 for a knowledge page).
- Reading one is "a database read. No retrieval, no synthesis, no LLM call, no waiting."
- **A refresh costs a full reflect run**: "A refresh is a full reflect run: retrieval plus an
  agentic LLM loop." So: up to 10 agent iterations + final synthesis, + 1 structured-output pass if
  `trigger.response_schema` is set. Dry run costs the same. The refresh operation's
  `result_metadata` reports `based_on_counts` and `outcome`, but (Atlas notes) no token usage;
  Hindsight's per-bank LLM request log (`GET …/llm-requests[/stats]`, feature matrix) has tokens.
  Observed (`mental_models/05-refresh-final.json`): ~24 s, outcome `content_written`, 6
  observations cited, 0 world.
- **Zero-cost refreshes**: staleness gating ("is there a memory in this model's resolved scope
  newer than its last refresh?") skips automatic triggers when nothing in scope changed; and even a
  manual refresh makes no LLM call when nothing is in reach under the model's own scope/window.
  Deletions are invisible to staleness. Unconsolidated memories count as new.
- **Triggers**: `refresh_after_consolidation` (default false per schema) xor `refresh_cron` (UTC,
  5 fields); `min_refresh_interval_seconds` floor for *automatic* triggers only (queued, coalesced,
  not dropped); manual refresh is never rate-limited and releases a parked one. Bank-wide floor:
  `mental_model_min_refresh_interval_seconds`. Refreshes coalesce (one queued at a time).
- **Modes**: `full` (default: regenerate) or `delta` (typed operations on a structured doc;
  untouched sections "copied through **byte-identical**"; delta reads only "memories created since
  the last refresh"; `based_on` accumulates across delta refreshes; falls back to full on no
  content or changed `source_query`; never writes a partial doc; docs suggest periodic clear +
  refresh, e.g. every 48 h, to undo drift).
- **Scope**: `tags` decide what it reads on refresh *and* who sees it in reflect. Refresh default
  for a tagged model is `all_strict` (memory must carry all model tags; untagged excluded);
  override with `trigger.tags_match` or `tag_groups`. `fact_types` restricts to world /
  experience / observation. `exclude_mental_models` / `exclude_mental_model_ids` hide sibling
  models from the refresh. `include_chunks`, `recall_max_tokens`, `recall_chunks_max_tokens` tune
  the refresh's internal recall.
- **Structured output on a model**: `trigger.response_schema` stores a `structured_output` next to
  the markdown each refresh, extracted from the final stored doc; a failed extraction **fails the
  refresh** and keeps the previous content.
- **History**: previous content kept on each change (default 50 entries); failed refreshes append
  failure records (`kind: "refresh_failed"`, `failure_reason`, `previous_content: null`).
  `keep_trace` stores the last refresh's tool calls (counts only), LLM calls, delta ops, usage.
- **Provenance**: `reflect_response.based_on` (GET default detail `full`). In 0.10.1 a model's
  `based_on` is grouped by fact type (`world`, `observation`, `opinion`, `experience`,
  `directives`, `mental-models`) — a different shape from reflect's `based_on.memories`
  (recording `mental_models/03-get.json`; Atlas's `_memories_in_based_on` handles it and drops the
  `directives` and `mental-models` groups).
- **Do recall/reflect use models automatically?** Reflect: yes, `search_mental_models` is its first
  tool, filtered by the request's tags. Recall: reflect.md's example says `recall("Alice")` "Returns
  all Alice facts and relevant mental models"; nothing else in my slice confirms or details that
  (the lead's recall pages should settle it).

## 3. Knowledge pages vs mental models

- "A knowledge page *is* a [mental model](./mental-models). Same synthesis, same background
  refresh, same provenance." Storage: `knowledge_pages` (tree) + `mental_models` (content).
- What they add: a folder tree; defaults pre-chosen (`mode: delta`, `fact_types: ["observation"]`
  — with only observations in scope "the refresh agent isn't given the raw-memory recall tool at
  all" —, `exclude_mental_models: true`, `refresh_after_consolidation: true`), `max_tokens` 4096;
  a `type:<x>` tag (which still filters!); page **search**: "Document-level hybrid search: a
  full-text (BM25) match and a vector-similarity match, fused with Reciprocal Rank Fusion. There
  is no reranking step"; markdown export bundle with a `.log.md` refresh history; `hindsight fs
  mount`.
- Trigger supplied at create is a patch; setting `refresh_cron` clears
  `refresh_after_consolidation`. Bank config `knowledge_page_default_trigger` (template schema)
  merges over the default for every new page — the way to make pages cron-driven bank-wide.
- Pages are **not** in the bank-template manifest (only `bank`, `mental_models`, `directives`);
  they'd need their own API calls (feature matrix: `POST …/knowledge-base/pages` → 201, listed via
  `GET …/knowledge-base/tree`; `GET …/pages` is 405).
- Same tag trap: a tagged page defaults to `all_strict`; tags invented at page creation match
  nothing.
- For Atlas, a page adds nothing a mental model with the same trigger fields can't do, except tree
  organisation and page search. Their default `refresh_after_consolidation: true` collides with
  Atlas's no-runaway-trigger rule; if used, set `knowledge_page_default_trigger` to a cron.

## 4. Directives, missions, dispositions

- Directives "only affect the `reflect` operation" (and so mental-model refreshes, which are
  reflects). "**Untagged directives always apply**, on every `reflect`." Tagged ones apply only
  with matching request tags; an unscoped reflect loads only untagged directives
  ("intentionally asymmetric"). `apply_all_directives: true` forces all. `priority` (higher = more
  important), `is_active`.
- Enforcement wording conflicts: memory-banks.md "Strict — responses are rejected if violated";
  reflect.md just "must be followed exactly". No rejection mechanism is described anywhere in my
  slice: "not documented" how a violation is detected.
- `reflect_mission`: "A first-person narrative that provides identity and framing context for
  `reflect`." Lives in the system prompt. `retain_mission` and `observations_mission` are separate;
  `observations_mission` *replaces* the built-in consolidation rules.
- Disposition: soft; presets: "Research Assistant" 4/3/3, "Legal Analysis" 5/5/2. Defaults 3.
- `POST /banks/{id}/prompts/preview` with `{"operation": "reflect"}` renders the exact reflect
  prompt (mission, disposition, directives) with no LLM call — a cheap way to check the template.

## 5. Bank templates

- Manifest `version: "1"`, sections `bank` (any per-bank config field), `mental_models` (matched
  by `id` on re-import: updated or created), `directives` (matched by `name`). Import creates the
  bank if missing; mental model content is generated asynchronously (import queues refresh
  operations — LLM cost). `?dry_run=true` validates. Export includes only explicit overrides.
- Nothing in the docs says re-import deletes models or directives that a newer template dropped:
  "not documented" (Atlas should assume they remain).
- Schema (recorded `bank_templates/01-schema.json`) also carries bank fields
  `reflect_default_options`, `reflect_source_facts_max_tokens`,
  `mental_model_min_refresh_interval_seconds`, `knowledge_page_default_trigger`.

## 6. Atlas today vs the docs

What is well set:
- Both models: `refresh_after_consolidation: false`, `refresh_cron: "0 6 * * *"`,
  `min_refresh_interval_seconds: 43200` — staleness-gated daily refresh, no runaway. Atlas's
  refresh job checks `is_stale` and the interval before asking, records every decision, resolves
  citations on read. Bottlenecks is read by the Scout as a DB read (no LLM call) — the use the docs
  intend ("the answer is already written").
- `source_query` texts are good reflect questions: they ask for supporting *and* opposing evidence
  and for what is missing, which matches the directives.
- Directives untagged → global → apply to every reflect and refresh, scoped or not. Their content
  (cite, say what's missing, no invented figures, flag origin, no trading orders) is the docs'
  recommended use (compliance/guardrails).
- Skepticism 4 / literalism 4 sits between the docs' Research Assistant and Legal presets.
- Atlas validates structured-output schemas and refuses union types (feature-matrix bug).

What the docs advise differently / gaps:
1. **Atlas's theme-scoped reflect never sees its own mental models.** Atlas scopes reflect with
   `any_strict` (`SCOPE_MATCH: TagMatch = "any_strict"`), and the models carry no tags (decisions
   2026-09-29). api/reflect.md: "| Non-empty `tags`, `any_strict` or `all_strict` | Matching tagged
   data only | Matching tagged models only | …". So `search_mental_models` returns nothing for
   every Atlas reflect. Options: tag both models `theme:photonics` (refresh then reads
   `all_strict` theme-tagged memories — the same material, since every company memory carries its
   theme tag) so a theme-scoped reflect sees them; or keep them hidden deliberately, because a
   reflect answering from a model cites `based_on.mental_models`, which Atlas's resolver can't map
   to a Source Version section (lower traceability). Either way, make it a decision.
2. **Reflect runs at budget `low`.** The gateway sends no `budget` (`body = {"query": query,
   **_scope_fields(scope)}`), so every Atlas reflect is the "shallow search optimized for speed".
   Multi-hop supply-chain questions are what `high` is for ("may use multiple query variations to
   find indirect connections"). Expose `budget` on `ReflectRequest` (default `mid`, `high` for the
   replay question set and investigations). Mental-model refresh budget: no trigger field for it
   is documented — "not documented".
3. **Models can read each other.** No `exclude_mental_models` → Theme status may synthesise from
   Bottlenecks and vice versa; Atlas's resolver drops the `mental-models` group from `based_on`, so
   such a citation is lost silently. The knowledge-page defaults exist to prevent exactly this
   feedback loop. Set `exclude_mental_models: true` on both.
4. **`fact_types` unset and `mode: full`.** For a document-like standing answer the docs' page
   defaults are `delta` + observations only. For Atlas, observation-only refreshes cite
   observations (two-hop resolvable) and are cheaper; `delta` keeps the doc stable but its edits
   read only new memories, so contradictions to old content depend on observation updates — keep
   `full` for Bottlenecks (it must re-judge each constraint) unless cost forces delta. Worth an
   experiment with `dry-run-refresh` (costs a refresh).
5. **No structured output on Bottlenecks.** The Scout gets markdown. A `trigger.response_schema`
   (constraints with `status` confirmed/unconfirmed, `missing_evidence[]`, `layer`, companies;
   explicit `*_known` booleans instead of unions) would let code pass the Scout structured gaps,
   and drive the Theme explorer's gap list. A failed extraction fails the refresh and preserves the
   old content.
6. **`reflect_source_facts_max_tokens` / `HINDSIGHT_API_REFLECT_SOURCE_FACTS_MAX_TOKENS` off.**
   With it on, `search_observations` returns each observation's grounding facts, so reflect and
   refreshes see world facts (single-hop resolvable, with figures and periods) next to the
   consolidated belief. Matches the "Never fabricate figures" directive. Costs context tokens.
7. **Mission style.** Docs ask `reflect_mission` to be a first-person identity narrative ("You are
   …"); Atlas's is imperative. Low impact; `prompts/preview` shows how it lands.
8. **`disposition_empathy` unset (3).** For filings analysis 1-2 ("Detached — focuses on facts and
   logic") fits the docs' Code Review / Legal presets better. Low impact.
9. **Budget accounting.** `reflect` and `refresh_mental_model` are `codex` kinds (held when the
   window is spent) but no unit is recorded for them: the `codex` sweep counts only
   `hindsight_operation` rows (retain/reprocess) and replay operations. And Hindsight's own
   `refresh_cron` runs outside Atlas's queue entirely ("Hindsight's cron isn't pause-aware; that's
   accepted"). Fine with 2 models; not with 20.
10. **Bottlenecks has no as-of.** The Scout reads today's Bottlenecks content for an investigation
    with a past `as_of` (`_gaps()` takes no time). A temporal leak for back-dated investigations
    (replay banks import no models, so replays are unaffected).
11. **History failure records.** `MentalModelRevision` ignores `kind`; a `refresh_failed` entry
    (`previous_content: null`) would read as a revision with empty content. Low.
12. **Observation scope interacts with models.** Observations are scoped to a memory's full tag set
    by default (observations.md), and Atlas tags every memory with `company`, `theme`, `source`,
    `doctype`, `form` (`retention/service.py` `version_tags`), with no `observation_scopes`. So
    observations never merge across companies — or even across a company's 10-K and 8-K. The
    cross-company synthesis a theme model needs happens only inside the model's reflect. (The lead
    owns observations; flagged here because it decides what theme/layer models can read.)

## 7. What else a theme-scoped research bank could hold, and the cost

Budget frame: Atlas's `codex` budget is 40 Hindsight operations per 5 h window (≈ 192 a day).
A refresh is one Hindsight operation but one full reflect loop (≤ 10 agent iterations + final,
+1 if a response schema). Staleness gating makes a refresh over an unchanged scope free, so the
real cost tracks *how often new memory lands in the model's scope*.

- **Per-company models** (12 researched companies): tag `company:<uuid>`; default `all_strict`
  reads exactly that company's memories (every memory carries it). Query: the company's documented
  capacity, customers, suppliers, constraints, guidance, with dates and what is missing. A company
  files ~4-8 times a quarter, so on most days its model is not stale: expected ≈ 1-3 refreshes a
  day across all 12, worst case 12 on a heavy filing day. Stagger `refresh_cron` (e.g. two
  companies per hour) so the worst case never lands in one window (12 of 40 would be 30 % of it).
  Value: an investigation's Investigator could be handed the company model's *structure* (not
  text) or the Editor its gaps; the dossier gets a current summary with citations. Caveat: a
  company-tagged model is invisible to a theme-scoped reflect (tags must match), and visible to a
  company-scoped one.
- **Per-layer models** (7 layers: substrate, epi, chip-laser, dsp, module,
  contract-manufacturing, system): memories carry no layer tag, but a layer model can be scoped
  without new tags via `tag_groups` (or flat `tags` + `trigger.tags_match: "any_strict"`) over its
  companies' `company:` tags. That misses layer statements in other companies' filings (a module
  maker's 10-K on laser supply), so either leave it untagged (whole bank, topic by `source_query`
  only — then stale on every retain) or accept the company approximation. Any layer company filing
  makes it stale: ≈ 2-5 refreshes a day for 7 models. Value: the Bottlenecks question, decomposed
  per layer, gives the Scout per-layer gaps and the Theme explorer per-layer status.
- **Total** with the 2 existing: 21 models; realistic ≈ 5-10 refreshes a day (≈ 3-5 % of daily
  codex capacity), worst case 21 in a day. Prerequisites: count refresh operations against the
  `codex` budget (finding 9), `exclude_mental_models: true` on all, and decide finding 1 (tags).
- **Knowledge pages** instead: same cost; page search could be a document-level index over the
  models; but pages need separate API calls (not in the template) and a cron default via
  `knowledge_page_default_trigger`. No clear gain over mental models for Atlas now.

## Not covered / not settled

- How much each `budget` level changes iterations or tokens: not documented.
- Whether a mental-model refresh's internal reflect uses budget low/mid/high, or any trigger field
  for it: not documented.
- Whether `recall` returns mental models (reflect.md example only); the lead's recall pages.
- How directive violations are "rejected": not documented.
- Whether template re-import removes models/directives absent from the new template: not documented.
- The trace tool names differ between pages (`lookup`, `recall`, `learn`, `expand` in api/reflect.md
  vs `search_mental_models`, `search_observations`, `recall`, `expand`, `done` in reflect.md); not
  observed live (`trace` was null in the recording).
- Not read: configuration.md (server-wide env vars such as `HINDSIGHT_API_REFLECT_SOURCE_FACTS_MAX_TOKENS`
  defaults), monitoring, the MCP and SDK pages, `backend/atlas/mental_models/reads.py`, the
  provenance resolver.
