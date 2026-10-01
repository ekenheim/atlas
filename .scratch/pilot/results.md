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

## Investigation 1, third run (2026-10-01, production 0.2.5, after pilot fixes 06–12)

- **ID:** `ead2b86e-3556-42ba-9f3e-08660a938f98`. **Seeds:** Coherent, Lumentum (the same question). **Stop:** `needs_review` ("4 findings are contradicted by independent counterevidence"). **Usage:** 141,344 tokens in, 17,498 out, 1 round, 16 role calls (Scout, 8 Investigator batches, the Skeptic's plan and 4 readings, Analyst, Editor); 5 minutes 29 seconds (16:46:27–16:51:56 UTC).
- **Outcome:** a research card with 5 findings from 10 accepted Claims (15 more rejected), 9 new Relationships (3 `machine_reviewed`, 6 in the exceptions queue) and more Evidence on one existing edge, 30 counterevidence items (29 accepted), 7 open questions, and production's first 16 Candidates. Run `a54b3ec5-3466-4038-a9be-b39cce2b636a`, discovery `ca235cf4-e60c-408e-a8a8-83fc6f43dd43`, extractions `be086921-ee92-41c2-a715-90840b24595e` (Coherent) and `40d93d72-826c-415a-8348-b7642ed301ac` (Lumentum).

**Saved work** (correct, on the question, cited to a primary span):
1. Coherent is expanding InP capacity and names a shortage: "including expanding our indium phosphide capacity in Sherman, Texas, to address our increased customer demand and industry-wide shortage" (10-Q filed 2026-05-06); "We continue to expand our global 6-inch InP manufacturing capacity in the United States and Europe" (10-K filed 2026-08-14). New: the 10-Q was not read before.
2. NVIDIA bought 7,788,161 Coherent shares for $2 billion on 2026-03-02 (10-Q), and "NVIDIA’s investment will support research and development initiatives, future capacity expansion, and operational capabilities, as Coherent expands its U.S.-based manufacturing footprint" (8-K filed 2026-03-02). New: a customer financing a laser supplier's capacity.
3. "NVIDIA is investing $2 billion in Lumentum to support R&D, future capacity and operations as the company builds out its U.S.-based manufacturing capabilities in a new fab" (8-K filed 2026-03-02, EX-99.1). New.
4. Coherent designs and makes its transceivers and "many of their critical components, including lasers, detectors, ICs, passive optics, thermal solutions, and PICs" in house (10-K). A catalog fact, counted once.

**Unsupported or wrong** (4 of 10 Claims; 2 of them `machine_reviewed`):
- Lumentum `owns` NVIDIA: the quote says Lumentum issued Series A preferred stock **to** NVIDIA. The direction is reversed. In the exceptions queue; the card's finding states the fact the right way round.
- Coherent `capacity_constrained` "manufacturing capacity" (`module`): the quote says Coherent is "prioritizing investments to expand manufacturing capacity". It states an expansion, not a constraint, and the object is generic. In the exceptions queue.
- Coherent `capacity_constrained` "indium phosphide capacity" and `expands_capacity_for` "indium phosphide capacity in Sherman, Texas", both tagged `substrate` and both `machine_reviewed`: the facts are right, the layer is wrong. Coherent's 10-K lists InP substrates among the raw materials it buys from third parties; Sherman is its InP device fab. On the theme map these edges make Coherent a constrained substrate maker, which misleads on exactly the question asked.
- Layers the quote doesn't name (counted right on the edge, reported here): NVIDIA `owns` Coherent, Coherent's U.S. manufacturing footprint and Lumentum's new fab all carry `chip-laser`, the question's layer. So does Lumentum `owns` NVIDIA. With the two wrong ones and the generic "manufacturing capacity", 7 of 10 Claims carry a layer their quote doesn't support.

**Missed evidence:**
- **The allocation statement is gone.** Lumentum's "This demand is outpacing our current supply which has required us to make decisions on supply allocation" (the 0.2.3 run's best finding) was not read: the passage budget now gives every document an equal share, so the 10-K got 3 passages (characters 8,628–13,178 of Item 1 and a tax note) and stopped about 2,000 characters short of it, while 8-Ks about officer changes (Item 5.02), share sales (Item 3.02) and exhibit lists (Item 9.01) each got a passage.
- **The NVIDIA supply agreements were proposed and rejected.** "The non-exclusive agreement includes an NVIDIA multi-billion-dollar purchase commitment and future access and capacity rights for advanced laser and optical networking products" (Coherent's 8-K; the same for Lumentum's "advanced laser components") was proposed four times as `supplies` or `buys_from` and rejected `party_not_in_quote`: an impersonal sentence in the filer's own document doesn't name the filer. This is the most direct answer to "who is allocation-constrained" in the archive. The 0.2.3 run's Coherent → NVIDIA `supplies` edge was not found again either: its 10-K sentence ("entered into a strategic multi-year supply agreement with NVIDIA") was in a passage the Investigator read, and no Claim was proposed from it this time.
- **Coherent's slides were read and lost.** "On track to double internal InP output by year-end and more than double again by 2027" and "6-inch platform producing EMLs, CW lasers, and photodiodes, with higher yields than 3-inch lines" (8-K filed 2026-08-12, EX-99.2) were rejected `party_not_in_quote` (a slide bullet names no company), and their May versions `quote_mismatch`: the parsed text has a non-breaking hyphen (U+2011) where the model wrote an ASCII one.
- Lumentum's own laser products (the 0.2.3 run's `manufactures` Claim) were proposed from two sentences and rejected (`party_not_in_quote`, `no_directional_language`).
- Still nothing on substrate vendors, MOCVD or export controls from the seed companies' filings. The kept leads now point at them ("AXT Signs Major InP Wafer Supply Agreement", Sumitomo Electric's InP expansion), and the card's open questions ask for them.

