# A session's statements are judged before they become Beliefs; `disputed` needs a contradiction

Type: build
Status: ready-for-agent
Blocked by: none

## Why

The proof sessions (`.scratch/pilot/results.md`, "The proof sessions") read and record better than the pipeline on every measure but one: the trust gate, where 8% and 29% of their statements say more than their cited quotes (a qualifier added, a subject taken from the context, two dates joined). No judge was applied to them. The judge measured the same day catches 11 of 17 such statements on luna against MiniMax's 5 (`docs/experiments.md`, 2026-10-12). And the sessions marked steps `disputed` on counterevidence that only limits, where the pipeline's counter-judge already distinguishes contradicts, limits, dates and qualifies.

## What to build

1. `POST /api/v1/statements/judge`: the question, a statement, its cited Facts by ID (Atlas supplies their quotes, dates, status and period), optional counterevidence Fact IDs; Atlas runs the finding judge exactly as the Editor's task does (the role's prompt, the per-role model from `ATLAS_LLM_ROLE_MODELS`, the basis check in code), one vote by default (`votes` optional), and answers `supported` or `misstated` with the bases and the reason; recorded as a role call in a run of the caller's choosing (a `run_id` in the request, else a run per call). `POST /api/v1/statements/relate`: two Facts (a Fact and a counterevidence Fact), the counter-judge's relation (`contradicts`, `limits`, `dates`, `qualifies`, `supports`, `unrelated`). The bridge's HTTP 500 "Unknown items in responses API response" is classed transient so the caller retries it. The skill's tool gains `judge` and `relate`; SKILL.md: every statement is judged before the card and a misstated one rewritten by the session; a step is `disputed` only on a judged `contradicts`.
2. Tests at the API seam with the judge and counter-judge scripted in the LiteLLM fake (supported, misstated with bases, the basis check turning an answer, the transient 500 retried, `relate` for each relation).
3. (Ticket 02 then refuses a Belief from a `claude` session whose statement was not judged `supported`.)

## Done when

- [ ] The route and the skill command, with tests at the API seam (the judge scripted in the fake).
- [ ] Question 2 re-run as a session with the judge: the trust gate at or below the pipeline's rate, recorded in `.scratch/pilot/results.md`.
