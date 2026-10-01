# 08: An edge carries a layer only when its quote supports one

**What to build:** The theme map never places a company in a layer its Evidence doesn't name, and a right edge without a layer is machine-reviewable. Evidence: pilot investigation 1 on 0.2.5, where 7 of 10 accepted Claims carried a layer their quote didn't support, two `machine_reviewed` edges tagged Coherent's InP device capacity `substrate`, and four right edges went to the exceptions queue for the layer (pilot-fix ticket 18, which this supersedes).

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("Layer").

- A Claim's layer is optional. It is kept only when a taxonomy term of that layer occurs in the quote or in the object text; otherwise it is stored as null and the reason recorded (`layer_unsupported`). "indium phosphide capacity" supports no layer: InP is a term of the substrate, epi and chip-laser layers alike, so a term shared by several layers supports none.
- A Relationship may have no layer. It shows on the companies' dossiers and in the edge table (the layer filter gains "none"); on the theme map it is listed under the companies, not under a layer.
- An edge's identity is subject, predicate and object. New Evidence with a different supported layer does not make a second edge: the edge goes to the exceptions queue with `layer_conflict`. Existing duplicate edges that differ only by layer are left as they are and listed by a read-only report for the owner.
- The Reviewer answers each check separately (direction, hedge, layer). An unsupported or unconfirmed layer no longer records `direction_not_confirmed`; with direction confirmed, no hedge and no layer, the edge is `machine_reviewed` with a null layer.
- The Investigator's prompt says the layer may be left out and when.

**Blocked by:** 02 (Claim checks), which edits the same checks

**Status:** ready-for-agent

- [ ] At the extraction and review seams: NVIDIA `owns` the issuer with the question's layer proposed is accepted with a null layer and becomes `machine_reviewed`; "expanding our indium phosphide capacity in Sherman, Texas" proposed as `substrate` is accepted with a null layer; "InP substrates" as the object keeps `substrate`.
- [ ] A second Claim for an existing edge with another supported layer puts the edge in the exceptions queue with `layer_conflict`; no second edge exists.
- [ ] The edge table filters by no layer; the theme map lists layerless edges under their companies (frontend unit tests; API client regenerated).
- [ ] The evaluation gold cases still pass; the layer-conflation case still fails a wrong layer.
- [ ] Decision entry (layer rule, edge identity), glossary if a term changes, migration with the revision the lead names, prompt versions.
