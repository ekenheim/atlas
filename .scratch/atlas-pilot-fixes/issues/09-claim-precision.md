# 09: Claim precision: the layer comes from the quote, and a verb in a neighbouring clause is no cue

**What to build:** In pilot investigation 1's re-run (0.2.3), 4 of 14 accepted Claims were wrong or worthless, and one of them became a `machine_reviewed` edge:
1. **Layer over-tagging.** Three Lumentum `sole_sources` Claims quote generic risk-factor sentences ("some of our suppliers are our sole sources for certain materials, equipment and components"; "we purchase raw materials, packages and components from a limited number of suppliers") and carry `layer: substrate`, which the text never names. The Investigator tags a company-level fact with the layer the *question* is about. A Coherent `sole_sources` about the Industrial segment's "exotic materials, crystals, and optics" was tagged `substrate` too.
2. **A verb in the neighbouring clause.** "We continue to expand our global 6-inch InP manufacturing capacity …, while also operating multiple 6-inch GaAs VCSEL manufacturing facilities" became `expands_capacity_for` → GaAs VCSEL facilities, and the Reviewer (`reviewer.v2`) passed it. The directional cue ("expand") is in the other clause. Fix 03's report predicted this case.

Build:
- **Investigator `investigator.v5`:** `layer` must be the layer of the object the quote names; a fact whose quote names no layer-specific input or product (generic "materials, components, suppliers") is not a Claim; the four bottleneck predicates need the input or product named in the quote. Keep the schema.
- **Deterministic cue-proximity check** (in `atlas.claims` or the Relationship checks, wherever the directional-language check lives): the predicate's cue must occur in the same clause as the object text (no clause boundary such as `, while`, `; `, `, and also`, ` whereas ` between them), else `no_directional_language` (or a new reason `cue_in_other_clause`). Unit tests with the VCSEL sentence and with sentences where the cue rightly spans no boundary.
- **Reviewer `reviewer.v3`:** rejects generic risk-factor language for the bottleneck predicates and a cue that belongs to another clause; the rubric names both failure shapes with the pilot's sentences as examples.
- Record the decisions in `docs/decisions.md`; the glossary if a term changes.

**Blocked by:** None

**Status:** done

- [x] Unit tests: the VCSEL sentence yields no `expands_capacity_for` for the VCSEL object; "we continue to expand our 6-inch InP capacity" still does for InP.
- [x] Integration test at the extraction seam (scripted Investigator): a generic sole-source sentence tagged `substrate` is rejected with a reason that names the layer; a specific one ("we purchase InP substrates from a limited number of suppliers") is accepted with `substrate`.
- [x] Prompt versions bumped (`investigator.v5`, `reviewer.v3`) with the structural prompt tests updated.
