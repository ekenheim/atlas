# 26: Research that compounds: a question's state at session start, Facts reused, Beliefs examined by delta

Type: build
Status: in-review
Blocked by: none

## Why

The owner asked (2026-10-15) whether session-based LLMs make Atlas restart its questions. They do: the MCP session on question 2 (`19c130c7`, 15 October) took 35 of its 38 Facts from documents the closing session (`8e4dbf23`, 12 October) had already cited, and 15 overlap a span already recorded. A session sees proven Beliefs (recall of the conclusions bank) and the Issue frontier, but no tool lists the Facts already recorded for its companies and steps, the Beliefs of any judgement, or the documents already read and when. The objective (catch a bottleneck early, keep the thesis on the shelf, notice confirmation; the AXT case took three months to price) needs research that compounds: each new document weighed against what Atlas already holds.

## What to build

- **`prior_work`, an MCP tool and route** (`GET /api/v1/research/prior-work?theme=&company_ids=&steps=&question=` bounded by the session's as-of): the existing Facts for the companies and steps (statement, status, period, document title and date, Fact id; a cap, newest first, with counts beyond it), the Beliefs of any judgement that name those companies or steps (statement, judgement and who, last examined), the documents already read in earlier sessions with their dates and the sessions' as-of times, and the open Issues touching them. SKILL.md: a session calls it right after `open_session` and spends its calls on documents after the latest earlier session's as-of and on the gaps the earlier sessions named; it cites an existing Fact rather than recording the same span again.
- **Facts reused:** `POST /facts` (and `record_fact`) for a span that overlaps an existing Fact's span in the same Source Version with the same step returns the existing Fact (`reused: true`, no new row, the call recorded on the session) unless the statement differs materially (then a new Fact citing the same span is allowed, flagged `same_span_as`).
- **Beliefs examined by delta:** a Belief records `last_examined_at` and `last_examined_as_of` (set by a Skeptic or Researcher session that tests it: `examine_belief` MCP tool / route with the session id and the outcome `confirmed | qualified | contradicted | nothing_new`); `list_beliefs` sorts by staleness; the Skeptic routine takes the stalest proven Belief and reads only documents after its `last_examined_as_of`.
- **Confirmation notices:** a session that records a Fact related `supports` (the counter-judge) to a proven Belief's load-bearing Fact from a document newer than the Belief's as-of raises a `belief_confirmed` notice beside the existing flags (shown on the Beliefs page and the theme page; never changes the judgement).
- Docs: decisions entry, AGENTS.md bullet, SKILL.md, scout/skeptic/researcher routine prompts and the prompt-tools test.

## Acceptance criteria

- [x] HTTP-seam tests: `prior_work` lists Facts, Beliefs, documents read and Issues within the as-of bound; a same-span record returns the existing Fact; `examine_belief` sets the staleness fields and `list_beliefs` orders by them; a supporting Fact from a newer document raises `belief_confirmed`.
- [ ] Question 2 once more as a session after deploy (the lead): at most 10 of its Facts from documents the earlier sessions cited, unless they cover a named gap; the gaps (germanium, the U.S. InP permits) attempted. Measure the re-recording as new Facts from documents earlier sessions cited plus `facts_reused` (a reused Fact keeps the earlier session's `session_id` and is not in the session's `facts`).
