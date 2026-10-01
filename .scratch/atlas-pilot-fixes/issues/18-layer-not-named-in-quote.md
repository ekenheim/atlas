# 18: Layers the quote doesn't name: wrong layers reach `machine_reviewed`, and right edges go to the queue

**What to build:** Fix 09 made the layer rule deterministic only for a bottleneck predicate with a generic object. In investigation 1 on 0.2.5 (`ead2b86e-3556-42ba-9f3e-08660a938f98`), 7 of 10 accepted Claims carry a layer their quote doesn't support, with two different harms:
- **Wrong layers pass.** Coherent `capacity_constrained` "indium phosphide capacity" (edge `2add892e-9998-4467-a393-8511d9f6b1a7`) and `expands_capacity_for` "indium phosphide capacity in Sherman, Texas" (edge `8bab66e5-c53a-4840-8ec1-baca91703033`) are tagged `substrate` and are `machine_reviewed`. Coherent buys InP substrates (its 10-K's "Sources of Supply"); Sherman is its InP device fab. The same capacity is `chip-laser` in a third Claim and was `epi` in the 0.2.3 run, so one fact now has edges in three layers.
- **Right edges are held.** NVIDIA `owns` Coherent (`d3c18f3f-49bf-444e-a735-f6643ce34067`), Coherent's 6-inch InP capacity (`bca720fb-f655-40e1-936a-b4aa4353cd17`), Coherent's U.S. footprint (`39d54163-9440-4977-9f91-1510e4741572`) and Lumentum's new fab (`a8d7ab03-3749-46dc-a80d-0de910ffc7e1`) are in the exceptions queue with the same three reasons (`reviewer_rejected`, `direction_not_confirmed`, `layer_not_confirmed`), although subject, predicate, object and direction are right. `reviewer.v3` rejects on the layer and the answer is recorded as if the direction failed too.

Decide and build:
- Whether an edge needs a layer at all. An ownership edge between two companies has none; a company-level capacity statement ("manufacturing footprint", "a new fab") names none. Options: allow no layer (the edge shows on the company, not on a layer of the theme map), or take the layer from the object product's taxonomy terms only.
- One edge per fact: the same subject, predicate and object in two layers should be one edge whose layer is in question, not two edges.
- The Reviewer's answer per check (direction, layer, hedge), so an unconfirmed layer doesn't record an unconfirmed direction.

**Blocked by:** None

**Status:** needs-triage

- [ ] The decision in `docs/decisions.md` (layer optional or derived; edge identity across layers).
- [ ] At the review seam: an ownership Claim with a right direction and no layer becomes `machine_reviewed`; "indium phosphide capacity" tagged `substrate` does not.
