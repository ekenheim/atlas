# Beliefs, Issues and the session as researcher

Status: ready-for-agent (the lead, 2026-10-12; the owner approved the revision and its page, https://claude.ai/artifact/5WrVWvPLAuXgDEt2xEbmgB, the same day)
Supersedes the draft of the same morning. Execution: the tickets in `issues/` (01 parked for the owner; 05 resolved: the proof); the pilot-review map hands over to this effort's map once charted.

## Where this comes from

- The pilot (`docs/pilot-report.md`; `.scratch/pilot/results.md` to 0.5.6): the evidence substrate holds (every quote verbatim at an archived span), the argument plan beats the default plan, and the MiniMax role pipeline still loses to one strong agent with a search box at a tenth of the tokens.
- The proof sessions (`.scratch/pilot/results.md`, "The proof sessions", 2026-10-12): a Claude session with the `atlas-research` skill records Facts 100% and 93% right against the pipeline's 75% on the same question, holds 19 of the researcher's 32 facts on its card against 8, reaches AXT from Coherent and Lumentum as of 2025-08-31 and states the early signal in substance. Its one weak measure is the trust gate (8% and 29% of statements say more than their quotes) because no judge was applied to its statements.
- The judge measurement (`docs/experiments.md`, 2026-10-12): on the same prompt and 130 labelled statements, MiniMax-M3 catches 5 of 17 misstatements, gpt-5.6-luna 11, gpt-6-astra 14. Luna judges; astra is parked.
- Memory's measured contribution as the reading index is small (known-answer recall 0.08); consolidation over every section makes one-fact observations; feeding it cost most of the quota incidents.
- Trackinizer's model (Apache 2.0) names the missing layer: a Belief is one proposition with an author's judgement, cited with a signed weight, falsified by one load-bearing counter-artifact, superseded without loss, flagged when a cited artifact changes; Issues are work that narrows and requires. The owner runs trackinizer in the cluster and will try a projection personally (ticket 01).
- The owner's direction: the objective first and cost after; prove on the strong model, then measure what can drop to cheaper ones; the Claude subscription runs the research, Atlas keeps the record, the website presents the findings to a reader who wants to understand and consume the thesis.

## Problem Statement

The owner wants to know, for a supply-chain bottleneck, whether to put money on it, and to have made the call early, with the evidence by span and date in front of them. Atlas today answers with a research card per investigation: perishable, written by a weak model, and not the owner's assessment of anything. Nothing persists what Atlas believes about a bottleneck, on what evidence, since when, and what was tried to break it. The sessions that research well have no home for their conclusions except files, and the website still presents the pipeline's cards, Claims and edges, not an assessment.

## Solution

A Claude session is the researcher; Atlas is the substrate, the gatekeeper and the record; the website presents what Atlas believes.

1. **Beliefs.** One falsifiable proposition each, in Atlas's words, with a judgement set only by an author, a confidence, an as-of time, citations of Facts with a signed valence and a weight class (load-bearing or context), supersession, insert-only history, and flags raised by code when a cited Fact's document changes or a load-bearing negative Fact stands. A Belief cites Facts; Facts cite spans; nothing else counts.
2. **Issues.** The open research questions as work: a bottleneck question narrows into its argument steps, a step into what it needs; `requires` orders them; the next action is chosen by rule (the open, unblocked Issue whose Belief would most change the argument).
3. **Research sessions recorded.** A session registers itself (question, theme, seeds, as-of, the model, the actor), records Facts through the existing route, has each statement judged by Atlas before it may become a Belief, proposes Beliefs and Issues through the API, and closes with its usage and its card. The judge runs on the per-role model (luna in production) and a session rewrites a misstated statement itself. A step is `disputed` only on a judged contradiction.
4. **Memory holds what was found.** A judged Belief is retained into the research bank as its own document, replaced when superseded or re-judged; a citation of it resolves to the Belief. Bulk retention of every section is switched off once Beliefs feed Memory; the pipeline stays as the bulk mode.
5. **The website presents the findings.** A theme page leads with its Beliefs by step and judgement, each opening to its evidence; a company page with the Beliefs it concerns; a Belief page with the statement, judgement and confidence, every citation's quote and span (opening the source viewer at the span), the history, the flags and what supersedes it; an Issues page as the research frontier; a sessions list with each session's card and what it recorded. Dark, terse, no commands; the assessment first, records one click deeper.

## User Stories

1. As the owner, I want to open a theme and see what Atlas believes about each step of each bottleneck argument, with the judgement and confidence, so that I read an assessment, not a pile of records.
2. As the owner, I want every Belief to open to the quotes behind it, each at its archived span with its date, so that I can check the evidence myself before I bet.
3. As the owner, I want to see when a judgement was formed and with what evidence available then, so that I can tell an early call from hindsight.
4. As the owner, I want a Belief flagged, never silently changed, when a filing it rests on gets a new version that no longer contains the quote, so that I know what to revisit.
5. As the owner, I want a Belief flagged when a load-bearing Fact against it stands, so that counterevidence is visible on the page and not buried in a run.
6. As the owner, I want to see what was tried to break a Belief and what remains unchecked, so that a story resting on one untested step shows it.
7. As the owner, I want the open Issues of a theme in one list, ordered by what would most change the argument, so that I know what the next session should do.
8. As the owner, I want to see each research session (its question, as-of, seeds, model, cost, card, Facts and Beliefs), so that I can judge the research and its price.
9. As the owner, I want to set or change a Belief's judgement and confidence myself, with my reason recorded, so that the verdict stays mine.
10. As the owner, I want a company page that shows the Beliefs the company figures in and its exposure to each bottleneck, so that a company's case reads as an argument, not as a list of edges.
11. As the owner, I want the pages to stay dark, terse and free of commands, so that they read as a product.
12. As the lead's agent, I want to register a session and record Facts with the tool I already have, so that the proof's workflow carries over unchanged.
13. As the lead's agent, I want Atlas to judge each of my statements against its quotes before I write the card, so that my card holds only statements that survive the check.
14. As the lead's agent, I want to propose a Belief citing Facts with a weight and a valence, and to have Atlas refuse one that cites nothing load-bearing, so that a Belief never rests on air.
15. As the lead's agent, I want to open, narrow and complete Issues as I work, so that the next session starts from the frontier and not from the question.
16. As the lead's agent, I want the next Issue chosen by rule, so that I do not need a planner to decide where to read.
17. As the lead's agent, I want recall to return only memories resolved to sections available by my as-of time, so that a replay cannot leak the future.
18. As the lead's agent, I want a judged Belief to be in Memory for my next session's recall, with its Facts, so that conclusions accumulate across sessions and themes.
19. As the lead, I want a session's trust-gate rate measured the same way as a card's, so that the method is held to the pilot's bar.
20. As the lead, I want the pipeline's argument plan to keep working as the bulk mode and to propose Beliefs from its statements too, so that nothing built is thrown away before it is replaced.
21. As the lead, I want bulk retention switched off by a setting once Beliefs feed Memory, reversibly, so that the quota goes to research.
22. As the lead, I want a Belief's memory replaced when it is superseded or re-judged, and recorded as replaced, so that Memory never holds two versions of one conclusion.
23. As a reader given the link, I want a Belief page to make sense on its own: the proposition, the verdict, the evidence, the date, the doubts; so that I can consume the thesis without the workbench.
24. As the lead, I want every write to Beliefs, Issues and sessions audited, so that the record is as trustworthy as the ledger.
25. As the lead, I want the glossary and an ADR to record Belief, Issue and Research Session, so that agents use one vocabulary.

## Implementation Decisions

**Vocabulary (into `CONTEXT.md`).** *Belief*: one falsifiable proposition about a Bottleneck or a company's Exposure, stated in Atlas's words, with an author's judgement; it cites Facts (and Assertions) and nothing else. *Issue*: a research question still to answer, scheduled work that narrows into finer Issues and requires others before it. *Research Session*: one run of a researcher (a Claude session, or the pipeline's argument plan) on a question as of a time, recorded with what it searched, recorded, proposed and spent. Avoid: finding, conclusion, claim (for Belief); task, question (for Issue); investigation (for a session; an investigation is the pipeline's run, a kind of session).

**Beliefs.** A `belief` row: statement, theme, step (`constraint`, `demand_vs_supply`, `relief`, `control`, `capture`, `invalidation`), companies (many), `as_of`, `produced_by` (session), `status` (`active`, `superseded`, `withdrawn`). `belief_judgement`, insert-only: judgement (`proven`, `disproven`, `unproven`, `undecidable`), confidence [0, 1], actor, reason, at; the current judgement is the latest row; a Belief is born `unproven` by its proposer. `belief_citation`: Fact or Assertion, valence [-1, 1], weight (`load_bearing`, `context`), note, actor. `belief_supersession`: many-to-many, with the actor and reason; a superseded Belief keeps its citations and its history. `belief_flag`, insert-only: kind (`counterevidence_stands`, `source_revised`, `assertion_reviewed`, `fact_superseded`), the ref, raised at, cleared by which judgement; raised by code, cleared by an author's judgement. Rules: a proposal must carry at least one load-bearing citation with positive valence; judgement is set only by `POST /beliefs/{id}/judge` (actor required; roles and jobs never call it); the valence is recorded, not computed; the counter-judge's relations map to default valences (`contradicts` -1, `limits` -0.5, `dates` -0.5, `qualifies` -0.25, `supports` +0.5); a load-bearing citation with valence <= -0.75 whose Fact stands raises `counterevidence_stands`. Every write audited.

**Issues.** An `issue` row: title, body, theme, kind (`question`, `step`, `read`), priority, status (`active`, `complete`, `abandoned`, `invalid`), `produced_by` (session), companies. `issue_edge`: `narrows` and `requires`, acyclic, child to parent. `issue_product`: the Beliefs and Facts an Issue produced. The next action: among active Issues with no active `requires` prerequisite, the one whose step Belief is `unknown` (no Belief) and load-bearing to the argument, then one flagged or disputed, then by priority, then oldest. A session's card's open questions, unknown steps and unread companies become Issues under the session's root Issue (the question).

**Research sessions.** A `research_session` row: question, theme, seeds, `as_of`, kind (`claude`, `pipeline`), model, actor, started, finished, usage (calls, tokens, records, refusals), the card (JSON as the argument plan's card: steps, statements with their Facts and counterevidence, question parts, open questions) and its markdown. `POST /sessions` opens one; `POST /sessions/{id}/close` sets the card and usage. A Fact recorded with a `session_id` belongs to it (the Facts route gains the optional field; `investigation_id` stays for the pipeline). The pipeline's investigation becomes a session of kind `pipeline` at its Editor's end, so both appear in one list.

**The statement judge.** `POST /statements/judge`: the question, a statement, its cited Facts by ID (Atlas supplies their quotes, dates, status, period), optional counterevidence Facts; Atlas runs the finding judge exactly as the Editor's task does (the role's prompt, the per-role model, the basis check in code), one vote by default, and answers `supported` or `misstated` with the bases and the reason; the call is recorded as a role call under the session's run. The session rewrites and asks again; a session's card accepts only judged statements, and `POST /beliefs` refuses a Belief whose `statement_judgement` is not `supported` when the session is of kind `claude`. The bridge's HTTP 500 ("Unknown items in responses API response") is classed transient and retried. `POST /statements/relate`: two Facts, the counter-judge's relation (`contradicts`, `limits`, `dates`, `qualifies`, `supports`, `unrelated`); the session uses it to set a step `disputed` only on `contradicts`.

**Memory.** A judged Belief (any judgement but `unproven`) is retained by a `retain_belief` job (pausable, the research bank, extractor as configured) as its own document `belief:<id>` with observation scopes per theme tag, tags `belief`, `judgement:<value>`, `step:<value>` and the companies' entity names, carrying the statement, the as-of, the judgement and confidence, the load-bearing Facts' statements and quotes, and the session; a re-judgement or supersession deletes the document and retains again (`memory_replacement` recorded). The provenance resolver labels a memory from a `belief:` document `belief`, resolved to the Belief, never to a section. `GET /memory/health` counts Beliefs in Memory. `ATLAS_BULK_RETENTION` (default `on`) switches the ingest's section retains, triage and the daily consolidation try off together (the existing budgets of 0 are the mechanism; health reports `bulk_retention: off`); the owner switches it after Beliefs feed Memory.

**Recall as a tool.** `POST /memory/recall` gains `available_by` (ISO): the answer drops memories none of whose resolved sections (or Beliefs) were available by that time, and reports `dropped_future`; the skill's tool uses it instead of its own filter.

**The skill.** `atlas_tools.py` gains `session open|close`, `judge`, `relate`, `belief propose|cite|supersede`, `issue open|narrow|complete|next`; `SKILL.md` gains the rule for `disputed`, the judge loop before the card, and the Issue frontier as the session's start. The pipeline's Editor task proposes Beliefs from its judged step statements and opens Issues from its open questions, so both kinds of session feed the same record.

**The website.** Pages (Next.js static export, as the rest): `app/beliefs/` the theme's Beliefs by step and judgement with filters in the URL; `app/belief/?id=` the Belief (statement, judgement, confidence, as-of; citations with company, date, quote and a link to the source viewer at the span; counterevidence; flags; history; supersession; the session); `app/issues/` the frontier with the next action first; `app/sessions/` and `app/session/?id=` the sessions and one session's card, Facts, Beliefs and usage; the theme page (`app/theme/`) leads with the Beliefs (the map and edges below), the company page (`app/company/`) with the company's Beliefs and Exposure first. Pure parts in `lib/beliefs.ts`, `lib/issues.ts`, `lib/sessions.ts` (grouping, ordering, labels); components shared in `components/beliefs.tsx`. The API client regenerated. Dark, terse, no commands, the assessment first (the owner's standing rules).

