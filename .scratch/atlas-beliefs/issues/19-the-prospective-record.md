# 19: The prospective record

Type: build
Status: in-review
Blocked by: none

## What to build

A published Hypothesis's `measurable_predictions` become rows: measure, expected range, deadline, settling source (a Fact, an XBRL observation, or a TradingView price under 16b's rules), each with its state (`open`, `settled`, `lapsed`) and its settlement appended, never rewritten; rejected and lapsed Hypotheses kept and listed. `POST /api/v1/hypotheses/{id}/predictions`, `POST .../predictions/{id}/settle`, the dossier page's predictions section.

## Acceptance criteria

- [ ] API tests and the dossier e2e; one prediction recorded on the photonics Hypothesis (the lead).

## Extended by the lead (2026-10-15): the dated call record

The owner's aim is early calls, and every success so far is a replay of a known winner (the bias the owner named). The forward test needs calls made now and settled later. Beside the Hypothesis predictions above:

- **`call` rows (insert-only):** made when a Belief is judged `proven`, when a published Hypothesis version appears, and when a Scout session escalates an archive signal to a question Issue (`origin`: `belief` | `hypothesis` | `signal`, with its id), each with the call date (the judgement, publication or session time), the theme, the companies (each with its TradingView symbol from the theme config), the claim (the Belief statement, thesis or signal sentence), and a direction where the origin carries one (`constraint`/`demand` steps: `tightening`; `invalidation`/`relief`: `easing`; else none).
- **Settlement (appended, never rewritten):** a daily `settle_calls` job (no LLM; pausable only by the TradingView budget) reads each company's daily closes through the existing price-history route/service (16b/16c rules: through Atlas, capped, never a Belief's evidence) and appends checkpoints at +1, +3 and +6 months (the close, the change from the call date, and the change of a benchmark: the theme's equal-weighted universe, so a call is read relative to its peers); a call with no price source records `unpriced` once. Missing days take the last close.
- **Read side:** `GET /api/v1/calls?theme=&origin=&state=` with checkpoints; the theme page gets a terse "Calls" panel (date, claim, companies, +1m/+3m/+6m relative change; open calls show what is due). Dark, terse, no commands; framed as a record of what Atlas said and what followed, never advice.
- **Backfill:** the Beliefs already proven get their call rows at their judgement time (no back-dating).

## Acceptance criteria (replacing the above)

- [x] API and job tests against the TradingView fake: calls made from each origin, checkpoints appended at their dates (a test clock), relative to the benchmark, `unpriced` once, insert-only enforced; predictions on a published Hypothesis recorded and settled; the theme page's panel (frontend unit test for the pure parts).
- [ ] On production after deploy (the lead): the proven photonics Beliefs have call rows; the first checkpoint lands when due.
