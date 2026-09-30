# Research pilot results

## Investigation 1: laser chips for 800G/1.6T (2026-09-30, production 0.2.1)

- **ID:** `c7674cb9-8582-4e6f-8ac5-3f6d2c6233fb`. **Seeds:** Lumentum, Coherent. **Stop:** `no_new_independent_evidence` ("the Investigator accepted no Claims"). **Usage:** 26,828 tokens in, 475 out, 1 round.
- **Outcome: no research output at all.** 0 Claims, 0 Evidence and no card; the Skeptic, Analyst and Editor were skipped.

What worked:
- **The Scout's queries follow the bottleneck method well:** 10 layer-tagged queries covering EML capacity at 200G/lane, second EML sources, InP wafer supply (Sumitomo, IQE), CW lasers for silicon photonics, VCSEL sources, MOCVD tool supply, indium, gallium and germanium feedstock, NVIDIA allocation agreements, EML qualification cycles, and InP export controls.

What failed (four defects, each reproducible):
1. **The document budget was spent by the first Investigator.** Coherent's task took all 25 documents; Lumentum's read 0 (200 dropped). The budget must be split across seed companies.
2. **The leads were junk.** The 10 leads taken (of 100) were dictionary entries for "coherent", Wikipedia pages, Swedish-language pages (Avanza, bab.la, Kista) and a Merriam-Webster definition. SearXNG answered in the instance's locale (sv), and lead ranking kept generic pages over results matching the query. It needs `language=en` and relevance ranking against the query and its purpose.
3. **The Investigator proposed nothing from relevant text.** It saw 24 passages from Coherent's FY2026 10-K Items 1 and 1A (business and risk factors: where capacity, sourcing and in-house InP statements live) and returned `{"claims": []}` in all 4 calls. The claim model and prompt only express two-party relationships with a named counterparty and directional language. 10-Ks rarely name customers, and they state bottleneck facts about the company itself ("we manufacture our own InP substrates", "demand exceeds supply", "we are adding capacity in Sherman, Texas"). Those facts have no place in the current Claim schema, so the Investigator correctly returns nothing, and the research card is empty.
4. **As a result, the Skeptic, Analyst and Editor never ran.** One weak step stops the whole plan, with no partial card.

Assessment: evidence traceability holds, but the research pipeline, as specified, can't express most bottleneck evidence. This is the Codex review's concern in concrete form, and the priority for the next development work.