**Reads.** `GET /beliefs?theme=&step=&company_id=&judgement=&status=&flagged=&as_of=` (as_of: the judgement current at that time), `GET /beliefs/{id}`, `GET /issues?theme=&status=`, `GET /issues/next?theme=`, `GET /sessions?theme=`, `GET /sessions/{id}`; `GET /themes/{id}/map` and `GET /companies/{id}/dossier` gain `beliefs`. Research Snapshots carry the Beliefs a published version rests on; the publish gate requires every load-bearing Belief of a version to be `proven` or the owner's explicit override, recorded.

**Migrations.** One chained at integration; the triggers of proposed updates gain Belief dependents (a revised source, a reviewed Assertion, a superseded Fact flag the Beliefs citing them).

## Testing Decisions

A good test exercises a public seam and asserts the behaviour the stories name, never the tables or the functions behind it; expected values come from the spec and fixtures, never recomputed the way the code does. Real Postgres, never SQLite; the LiteLLM and Hindsight fakes at the transport.

Seams, all existing:

1. **The HTTP API** (FastAPI TestClient, `tests/integration/`): sessions, Facts with a session, the statement judge (the judge scripted in the LiteLLM fake; the basis check observed through the answer), Beliefs (propose, cite, judge, supersede, flags raised by the proposed-updates triggers, the refusals), Issues (narrow, require, next), the reads, the dossier and map additions, recall's `available_by`. Prior art: `test_facts.py`, `test_investigations*.py`, `test_proposed_updates.py`, `test_memory_recall.py`.
2. **The worker single pass** (`atlas worker --once` through the harness): `retain_belief` against the Hindsight fake (the document, its tags and scopes, the replacement on re-judgement), bulk retention off. Prior art: the retention and backfill tests, `test_queue_pause.py` for the pausable kind.
3. **The frontend**: unit tests of the pure modules in `frontend/unit/` (prior art: `company-findings.test.ts`), and the Playwright e2e of the new pages and the theme and company pages seeded through `scripts/e2e.py` (prior art: `theme-explorer.spec.ts`, `hypothesis-dossier.spec.ts`).
4. **The skill's tool**: a unit test of its pure parts (the quote fold and locate, the as-of filter) in `tests/unit/`; its live commands are exercised by the proof sessions, not by CI.

