# 08: Research sessions recorded, with their Facts and card, and a sessions page

Type: build
Status: ready-for-agent
Blocked by: none

## Parent

`../spec.md` (Implementation Decisions, "Research sessions"; User Stories 8, 12, 19, 24).

## What to build

A `research_session` row (question, theme, seeds, `as_of`, kind `claude` or `pipeline`, model, actor, started, finished, usage JSON, card JSON, card markdown), insert-only history not needed; audited. `POST /api/v1/sessions` opens one (question, theme, seeds, as_of, kind, model, actor); `POST /api/v1/sessions/{id}/close` sets usage, the card (the argument plan's card shape: steps with statements, facts and counterevidence, question parts, open questions) and the markdown; `GET /api/v1/sessions?theme=` and `GET /api/v1/sessions/{id}` (with its Facts). `POST /api/v1/facts` takes an optional `session_id`; `GET /api/v1/facts?session_id=` lists them. The pipeline's investigation records a session of kind `pipeline` when its Editor task ends (question, seeds, as_of, usage, card), so both kinds list together. Pages `app/sessions/` (the list: question, kind, model, as-of, Facts, cost, when) and `app/session/?id=` (the card rendered as the investigation page renders an argument card, its Facts with spans opening the source viewer, usage); pure parts in `lib/sessions.ts`; the API client regenerated. The skill's tool gains `session open` and `session close`, and `record` sends the session id; `SKILL.md` opens a session first and closes it last.

## Acceptance criteria

- [ ] API tests: open, record Facts into, close and read a session; a pipeline investigation appears as a session after its Editor; the list filters by theme.
- [ ] Frontend unit test of the pure parts; Playwright e2e of the two pages seeded through `scripts/e2e.py`.
- [ ] The skill's tool and SKILL.md updated; a dry run of `session open`/`close` documented in the log.
- [ ] Migration chained; audit entries for open and close; `docs/implementation-log.md` entry.
