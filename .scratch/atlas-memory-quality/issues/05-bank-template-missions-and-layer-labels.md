# 05: The bank template: missions that stand alone, and a layer label on each fact

**What to build:** The research bank is told what to extract and what to leave out, and what an observation is, in full; and the extractor labels each fact with the supply-chain layer it concerns, so that a recall can be filtered to a layer.

Spec: `.scratch/atlas-memory-quality/spec.md` ("The bank template"). Study: finding 5 (`observations_mission` replaces the built-in rules entirely; the retain mission has no ignore list) and finding 4 (`entity_labels` with `tag: true`). Recordings: ticket 01 (`entity_labels`, the template schema on 0.10.2, `dry-run-extract`).

- `retain_mission`: what to extract (as now), what to ignore (safe-harbor and forward-looking boilerplate, officer certifications, exhibit lists, signature blocks, generic risk language that names no product, counterparty or figure), and that each statement is attributed to who made it.
- `observations_mission`, written to stand alone: durable and specific statements about a company and about the industry; a change is recorded with its dates and periods, not overwritten; figures keep unit and period; who supplies or depends on whom; contradictions kept; repetition across filings is not corroboration.
- `entity_labels`: one group `layer`, values the Claim layer taxonomy's (`atlas.claims`), with a one-line description each taken from that taxonomy, several per fact allowed, optional, `tag: true`. A test fails when the template's values and the taxonomy's differ.
- The template version goes up; `atlas hindsight apply-template` dry-runs and applies it as today. The dev bank template is left alone unless it shares the missions.
- Before fixing the texts, compare the old and the new missions on three recorded sections (a 10-K Item, an 8-K exhibit, a transcript part) with `dry-run-extract` on the local Hindsight: the lead runs it with the owner's go-ahead for ticket 01; the comparison goes into `docs/research/` and the texts are adjusted once from it.
- `docs/decisions.md`: the missions' reasoning and the label group.

**From ticket 01 (recordings `entity_labels/`, `dry_run_extract/`, `reprocess/03`):** a label group with `tag: true` writes its values as tags and a recall filtered by the tag returns only those facts; `reprocess` applies labels configured after the retain, without a new context. 0.10.2 also has consolidation strategies (a mission per scope), not exercised: leave them out.

**Blocked by:** 01

**Status:** done, except the comparison: the lead runs `spikes/hindsight/mission_compare_05.py` live, writes the note and adjusts the texts once (`docs/implementation-log.md`)

- [x] The template validates against the recorded 0.10.2 schema; the dry-run import through the fake accepts it; the recorded version is the new one.
- [x] Unit test: the `layer` values equal the taxonomy's layer names.
- [x] The fake derives label tags on derived facts (from the recording), and a recall filtered by a label tag returns only those (gateway-level test through the public recall once ticket 07's fields exist, otherwise through the fake's contract test).
- [x] The comparison note exists, says what was live, and the final texts follow it. (`docs/research/mission-comparison.md`, run by the lead on 2026-10-02: 6 live requests; the label description was tightened after it.)
- [x] Decision entry; `AGENTS.md` line.
