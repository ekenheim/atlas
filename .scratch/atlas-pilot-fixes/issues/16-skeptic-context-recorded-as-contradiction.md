# 16: The Skeptic records bear-checklist context as contradictions of unrelated Claims

**What to build:** In investigation 1 on 0.2.5 (`ead2b86e-3556-42ba-9f3e-08660a938f98`; Skeptic role calls `45229383-…`, `ea80697f-…`, `263ec26f-…`, `6a6faaf9-…`, prompt `skeptic` v2), the Skeptic read 24 passages and 29 of its 30 items were accepted as counterevidence, 15 of them independent. None contradicts a Claim:
- Lumentum's risk factor "for certain components we have sole or limited source supply arrangements" is independent counterevidence against Coherent `manufactures` and `vertically_integrates`, and against Lumentum `owns` NVIDIA.
- Balance-sheet rows ("Inventories 2,126,823 1,437,636", "Property, plant & equipment, net 2,420,081 1,877,507", "Diluted 96.2 69.3 87.4 68.8") are counterevidence against capacity Claims.
- "We continue to expand our global 6-inch InP manufacturing capacity" is counterevidence (`capacity_additions`) against Coherent `capacity_constrained`, which is at least on the point.
- 12 items name no Claim at all (`contradicts_claim_ids` empty).

The Editor then marks findings contradicted (5 of 5 carry independent counterevidence families) and the investigation stops `needs_review` with "4 findings are contradicted by independent counterevidence". A researcher can't tell a real contradiction from context. The context itself is worth keeping: the Editor's open questions used it well (inventories against revenue, customer concentration, dilution).

Decide and build:
- Two kinds of Skeptic output: a **contradiction** (the quote denies or limits a named Claim's statement, about the same company and object) and **bear context** (a checklist item about the company, attached to no Claim). Only contradictions mark a finding and drive `needs_review`; bear context goes to the card as its own section.
- Independence stays a property of contradictions. Whether another company's statement can contradict a Claim at all needs a rule (a competitor's capacity addition can bear on a shortage; a competitor's boilerplate cannot bear on vertical integration).
- A table row with no words is not a quotable statement unless the item names the figure and period.

**Blocked by:** None

**Status:** needs-triage

- [ ] The decision in `docs/decisions.md` and the glossary (`CONTEXT.md`: counterevidence, bear context).
- [ ] At the investigation seam: a Skeptic answer with one real contradiction and three context items marks one finding contradicted, lists the context on the card, and stops `needs_review` naming one finding.
