# A session's statements are judged before they become Beliefs; `disputed` needs a contradiction

Type: build
Status: open
Blocked by: none

## Why

The proof sessions (`.scratch/pilot/results.md`, "The proof sessions") read and record better than the pipeline on every measure but one: the trust gate, where 8% and 29% of their statements say more than their cited quotes (a qualifier added, a subject taken from the context, two dates joined). No judge was applied to them. The judge measured the same day catches 11 of 17 such statements on luna against MiniMax's 5 (`docs/experiments.md`, 2026-10-12). And the sessions marked steps `disputed` on counterevidence that only limits, where the pipeline's counter-judge already distinguishes contradicts, limits, dates and qualifies.

## What to build

1. `POST /api/v1/statements/judge` (or a `judge` command of the skill's tool over an existing route): a statement, its cited Facts' quotes and dates, the question; Atlas runs the finding judge (`finding_judge.v4`, the role's model from `ATLAS_LLM_ROLE_MODELS`, luna in production) and answers `supported` or `misstated` with the basis clauses, exactly as the Editor's task does. The session calls it on every statement before writing the card and rewrites a misstated one itself (the session is the writer; Atlas is the check). The bridge's HTTP 500 is classed transient and retried.
2. The skill's rule for a step's status: `disputed` only when a recorded counterevidence Fact contradicts a cited Fact (the counter-judge's `contradicts`, through the same route with the two Facts), else `supported` with the limitation written into the statement; `unknown` when nothing was established.
3. When Beliefs exist (ticket 02), a Belief may be proposed only from statements that passed the judge.

## Done when

- [ ] The route and the skill command, with tests at the API seam (the judge scripted in the fake).
- [ ] Question 2 re-run as a session with the judge: the trust gate at or below the pipeline's rate, recorded in `.scratch/pilot/results.md`.
