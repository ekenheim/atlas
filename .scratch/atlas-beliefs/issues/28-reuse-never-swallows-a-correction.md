# 28: Fact reuse never swallows a correction

Type: build
Status: ready-for-agent
Blocked by: none

## Why

On 2026-10-15 the lead corrected Fact 34aa1f72, whose statement says "the merchant indium phosphide market" while its quote says only "the market" (the word that made the Editor's thesis `thesis_misstated` on 0.6.8). Recording the faithful statement on the same span returned the old Fact (`reused`, HTTP 200, the wrong statement, not judged), because ticket 26's reuse treats statements as alike at word-set Jaccard >= 0.5 (`atlas.facts.duplicates.alike`): dropping one qualifier keeps the overlap high, and the qualifier was the error. A correction must always be recordable beside the Fact it corrects.

## What to build

- `atlas.facts.reuse`: reuse an existing Fact only when the new statement equals the existing one after normalising case, whitespace and punctuation (and the same step and status); any other statement on an overlapping span is a new Fact naming the earlier one (`same_span_as`) and is judged at record like any session Fact (ticket 23).
- The `alike` rule (Jaccard) stays where it is used for duplicate reporting, not for reuse.
- SKILL.md: one sentence: to correct a Fact, record the faithful statement on the same span; the old Fact stays (insert-only), the new one names it.

## Acceptance criteria

- [ ] HTTP-seam tests: an identical statement (case and punctuation aside) is reused; a statement that drops a qualifier ("the merchant indium phosphide market" → "the market") on the same span is a new Fact with `same_span_as` and a judge verdict; the existing reuse tests updated with the reason.
- [ ] The lead's correction of Fact 34aa1f72 recorded on production after deploy, and Belief 53a43503 superseded by atomic Beliefs citing it.
