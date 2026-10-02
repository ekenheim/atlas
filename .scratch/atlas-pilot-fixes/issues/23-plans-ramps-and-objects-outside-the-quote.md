# 23: A plan is not a fact, a ramp is not an expansion, and the object is in the quote

**What to build:** Three checks the accepted Claims of the fifth run fail most: a statement of what is expected is not accepted as what is; a predicate is accepted only for the kind of statement it names; and the object the Claim names is in the quote.

Evidence: production 0.3.1, investigation `452c3b9d-2e2f-4cc6-bc54-5130155b9aac` (pilot investigation 1, fifth run; reviewed in `.scratch/pilot/results.md`, "Investigation 1, fourth and fifth runs"); 20 of the 28 wrong Claims (the table in the results section):
- **expected, planned or possible (6):** Coherent `manufactures` 1.6T transceivers from "We expect to have 1.6T in production this year"; Applied Optoelectronics `qualified_for` from "We expect full qualification ... within the next couple of weeks" and "I think AOI will be the fourth supplier qualified"; AXT `expands_capacity_for` from "we are well into the planning process to double our capacity again in 2027"; Applied Optoelectronics from "which will allow expansion"; Lumentum `vertically_integrates` CW lasers from a delayed plan.
- **the predicate does not fit (8):** a capacity level ("Today, we have capacity for over 1 billion VCSEL arrays per year"), a reservation of capacity, a production ramp, a demo, a product developed and cancelled, each accepted as `expands_capacity_for`, `manufactures` or `vertically_integrates`; a market-wide shortage accepted as the speaker's own `capacity_constrained` (2, counted under "the subject is not the actor").
- **the object is not in the quote (6):** "We're currently expanding our capacity", "The capacity is growing faster than we thought", "The third ramp is our Greensboro fab": the product is in a neighbouring sentence. `object_not_in_quote` exists as a rejection (3 in this run) and did not catch these.

Decide and build:
- Which predicates state a present fact and so refuse expectation language (`manufactures`, `qualified_for`, `vertically_integrates`, `supplies`, `capacity_constrained`), and that `expands_capacity_for` accepts a committed or under-way expansion ("we are doubling", "we agreed to increase") and refuses a possibility or a plan still being made ("planning process", "will allow", "may"). The hedge list the Reviewer uses for `machine_reviewed` is the starting point; here it decides acceptance.
- Whether a quote may be widened to the neighbouring sentence that names the object (the Claim's quote would then be two sentences), or the Claim is rejected `object_not_in_quote` and the Investigator's prompt asks for the sentence that names the product. The second keeps a quote one statement; the first keeps three Claims that are right in context.
- Whether `capacity_constrained` about "the industry" or "the market" becomes a theme-level statement or is refused (`subject_not_the_actor`).

**Blocked by:** None

**Status:** needs-triage

- [ ] The decision in `docs/decisions.md`, with these Claims as the evidence.
- [ ] At the `extract_claims` seam: each of the quoted examples above is rejected with its reason, and the committed expansions of the same run ("we are doubling our capacity through 2026", with the product in the quote) are still accepted.
