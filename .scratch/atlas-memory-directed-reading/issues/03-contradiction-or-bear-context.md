# 03: The Skeptic's output is a contradiction of a Claim or bear context, never both

**What to build:** On a research card, "contradicted" means a quoted statement that denies or limits a named Claim. Everything else the Skeptic finds on the bear checklist is shown as bear context about a company. Evidence: pilot investigation 1 on 0.2.5, where 29 Skeptic items were accepted as counterevidence, none contradicted a Claim, and the run stopped "4 findings are contradicted" (pilot-fix ticket 16, which this supersedes).

Spec: `.scratch/atlas-memory-directed-reading/spec.md` ("Contradiction or bear context").

- The Skeptic's answer gives each item a kind. A **contradiction** names the Claim it contradicts and how (denies, limits, or dates it), about the same company and object. A deterministic check refuses a contradiction whose quote names neither the Claim's subject nor its object, and turns it into bear context. **Bear context** is a checklist item, a company and a span, attached to no Claim.
- Only contradictions mark a finding contradicted and drive `needs_review`; independence (another Evidence Family than the supporting Claims) stays a property of contradictions.
- A table row with no words ("Inventories 2,126,823 1,437,636") is accepted as bear context only when the item states the figure's name and period; otherwise it is rejected.
- The research card gains a bear-context section, grouped by checklist item and company; the Editor is sent contradictions and bear context separately and writes open questions from both. The investigation page shows the section.
- The stop detail counts contradictions only.

The Skeptic's reading (which documents and passages) is unchanged here; ticket 07 changes it.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Integration test at the investigation seam: a Skeptic answer with one real contradiction (a later filing limiting a supply Claim) and three context items (customer concentration, inventories, another company's risk factor) marks one finding contradicted, lists three bear-context items on the card, and stops `needs_review` naming one finding.
- [ ] A "contradiction" whose quote names neither the Claim's subject nor its object is stored as bear context, with the reason.
- [ ] The existing contradiction tests (the evaluation case EV-CON-001, proposed updates from independent counterevidence) still pass with the new kind.
- [ ] Glossary (`CONTEXT.md`: counterevidence, bear context), decision entry, the Skeptic's and the Editor's next prompt versions, migration with the revision the lead names, API client regenerated.
