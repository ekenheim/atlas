# Beliefs: tables, judgement history, citations with valence, read API

Type: build
Status: open
Blocked by: none

Spec §1 and Implementation Decisions. Tables `belief`, `belief_judgement`, `belief_citation`, `belief_supersession`; `GET /api/v1/beliefs`, `GET /api/v1/beliefs/{id}`, `POST /api/v1/beliefs` (propose: statement, theme, step, companies, citations), `POST /api/v1/beliefs/{id}/cite`, `POST /api/v1/beliefs/{id}/judge` (author only; actor recorded; audited), `POST /api/v1/beliefs/{id}/supersede`. A Belief with a load-bearing negative citation whose Fact stands is listed `flagged: counterevidence_stands` until judged. Tests at the API seam; the API client regenerated.

## Done when

- [ ] Tables, API, audit, tests; the glossary gains **Belief** and **Issue** (`CONTEXT.md`), with an ADR.