The measure that closes the effort: question 2 re-run as a session with the judge loop, scored by the pilot's procedure, at or above the proof's precision and with the trust gate at or below the pipeline's rate; the Beliefs visible on the theme page.

## Out of Scope

- Automated judgement of Beliefs; a planner beyond the next-action rule; portfolio sizing; price data; return measurement.
- Replacing Hindsight; a fork of trackinizer (the owner's projection is ticket 01, parked for them).
- Retiring the default investigation plan and the pipeline's edge review (separate; the pipeline is kept as the bulk mode).
- Scheduling sessions in the cluster or as cloud routines (after the judge loop and the pages exist).
- A second theme (preparation only; the memory format freezes on photonics first).

## Further Notes

- The frozen pilot procedure and the verdict criteria (pilot-review ticket 02) stay the yardstick for sessions; the bar's revision proposal is withdrawn as moot once faithfulness and on-question share are both reported.
- Trackinizer's `proves`/`favors` with a signed valence, "the system never forms the verdict" and lossless supersession are adopted as rules; its software is not.
- The owner's constraints hold: nothing depends on the 5090 being on; the pages never show CLI commands; Memory is derived, never Evidence.
- Keys: the `atlas-eval` LiteLLM key is the lead's (home-ops-upgrade #7479, #7481); production's `atlas` key needs `chatgpt` for the judge (a home-ops change the owner merges).
