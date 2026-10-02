# How Hindsight works, and what Atlas leaves unused

Studied on 2026-10-02 for pilot-review ticket 19, at the owner's request: how to make the best use of Hindsight's memory. The findings feed the spec `.scratch/atlas-memory-quality/spec.md`.

## Method and what it rests on

- **Sources:** the pinned docs (`.agents/skills/hindsight-docs/references/`, vendored from v0.10.1), `docs/hindsight-feature-matrix.md` and the recordings, Atlas's code, the cluster's Hindsight settings (home-ops `kubernetes/apps/llm/hindsight/app/helmrelease.yaml` at `origin/main`), and one read-only recall on production.
- **Who read what:** the lead read the concept pages (best practices, retain, recall and its scoring, observations, reflect, mental models, the bank configuration). Six Opus readers took the configuration reference (twice: intake, and retrieval and reasoning), the API surface against Atlas's client, reflect and mental models, the changelog with the model and performance guidance, and Atlas's own use of Hindsight. Their notes are in `.scratch/hindsight-study/`.
- **How the readers were checked:** each finding had to carry a verbatim quote from the file it cites. `.scratch/tools/study_audit.py` found all 110 quotes in their files; none was over length or elided. The lead then checked the claims the readers marked unverified against the cluster's settings and production (below).
- **Three levels of certainty** are kept apart in this file: *observed* (on production or in the cluster's manifests), *documented* (the pinned docs say so; not yet exercised against the server), *open* (the docs don't say).
- **Version caveat:** the cluster runs Hindsight **0.10.2**; the vendored docs are 0.10.1 and their changelog ends at 0.10.0. None of the unused features below has a recording. The first ticket of the spec records them on 0.10.2 before anything is built on them.

## The model in one page

- **Retain** chunks an item's content (3,000 characters a chunk by default) and makes one LLM call per chunk. It stores facts (`world`, `experience`), entities and links, never the text as memories. The item's `context`, `timestamp` and `metadata` all go into the extraction prompt; `context` is called one of the highest-leverage inputs. A retain that yields no fact still ends `completed`, and by default so does one where some chunks failed extraction.
- **Entities** are resolved by fuzzy name matching, co-occurrence and closeness in time (the time signal decays to zero at 7 days). There are no entity-to-entity edges: two facts are linked by sharing an entity, by a semantic link made at retain time (cosine at least 0.7), or by an extracted causal link.
- **Observations** are consolidated from facts in the background, on the server's primary LLM. An observation's scope is a tag set. By default (`combined`) it is the item's full tag set, and only observations with exactly that tag set are updated.
- **Recall** runs four arms (semantic, keyword, graph, temporal) per fact type, fuses them by rank (RRF), reranks the top 300 with a cross-encoder and applies small recency (±10%), temporal (±10%) and proof-count (±5%) boosts. `budget` (low/mid/high: 100/300/1,000 candidates per arm) sets how wide it searches; `max_tokens` (4,096 by default) sets how much comes back. It makes no LLM call.
- **Reflect** is an agent loop of at most 10 steps: mental models first, then observations, then raw facts. Its `budget` defaults to `low`.
- **A mental model** is a stored reflect answer, rebuilt only when something in its scope changed. Its tags decide both what it reads and which tag-scoped reflects can see it.

## Findings, ranked

### 1. Three quarters of the retained sections are recorded as failed (observed)

Production, 2026-10-02 07:53 UTC: `atlas_retained_sections_total` is 695 completed, 22 zero-fact, **1,907 failed**, with 59 pending. Memory can only point at what was retained.

What the code shows (reader `atlas-usage`, quotes in its notes):
- A Source Version's sections go to Hindsight as one operation. When it ends with an error that is not a quota or an outage, every pending section of the version is marked failed, without looking at which documents were in fact stored.
- Only quota and outage texts count as transient. A timeout, a relayed 500 or a failure with no message is permanent, and a failed section is never retried without the owner's `retry_failed`.
- Hindsight reports `extraction_errors_count` on the operation; Atlas stores it and never reads it.
- Hindsight's own default leaves a retain `completed` when some chunks failed extraction (`HINDSIGHT_API_FAIL_ON_EXTRACTION_ERRORS`, off on the cluster), so partial loss inside a long Item is invisible.

Open: the error texts behind the 1,907. Nobody has grouped them yet.

### 2. Observations never cross a company, a form or a source (observed)

Atlas tags each item with company, theme, source, document type and form, and sends no `observation_scopes`. On production every observation in the probe recall carries that full tag set, for example `company:…, theme:photonics, doctype:filing, source:sec_edgar, form:8-K`. So AXT's 8-K about its supply agreement with Coherent is never consolidated with AXT's 10-Q, with its call transcripts, or with what Coherent says about the same agreement. The docs offer an explicit list of scopes per item, for example one for the theme and one for the company, and `GET …/observations/scopes` lists what exists.

Open: whether a stored memory can change scope without being retained again.

### 3. Recall is asked for the least it can give (observed in code; effect documented)

Atlas sends the query, `budget` (`mid`) and the tags. Not sent:
- `max_tokens`: the default 4,096 returned 45 memories in the probe, so each pointer recall is capped near that.
- `query_timestamp`: recency is scored against the server's clock, not the investigation's `as_of` (which matters for replays and any as-of run).
- `prefer_observations`: the probe returned the same fact as an observation and as its source fact several times (ranks 5 and 14, 13 and 20), and the same sentence from two quarters' 10-Qs (ranks 24, 31, 37).
- `include.source_facts`: Atlas makes one extra request per recalled observation to find its sources; this returns them in the same answer.
- `include.chunks` and each fact's `chunk_id`: the source text a fact was extracted from, which could place a pointer inside a long section exactly.
- `budget: high` for the few pointer recalls an investigation makes; recall costs no LLM call.

