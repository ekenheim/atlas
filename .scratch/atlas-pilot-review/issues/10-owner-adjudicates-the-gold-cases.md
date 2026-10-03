# The gold cases are adjudicated (the lead, delegated by the owner on 2026-10-02)

Type: task
Status: resolved
Blocked by: none

## Question

The 12 evaluation gold cases are agent drafts (`adjudication.method: agent_draft`); none is adjudicated (`.scratch/pilot/gold-adjudication.md`: 12 unchecked). For each, the owner marks Accept or writes what is wrong; a change becomes a new superseding case (`docs/evaluation-methodology.md`).

Resolved when every case is accepted or superseded, and the answer records the changes.

**2026-10-02, the owner delegated this to the lead.** Each case is checked against its sources by a reviewer that did not draft it, and the lead accepts it or writes the superseding case; `adjudication.method` records `lead_review`, not the owner's. The pilot report says so: the gold set is agent-drafted and lead-adjudicated, so the live evaluation measures agreement with the lead's reading, not with an independent expert.

## Answer

**2026-10-03, the lead: all twelve adjudicated.** Three independent Opus reviewers (four cases each, none of them the drafter) checked each case against its sources' text and Atlas's current rules (layer terms, party and direction checks, hedges, the Skeptic's contradiction rule, grounding, corrected availability, Evidence Families); the lead checked their three change requests against the case files. Nothing in any case's expected outcome changed.

- **Accepted (9):** EV-SUP-001, EV-SUP-002, EV-DIR-001, EV-LAY-001, EV-COM-001, EV-COM-002, EV-INF-001, EV-HED-001, EV-FUT-001. Recorded as the manifest's `adjudicated` (by the lead, 2026-10-03); the case files are immutable.
- **Superseded for metadata (3), gold unchanged:** EV-CON-002 (s2 was titled "10-Q Q1 fiscal 2026" but, filed 2025-08-05 after the fiscal-2024 10-K, is Q2 fiscal 2025; the script's skeptic-plan `documents`, ignored since memory-directed reading ticket 07, removed). EV-RST-002 (both Nokia sources claimed availability at the restating 20-F's acceptance; they are API responses retrieved 2026-09-29, `observed_discovery`). EV-SYN-002 (the ten mirrors are Tier C news copies, not Tier A; s0 and s11 are press releases, not 8-Ks). Each new case's `adjudication` is `agent_draft_reviewed` with the reviewer's note as a disagreement resolved; the format has no `lead_review` method, so the labeler names the lead.
- **Noted, no change:** EV-SYN's mirrors s4 and s8 are exactly 3 SimHash bits from s0, the limit: a parser or SimHash change would split them, and the case would catch it. In EV-LAY the `[epi] not_verified` row can no longer see a separate epi edge (layer left an edge's identity with migration 0055); it checks the edge's layer. Two declarative `metrics` lists omit a metric the scorer computes (EV-DIR `citation_correctness`, EV-SUP-001 `relationship_precision`); scoring ignores the list.
- **What this measures:** the gold set is agent-drafted and lead-adjudicated, so the live evaluation (ticket 11) measures agreement with the lead's reading, not with an independent expert. The pilot report says so.
- Validated with `atlas.evaluation.validate_gold`; the fake-mode run is the runners' (no local Postgres).
