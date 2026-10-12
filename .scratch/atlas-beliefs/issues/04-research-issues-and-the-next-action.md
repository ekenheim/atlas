# 04: Issues: the research frontier, narrowing and requiring, the next action by rule, the Issues page

Type: build
Status: ready-for-agent
Blocked by: 08

## Parent

`../spec.md` (Implementation Decisions, "Issues"; User Stories 7, 15, 16).

## What to build

Tables `issue` (title, body, theme, kind `question|step|read`, priority, status `active|complete|abandoned|invalid`, companies, `produced_by` session), `issue_edge` (`narrows`, `requires`; acyclic; child to parent), `issue_product` (Beliefs and Facts produced); audited. Routes: `POST /api/v1/issues` (with optional `narrows` and `requires`), `POST .../{id}/complete|abandon`, `POST .../{id}/produced` (a Belief or Fact), `GET /api/v1/issues?theme=&status=`, `GET /api/v1/issues/next?theme=` by the spec's rule (unblocked; a step with no Belief first, then flagged or disputed, then priority, then age). A session's close creates the root Issue (the question) narrowed into its steps, and Issues for the card's open questions and unread companies; a follow-up session may be opened on the next Issue. Page `app/issues/` (the frontier, the next action first, each Issue with its parent question, step, companies and what it produced); `lib/issues.ts`; the skill's tool gains `issue open|narrow|complete|next`; SKILL.md starts a session from the frontier when the prompt names none.

## Acceptance criteria

- [ ] API tests: create, narrow, require, complete, the acyclicity refusal, `next` under each rule branch, the Issues a session's close creates.
- [ ] Frontend unit test of the ordering; Playwright e2e of the page, seeded.
- [ ] Migration chained; log entry.
