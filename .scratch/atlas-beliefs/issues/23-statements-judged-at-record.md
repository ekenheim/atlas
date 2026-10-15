# 23: A Fact's statement, the thesis and a Belief judged at record

Type: build
Status: in-review
Blocked by: none

## Why

The MCP session (2026-10-15, `.scratch/pilot/results.md`, "The MCP session") kept the trust gate at 4% but left Fact precision at 92%: three Facts whose statements carried a clause from the context, the kind the skill's rule (ticket 11) names. Six of eleven Beliefs were compound, and the thesis sentence, never judged, misstated a tense. Rules in the prompt reduce these errors; the judge stops them where it is applied.

## What to build

- **A Fact's statement judged at record.** `POST /api/v1/facts` (and the MCP `record_fact`) with a `session_id` runs the finding judge on the statement against its own quote, the source title and date (`atlas.investigations.meaning`; one call, the configured judge model; `ATLAS_FACT_STATEMENT_JUDGE`, default on for sessions, off for the pipeline's Readers unless set). `misstated`: the Fact is refused (`statement_beyond_quote`, with the judge's `beyond` and `kinds`) so the agent rewrites the statement or takes a longer quote; `supported`: recorded, the verdict stored on the Fact. A judge failure records the Fact unjudged (marked), never blocks.
- **The thesis judged.** `close_session` (and `POST /sessions/{id}/close`) judges the card's thesis against the Facts its statements cite; the verdict on the session's card; a `misstated` thesis is flagged on the card, not refused.
- **A Belief judged at proposal.** `POST /api/v1/beliefs` (and `propose_belief`) from a session judges the statement against its load-bearing positive citations' quotes, with atomicity in the judge's brief (one claim, one period, one actor); `misstated` or `compound` refuses it with the reason; the `joins_dated_documents` warning stays.
- Skill: SKILL.md says the server judges these, so the agent judges its own card statements as before and reacts to refusals.

## Acceptance criteria

- [x] HTTP-seam tests with the scripted judge: a Fact refused for a statement beyond its quote, one recorded with its verdict, a judge outage recording it unjudged; the thesis verdict on a closed session's card; a compound Belief refused, an atomic one accepted; the pipeline's Readers unaffected by default.
- [ ] The three wrong Facts and six compound Beliefs of session `19c130c7` replayed through the judge offline (a script over `review/`): how many each check catches (the lead).
