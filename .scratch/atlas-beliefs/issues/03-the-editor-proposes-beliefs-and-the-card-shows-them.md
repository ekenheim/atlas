# 03: The theme and company pages lead with Beliefs; the pipeline proposes them too; the publish gate and snapshots carry them

Type: build
Status: ready-for-agent
Blocked by: 02

## Parent

`../spec.md` (Implementation Decisions, "Reads", "The website", the publish gate; User Stories 1, 10, 11, 20, 23).

## What to build

`GET /api/v1/themes/{id}/map` and `GET /api/v1/companies/{id}/dossier` gain `beliefs` (the theme's by step and judgement; the company's with its Exposure per Belief: holder, supplier, dependent, from the citations' companies). `app/theme/` leads with the Beliefs (the map and edges below); `app/company/` leads with the company's Beliefs and Exposure (identity, sources, edges and financials below). The argument plan's Editor task proposes one `unproven` Belief per judged step statement, citing its Facts (+0.5) and the Skeptic Facts by the counter-judge's valence map, in the card's transaction; the card's steps list `belief_ids`. A published Hypothesis version records the Beliefs it rests on; the Research Snapshot carries them; the publish gate requires every load-bearing Belief `proven` or the owner's recorded override (`publish_gate_failed` names `belief_not_proven`).

## Acceptance criteria

- [ ] API tests: the map and dossier additions; a harness investigation produces Beliefs on its card; the gate refuses and the override passes; the snapshot holds the Beliefs.
- [ ] Playwright e2e of the theme and company pages with Beliefs first, seeded.
- [ ] Log entry.