**Baseline** (`scripts/pilot_baseline.py`; 69 documents, 18 hits judged to reach 10 on-question): the card covers 2 of the 10 (Coherent's vertical integration; the 10-K's InP expansion paragraph), 20%. Three more are covered in substance but not in magnitude (the slides' "3X InP capacity increase", "New 6” line begins production" in Sherman, "double internal InP output by year-end"). Not covered: Coherent's laser portfolio by type (VCSEL, EML/DML, CW) with CW lasers "sold to other Transceiver Manufacturers" (two hits), Lumentum's laser components and its "particular strength in components, specifically EML chips", and whom Lumentum's chips are supplied to. All 20 hits lie in sections recall resolved to.

**The tasks:**
- **Scout** (`scout.v3`): 10 layer-tagged queries, each with a filing phrase. 173 leads found, 10 kept, all web results and all on topic (industry and market pages on InP wafers, EML/CW/VCSEL, a Yole opinion piece): the first useful web leads of the pilot, after the deploy changed the SearXNG engines. No EDGAR lead made the top 10.
- **Candidates:** 16 proposed from EDGAR filers, production's first. About 5 are on the theme (Aeluma, Veeco, Tower Semiconductor, Axcelis, Semilux); the rest come from one-word phrases ("VCSEL", "CW laser", "MOCVD", "export controls"): lidar (Hesai, Ouster), medical lasers (IRIDEX), Applied Energetics, Mesa Laboratories, NOVONIX, ECARX, Super Micro.
- **Investigators:** all 25 documents got passages (1 to 3 each), so 8-Ks, exhibits and 10-Qs are now read. 25 Claims proposed, 10 accepted; rejections: `party_not_in_quote` 9, `quote_mismatch` 3, `no_directional_language` 2, `missing_object` 1. Fix 09 worked on its two cases: the VCSEL sentence came back as `manufactures` (and was rejected for another reason), and no generic `sole_sources` was proposed.
- **Skeptic:** its plan (`skeptic-plan.v3`) answered `{"queries": [], "documents": []}`, so it searched nothing; the fallback gave it both companies' latest 10-K and 10-Q, 24 passages. It proposed 30 items and 29 were accepted, 15 of them "independent". None contradicts a Claim. They are bear-checklist context (customer concentration, inventories, dilution, risk-factor boilerplate, balance-sheet rows such as "Inventories 2,126,823 1,437,636"), attached to Claims they don't bear on: Lumentum's "for certain components we have sole or limited source supply arrangements" is recorded as independent counterevidence against Coherent's vertical integration. The card's "contradicted" marks and the stop reason are therefore noise. The context itself is useful and the Editor's open questions use it well (Coherent's inventories up 48% against revenue up 20%; Lumentum's two customers at 26% and 12%).
- **Financial Analyst:** sourced inputs from as-of XBRL for both companies (cash, diluted shares, reported revenue; total debt for Lumentum). Fix 07 works. Coherent's total debt was rejected: the observation it cited is only the current portion (7.9 million USD).
- **Editor:** 5 findings, each faithful to its quotes (the Lumentum finding states the investment the right way round although its Claim does not); verdict `needs_review`; open questions name the next documents.

**Corrections needed** (the owner's; with links in `.scratch/atlas-pilot-review/issues/09-owner-reviews-the-pilot-edges.md`): of the 6 new exceptions, approve NVIDIA `owns` Coherent, Coherent's 6-inch InP capacity, Coherent's U.S. footprint and Lumentum's new fab (the Reviewer sent all four to the queue with the same three reasons); reject Lumentum `owns` NVIDIA and Coherent `capacity_constrained` manufacturing capacity. Reject the two `machine_reviewed` `substrate` edges (a review can't change a layer).

**Cost and latency:** 158,842 MiniMax tokens (1.5 times the 0.2.3 run), 5.5 minutes; no Codex operation.

**New defects** (tickets 13–20 in `.scratch/atlas-pilot-fixes/issues/`; none is a blocker, so all wait for the verdict):
13. The party check rejects the filer's own impersonal sentences and slide bullets.
14. A typographic hyphen in the parsed text makes a correct quote mismatch.
15. The equal passage share starves the long filings and feeds administrative 8-Ks.
16. The Skeptic records bear-checklist context as contradictions of unrelated Claims.
17. `skeptic-plan.v3` returns an empty plan.
18. Layers the quote doesn't name: wrong layers reach `machine_reviewed`, and the Reviewer sends right edges to the queue.
19. `capacity_constrained` from an expansion statement; `owns` reversed for a share issuance.
20. One-word filing phrases make off-theme Candidates.

**Assessment** (the verdict criteria, `.scratch/atlas-pilot-review/issues/02-pilot-verdict-criteria.md`):

| Measure | Result | Bar | Met |
|---|---|---|---|
| Trust gate | 10 of 10 quotes verbatim at their spans; 5 of 5 findings say what their quotes say | all | yes |
| Claim precision | 6 of 10 (60%); 8 of 10 if the two wrong layers counted as right | at least 80% | no |
| Saved work | 4 findings | at least 3 | yes |
| Baseline coverage | 2 of 10 (20%); 5 of 10 counting the three hits covered in substance | at least 50% | no |
| The roles ran | Skeptic 4 documents and 24 passages; Analyst 3 and 4 sourced inputs; Editor's card with 7 open questions | all three | yes |
| Cost | 158,842 tokens, no Codex operation | at most 200,000 | yes |
| Latency | 5 min 29 s | at most 10 min | yes |

**Investigation 1 does not meet the bar** (precision and baseline coverage). Both failures rest on the stricter readings recorded in the criteria ticket's comment on 2026-10-01, after this run's results were known: on the lenient readings both measures sit exactly at their thresholds and the investigation would meet the bar. `machine_reviewed` edges: 2 of 4 right (the two `substrate` edges are wrong by layer). Against the 0.2.3 run: every role now does its work and the card has new, important facts, but precision fell from 10/14 to 6/10, and the two best earlier findings (the allocation statement, the NVIDIA supply edge) were lost: the first to the passage share, the second proposed from other sentences and rejected by the party check. A correction to the 0.2.3 review: its "7 of 8" `machine_reviewed` edges should read 6 of 8, since it also called the `machine_reviewed` "certain components" edge worthless.

## Breadth runs on 0.2.5 (2026-10-01, investigations 2 to 5, unreviewed)

Each investigation of the plan was run once on production 0.2.5 with the raised budgets (72 passages per Investigator, 48 for the Skeptic, 1,000,000 tokens per run), to see which of investigation 1's defects recur on other questions and seeds. **No Claim was checked against its span**, so there is no precision figure and these runs don't count for the verdict; the reviewed runs come on the memory-directed reading release. Everything below is read from the API and from `scripts/pilot_baseline.py`; the saved runs are in `.scratch/live-runs/breadth-0.2.5/` (not in git).

| | 2: InP substrates | 3: module assembly | 4: DSP and drivers | 5: coherent optics |
|---|---|---|---|---|
| ID | `7d266ac6-73c1-4035-ba09-ee48726f13e0` | `e5fbe2d8-4df5-43b8-a792-44c821098a3e` | `066e2cde-e7e1-4bd1-ac4e-ab688b49a88d` | `29cad6a8-fbe2-42fc-b3e9-fd68b0878fe2` |
| Seeds | AXT, Coherent, Lumentum | Fabrinet, Applied Optoelectronics, Coherent | Marvell, MACOM | Ciena, Lumentum, Coherent |
| Stop | `needs_review` | `needs_review` | `needs_review` | `needs_review` |
| Tokens in / out | 547,119 / 47,006 | 509,932 / 40,703 | 341,863 / 26,208 | 478,150 / 34,019 |
| Minutes (role calls) | 12.6 (49) | 12.2 (48) | 10.6 (37; the pod restarted during it) | 9.1 (48) |
| Claims accepted / proposed | 28 / 62 | 31 / 60 | 10 / 24 | 22 / 50 |
| Accepted by Investigator | AXT 13, Coherent 13, Lumentum 2 | Fabrinet 6, Applied Optoelectronics 12, Coherent 13 | Marvell 1, MACOM 9 | Ciena 0, Lumentum 1, Coherent 21 |
| Findings / open questions | 5 / 10 | 4 / 10 | 2 / 8 | 6 / 9 |
| Unsupported findings the Editor dropped | 2 | 1 | 1 | 1 |
| Skeptic: documents, passages, by fallback | 4, 48, yes | 4, 48, yes | 3, 48, yes | 5, 48, yes |
| Skeptic: plan queries, plan documents | 10, 0 | 10, 0 | 10, 0 | 10, 0 |
| Skeptic: items accepted, "independent" | 35, 0 | 41, 0 | 40, 24 | 48, 16 |
| Analyst: sourced inputs per seed | 3, 4, 4 | 3, 3, 3 | 3, 3 | 4, 3 (two proposals) |
| Baseline: hits holding an accepted Claim's quote | 6 of 20 | 3 of 20 | 0 of 20 | 1 of 20 |
| Baseline: accepted Claims in no hit | 25 of 28 | 26 of 31 | 10 of 10 | 17 of 22 |
| Baseline: hits in sections recall resolved to | 5 of 20 | 10 of 20 | 1 of 20 | 9 of 20 |

**Rejections by reason** (all four runs, 105 rejected of 196 proposed): `party_not_in_quote` 31, `no_directional_language` 26, `quote_mismatch` 19, `quote_outside_passage` 12, `unresolved_company` 9, `object_not_in_quote` 3, `missing_object` 2, `generic_object` 2, `cue_in_other_clause` 1.

**What recurs from investigation 1** (each already a ticket of `.scratch/atlas-memory-directed-reading/`):
- The party check is the largest single loss on every question (5 to 11 Claims a run; ticket 02).
- Quote mismatches cost 1 to 8 Claims a run (ticket 02's fold covers the typographic ones; the rest need looking at on the release).
- The Skeptic's plan chose no document in any run (it did write 10 queries each time, unlike the empty plan of investigation 1), so all its reading came from the fallback; it accepted 35 to 48 items a run, most of them attached to no Claim (tickets 03 and 07).
- The layer follows the question: 18 of investigation 2's 28 accepted Claims are tagged `substrate`, 17 of investigation 3's 31 `module`, 9 of investigation 4's 10 `dsp` (ticket 08).
- The cards cover little of what a term search finds, and on these questions recall with the whole question covers little of it either (1 to 10 of 20 hits lie in a recalled section, against 20 of 20 for investigation 1): the long question recalled with one company's scope is a poor query, which is what the reading pointers replace (tickets 01, 05, 06).

**New in these runs:**
- **Some Investigators propose almost nothing.** Ciena's Investigator proposed 1 Claim from 72 passages (rejected), Marvell's 5 (1 accepted), Lumentum's 2 or 3, against 46 from Coherent's in investigation 5. The passages are dealt in text order, not by relevance, so 72 passages of a systems or DSP company are mostly not about the question; ticket 05 changes which passages are read, and the reviewed runs will show whether the predicates also fail to fit these companies.
- **The allocation statement is now read and still lost.** In investigation 5 Lumentum's "This demand is outpacing our current supply which has required us to make decisions on supply allocation." was proposed as `capacity_constrained` with object "our products" and rejected `object_not_in_quote`. The sentence names no product: the constraint is the company's. Fix 09's rule (a bottleneck Claim needs a named, specific object) rejects the pilot's most valuable kind of statement. New ticket 09 of the memory-directed reading spec.
- **Acquisitions of private companies are lost:** Marvell `owns` Celestial AI and XConn were rejected `unresolved_company` (no exact match in SEC or GLEIF). A candidate for the counterparty work, not this release.
- **Filing leads crowd the kept leads.** In investigations 3 to 5 the ten kept leads are nearly all EDGAR hits, often one filer many times (eight POET Technologies 6-Ks in investigation 3). Investigation 2's ten are web results and on the point ("China Export Curbs Delay AXT's US-Bound Indium Phosphide Shipments", "AXT Subsidiary Secures Export Permits in China"). Ticket 04's ranking version 3 scores filing leads differently; a cap per filer is not built.
- **The baseline repeats itself across filings.** For investigation 2 its top five hits are the same export-permit paragraph in five AXT filings, worded slightly differently each time; exact-duplicate dropping doesn't catch that. The baseline needs near-duplicate dropping before the reviewed runs.
- **Cost:** 368k to 594k tokens and 9 to 13 minutes a run at 72 passages, inside the new bars (1,000,000 tokens, 20 minutes). The four runs spent about 2.0 million tokens of the 4 million window.