Dropped from the answer: the per-result scores (only the order is kept), the entity names and IDs of every result, and `trace`.

### 4. The graph is fed nothing Atlas knows (documented)

- Atlas passes no `entities` on a retain item, though it knows the filer and has the universe's and the counterparties' names. Resolution is left to fuzzy matching, whose time signal is useless for filings months apart; the recordings show one company split into two entities ("Aurora Optics", "Aurora Optics Inc."). Graph retrieval expands through shared entities, so a split company breaks the hop.
- `entity_labels` are not configured. A label group with `tag: true` has the extractor classify each fact, for example by supply-chain layer, links facts of the same label in the graph, and makes the label a hard filter at recall.
- `GET …/memories/list?entity_id=` lists every fact that names an entity, filterable by tags and by date. That is an exhaustive company-to-company hop that ranked recall cannot give. Atlas never calls it and discards the entity IDs recall returns.

### 5. The context and the missions under-describe the material (observed and documented)

- **Context:** Atlas sends `<title>: <heading or anchor>`. For a transcript that is "Q4 2026: chunk-004" on production: no company, no event, no speaker. Memories from transcripts read "Jordan Klein warned that…" with nothing to tell an analyst's question from the company's statement. The docs say to describe the source and who is speaking.
- **`observations_mission` replaces the built-in rules entirely.** Atlas's is one sentence, so the defaults (durable, specific beliefs; changes tracked with their dates) are gone.
- **`retain_mission`** lists what to extract and nothing to ignore; the docs call the ignore list as important as the include list.
- **One mission and the `concise` mode for everything.** Retain strategies allow a profile per document type (a transcript, a periodic report, an exhibit), and `dry-run-extract` compares them without storing anything.

### 6. Reflect and the mental models run shallow and partly blind (documented)

- Atlas sends no `budget` to reflect, so every reflect runs at `low`.
- Atlas scopes each reflect strictly by tags, and its two mental models carry no tags. By the docs, a strictly tag-scoped reflect sees only models whose tags match, so no Atlas reflect has ever consulted Theme status or Bottlenecks.
- The models may read each other (`exclude_mental_models` is unset), and Atlas drops a citation of a model from `based_on` silently.
- Reflect's own recall includes raw chunks by default, which is content Atlas cannot resolve to a section; the facts behind an observation are not shown to it (`reflect_source_facts_max_tokens`).
- Neither reflect nor a mental-model refresh adds to Atlas's `codex` budget count, and Hindsight's own cron refreshes outside Atlas's queue.

### 7. Server settings that only the owner can change (observed in the manifests)

The server is shared with other consumers, so each of these is the owner's decision.
- **Embeddings:** Qwen3-Embedding-0.6B through the `openai` provider with no query instruction. The manifest's comment says the client cannot add one; the pinned docs have `HINDSIGHT_API_EMBEDDINGS_QUERY_PREFIX` for exactly this, acting on the query side only, so nothing is re-indexed.
- **Similarity thresholds:** five gates (semantic 0.3, graph seed 0.3, temporal 0.1, semantic links 0.7, observation dedup 0.97) are calibrated for another embedding model; the docs say to recalibrate after a change. The link threshold is not retroactive.
- **`HINDSIGHT_API_FAIL_ON_EXTRACTION_ERRORS`** is off (finding 1).
- **The reranker** is a small web-search cross-encoder (ms-marco MiniLM) in a sidecar, with no fail-open: if it fails, recall fails.
- **Consolidation** runs on the Codex primary; metadata routing moves extraction only. A separate consolidation chain exists as a setting.

## What held up, reader by reader

| Reader | Findings | Quotes found | Notes |
|---|---|---|---|
| `config-intake` | 16 | 16 | Found the embeddings query prefix and that the observations mission replaces the defaults. Said plainly that the cluster's settings were unverified; the lead verified them. |
| `config-retrieval` | 18 | 18 | Best account of what `budget` does and of what is server-only. Repeats the similarity-gate finding of `config-intake`. |
| `api-surface` | 19 | 19 | Found the entity lookup and `include.source_facts`. One over-reach: "10 to 14 memories per recall" comes from the synthetic recordings; production returned 45. |
| `reflect-models` | 19 | 19 | Found that the untagged models are invisible to Atlas's reflects and that reflect runs at `low`. Its cost estimate for more models is marked as its own inference. |
| `changelog-models` | 19 | 19 | Found the version mismatch (0.10.2 on the cluster) and the silent partial-extraction default. |
| `atlas-usage` | 19 | 19 | Precise inventory with code quotes; traced the failure paths. Marked the observation-scope reading as inference; the lead confirmed it on production. |

The same three findings (entities on retain, observation scopes, the bare recall request) came back from three or four readers working apart, which is the strongest sign they are real.

## Not settled

- The error texts of the failed sections.
- Whether `reprocess` or a re-consolidation applies new scopes, context, entities and labels to documents already stored, or whether they must be retained again.
- Whether a chunk's text is a verbatim slice of the retained content (needed for chunk-exact pointers).
- What changed between 0.10.1 and 0.10.2.
- How many LLM calls consolidation spends per retained section, and so what explicit scopes cost on the shared Codex subscription.
