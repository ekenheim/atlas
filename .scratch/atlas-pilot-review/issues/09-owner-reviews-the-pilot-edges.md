# The owner reviews the pilot's edges

Type: task
Status: open
Blocked by: none

## Question

The owner's review decisions from the 0.2.3 run of investigation 1 are still open (`.scratch/pilot/results.md`, "Corrections needed"). They are the owner's acts (`POST /api/v1/relationships/{id}/review`, or the exceptions page):
- approve Lumentum `capacity_constrained` (the allocation statement), in the exceptions queue;
- reject the three boilerplate Lumentum `sole_sources` edges (two in the exceptions queue, one `machine_reviewed`) and Coherent's Industrial-segment `sole_sources`;
- reject Coherent `expands_capacity_for` 6-inch GaAs VCSEL manufacturing facilities (`machine_reviewed`; the verb belongs to the InP clause).

The lead prepares the list with each edge's ID and link; each later investigation's "Corrections needed" is added here. Resolved when the exceptions queue holds no pilot edge and the answer records what the owner decided.

## Comments

**2026-10-01, the lead: the list for the owner** (production 0.2.3; investigation `4620f8c2-709c-465a-b0ca-ee0486f3e1b2`). Seven edges: the five in the exceptions queue and two `machine_reviewed` ones that are wrong. The other six `machine_reviewed` edges are right and need nothing.

| Edge | State | Recommendation |
|---|---|---|
| [Lumentum `capacity_constrained`: products for AI and cloud customers' data center expansion](https://atlas.ekenhome.se/relationship?id=333f53f9-2461-49cd-afa2-22f91ed637cf) | needs_human_review | **Approve.** "This demand is outpacing our current supply which has required us to make decisions on supply allocation." The direct answer to the question. |
| [Lumentum `expands_capacity_for`: manufacturing capacity, internally and with contract manufacturers](https://atlas.ekenhome.se/relationship?id=65601701-8ff1-4532-9d69-bba298decd72) | needs_human_review (`layer_not_confirmed`) | **Approve the fact, the layer is the doubt.** "We are investing in manufacturing capacity, both internally and with contract manufacturers, to meet demand." True and on the question, but the quote names no layer; it is tagged `chip-laser`. Reject if an edge with an unconfirmed layer should not stand. |
| [Lumentum `sole_sources`: raw materials, packages and components (`substrate`)](https://atlas.ekenhome.se/relationship?id=4a0f7751-9ece-48d8-b934-6dfeb69cce61) | needs_human_review | **Reject.** Generic risk-factor language ("a limited number of suppliers"); the text names no substrate. |
| [Lumentum `sole_sources`: materials, equipment and components (`substrate`)](https://atlas.ekenhome.se/relationship?id=fdda7871-7eca-4569-aeb1-72d31e46858f) | needs_human_review | **Reject.** Generic risk-factor language about sole suppliers; no layer named. |
| [Coherent `sole_sources`: exotic materials, crystals, and optics (`substrate`)](https://atlas.ekenhome.se/relationship?id=e0c1dadd-9a81-4343-943c-e7c83743494e) | needs_human_review | **Reject.** The Industrial segment, not AI transceivers; the layer is wrong. |
| [Lumentum `sole_sources`: certain components (`chip-laser`)](https://atlas.ekenhome.se/relationship?id=fd8c7f82-959d-4d59-9712-fa78c707bc79) | machine_reviewed | **Reject.** "for certain components we have sole or limited source supply arrangements": boilerplate, and no layer named. Fix 09 rejects this shape from 0.2.5 on. |
| [Coherent `expands_capacity_for`: 6-inch GaAs VCSEL manufacturing facilities](https://atlas.ekenhome.se/relationship?id=c560c5aa-6bc8-4424-be19-723cfd13ef91) | machine_reviewed | **Reject.** The quote says Coherent is "operating" the VCSEL facilities; "expand" belongs to the InP clause. Fix 09 rejects this shape from 0.2.5 on. |

The results section counted the three boilerplate `sole_sources` edges and the Industrial one as four of the five exceptions; the queue in fact holds two of the three (the third is `machine_reviewed`) plus the `layer_not_confirmed` capacity edge above.
