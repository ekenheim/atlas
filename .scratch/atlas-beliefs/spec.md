# Beliefs, research work and the agent as researcher

Status: draft (the lead, 2026-10-12; the owner agreed with the direction in the review session of the same day)
Map: `.scratch/atlas-pilot-review/map.md` carries execution until this effort has its own; pilot-review tickets 25 and 26 run first.

## Where this comes from

- The pilot (`docs/pilot-report.md`; `.scratch/pilot/results.md`, 0.5.3 to 0.5.6): the evidence substrate holds (364 of 364 quotes verbatim; faithfulness 88–95% on 0.5.6), the argument plan beats the default plan, and the pipeline still loses to one strong agent with web search and the archive's term search at a tenth of the tokens (the researcher's hour: 144 facts against 16 on the cards, 72 in Facts).
- Memory's measured contribution is small (known-answer recall 0.08 at 10; the Reader's term search overtook the pointers; consolidation makes one-fact observations, almost none across companies), while feeding it has cost most of the quota incidents.
- Each investigation starts from nothing. Its step conclusions (supported, disputed, unknown) live inside one card and die with it. Nothing persists what Atlas believes about a bottleneck, what was checked and what refuted it, across investigations and sessions.
- Trackinizer (`github.com/rekursiv-ai/trackinizer`, Apache 2.0) names the missing layer: a Belief is one atomic proposition with an author's judgement and confidence, cited by Artifacts through `proves` edges with a signed valence, falsified by a single load-bearing counter-artifact, superseded without loss, and flagged (never flipped) when a cited artifact changes; Issues are schedulable work that narrows and requires. Its rule "the system never forms the verdict" is Atlas's rule that the bet is the owner's.

## Problem Statement

The owner wants to know, for a supply-chain bottleneck, whether to put money on it, and to have made that call early. Atlas today produces a card per investigation: a defensible but perishable argument. A researcher (or the next investigation) cannot ask Atlas "what do we believe about InP substrate supply, on what evidence, since when, and what has been tried to break it?" The answer exists only scattered across cards, Facts and Memory's observations.

## Solution

Four changes, each independently useful, in this order.

### 1. A Belief layer between Facts and Hypotheses

A **Belief** is one falsifiable proposition about a bottleneck or a company's exposure to it, stated in Atlas's own words, with:

