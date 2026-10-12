# 02: Beliefs: propose, cite, judge, supersede, flag; the Belief page and the theme's Beliefs

Type: build
Status: done
Blocked by: 08

## Parent

`../spec.md` (Implementation Decisions, "Beliefs", "Reads", "The website"; User Stories 1 to 6, 9, 14, 22 to 25).

## What to build

Tables `belief`, `belief_judgement` (insert-only), `belief_citation` (Fact or Assertion, valence, weight, note, actor), `belief_supersession`, `belief_flag` (insert-only, cleared by a judgement), `belief_company`; every write audited. Routes: `POST /api/v1/beliefs` (propose: statement, theme, step, companies, as_of, session_id, citations; refused without a load-bearing positive citation; born `unproven`), `POST .../{id}/cite`, `POST .../{id}/judge` (actor, judgement, confidence, reason; clears open flags), `POST .../{id}/supersede` (by one or more Beliefs, reason), `GET /api/v1/beliefs?theme=&step=&company_id=&judgement=&status=&flagged=&as_of=`, `GET /api/v1/beliefs/{id}` (citations with their Facts' quotes, spans and dates; counterevidence; flags; history; supersession; session). Flags raised by code through the proposed-updates trigger path: a cited Fact's Source Version revised without the quote, its Assertion reviewed disputed or superseded, and `counterevidence_stands` when a load-bearing citation with valence at or below -0.75 stands. Glossary entries **Belief**, **Issue**, **Research Session** in `CONTEXT.md` and an ADR recording the revision of the method. Pages: `app/beliefs/` (the theme's Beliefs by step and judgement, filters in the URL) and `app/belief/?id=` (statement, judgement and confidence with who set it and when, as-of, citations by company and date with the quote and a link to the source viewer at the span, counterevidence, flags, history, what supersedes it, the session); `lib/beliefs.ts` pure parts; `components/beliefs.tsx`; the API client regenerated. The skill's tool gains `belief propose|cite|supersede`; SKILL.md writes `beliefs.json` through it.

## Acceptance criteria

- [x] API tests at the seam for every route and refusal, the flags through the triggers, the as-of read of a past judgement.
- [x] Frontend unit tests of the pure parts; Playwright e2e of both pages, seeded.
- [x] Glossary and ADR; migration chained; log entry.
