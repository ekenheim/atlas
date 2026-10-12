# 06: Memory holds judged Beliefs; recall takes `available_by`; bulk retention has a switch

Type: build
Status: ready-for-agent
Blocked by: 02

## Parent

`../spec.md` (Implementation Decisions, "Memory", "Recall as a tool"; User Stories 17, 18, 21, 22).

## What to build

A `retain_belief` job (pausable, the research bank, `ATLAS_RETAIN_EXTRACTOR` honoured) enqueued when a Belief's judgement becomes anything but `unproven`, or it is superseded or re-judged: the document `belief:<id>` with observation scopes per theme tag, tags `belief`, `judgement:<value>`, `step:<value>`, the companies' entity names, carrying the statement, as-of, judgement, confidence, the load-bearing Facts' statements and quotes, and the session; a re-judgement or supersession deletes the document first (`memory_replacement` recorded). The provenance resolver labels a memory from a `belief:` document `belief` and resolves it to the Belief (`GET /api/v1/beliefs/{id}`), never to a section; `GET /api/v1/memory/health` counts Beliefs in Memory per theme. `POST /api/v1/memory/recall` gains `available_by` (drops memories none of whose resolved sections or Beliefs were available by that time; reports `dropped_future`); the skill's `recall` uses it. `ATLAS_BULK_RETENTION` (`on` by default): `off` holds the ingest's section retains, triage and the daily consolidation try (through the existing budgets of 0) and health reports it. Rules in `docs/decisions.md` ("Memory holds what was found"); the runbook for switching bulk retention off and back.

## Acceptance criteria

- [ ] Worker tests with the Hindsight fake: retain on judgement, replace on re-judgement and supersession, the `belief` citation label on recall, `available_by`, bulk retention off.
- [ ] A before/after probe on production recorded in `docs/experiments.md` once a few Beliefs exist.
- [ ] Decisions and runbook entries; log entry.