- `statement` (one proposition; a Belief that turns out half right is superseded by finer ones, never edited in place), `theme`, the `step` of the argument it belongs to (`constraint`, `demand_vs_supply`, `relief`, `control`, `capture`, `invalidation`) and the companies it concerns;
- `judgement`: `proven`, `disproven`, `unproven`, `undecidable`, set only by an author (the lead's agent or the owner; a role may propose, code never sets it); `confidence` in [0, 1], the author's;
- `as_of`: the time the judgement was formed with the evidence available then;
- citations: Facts (and Assertions) that bear on it, each with a signed `valence` in [-1, 1] and a `weight` class, `load_bearing` or `context` (trackinizer's `proves` / `favors`); a load-bearing negative citation whose Fact stands makes the Belief `flagged` until the author's next pass (the system flags, the author sets);
- `superseded_by` (many-to-many; a superseded Belief is terminal and keeps its citations), `produced_by` (the investigation, run or session that formed it), insert-only history (every judgement change is a new row in `belief_judgement`, audited).

Rules:

- A Belief cites Facts; Facts cite spans. A Belief never cites Memory, another Belief alone, or a role's answer. Every evidence chain ends at an archived span (`CONTEXT.md`, Evidence).
- A Fact whose Source Version gets a new version that no longer contains the quote, or whose Assertion is reviewed disputed or superseded, flags every Belief citing it (`belief_dependency_changed`; the proposed-updates trigger path, extended), never flips it.
- A Hypothesis version's steps are Beliefs. The argument card's `steps` become the per-investigation view of the Beliefs that round touched: each step shows the Beliefs it supports, disputes or leaves unknown. Free-text step statements stay as the Editor's prose over the Beliefs, grounded as today.
- Read side: `GET /api/v1/beliefs?theme=&step=&company_id=&judgement=&as_of=` and `GET /api/v1/beliefs/{id}` (its citations with their Facts and spans, history, supersession, what flagged it); the Theme explorer and the Company dossier lead with the Beliefs (the owner wants the assessment first, records one click deeper).

### 2. Research work as Issues

An **Issue** is a research question Atlas or the owner still has to answer, with `narrows` (a bottleneck question narrows into its six steps, a step into the facts it needs) and `requires` (do-time order), a `priority`, a status (`active`, `complete`, `abandoned`, `invalid`), and the Beliefs and Facts it produced (`produces`). The card's open questions, `not_read` companies and `unknown` steps become Issues instead of text, so the next investigation or session starts from the open frontier, not from the question again.

The next action is chosen by rule, not by a planner: the open, unblocked Issue whose Belief, if settled, would most change the argument (an `unknown` load-bearing step first, then a `disputed` one, then `context`). `GET /api/v1/issues/next?theme=`.

### 3. The agent as researcher; Memory as a tool and as the store of conclusions

The pipeline's roles stay as the cheap bulk mode (MiniMax reading the archive step by step). The researcher that forms Beliefs is a strong agent with tools, the owner's idea of 2026-10-07: a Claude Code skill (`atlas-research`) whose tools are Atlas's API: `archive-search` (as-of), `facts` (record a Fact at a span; refused as today when the quote or status is wrong), `recall` (Memory, scoped, as-of), `beliefs` (propose, cite, supersede; the judgement is the author's), `issues` (open, narrow, complete), and web search outside Atlas (a web fact becomes a Tier C lead or a manual import, never a Fact, unless the fetch gate allows the site). The skill holds the method (the six steps, the bottleneck test, what counts as evidence) and the gates hold the discipline.

Memory's two seats:

- **A tool the agent calls** when a cross-document question is worth asking; a weak answer is ignored. No pointer machinery decides what the agent reads.
- **The store of settled conclusions.** A Belief whose judgement is set is retained into the research bank as a derived memory in its own document (`belief:<id>`, tagged `theme:<slug>`, `belief`, `judgement:<value>`), with its statement, as-of, judgement and the IDs of its load-bearing Facts, so the next session's recall returns what Atlas believes and why, and the agent reads the Beliefs API for the detail. A superseded or re-judged Belief's memory is replaced (`DELETE .../documents/{id}`, then retain), recorded as a `memory_replacement`. A citation of such a memory resolves to the Belief, never to a section, and is labelled `belief`, never `resolved`.

Open: whether to keep consolidation for the research bank once Beliefs are the conclusions; measured after 1 and 3 ship (the mental models may become reflects over Beliefs).

### 4. The graph view: trackinizer as a projection

The owner likes trackinizer's UI and connecting graphs. Atlas stays the system of record (Postgres, the audit chain, Hypotheses, snapshots). Trackinizer is tried first **unmodified, as a projection**: a sync writes Atlas's Facts (as Artifacts with the source viewer's span URL), Beliefs (as Beliefs with the same judgement), citations (as `proves` / `favors` edges with the valence) and Issues (as Issues with `narrows` / `requires`) through its batch API with Atlas's IDs as idempotency keys, one way. The owner looks at the graph, the Belief pages and the console with a real investigation's data and judges whether it earns a place as the stakeholder view or the agent's workspace. A fork follows only if its UI needs changes Atlas cannot make through the API; its AI policy forbids autonomous agents contributing upstream, so any upstream change is the owner's by hand.

## User Stories

- As the owner, I open a theme and see what Atlas believes about each bottleneck step, with the judgement, its load-bearing Facts and what has tried to break it, and when the judgement was formed.
- As the owner, when a filing changes a cited quote, I see the Beliefs flagged, not silently changed.
- As the lead's agent, I start a session from the open Issues of a theme, record Facts and propose Beliefs with tools, and the next session recalls the conclusions.
- As a stakeholder, I see the graph of questions, evidence and beliefs for one bottleneck.

## Implementation Decisions

- Tables: `belief`, `belief_judgement` (insert-only), `belief_citation` (Fact or Assertion, valence, weight), `belief_supersession`, `issue`, `issue_edge` (`narrows`, `requires`), `issue_product` (what an Issue produced). Audited like the rest. One migration chained at integration.
- Judgement is set only through `POST /api/v1/beliefs/{id}/judge` by an author (actor recorded); roles and jobs may `propose` (an unproven Belief with citations) only.
- The valence is recorded, not computed: the counter-judge's relations (`contradicts`, `limits`, `dates`, `qualifies`, `supports`) map to default valences (−1, −0.5, −0.5, −0.25, +0.5); the author may change it.
- The existing proposed-updates triggers gain Belief dependents; the cascade flags.
- The argument plan's Editor task proposes Beliefs from its steps (one per step statement that cites load-bearing Facts) in the same transaction as the card; nothing is judged automatically.
- The skill is a repo skill (`.claude/skills/atlas-research/`), its tools thin wrappers over the public API with the production base URL; it writes nothing the API would refuse.
- Trackinizer runs as its own service (the published package, Postgres), in Compose locally and, if kept, in home-ops behind Authentik like Atlas; Atlas never reads from it.

## Out of Scope

- Automated judgement of Beliefs; portfolio sizing; price data.
- Replacing Hindsight (its role is narrowed and measured, not removed).
- A fork of trackinizer before the projection has been judged.
- The default investigation plan's retirement (pilot priority 7; separate).

## Tickets

Numbered from 01 in `issues/`. 01 (the trackinizer projection) needs no Atlas change and can run now; 02–06 follow pilot-review tickets 25 and 26.
