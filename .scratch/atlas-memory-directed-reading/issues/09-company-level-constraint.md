# 09: A company-level constraint needs no named product

**What to build:** "This demand is outpacing our current supply which has required us to make decisions on supply allocation." becomes a Claim. It is the pilot's most valuable kind of statement, and the checks reject it: in the breadth run of investigation 5 (`29cad6a8-fbe2-42fc-b3e9-fd68b0878fe2`, extraction `ef385730-c5d3-4abe-9d2d-1841c314834d`) Lumentum's sentence was proposed as `capacity_constrained` with object "our products" and rejected `object_not_in_quote`; with ticket 02's wider generic-word list it would be `generic_object`. The sentence names no product because the constraint is the company's own supply.

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("Cues", "Layer"); evidence: `.scratch/pilot/results.md`, "Breadth runs on 0.2.5".

- `capacity_constrained` may be **company-level**: no object text, no layer. It is accepted when the quote carries a constraint cue (ticket 02's list), the subject is the filer of the document (named, first person, or by ticket 02's filer rule), and the quote names no other company as the constrained party. The Claim records that it is company-level; a proposed generic object ("our products", "manufacturing capacity") is dropped to company-level instead of rejecting the Claim.
- With a named, specific object the rule is as today (the object in the quote, its layer if supported).
- The other three bottleneck predicates keep the named-object rule: a company-level `sole_sources` is the boilerplate fix 09 was built to refuse.
- The Relationship is the company's own edge with no object and no layer (ticket 08's layerless edge): it shows on the company's dossier and the edge table, and on the theme map under the company. One company-level `capacity_constrained` edge per company; new Evidence adds to it.
- The Reviewer's rubric says what makes it right: the statement is about the company's own supply against demand, unhedged, and current (not a risk factor's "could").

**Blocked by:** 08 (Layer supported or absent), which makes a layerless edge possible and edits the same checks

**Status:** ready-for-agent

- [ ] At the extraction seam on the recorded Lumentum 10-K: the allocation sentence proposed with object "our products" is accepted as a company-level `capacity_constrained` Claim with no object and no layer; the same sentence proposed for another company is rejected.
- [ ] "we could experience supply constraints" (a risk factor's conditional) is accepted as a Claim but not machine-reviewed (the hedge check), and "prioritizing investments to expand manufacturing capacity" is still no `capacity_constrained` Claim.
- [ ] At the review seam: the company-level edge becomes `machine_reviewed` from a Tier A unhedged quote; a second quote from another filing adds Evidence to the same edge.
- [ ] The edge table, the dossier and the theme map show an edge with no object (frontend unit tests; API client regenerated).
- [ ] Decision entry (amends "Claim precision: the layer from the quote, one clause"), glossary (Bottleneck Predicate), the Investigator's and Reviewer's next prompt versions, migration with the revision the lead names.
