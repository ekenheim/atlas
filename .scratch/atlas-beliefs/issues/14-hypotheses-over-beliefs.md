# 14: A Hypothesis is its thesis and the Beliefs it rests on

Type: build
Status: ready-for-agent
Blocked by: none

## What to build

`atlas.hypotheses`: a version's content gains `steps`, each argument step with the Beliefs it rests on (id, statement, judgement, confidence, as-of, the load-bearing citations), beside the existing fields; the `draft_hypothesis` job drafts from a theme's or a session's proven Beliefs (the Editor role's draft prompt sent the Beliefs and their Facts' quotes, not old findings; the thesis statement, mechanism, falsifiers and open questions written from them; every statement cites Beliefs by short reference, mapped back by code as the card's are; grounding-checked and judged as a card statement is); the publish gate's Belief rule (ticket 03) is the gate; the Research Snapshot carries the steps with each Belief's citations and judgement at publish time; `GET /api/v1/hypotheses/{id}` returns the steps; the dossier page (`frontend/app/hypothesis/`, `components/hypothesis.tsx`, `lib/hypotheses.ts`) leads with the thesis and the steps, each Belief with its judgement and its quotes at their spans, then falsifiers, open Issues, the old sections below. Pages dark, terse, no commands.

## Acceptance criteria

- [ ] API tests: a draft from proven Beliefs; the gate; the snapshot's steps; the read. Hypothesis e2e extended with a seeded Belief-backed version.
- [ ] One photonics Hypothesis published on production from the closing session's Beliefs plus one more session (the lead; `.scratch/pilot/results.md`), linked from the artifact page.
