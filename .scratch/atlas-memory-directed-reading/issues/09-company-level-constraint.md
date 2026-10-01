# 09: A company-level constraint needs no named product

**What to build:** "This demand is outpacing our current supply which has required us to make decisions on supply allocation." becomes a Claim. It is the pilot's most valuable kind of statement, and the checks reject it: in the breadth run of investigation 5 (`29cad6a8-fbe2-42fc-b3e9-fd68b0878fe2`, extraction `ef385730-c5d3-4abe-9d2d-1841c314834d`) Lumentum's sentence was proposed as `capacity_constrained` with object "our products" and rejected `object_not_in_quote`; with ticket 02's wider generic-word list it would be `generic_object`. The sentence names no product because the constraint is the company's own supply.

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("Cues", "Layer"); evidence: `.scratch/pilot/results.md`, "Breadth runs on 0.2.5".

- `capacity_constrained` may be **company-level**: no object text, no layer. It is accepted when the quote carries a constraint cue (ticket 02's list), the subject is the filer of the document (named, first person, or by ticket 02's filer rule), and the quote names no other company as the constrained party. The Claim records that it is company-level; a proposed generic object ("our products", "manufacturing capacity") is dropped to company-level instead of rejecting the Claim.
- With a named, specific object the rule is as today (the object in the quote, its layer if supported).
- The other three bottleneck predicates keep the named-object rule: a company-level `sole_sources` is the boilerplate fix 09 was built to refuse.
- The Relationship is the company's own edge with no object and no layer (ticket 08's layerless edge): it shows on the company's dossier and the edge table, and on the theme map under the company. One company-level `capacity_constrained` edge per company; new Evidence adds to it.
- The Reviewer's rubric says what makes it right: the statement is about the company's own supply against demand, unhedged, and current (not a risk factor's "could").

**Blocked by:** 08 (Layer supported or absent), which makes a layerless edge possible and edits the same checks

**Status:** done

- [x] At the extraction seam on the recorded Lumentum 10-K: the allocation sentence proposed with object "our products" is accepted as a company-level `capacity_constrained` Claim with no object and no layer; the same sentence proposed for another company is rejected.
- [x] "we could experience supply constraints" (a risk factor's conditional) is accepted as a Claim but not machine-reviewed (the hedge check), and "prioritizing investments to expand manufacturing capacity" is still no `capacity_constrained` Claim.
- [x] At the review seam: the company-level edge becomes `machine_reviewed` from a Tier A unhedged quote; a second quote from another filing adds Evidence to the same edge.
- [x] The edge table, the dossier and the theme map show an edge with no object (frontend unit tests; API client regenerated).
- [x] Decision entry (amends "Claim precision: the layer from the quote, one clause"), glossary (Bottleneck Predicate), the Investigator's and Reviewer's next prompt versions, migration with the revision the lead names.

## Resolution

Built on `integrate/mdr` (tickets 01-04 and 08). The decision entry is `docs/decisions.md`, "A company-level constraint needs no named product"; the log entry is `docs/implementation-log.md`, "memory-directed reading ticket 09".

- **The rule** (`atlas.claims.company_level`): a `capacity_constrained` Claim proposed with no object text, or with one that names no product (generic words and the words of the constraint itself: "our products", "manufacturing capacity", "our current supply", "supply allocation"), is company-level: no object, no layer, `claim.company_level` true (the proposal stays in `claim.proposed`). It is accepted when the subject is the filer of the document (`company_level_not_filer`), named, in the first person or by ticket 02's filer rule; the quote names no other company (`other_company_in_quote`, or `party_not_in_quote` when the filer is unnamed); and it carries a constraint cue. A named, specific object and the other three bottleneck predicates are as before.
- **The edge:** no object company, no object text, no layer; `object_key` is the reserved empty string, so the identity index holds one company-level edge per company and new Evidence joins it. The same rule applies at review to any Assertion. Migration `0057` (`down_revision` `0055`; the lead re-chains).
- **The hedge check** is unchanged: the risk factor's "could" is a Claim whose machine review is `needs_human_review` `hedged_language`; the allocation sentence is machine-reviewable.
- **Prompts:** `investigator.v8`, `reviewer.v5` (the Reviewer's item gains `company_level`).
- **Read side:** `Relationship.company_level` and `Claim.company_level` on the API; the edge table, the dossier and the Theme explorer name the missing object "company-level".

Decided here, beyond the ticket (see the log's deviations): "names no other company as the constrained party" is "names no other company"; the words of the constraint itself count as naming no product; a company-level Claim's proposed layer is dropped without a `layer_reason`; a company-level edge can never take a layer; the same sentence in the recorded 10-K that says "could" stands in for the ticket's "we could experience supply constraints".
