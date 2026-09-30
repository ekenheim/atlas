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

## Investigation 1, re-run (2026-09-30, production 0.2.3, after pilot fixes 01–05)

- **ID:** `4620f8c2-709c-465a-b0ca-ee0486f3e1b2`. **Seeds:** Lumentum, Coherent (same question). **Stop:** `needs_review` (the Editor asks for review). **Usage:** 93,530 tokens in, 11,149 out, 1 round, 12 role calls (Scout, 8 Investigator batches, Skeptic, Analyst, Editor); 2 minutes wall time (18:16–18:18 UTC).
- **Outcome: a research card with 8 findings, 14 accepted Claims (13 Relationships: 8 `machine_reviewed`, 5 in the exceptions queue), 14 open questions, and one counterparty company created (NVIDIA, CIK 1045810, resolved through SEC's ticker file and submissions).** Both Investigators read (12/13 documents, 24 passages each, 6 and 8 Claims accepted); the Skeptic, Analyst and Editor all ran.

**Saved work** (correct, useful, cited to a primary span):
1. Lumentum `capacity_constrained`: "This demand is outpacing our current supply which has required us to make decisions on supply allocation." (10-K filed 2026-08-17, Item 1). The direct answer to the question's second clause. In the exceptions queue (hedge-free, so it should be approvable).
2. Coherent `supplies` → **NVIDIA**: "entered into a strategic multi-year supply agreement with NVIDIA for advanced lasers and optical networking products supporting next-generation AI infrastructure" (10-K filed 2026-08-14). The edge pilot 1 could not form; `machine_reviewed`.
3. Coherent `expands_capacity_for` 6-inch InP manufacturing capacity (US and Europe), layer `epi`; Coherent `uses_material` InP substrates (named among its raw materials), layer `substrate`; Coherent `vertically_integrates` transceivers and their critical components including lasers. Together they place Coherent on the InP chain the question asks about.
4. Lumentum `manufactures` high-speed laser transmitters, PICs, photodiodes, high-power laser light sources; `expands_capacity_for` new and high-growth product lines.

**Unsupported or wrong** (4 of 14 Claims; 1 of them `machine_reviewed`):
- Coherent `expands_capacity_for` **6-inch GaAs VCSEL manufacturing facilities** (`machine_reviewed`): the quote says Coherent is "operating multiple 6-inch GaAs VCSEL manufacturing facilities" while expanding InP; the expansion verb belongs to the InP clause. Wrong predicate, and the Reviewer passed it (the fix-03 report predicted exactly this failure mode: "expand" in a neighbouring clause).
- Lumentum `sole_sources` × 3 from generic risk-factor sentences ("some of our suppliers are our sole sources for certain materials, equipment and components"; "we purchase raw materials, packages and components from a limited number of suppliers"; "concerns we periodically encounter with our sole suppliers"), tagged layer `substrate` although the text names no layer. Two are in the exceptions queue; "certain components" (`chip-laser`) is `machine_reviewed`. Boilerplate, not bottleneck evidence, and the layer is an overreach.
- Coherent `sole_sources` for the **Industrial segment's** exotic materials, crystals and optics (`substrate`): off-topic for AI transceivers; correctly in the exceptions queue.
- Layer tagging is the weak spot: the Investigator tags a company-level fact with the layer the question is about rather than the layer the quote names.

**Missed evidence** (spot check of what was read):
- Each Investigator read only the 10-K's Items 1, 1A (and Coherent's Item 5): the 24-passage budget was spent before any 8-K or press release (EX-99.1: results calls with capacity and allocation statements) was opened, although 12–13 documents were "taken". The passage budget, not the document budget, is now the binding limit.
- A Lumentum `capacity_constrained` Claim was rejected `quote_mismatch` ("Due to increased demand across a range of industries, our business and customers' businesses are experiencing…"): the quote doesn't occur exactly in the `text-v2` parse. Production's filings keep their old parse (fix 04 applies to new versions only), so page-break artifacts still cost quotes.
- Nothing names an InP substrate vendor (AXT, Sumitomo Electric), MOCVD equipment, EML second sources or export controls, because no read document says so; the card's open questions ask exactly these, which is the right next round (AXT is in the universe and its filings arrive with the nightly rollout).

**Corrections needed:** the owner's review of the 5 exceptions (approve the allocation Claim; reject the three boilerplate `sole_sources` and the Industrial-segment one) and rejection of the VCSEL `expands_capacity_for` edge. Nothing else to correct by hand.

**Cost and latency:** 93.5k in / 11.1k out MiniMax tokens (3.5× pilot 1, which produced nothing), 2 minutes, no Codex operations (recall only).

**Three new defects** (tickets 06–08 in `.scratch/atlas-pilot-fixes/`):
1. **The Skeptic read nothing.** It searched 10 queries and found 59 new leads, but read 0 archived documents and 0 passages, so it proposed no counterevidence. Leads aren't Evidence and aren't fetched; the Skeptic only reads archived Source Versions it chooses, and it chose none. Either its plan should pick archived documents for the bear checklist (the other seed company's filings, older filings, the 8-Ks) or the step is empty by construction for a two-company theme.
2. **The Financial Analyst had no XBRL figure.** Every scenario input for both companies is `missing` with "No XBRL figure supplied", although both companies' companyfacts are normalized in production. Either the as-of selection, the metric names sent, or the Analyst's context is wrong; to diagnose against `GET /companies/{id}/financials?as_of=`.
3. **Leads are now on-topic but shallow.** All 10 kept leads are the seed companies' own pages (IR, homepage, LinkedIn, "About us") because the ranking rewards a company name in the title; the 90 rejected included the industry articles the Scout's queries were written for. Rank query-specific terms above company names and demote the companies' own domains and social profiles.

**Assessment:** the pipeline now produces a research card a researcher can act on, with the one edge (Coherent → NVIDIA) and the one statement (Lumentum allocation) that pilot 1 could not express. Precision is 10/14 on Claims and 7/8 on machine-reviewed edges; the misses are layer over-tagging, boilerplate sole-source language and one neighbouring-clause verb. Coverage is bounded by the 24-passage budget and by the Skeptic reading nothing. Investigation 2 (InP substrates: AXT, Coherent, Lumentum) runs after tonight's rollout brings AXT's filings in.
