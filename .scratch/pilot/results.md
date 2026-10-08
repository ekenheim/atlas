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

## Investigation 1, fourth and fifth runs (2026-10-02, production 0.3.0 and 0.3.1, memory-directed reading)

- **Fourth run (0.3.0), no card:** `fcb1ef32-50fd-4788-84c3-e2397a92dd97`. Six Investigators from two seeds, 89 accepted Claims, every quote verbatim; the Editor's answer was cut off at its 4,096-token output cap on all six attempts, so the investigation stopped `needs_review` with no research card (1,243,309 tokens in, 111,002 out; 30.5 minutes with a pod restart). A blocker; fixed by memory-quality ticket 16 and released as 0.3.1. Its Claims were not reviewed.
- **Fifth run (0.3.1), reviewed here. ID:** `452c3b9d-2e2f-4cc6-bc54-5130155b9aac`. **Seeds:** Lumentum, Coherent (the same question; a 2,000,000-token budget in the request). **Stop:** `needs_review` ("the Editor asks for review"). **Usage:** 1,445,503 tokens in, 140,885 out; 85 role calls (Scout 1, Investigator 72, Skeptic 9, Financial Analyst 2 of which 1 quarantined, Editor 1); 34 minutes 45 seconds (10:07:28 to 10:42:13 UTC), no budget pause.
- **Outcome:** a research card with 11 findings and 18 open questions from **182 accepted Claims** (309 more rejected); 42 new Relationships by the time the run was saved (41 in the exceptions queue, 1 `machine_reviewed`); 38 bear-context items, no contradiction. The Scout stored 1,009 reading pointers from 11 recalls; the plan grew from the two seeds to six Investigators (AXT 159 pointers, Applied Optoelectronics 42, IQE 9, MACOM 8, all added; Fabrinet, STMicroelectronics and Ciena were pointed at and had no room). 154 of the 182 Claims rest on call and conference transcripts (Tier B), 28 on filings or results releases.

**How it was reviewed.** Fifteen Opus reviewers, each working from files cut out of the saved run (`.scratch/live-runs/pilot-0.3.1/inv-1/review/`, not in git): every accepted Claim judged twice by two judges who could not see each other's work (the lead checked from their transcripts that neither read the other's notes), one reviewer for the card against its cited quotes, one for the baseline, one for the run. The lead ran the trust gate's span check (182 of 182 quotes verbatim at their span), adjudicated the judges' disagreements, read every Claim both called wrong and a seeded sample of 18 they both called right (all 18 hold). The two judges are the same model with the same rubric, so their agreement (174 of 182, kappa 0.81) shows consistency, not independence: the owner's edge decisions remain the independent check.

**Saved work** (correct in what its cited quotes say, on a clause of the question):
1. **InP substrates are the feedstock constraint, with figures** (finding 5, fully supported): AXT's "Demand just completely outpaces our ability to increase capacity, even though we've increased capacity, or we're about to increase capacity 3x this year. Just simply can't keep up with it." AXT is doubling InP capacity in 2026 and planning to double again in 2027 (finding 6), and has a Master Development and Supply Agreement with Coherent for 6-inch InP substrates (June 26, 2026, three years) and a Capacity Reservation Agreement with Lumentum (six years, a minimum annual commitment) (finding 7). New: AXT was not a seed; Memory's pointers led there.
2. **Coherent names an industry-wide InP constraint and gives its expansion** (finding 2): "Given the exceptionally strong demand environment and the industry-wide constraint in indium phosphide, capacity expansion remains one of our highest priorities"; internal InP output doubling year on year and "more than double ... again by the end of calendar 2027"; 6-inch lines in Texas and Sweden "producing EMLs, CW lasers, and photodiodes with yields that continue to exceed our 3-inch lines" (finding 1).
3. **Lumentum is sold out and says when capacity comes** (finding 11): "The strain on our fab is high, right? We're very much sold out in our high-powered laser fab"; the ultra-high-power laser ramps in the U.K. fab from the second quarter of 2027 and Greensboro from mid-2028; "over 50% EML unit growth by the December 2026 quarter".
4. **Applied Optoelectronics is sold out and tripling laser capacity** (finding 10, fully supported): "we have to say, 'Sorry, we're really sold out at least through second half of next year and beyond'"; "we need to triple, even more than triple our laser manufacture capacity by Q2 next year"; the $300 million Texas investment.
5. **MACOM's lead times are stretching** (finding 9): "Utilization rates are definitely driving some of our lead times out, so we are quoting longer lead times for products that are manufactured inside of MACOM"; and of its $61 million investment in IQE: "We believe this investment will strengthen our supply chain resilience and competitive position."
6. **Coherent supplies NVIDIA under a multi-year agreement** covering "multiple CPO-related products, including our high-power CW laser", beside NVIDIA's $2 billion equity investment (the Claims under finding 3; the finding's own sentence is garbled, below).
Counted as the criteria count them (a company's product catalog once): nine of the eleven findings carry a correct, on-question core; two (5 and 10) are supported in every part.

**Unsupported or wrong.**
- **The card says more than its Claims (the trust gate's second half fails).** Nine of the eleven findings state something no cited Claim says, and five misstate what one says. The lead traced the additions: figures from the Skeptic's bear context written into findings as if evidenced by their Claims (AXT's "$600.1 million net" offerings in finding 6; IQE's "£81m fundraise" and "332,183,678 new ordinary shares" in finding 8; a "shortfall payment obligation" in finding 7); a place name from a web lead's title ("Järfälla, Sweden" in finding 1: a Tier C lead in a finding); Claims cited by another finding ("Zurich"); and errors of the Editor's own: "Covert is Coherent's laser customer for NVIDIA" (finding 3; "Covert" occurs nowhere), Coherent "vertically integrated" in InP where the quote says garnet (finding 4), the two AXT agreements run together as one with Coherent (finding 7), "adding capacity for VCSEL arrays" from a statement of existing capacity (finding 2), "200G-per-lane" added to MACOM's photodetector design wins (finding 9). Every quote on the card is real; the sentences around them are not held to them. Pilot-fix ticket 21.
- **28 of 182 Claims are wrong on the strict reading (precision 154 of 182, 84.6%); 7 of the 28 are right in context (161 of 182, 88.5%).** By reason: the predicate does not fit the quote 8 (a capacity level, a production ramp or a reservation read as an expansion; a demo read as integration); a plan or expectation stated as fact 6 ("We expect to have 1.6T in production this year"; "We expect full qualification ... within the next couple of weeks"); the object is not in the quote 6 (three of them right in context: "we are doubling our capacity", the product named a sentence earlier); the subject is not the actor 2 (an industry-wide EML shortage made Applied Optoelectronics' own constraint); **an analyst's words taken as the company's 2** ("you are expanding to Indium phosphide fabs in Japan", said by a Deutsche Bank analyst to Lumentum); the verb belongs to another clause 2; the layer is wrong 2 (IQE's epiwafer products tagged `chip-laser` because the quote says "laser"). By predicate: `expands_capacity_for` 42 of 55 right, `qualified_for` 4 of 7, `capacity_constrained` 7 of 9, `manufactures` 57 of 65, the other five predicates 44 of 46. By company: Lumentum 13 of 20, Applied Optoelectronics 29 of 35, AXT 30 of 36, IQE 5 of 7, MACOM 20 of 23, Coherent 56 of 60, NVIDIA 1 of 1.
- **82 of the 182 are catalog facts** (`manufactures` or `vertically_integrates` with no capacity, constraint, relationship or figure), and 52 to 64 are off the question (photodiodes, isolators, defence products, smartphone sensing). Right, on the question and more than catalog: 63 Claims, most of them `expands_capacity_for` (35), then `supplies` (8), `uses_material` (7) and `capacity_constrained` (7).
- None is boilerplate. Of the 95 Claims with a layer, both judges found the quote supports it for 85; for 6 at least one judge found it only unconfirmed, and for 4 at least one found it wrong (2 after adjudication, both IQE's). 87 Claims carry no layer, which is the new rule working.

The 28, each with its quote:

| Claim | Why wrong | Quote |
|---|---|---|
| Coherent `manufactures` 1.6T transceivers (module) | "We expect to have 1.6T in production this year." This is an expectation, stated as the fact that Coherent manufactures 1.6T transceivers. | "We expect to have 1.6T in production this year." (Investor Day 2025) |
| Coherent `expands_capacity_for` VCSEL array capacity (chip-laser) | "Today, we have capacity for over 1 billion VCSEL arrays per year" states a capacity level, not an expansion. "increased capacity" is in the preceding sentence and is about the GaAs lines. | "Today, we have capacity for over 1 billion VCSEL arrays per year." (European Conference on Optical Communica) |
| Coherent `manufactures` 200G VCSEL (chip-laser) | "In our tool chest is the 200G VCSEL. We continue to make good progress on that." Development progress; "we think that'll be deployed" is future. Not stated as manufactured. | "In our tool chest is the 200G VCSEL. We continue to make good progress on that." (Q4 2026) |
| Coherent `vertically_integrates` indium phosphide lasers (chip-laser) | "We demonstrated a 1.6T DR8 transceiver... with our own indium phosphide laser": a conference demo, not in-house supply for products; product "CW lasers" not in quote. | "We demonstrated a 1.6T DR8 transceiver at the Optical Fiber Conference last year with our own indium phosphide laser and our own 200G per lane silicon photonics." (Investor Day 2025) |
| AXT `manufactures` InP wafer substrates (substrate) | The quote says "compound and single element semiconductor substrate wafers". InP is not named, so the object "InP wafer substrates" is unsupported. | "AXT is a worldwide materials science company that develops and produces high-performance compound and single element semiconductor substrate wafers and certain raw materials integral to these substrat" (AXT INC 10-Q filed 2026-08-13) |
| AXT `expands_capacity_for` InP wafer substrates (substrate) | "agreed to reserve a minimum annual commitment of the Products by Lumentum" is a capacity reservation, not added capacity. "support any additional capacity that may be required" is conditional. | "AXT has agreed to reserve a minimum annual commitment of the Products by Lumentum (the “Product Capacity”) for a six (6) year period beginning upon entry into the Agreement and to support any addition" (AXT INC 8-K filed 2026-07-29) |
| AXT `expands_capacity_for` indium phosphide [right in context] | object_not_in_quote: the quote says "our capacity"; indium phosphide is only in the talk around it | "We're currently expanding our capacity, so we are doubling our capacity through 2026. By the end of this year, we should be double our capacity from the end of 2025." (28th Annual Needham Growth Conference Vi) |
| AXT `expands_capacity_for` indium phosphide | "we are well into the planning process to double our capacity again in 2027" is a plan, neither committed nor under way. "This will make AXT..." reads firmer, so I am unsure. | "we are well into the planning process to double our capacity again in 2027 in an adjacent location. This will make AXT by far the largest indium phosphide producer in the world." (Q2 2026) |
| AXT `manufactures` 8-inch gallium arsenide wafer | "we have developed an 8-inch gallium arsenide wafer ... scheduled to begin production in 2024", and then "its end-user customer cancelled its project". AXT never manufactured it. | "we have developed an 8-inch gallium arsenide wafer targeting an application in a consumer product, which was scheduled to begin production in 2024." (AXT INC 10-Q filed 2026-08-13) |
| AXT `expands_capacity_for` indium phosphide | "The capacity is growing faster than we thought." names no product. InP is only inferable from the call, so it is probably true but not in the quote. | "The capacity is growing faster than we thought." (Q2 2026) |
| Applied Optoelectronics `manufactures` four-inch substrate (substrate) | "we just move into a four-inch substrate volume manufacture" means AOI makes products on four-inch wafers; context names its substrate suppliers ("two supplier in Europe, two supplier in Japan, plus three supplier in China"). | "Yeah. I think especially right now, AOI, we just move into a four-inch substrate volume manufacture." (Q2 2026) |
| Applied Optoelectronics `capacity_constrained` EMLs (chip-laser) | "there's a very serious problem with shortage of lasers, especially for EML" describes an industry-wide shortage; it does not say AOI cannot meet demand for EMLs. | "Right now, you know there's a very serious problem with shortage of lasers, especially for EML, okay? Not to mention 200G, even 100G EMLs." (Q3 2025) |
| Applied Optoelectronics `expands_capacity_for` indium phosphide wafer capacity | "which will allow expansion of our indium phosphide capacity" makes an expansion possible; it does not commit to one. Unsure: AOI states a committed InP tripling elsewhere. | "which will allow expansion of our indium phosphide capacity" (Q2 2026) |
| Applied Optoelectronics `qualified_for` 1.6Tb transceivers (module) | "We expect full qualification of our first 1.6Tb product by this customer within the next couple of weeks" - qualification only expected, not done. | "We expect full qualification of our first 1.6Tb product by this customer within the next couple of weeks, followed by shipments of 1.6Tb beginning later this quarter." (Q2 2026) |
| Applied Optoelectronics `qualified_for` 1.6T transceiver (module) | "I think AOI will be the fourth supplier qualified"; context: qualification "should be finished within maybe ... two, three weeks" - not yet qualified. | "I think AOI will be the fourth supplier qualified by one big hyperscale data center customer for 1.6T transceiver." (Q2 2026) |
| Applied Optoelectronics `expands_capacity_for` 800G and 1.6T transceiver products (module) | The quote names only 800G: "ship an increasing amount of 800G products from our Texas facility as we expand our capacity". The object adds 1.6T, which it does not mention. | "We expect that we move throughout the year to ship an increasing amount of 800G products from our Texas facility as we expand our capacity." (Q4 2025) |
| Lumentum `capacity_constrained` EML CW lasers (chip-laser) | "in a constrained environment, we also see customers' behavior as wherever they can get a laser source" describes the market; it does not say Lumentum cannot meet demand. | "in a constrained environment, we also see customers' behavior as wherever they can get a laser source, they will use that solution to support their build-out. The dynamics of EML CW lasers is not only" (Q4 2026) |
| Lumentum `expands_capacity_for` ultra-high power laser (chip-laser) [right in context] | object_not_in_quote: "The third ramp is our Greensboro fab"; the laser is named two sentences earlier | "The third ramp is our Greensboro fab. We start to ramp in second quarter 2028 or mid 2028 as the third ramp." (Citi’s 2026 Global TMT Conference) |
| Lumentum `expands_capacity_for` Indium phosphide | "you are expanding to Indium phosphide fabs in Japan" is said by Gianmarco Conti (Deutsche Bank analyst). | "you are expanding to Indium phosphide fabs in Japan" (Deutsche Bank 2026 Technology Conference) |
| Lumentum `expands_capacity_for` indium phosphide capacity | Spoken by Samik Chatterjee (JP Morgan analyst): "Maybe I'll start off on the indium phosphide capacity ramp..." | "Maybe I'll start off on the indium phosphide capacity ramp, and just to clarify what you said in your prepared remarks, you pulled forward or front-end loaded some of that capacity increase that you h" (Q2 2026) |
| Lumentum `expands_capacity_for` indium phosphide wafer fab capacity [right in context] | object_not_in_quote: "our 40% expansion target"; the InP wafer fab capacity is the sentence before | "We have front-loaded our 40% expansion target, delivering on over half of that this past quarter." (Q2 2026) |
| Lumentum `manufactures` CW lasers (chip-laser) [right in context] | verb_not_on_object: the making cue is "800 gig manufacturers" (the customers); Lumentum is "shipping CW lasers" | "Simultaneously, we expanded our footprint in next-generation architectures, shipping CW lasers for 800 gig manufacturers and increased volumes of ultra-high power laser shipments for CPO applications." (Q2 2026) |
| Lumentum `vertically_integrates` CW lasers (chip-laser) | "Still the plan ... our timeline is pushed out a bit ... introducing our own CW lasers ... pushed out to late Q2, early Q3": a delayed plan, not in-house supply yet. | "Still the plan. Yeah, we, we had shipped, you know, CW lasers to the external market for the first time, Ryan, last quarter. Those shipments continue to sort of help us develop and improve our CW lase" (Q2 2026) |
| MACOM `expands_capacity_for` indium phosphide products [right in context] | predicate_does_not_fit: "ramping up our indium phosphide products" is a production ramp; "adding capacity" is elsewhere in the answer | "The mix here in the Massachusetts fab is a combination of telecom, defense, and now data center. This is sort of a new trend as we're really ramping up our indium phosphide products here." (Q3 2026) |
| MACOM `expands_capacity_for` production and engineering equipment as well as our facilities | "expand capacity to meet demand requirements across our end markets and also upgrade and enhance our production and engineering equipment". The equipment is upgraded; capacity is not added for it. | "We estimate fiscal year 2026 CapEx to be in the range of $55 million-$65 million as we expand capacity to meet demand requirements across our end markets and also upgrade and enhance our production an" (Q2 2026) |
| MACOM `manufactures` high-power GaN technology | "a customer that produces a drone defense system ... their expected production ramp-up ... utilizing our high-power GaN technology". The production is the customer's. | "we have been collaborating with a customer that produces a drone defense system, and we look forward to their expected production ramp-up in 2026, utilizing our high-power GaN technology." (Q4 2025) |
| IQE `qualified_for` laser and detector products enabling next-generation AI and hyperscale data centre infrastructure (chip-laser) [right in context] | layer_wrong: IQE makes epiwafers; its "laser and detector products" are epi, not chip-laser | "Secured multiple Tier 1 customer design wins for laser and detector products enabling next-generation AI and hyperscale data centre infrastructure, while simultaneously launching 6-inch foundry platfo" (IQE plc: H1 2025 Interim Results) |
| IQE `manufactures` VCSEL products (chip-laser) [right in context] | layer_wrong: IQE's VCSEL products are epiwafers; and the product is smartphone 3D sensing | "Successfully qualified and commenced production ramp of second-generation 3D sensing VCSEL products for a leading global smartphone platform, reinforcing position in premium consumer devices." (IQE plc: FY 2025 Financial Results) |

**Missed evidence.**
- **The seeds' filings were not read.** Every document the Lumentum and Coherent Investigators took was a call or conference transcript their pointers named (4 and 5 documents; 221 and 349 others dropped); no 10-K, 10-Q or 8-K of either. So Lumentum's allocation statement in its 10-K ("This demand is outpacing our current supply which has required us to make decisions on supply allocation") is again not on the card, though its call says the same more bluntly ("fully allocated to meet surging customer demand" is the sentence before an accepted quote, and "sold out" is accepted). NVIDIA's purchase commitments and the slides' capacity figures in the 8-K exhibits were not read either. Pilot-fix ticket 24.
- **The Skeptic checked two of six companies.** It made 36 recalls (3,112 pointers) and read 6 documents, all AXT's and IQE's and all already read by Investigators; nothing of Lumentum, Coherent, Applied Optoelectronics or MACOM (135 of the 182 Claims). The document budget was spent (25 of 25) and the pointers for those four lead to transcripts, which the Skeptic does not read. "No contradiction" therefore means "none found for AXT and IQE; the rest not checked". Its 38 accepted items are all bear context, 24 of them about IQE and 14 of those its financing. Pilot-fix ticket 25.
- **The equipment clause has no finding.** MOCVD or other tools appear only in one Lumentum quote about "getting reactors"; no equipment maker is in the universe.
- **No laser supplier outside the six read companies** (Broadcom, Mitsubishi, Sumitomo, the Chinese makers) appears except as an open question.

**Baseline** (the first 11 hits read to reach 10 on the question; `scripts/pilot_baseline.py`, 20 hits from 98 documents): on the question 10; **covered on the strict reading 5 of 10, on the lenient reading 10 of 10.** The five covered only in substance are hits whose point is a figure or a date the card does not carry: Coherent's "3X InP capacity increase" from 2023 to 2025 and "2X capacity increase next quarter in Sherman" (May 2025), its 250 million InP lasers and 1 billion VCSELs shipped and its sale of VCSELs to other transceiver makers, the 200G-VCSEL-based 1.6T ramp in the second half of 2026 (two hits), and Lumentum's 200G EML shipments "to multiple customers" with its EML business to "more than double" by the end of 2025. All five lie in filings and slides the Investigators did not open.

**Corrections needed** (the owner's decisions; the lead applies none). The exceptions queue gained 41 edges from this run, nearly all because their Evidence is a transcript (Tier B) and only Tier A makes a `machine_reviewed` edge. The one `machine_reviewed` edge of the run, AXT `manufactures` germanium substrates, is right. Recommendation: reject the edges of the 21 Claims that are wrong on any reading (the table above, those not marked "right in context"), and decide the open question of ticket 17 before approving 40 edges one by one: whether a management statement in a transcript may make a `machine_reviewed` edge.

**Cost and latency.** 1,586,388 tokens, inside the 2,000,000 bar. 34 minutes 45 seconds, outside the 20-minute bar: the 85 role calls run one after another (1,748 seconds inside role calls; six Investigators from 10:09 to 10:32), and 28.5% of the tokens went to schema repairs (29 of 72 Investigator calls answered with an extra `subject_name` or `claim_id` field and were asked again). Recall cost no LLM token: 47 recalls, 2,089 memories, 4,121 pointers, about 5 minutes of wall time (the Skeptic's 36 recalls took 233 seconds).

**New defects** (tickets in `.scratch/atlas-pilot-fixes/issues/`):
- 21: a finding says more than its Claims (bear context, a lead's text and the Editor's own errors in finding statements). The trust gate; fixed before the verdict runs.
- 22: an analyst's words accepted as the company's statement (2 Claims).
- 23: a plan, an expectation or a ramp accepted as fact, and an object that is not in the quote (20 Claims).
- 24: an Investigator reads only what the pointers name, so a seed's filings go unread.
- 25: the Skeptic checks only the companies whose pointers lead to Tier A documents, inside a document budget the Investigators have already spent.
- 26: the Investigator's answers carry extra fields; 28.5% of the run's tokens are repairs.
- 27: role calls run one after another; six Investigators take 23 minutes.
- 28: smaller ones kept together: the Financial Analyst's rejected inputs (a Decimal type error on `addressable_units` and `company_share`) and its inconsistent Coherent debt figure; six of the ten kept leads are one syndicated story; the `search` selection tag is on every passage, so it says nothing about which channel found a Claim; two Skeptic items rejected with document-scale offsets (one is AXT's export-permit backlog sentence); IQE's epi products tagged `chip-laser`.

**Assessment** against the verdict criteria (`.scratch/atlas-pilot-review/issues/02-pilot-verdict-criteria.md`):

| Measure | Result | Threshold | Met |
|---|---|---|---|
| Trust gate: quotes verbatim at their spans | 182 of 182 | all | yes |
| Trust gate: findings say what their Claims say | 2 of 11 in every part; 5 of 11 misstate a Claim | all | **no** |
| Claim precision | 154 of 182 (84.6%) strict; 161 of 182 (88.5%) lenient | at least 80%, at least 5 accepted | yes |
| Saved work | 9 findings with a correct on-question core (2 supported in every part) | at least 3 | yes on the core; no if only fully supported findings count |
| Baseline coverage | 5 of 10 strict; 10 of 10 lenient | at least 50% | yes (at the threshold on the strict reading) |
| The roles ran | Skeptic read 6 documents with 48 passages; Analyst has 4 and 3 sourced inputs for the seeds; Editor wrote a card with 18 open questions | each | yes |
| Cost | 1,586,388 tokens; no Codex operation | at most 2,000,000 | yes |
| Latency | 34 min 45 s | at most 20 min | **no** |
| Machine-reviewed edges | 1 of 1 right | pooled over the five runs | (1 edge) |

**Investigation 1 on 0.3.1 does not meet the bar:** the trust gate's second half fails and the run takes 35 minutes. What changed against the 0.2.5 run is large: 182 accepted Claims against 10, precision 84.6% against 60%, six companies read against two, the substrate maker and its agreements with both seeds on the card, baseline coverage 5 of 10 against 2 of 10 on the same strict reading. What stands between this run and the bar is the Editor's licence with its findings and the serial plan, not the reading.

## The verdict runs on 0.4.6 (2026-10-07)

**Preconditions, recorded 2026-10-07 12:20 UTC, before the first run** (the frozen procedure, section 1).

- **Version:** `atlas_build_info{version="0.4.6"}`; `/health/ready` ready (database, archive, hindsight, litellm all `ok`). `main` holds no backend or config change after `v0.4.6` (frontend and dependency updates only), so nothing is released before the runs.
- **Memory** (`GET /api/v1/memory/health`): 3,570 sections: 1,703 completed, 1,812 retired, 55 zero-fact, 0 pending, 0 failed, 0 stuck; 1,758 at profile, 0 below; 45,276 facts. Versions: 522 in Memory, 443 retired, 232 all skipped, 0 not submitted, 0 triage failed. No failed groups; nothing pending at any age.
- **Consolidation:** run `538b0cd3` (requested 2026-10-04 23:19 UTC) completed 2026-10-07 12:09 UTC after 583 rounds; `pending_consolidation` 1. Its observations are mixed: qwen3.8 27B on the 5090 (2026-10-04 11:13 to 10-05 07:19 UTC), MiniMax-M3 after, the 5090 again whenever MiniMax capped (ticket 21).
- **Reconciliation:** `eda74a86` (2026-10-07 03:30 UTC) `clean`, every count 0.
- **Conformance** (`scripts/memory-conformance.sh --only known-answers --strict`, read-only, no LLM call): **failed.** Recall at 10 is 0.08 (threshold 0.25), at 50 0.12 (threshold 0.5), over 25 answers; 2 found in the top 10, 3 in the top 50 (the before-measure on 2026-10-02: 0.22 and 0.22 over 23). By question: inp-substrates 0.50/0.75, every other question 0/0. Report: `.scratch/live-runs/pilot-0.4.6-conformance/`. The behaviours half was not run (it spends MiniMax, and the weekly allowance was at 81%).
  - Diagnosis, one recall per probe query through `POST /memory/recall`: a laser-chips recall returns 23 observations of 29 memories, mostly built from call transcripts and on the question; but recalling world and experience facts only points at the same 4 of 17 answer sections as recalling everything. The filings' Item 1, 1A and 7 sections that hold the answers are in Memory and ranked beyond 50 or not pointed at: filing recall, not observations crowding them out. (The check recalls at Hindsight's defaults, budget `mid` and 4,096 tokens; investigations recall at `high` and 8,192 tokens, so they reach more than this figure.)
  - **The owner's decision (2026-10-07): the runs start on the failed report**, and the verdict says so.
- **Queue:** no pause; the `minimax` window empty (0 of 8,000,000 tokens). The owner's weekly MiniMax allowance was at 81% used; a run on this version costs about 1.6M tokens (investigation 1's 0.3.1 run), so the five need about 8M.

### Investigation 1 on 0.4.6: laser chips for 800G/1.6T

- **ID:** `b226f892-2718-47ec-857e-4be38affd699`. **Seeds:** Lumentum, Coherent (the plan's question verbatim; a 2,000,000-token budget). **Stop:** `needs_review` ("6 unsupported findings were dropped; the Editor asks for review; the Skeptic did not check IQE"). **Usage:** 933,832 tokens in, 53,822 out; 85 role calls (Scout 1, Investigator 72, Skeptic 9, Financial Analyst 1, Editor 2), 2 schema repairs; 1 round; 10 leads, 25 documents, 6 Investigators (Lumentum, Coherent, and AXT, MACOM, Applied Optoelectronics and Marvell from Memory's pointers); 26 minutes 16 seconds (12:22:53 to 12:49:09 UTC), no budget pause. In the last 4 minutes the lead's recall-size test (about 100 recalls) ran on production beside it.
- **Review:** two blind Opus reviewers per chunk of Claims (4 chunks), agreement 86 of 95, **Cohen's kappa 0.81**; the lead adjudicated the 9 disagreements (4 right, 4 wrong, 1 off-question), confirmed all 12 Claims both called wrong and a random 6 of the 60 both called right. Artifacts: `.scratch/live-runs/pilot-0.4.6/inv-1/review/` (`workflow-result.json`, `disagreements.json`).

**Saved work.** Three findings, each answering a clause with named companies; two fail the trust gate (below), so none is counted until fixed.
1. Lumentum on high-power CW lasers for CPO: "We see the one competitor, right, who is Coherent that AMB also signed an LTA with, right? And we are really not seeing anybody else in this high-power laser area." (claim `a823081f`). Correct and on the clause "who supplies the laser chips"; it is Lumentum's own view and covers high-power CW only.
2. AXT as the InP substrate supplier to both seeds: a Capacity Reservation Agreement with Lumentum "for the supply and capacity reservation of InP wafer substrates" (`aaa6335f`), a Master Development and Supply Agreement with Coherent "for the development and supply of certain agreed-upon specifications for 6-inch InP wafer substrates" (`adcf1b4e`), and "We agreed to increase the manufacturing capacity of the Products at our Beijing, China facility in 2026 through 2028" (`b8838257`). The feedstock clause, answered with names.
3. Coherent and NVIDIA, and Coherent's InP allocation: a multi-year supply agreement "for advanced lasers and optical networking products" (`840fe71d`) and "we allocate indium phosphide capacity to whatever drives the most, the highest margin dollars" (`a623aeff`). The allocation clause, answered.

**Unsupported or wrong.**
- **Trust gate: fails on findings 2 and 3** (the Editor's wording, not the Claims). Finding 3 says InP devices take "one- to three-month[s]" to reach shipped transceivers; the quote (`c86629a1`) says "the next quarter, two to three months later". Finding 2 says AXT "manufactures … 6-inch InP wafer substrates"; the quote (`adcf1b4e`) gives an agreement "for the development and supply" of them, and its limitations say AXT "sole-sources" quartz tubing and polishing solutions where the quote (`9b6d93e0`) says "a limited number of suppliers". Both Claims under them are verbatim and right.
- **Claims:** 64 right, 16 wrong, 15 off-question of 95 accepted: **precision 67%**. (`9b6d93e0`, "We depend on a limited number of suppliers for … quartz tubing, and polishing solutions", is right: Atlas's `sole_sources` reads "a single supplier or a limited number of suppliers"; first adjudicated wrong, corrected 2026-10-07. The hedged "may only be available from a single or limited number" stays wrong.) (Atlas's layer taxonomy puts photodiodes and photodetectors in `chip-laser`, `backend/atlas/claims/predicates.py`; so MACOM's photodetector `bd5d0352` is off-question, for a question about laser chips, not a wrong layer.) Wrong, by kind: direction reversed (`5cd6f7b1`, "Coherent owns NVIDIA" from NVIDIA's equity investment in Coherent); the verb acts on another object (`a592ecc0` expansion of the Sherman facility read onto the NVIDIA products; `e7b404ab`, `83d2a57d`, `4d329e86`); development or qualification read as manufacturing or qualified (`e41817db`, `81b76dc6`, `90f3c158`); a revenue ramp read as capacity (`eeddeee4`); an industry shortage read as MACOM constrained (`07dcf257`); hedged "may only be available from a single or limited number of suppliers" read as sole-sourcing (`417642df`); an object the quote doesn't name, taken from the sentence before (`fd599919`); optical components tagged chip-laser (`459f2321`); AXT "uses" SOI or its own InP substrates (`c9c5df8c`, `17510241`); `10f8d03c`. Off-question: Coherent's consumer-market VCSELs and 3D-sensing arrays (6 Claims), risk-factor boilerplate and generic descriptions. Wrong Claims with reasons and right readings: `review/workflow-result.json`.

**Missed evidence.** Lumentum as the merchant EML supplier (record EML shipments, 200G EMLs to several customers, the EML business more than doubling; baseline hit 7); the magnitudes of Coherent's InP expansion (3X capacity, double internal InP output by year-end and again by 2027; hits 1, 2, 11); VCSEL 1.6T ramp timing (hits 6, 9). Unread for the company budget of 6: IQE, Ciena, Fabrinet, STMicroelectronics, Soitec.

**Baseline.** 11 hits judged, 10 on-question: **4 covered**, 5 covered in substance (the card has the fact but not its magnitude or date), 1 not covered. **Coverage 40%.**

**A researcher's hour.** 33 cited facts, all on the question and true; about 4 are on the card, partly. The researcher had what the card lacks: Lumentum's shortfall of 25–30% of demand and its EMLs sold out, Coherent saying InP stays constrained through 2027, AIXTRON MOCVD reactors at both, TrendForce EML and CW-DFB shares, Sumitomo and JX substrate expansion, AXT's export-permit shortfall. Of the card's 3 findings, the researcher's answer has 1 (finding 2, AXT, through the Lumentum capacity reservation); the card's own were Lumentum's competitor view, the Coherent–NVIDIA agreement and InP allocation, AXT's 6-inch agreement with Coherent and its Beijing expansion.

**Corrections needed.** The edge decisions (ticket 09's rule) are applied after the fifth run, so that no write reaches production during a run.

**Cost and latency.** 987,654 tokens, inside the 2,000,000 bar. 26 minutes 16 seconds, outside the 20-minute bar.

**New defects** (tickets after the fifth run):
- The Editor's findings paraphrase past their quotes (the trust gate).
- The Investigator tags the question's market on product-catalog sentences of other markets (consumer VCSELs, 3D sensing).
- Hedged or "limited" supply language becomes `sole_sources`.
- Generic "optical components" are tagged `chip-laser`.
- Recall's result cap, measured with the conformance check's plain recall (budget `mid`): the known answers reach 4 of 17 answer sections at Hindsight's default 4,096 tokens, 9 at 16,000 (10 with raw facts only), with no LLM call. Investigations already recall at budget `high` and 8,192 tokens (`pointer_recall_max_tokens`, observations preferred), so this overstates their gap; 8,192 against 16,000 is not measured yet. The conformance check itself recalls at the default, so its 0.08 understates what an investigation reaches.

**Assessment.** Precision 67% (bar 80%): no. Saved work 3, of which 2 fail the trust gate: no until fixed. Baseline coverage 40% (bar 50%): no. The roles ran (the Skeptic read with passages, the Analyst sourced every seed, the Editor wrote open questions): yes. Cost: yes. Latency 26 minutes (bar 20): no. **Investigation 1 does not meet the bar, and the trust gate fails.**

### Investigation 2 on 0.4.6: InP substrates as a chokepoint

- **ID:** `0e8b7e7e-f4fa-410e-8a1a-47c881531601`. **Seeds:** AXT, Coherent, Lumentum. **Stop:** `needs_review` ("2 unsupported findings were dropped; the Editor asks for review"). **Usage:** 862,391 tokens in, 50,230 out; 79 role calls (Scout 1, Investigator 66, Skeptic 9, Financial Analyst 1, Editor 2), 2 repairs; 1 round; 10 leads, 25 documents, 6 Investigators (the seeds, and IQE, Applied Optoelectronics and MACOM from pointers; STMicroelectronics, Marvell, Fabrinet, Ciena and Soitec unread for the company budget); 22 minutes 41 seconds (12:58:42 to 13:21:23 UTC), no pause.
- **Review:** two blind reviewers per chunk (3 chunks), agreement 70 of 76, **kappa 0.85**; the lead adjudicated the 6 disagreements (1 right, 5 off-question), confirmed the 5 Claims both called wrong and a random 5 of the 43 both called right. Artifacts: `.scratch/live-runs/pilot-0.4.6/inv-2/review/`.

**Saved work.** Two findings pass the trust gate and count:
2. China's export controls on InP substrates and the permits they need, from AXT's 10-Q of 2026-08-13: China added InP substrates to its export control list on 2025-02-04, and all three of Tongmei's substrate families need MOFCOM export permits. The export-control clause, with a named company and a date.
3. Lumentum: "This demand is outpacing our current supply which has required us to make decisions on supply allocation", it gets substrates, isolators and raw materials from Chinese suppliers, and it calls its UK laser fab "generally a safe harbor". The concentration clause, from a laser maker's side.
Findings 4 to 6 are faithful but don't answer the question (Lumentum's and Coherent's product catalogs and InP device-fab capacity, not substrate supply).

**Unsupported or wrong.**
- **Trust gate: fails on findings 1 and 7.** Finding 1 says AXT "supplies … 6-inch InP to Coherent" and "is increasing" Beijing capacity; the spans give a development-and-supply agreement and an agreement to increase the capacity of "the Products" in 2026 through 2028 (the same overstatement as investigation 1's finding 2). Finding 7 says MACOM is adding capacity "at its fabs" and that "a majority of its capex" goes to capacity; the spans say "We've been adding incremental capacity to support that demand" and "A majority of this CapEx", a specific capex, "and enhancing our R&D capabilities".
- **Claims:** 44 right, 5 wrong, 27 off-question of 76: **precision 58%**. Wrong: "a mix of internally produced and externally sourced" as a material (`74350fd3`); Umicore as an InP competitor where the quote names it for substrates in general (`a98397ca`); a capacity reservation read as AXT expanding capacity (`79c51b8b`); "our raw material companies produce" read as AXT using (`960a9eef`); Applied Optoelectronics "owns" Amazon from a warrant AAOI issued to Amazon's subsidiary (`79496d5c`). Off-question: Coherent's consumer, industrial and life-sciences sentences, generic material lists, pump lasers (GaAs-based), Lumentum's demand-over-supply sentence (it names no substrate).

**Missed evidence.** The binding half of the export-control clause, all in AXT's own filings: no InP permits in Q1–Q2 2025, then steadily from Q3 2025; permits for Europe, Japan, the UK and Canada but none yet for the US (Nov 2025 10-Q); no GaAs permits to the US because the customers are dual-use; InP permits "the most significant challenge" with a backlog of orders waiting (May 2026 10-Q); China's gallium and germanium controls of 2023 on AXT's GaAs and Ge substrates. Concentration: no market share at all.

**Baseline.** 10 hits judged, all on-question: **2 covered**, 1 covered in substance, 7 not covered. **Coverage 20%.**

**A researcher's hour.** 32 cited facts, all on the question and true; 5 on the card. The researcher answered all three clauses: who makes it (as the card), concentration (AXT about 40%, Sumitomo about 40%, JX about 10%, from a Needham transcript; customers qualify two suppliers; refined indium about 70% Chinese, USGS; JX's and Sumitomo's expansions), and whether controls bind (the permit timeline, no US InP or GaAs permits by August 2026, AXT's North America revenue from 8% to 2%, Lumentum's CEO on substrates "controlled by the Chinese government"). The card's findings 1 to 3 are in the researcher's answer; 4 to 7 are not (and are off the question).

**Corrections needed.** After the fifth run (edges by ticket 09's rule).

**Cost and latency.** 912,621 tokens, inside the bar. 22 minutes 41 seconds, outside the 20-minute bar.

**New defects:**
- The Editor's overstatement of agreements as present supply recurs (both runs, the same AXT spans).
- The Scout kept only SEC EDGAR filings (7 of AXT's own, 3 of Aeluma's); no market-share or trade source, though its queries asked for them.
- The Investigators read AXT's 10-Qs but did not extract the permit status, the most on-question content in them: a directional-language whitelist without a predicate for regulatory constraints (export permits) has nothing to put it in.
- `owns` from an investment or a warrant, with the direction reversed (`79496d5c`).

**Assessment.** Precision 58% (bar 80%): no. Saved work 2 (bar 3): no. Coverage 20% (bar 50%): no. Roles ran: yes. Cost: yes. Latency 23 minutes: no. Trust gate fails. **Investigation 2 does not meet the bar.**

### Investigation 3 on 0.4.6: transceiver module assembly

- **ID:** `8637ee32-4631-4c1f-897e-fc155bea9136`. **Seeds:** Fabrinet, Applied Optoelectronics, Coherent. **Stop:** `needs_review`. **Usage:** 917,577 tokens in, 62,829 out; 85 role calls, 2 repairs; 1 round; 10 leads, 25 documents, 6 Investigators (the seeds, and Ciena, Lumentum and Marvell from pointers); 24 minutes 58 seconds (13:22:11 UTC on), no pause.
- **Review:** two blind reviewers per chunk (2 chunks), agreement 66 of 71, **kappa 0.84**; the lead adjudicated the 5 disagreements (1 wrong, 4 off-question), confirmed the 11 Claims both called wrong and a random 4 of the 49 both called right. Artifacts: `.scratch/live-runs/pilot-0.4.6/inv-3/review/`.

**Saved work.** None. Finding 1 fails the trust gate (below). Findings 2 and 3 are faithful but empty: Fabrinet's "The material constraints are something that we have been used to in the past several years" and a supply-shortage risk factor (boilerplate), and Ciena's "we expect demand will continue to outstrip supply at least for the next several quarters" (a systems vendor outside the seeds; it names no module, input or customer). **The card is thin: no clause of the question is answered** (contract manufacturing and module capacity, customer concentration, qualification cycles).

**Unsupported or wrong.**
- **Trust gate: fails on finding 1.** It says Fabrinet manufactures OCS sub-assemblies and finished product; the quote (`8a834754`) is conditional, "if the customer would like us to do sub-assemblies … then we start to produce the finished product at a point in time", and never names OCS. It also drops the qualification in its own cited quote on Fabrinet as a customer's sole 400G/800G manufacturer (`fcc0bad3`).
- **Claims:** 49 right, 12 wrong, 10 off-question of 71: **precision 69%**. Wrong: development read as manufacturing (`884d539f` Coherent's 200G VCSEL "in our tool chest", `21b1ab6c`); a hypothetical or a request read as qualified (`4ee77ec1` "customers may require qualification", `bfd97c03` "we have been asked by customers to qualify"); "Coherent owns NVIDIA" again, reversed (`093d6525`); a market-wide remark read as Coherent constrained (`38896e24`); Fabrinet's "material constraints are something that we have been used to", which downplays a constraint, read as constrained (`050b6e17`); "expanding our data center transceiver business" read as capacity (`a5ad2ac1`); process technologies as a product (`8834e6c3`); Lumentum's substrates "mostly under control" read as constrained (`0e1b82ef`); spare capacity in Greensboro read as expanding (`51c04dc6`); the conditional OCS sentence (`8a834754`). Most right Claims are Coherent's InP laser capacity, which answers investigation 1's question rather than this one.

**Missed evidence.** Coherent's own transceiver assembly and test build-out (a second Malaysian site in Penang, Ipoh, Vietnam; 14 assembly sites in 7 countries); AOI's hyperscaler audit and approval of its Taiwan factory for 800G, its 800G/1.6T demand above capacity through mid-2027, its first 1.6T qualification "within weeks", and its contract-manufacturer capacity risk; all in the seeds' filings and calls.

**Baseline.** 12 hits judged, 10 on-question: **3 covered**, 0 in substance, 7 not covered. **Coverage 30%.**

**A researcher's hour.** 25 cited facts, all on the question and true; 1 on the card. The researcher placed the constraint (InP lasers, not assembly, for the vertically integrated makers; Fabrinet's shortage from the 200G EML with Lumentum now the second source; AOI's limit its own capacity and qualification), gave Fabrinet's capex ($299M against $131M) and Building 10, AOI's units per month (90k, about 200k, targets of 650k and 930k), Fabrinet's 10% customers, and the qualification timelines. Of the card's 3 findings, the answer has 1 (finding 2).

**Corrections needed.** After the fifth run.

**Cost and latency.** 980,406 tokens, inside the bar. 24 minutes 58 seconds, outside the 20-minute bar.

**New defects:**
- The Scout's 10 leads are all third-party commentary and SEO pages (thebuildout.ai, ainvest, Substacks, a vendor's "OEM SFP contract manufacturers" page); two are company pages of companies outside the universe.
- The Investigators read the seeds' assembly and qualification passages (the baseline found them in the same filings) but the Claims went to Coherent's InP capacity: the question's subject (assembly) lost to the theme's strongest signal.
- Conditional, hypothetical or downplaying sentences become positive Claims (`8a834754`, `4ee77ec1`, `050b6e17`, `0e1b82ef`).

**Assessment.** Precision 69%: no. Saved work 0: no (thin card). Coverage 30%: no. Roles ran: yes. Cost: yes. Latency 25 minutes: no. Trust gate fails. **Investigation 3 does not meet the bar.**

### Investigation 4 on 0.4.6: the DSP and driver layer

- **ID:** `995b8fb3-e87b-44ae-84ed-ff24bcac90fb`. **Seeds:** Marvell, MACOM. **Stop:** `needs_review` ("14 unsupported findings were dropped; no finding cites an accepted Claim; the Editor asks for review"). **Usage:** 897,722 tokens in, 45,671 out; 86 role calls, 4 repairs; 1 round; **3 leads**, 25 documents, 6 Investigators; 20 minutes 50 seconds (13:47:59 UTC on), no pause.
- **Review:** one chunk, two blind reviewers, agreement 33 of 36, **kappa 0.86**; the lead adjudicated the 3 disagreements (1 right, 1 wrong, 1 off-question) and confirmed the 3 Claims both called wrong. Artifacts: `.scratch/live-runs/pilot-0.4.6/inv-4/review/`.

**Saved work.** None: **the card has no finding.** The Editor wrote 14 findings, each citing accepted Claims, and the grounding check (`atlas.investigations.grounding.ungrounded`) dropped every one. They were faithful; the check failed them mechanically:
- a quoted phrase ending in a comma inside the quotation marks ("…to implement and produce highly capable TIAs and drivers,") where the Claim's quote ends in a full stop: quoted phrases must occur exactly;
- the Editor's own citation labels in the statement ("(c10, c15)"), read as numbers that no quote contains;
- nested quotation marks: the quote has `("TSMC")`, and the Editor, quoting it inside its own double quotes, wrote `('TSMC')`, which doesn't occur.
The dropped findings would have answered the question: TSMC "is currently our sole source foundry for all of our advanced process-node wafers" (Marvell, `33c3d5c9`); Marvell's 1.6T DSP family (Ara, Ara T for LRO optics, Ara X, Ara M, Petra; `90d2ab3b`) and its in-house TIAs and drivers (`19dc06d0`); Ciena on "the larger players like Broadcom and Marvell" (`ddf38a54`, `e1b07ff8`); Marvell's partners' constrained advanced-node capacity (`7ad7f58d`). The trust gate holds vacuously (no finding to misstate a Claim).

**Unsupported or wrong.** **Claims:** 14 right, 4 wrong, 18 off-question of 36: **precision 39%**. Half the accepted Claims are about the wrong layer: Coherent's InP lasers, photodiodes, VCSELs and substrates, Applied Optoelectronics' InP capacity, from Investigators the pointers sent to laser makers. Wrong: capacity read from a growth remark or a demand forecast (`52d2eb2d`, `4f8df503`), "our capacity investment" with no object in its clause (`2016b298`), the contract manufacturers' "produce" read onto Coherent (`8e8ebda9`). Off-question also: NVIDIA's $2.0B purchase of Marvell preferred stock (financing).

**Missed evidence.** MACOM is not covered at all, though it is a seed: customers moving from DSP modules to ACC and LPO for cost, MACOM's DSP in production with no further DSP R&D, its 800G/1.6T PAM4 products for DSP, LPO and LRO architectures (baseline hits 3, 6). Marvell: LPO chipsets and CPO drivers and TIAs (hit 2), Marvell DSPs sold to third-party module makers (hit 7), 1.6T coherent timing and its TIA lead (hit 8), the whole-stack claim (hit 9); magnitudes and process nodes (3 nm, 2 nm, 200G per lane).

**Baseline.** 10 hits, all on-question: **1 covered**, 3 covered in substance, 6 not covered. **Coverage 10%.**

**A researcher's hour.** 27 cited facts, 26 on the question and true; 1 on the card (as Claims, not a finding). The card has no finding to compare.

**Corrections needed.** After the fifth run.

**Cost and latency.** 943,393 tokens, inside the bar. 20 minutes 50 seconds, just outside the 20-minute bar.

**New defects:**
- **The grounding check drops faithful findings on punctuation, citation labels and replacement characters** (a whole card lost; the most damaging defect of the pilot so far, and a mechanical one).
- The Scout kept 3 leads, all EDGAR full-text hits of one query (Marvell's 10-K, Arista's and Celestica's 8-K exhibits); no SearXNG result survived.
- Memory's pointers send Investigators to the theme's laser makers whatever the question's layer (Coherent and Applied Optoelectronics on a DSP question).

**Assessment.** Precision 39%: no. Saved work 0: no. Coverage 10%: no. Roles ran: the Editor wrote a card with open questions but no finding: yes on the letter of the bar. Cost: yes. Latency 21 minutes: no. **Investigation 4 does not meet the bar.**

### Investigation 5 on 0.4.6: coherent-optics and systems demand

- **ID:** `321f555a-e79c-4d9d-9518-cb2e6a56381a`. **Seeds:** Ciena, Lumentum, Coherent. **Stop:** `needs_review`. **Usage:** 928,877 tokens in, 57,437 out; 85 role calls, 2 repairs; 1 round; 10 leads, 25 documents, 6 Investigators; 21 minutes 43 seconds (14:09:45 UTC on), no pause.
- **Review:** two blind reviewers per chunk (4 chunks), agreement 77 of 86, **kappa 0.77**; the lead adjudicated the 9 disagreements (1 right, 1 wrong, 7 off-question: Lumentum competing with Coherent in 1.6T modules, NVIDIA and CPO lasers, OCS, none of them coherent-optics or DCI supply), confirmed the 9 Claims both called wrong. Artifacts: `.scratch/live-runs/pilot-0.4.6/inv-5/review/`.

**Saved work.** One finding passes the trust gate and counts: 5. Ciena expects "demand outstripping supply" into 2027 and is "effectively double our CapEx intensity specifically this year to increase supply capacity" (the systems-demand side, from the company's own words). Finding 1 (AXT's InP substrate agreements with Coherent and Lumentum, with the $22,288,500 prepayment) would count but fails the gate.

**Unsupported or wrong.**
- **Trust gate: fails on findings 1 to 4.** 1: "6-inch" applied to Lumentum's agreement (only Coherent's names it) and "supplies" for a development-and-supply agreement (the third run with this overstatement). 2: a 6-inch platform and CW lasers attributed to Lumentum, which no Lumentum quote says, and Lumentum "supplies NVIDIA with co-packaged optics" where it supplies a laser. 3: "ramping in volume production" attributed to MACOM's 75 mW CW laser, whose quote says "qualification efforts continue". 4: two items of a forward-looking risk list merged into a stated dependency (Marvell's suppliers "for advanced-node wafers"). Coherent's InP-constraint and capacity-doubling finding was dropped as ungrounded though its Claims are right.
- **Claims:** 57 right, 10 wrong, 19 off-question of 86: **precision 66%**. Wrong: development read as manufacturing (AXT's 6-inch "development", `53dbb627`); a capacity reservation read as expansion (`cc79b65f`); "sole_sources" from hedged risk language (`e6e8e2b1`); qualification in progress read as qualified (`57c4d1e6`); an industry-wide constraint read as Marvell's (`acdba88c`); Lumentum "supplies NVIDIA" where NVIDIA ships the solution (`d21e6713`); EMLs from a unit forecast (`73b3c94c`); an R&D table entry as material use (`a1ee0ed9`); `d13d91b3`, `7e2689c7`.

**Missed evidence.** The question's demand side is almost absent: Coherent's own calls on extremely strong DCI demand for ZR/ZR+ transceivers and components, ramping capacity for every DCI component, communications revenue up 16% sequentially and 60% year over year on DCI and scale-across (baseline hits 1–3, 7, 8, 12); Lumentum negotiating for customers to fund its capex in exchange for long-term supply, its component shortages and incremental supply costs (hits 14, 16).

**Baseline.** 16 hits judged, 10 on-question: **1 covered**, 0 in substance, 9 not covered. **Coverage 10%.**

**A researcher's hour.** 28 cited facts, all on the question and true; 5 on the card. The researcher found where coherent supply binds: Ciena on external lasers and ITLAs, coherent driver modulators and gold boxes, explicitly not InP wafers; Lumentum on pump and narrow-linewidth lasers, more constrained than EMLs, and its LTAs at higher prices; Coherent's Nano-ITLA and IC-TOSA stack. It quantified the pull: Ciena's orders and backlog, 800ZR volume doubling, purchase commitments from $2.1B to $3.3B. Of the card's 5 findings, the answer has 1 (finding 5).

**Corrections needed.** Below, with all five.

**Cost and latency.** 986,314 tokens, inside the bar. 21 minutes 43 seconds, outside the 20-minute bar.

**New defects:**
- The Scout's queries are mostly about the theme's InP and laser supply; one of ten targets 800ZR or DCI demand, the question's subject.
- The card answers the theme's standing story (InP substrates, NVIDIA CPO lasers) instead of this question; the same drift as investigations 3 and 4.

**Assessment.** Precision 66%: no. Saved work 1: no. Coverage 10%: no. Roles ran: yes. Cost: yes. Latency 22 minutes: no. Trust gate fails. **Investigation 5 does not meet the bar.**

### The verdict on 0.4.6: fail

| | Inv 1 laser chips | Inv 2 InP substrates | Inv 3 module assembly | Inv 4 DSP and drivers | Inv 5 coherent demand | Bar |
|---|---|---|---|---|---|---|
| Accepted Claims, all verbatim | 95 | 76 | 71 | 36 | 86 | (trust gate, first half) |
| Precision | 67% | 58% | 69% | 39% | 66% | ≥ 80% |
| Saved work | 0 (3, two failing the gate) | 2 | 0 (thin card) | 0 (no finding) | 1 | ≥ 3 |
| Trust gate (findings) | fails (2) | fails (2) | fails (1) | holds (no finding) | fails (4) | must hold |
| Baseline coverage | 40% | 20% | 30% | 10% | 10% | ≥ 50% |
| The roles ran | yes | yes | yes | yes | yes | yes |
| Cost (MiniMax tokens) | 987,654 | 912,621 | 980,406 | 943,393 | 986,314 | ≤ 2,000,000 |
| Latency | 26.3 min | 22.7 min | 25.0 min | 20.8 min | 21.7 min | ≤ 20 min |
| Reviewer agreement (kappa) | 0.81 | 0.85 | 0.84 | 0.86 | 0.77 | (reported) |
| Researcher's hour: its true facts on the card | 4 of 33 | 5 of 32 | 1 of 25 | 1 of 26 | 5 of 28 | (reported) |
| **Meets the bar** | no | no | no | no | no | |

- **Pooled:** precision 228 of 364 accepted Claims (63%); baseline coverage 11 of 50 on-question hits (22%); 4,810,388 MiniMax tokens for the five.
- **Machine-reviewed edges** (pooled, the 76 `machine_reviewed` Relationships with Evidence from the five runs): 43 right, 5 wrong, 23 off-question, 5 mixed: **57%** (bar 90%); investigations 1 and 5 each have 2 wrong `machine_reviewed` edges (bar: at most 1). Counting right against wrong only: 43 of 48 (90%).
- **Edges applied** (ticket 09's rule, the lead, 2026-10-07 after the fifth run): of 233 Relationships with Evidence from the five runs, 87 approved (every Evidence Claim right), 29 rejected (every one wrong), 100 left (mixed, off-question, or Evidence from earlier runs not reviewed here), 17 already decided before. Plan and outcome: `.scratch/live-runs/pilot-0.4.6/edge-plan.json`.
- **A researcher's hour against the cards:** 144 of 145 cited facts on the question and true; 16 of them on a card (11%). The cards' 3 saved-work findings (investigation 2's findings 2 and 3, investigation 5's finding 5) are all in the researchers' answers: the cards found nothing the hour missed that counts as saved work.

**Verdict (ticket 02): fail.** No investigation meets the bar (the criteria: at most 1 is a fail), the trust gate fails in four of five, and the machine-reviewed edge precision is under 90%. Under ticket 02 a fail means no fix round: the research workflow's design is reopened (what the Claim model and the roles can express) before anything else is built. The researchers' answers say what the design must reach: magnitudes, shares, regulatory status and timing from transcripts, trade sources and filings, which the cards almost never carry.

**What holds:** every accepted quote is verbatim at an archived, dated span (364 of 364); two blind reviewers agree at kappa 0.77 to 0.86; the roles all ran; cost is half the bar.

**Not done yet** (procedure section 4): the held-out answer key (the owner lists Serenity's flagged names and dates; found, missed and found-before per item); `docs/pilot-report.md`; ticket 13.

## The argument plan on 0.5.3 (2026-10-07/08): the five questions again

The owner authorized 8M MiniMax tokens to run the five questions on the argument plan (bottleneck-argument effort; `docs/pilot-report.md` for why). Same questions and seeds, same 2,000,000-token budget, one at a time. The review keeps the verdict's method for the new output: every Fact judged twice blind (quote states the statement for that company; status, quantity and period exact; on the question), the lead adjudicating; every card statement for the trust gate and saved work; the same archive-search baseline; and the **same researcher's-hour answers** as the 0.4.6 verdict, so the comparison is exact. Review files: `.scratch/live-runs/pilot-0.5.3-arg/inv-<n>/review/` (not in git). Tools: `.scratch/tools/argument_review_pack.py`.

### Question 1 on 0.5.3: laser chips for 800G/1.6T

- **ID:** `18ef6c9e-909d-43f7-89e6-699156046a78`. **Seeds:** Lumentum, Coherent. **Stop:** `needs_review` (3 steps disputed, 2 statements dropped). **Usage:** 1,495,671 tokens in, 88,981 out; 196 role calls, 0 quarantined; 13 min 17 s.
- **Card:** all six steps stated, 34 statements (2 dropped by the checks); 170 Facts (11 with a quantity); 23 counter-Facts from the Skeptic; constraint, relief and capture disputed.
- **Review:** two blind reviewers per chunk (5 chunks), agreement 161 of 170, **kappa 0.85**; the lead adjudicated 9 (3 right, 6 wrong: fiscal-period labels, a remark that the fab is much of the cost read as a constraint, context from the next sentence added).

| Measure | 0.4.6 | **0.5.3 argument** | Bar |
|---|---|---|---|
| Precision (Facts or Claims right) | 67% | **78%** (133 of 170) | ≥ 80% |
| Saved work | 0 (2 of 3 failed the gate) | **23 statements** | ≥ 3 |
| Trust gate | fails (2 of 3 findings) | **fails (4 of 34 statements)** | holds |
| Baseline coverage | 40% | **90%** (9 of 10, 1 more in substance) | ≥ 50% |
| Researcher's facts on the card | 4 of 33 | **8** (+7 in Facts only; 18 absent) | reported |
| Latency | 26 min | **13 min** | ≤ 20 min |
| Cost | 0.99M | 1.58M | ≤ 2M |

- **Saved work, the strongest:** Broadcom and Lumentum as the only large 200G EML suppliers; Lumentum's EML capacity sold out and its allocation trade-offs between EML and CW and across customers; InP constrained across EML, CW and photodetectors, likely through 2027; EML share about 70–80% at 800G and an expected 40–50% at 1.6T; ASPs roughly doubling from 100G to 200G; Coherent's 6-inch InP against Lumentum's caution; Greensboro not operational before early 2028; MACOM emerging in CW lasers.
- **Trust gate failures (the judge missed all four):** "800G" added to "Datacom transceiver order strength"; "these components" widened to all of Lumentum's; a GaAs-to-InP conversion taken from a Fact the statement doesn't cite; "end of year" read as the fiscal year's.
- **Missed:** almost all of the question's feedstock and equipment half, which the researcher had: InP substrate scarcity (Lumentum's 7-year deal, AXT's reservation and deposits, Lumentum no longer well covered, China's export permits, Sumitomo's 3.1x expansion and JX's share), MOCVD reactors and e-beam tools (AIXTRON orders), and third-party market shares. AXT and the equipment makers aren't seeds, and Readers read the seeds' and Memory's companies; the web sources the researcher used aren't evidence in Atlas.
- **Weaker parts:** the invalidation step holds no invalidating observation; capture has no margin evidence; the Skeptic's counter-Facts all challenge constraint Facts and mostly support them; some statements repeat.
- **Assessment:** precision 78% (just under 80%); saved work and coverage far above the bar; latency and cost inside; **the trust gate fails** on four narrow overstatements. Against 0.4.6 on the same question: twice the researcher's facts on the card (8 against 4), more than twice the baseline coverage, every step argued, half the time.

### Question 2 on 0.5.3: InP substrates as a chokepoint

- **ID:** `f8161b4c-…` (saved in `inv-2/investigation.json`). **Seeds:** AXT, Coherent, Lumentum. **Stop:** `needs_review`: the Financial Analyst failed after 3 attempts, and that cancelled the Editor, so **there is no card**. **Usage:** 1,553,485 tokens in, 90,218 out; 9 min 40 s.
- **Facts:** 188 (177 from the Readers, 11 from the Skeptic).
- **Review:** two blind reviewers per chunk (6 chunks; reviewer B skipped 2 Facts), agreement 162 of 186, **kappa 0.69**. The lead adjudicated the 24 disagreements and the 2 skipped Facts: 13 right, 9 wrong, 4 off-question. The rubric was applied strictly: a status the quote doesn't support counts as wrong, as the reviewers did on the Facts they agreed on.

| Measure | 0.4.6 | **0.5.3 argument** | Bar |
|---|---|---|---|
| Precision (Facts or Claims right) | 58% | **72%** (136 of 188; two labels corrected 2026-10-08, below) | ≥ 80% |
| Saved work | 2 | **0: no card** | ≥ 3 |
| Trust gate | fails (2) | **no statements** | holds |
| Baseline coverage | 20% | **60% in the Facts** (6 of 10, 4 more in substance); 0 on a card | ≥ 50% |
| Researcher's facts on the card | 5 of 32 | **0** (22 in Facts only; 10 absent) | reported |
| Latency | 22.7 min | **9.7 min** | ≤ 20 min |
| Cost | 0.91M | 1.64M | ≤ 2M |

- **The Facts hold the answer.** 22 of the researcher's 32 facts are among the Facts, against 5 on 0.4.6's card. Examples:
  - concentration: AXT's own split of the 2024 merchant InP market (AXT ~40%, Sumitomo ~40%, JX ~10%), and its CEO placing AXT first or second with at least 40%;
  - export permits: permits for the UK and Canada, US permit timing uncertain, the InP backlog rising from $49M to over $100M;
  - the AXT–Coherent and AXT–Lumentum agreements with their prepayments;
  - Lumentum saying its large deal with a Japanese supplier is not enough.
  
  The Facts also have what the researcher lacked: Coherent's own InP build-out and IQE calling InP substrates a bottleneck.
- **Absent:** 6 of the 10 come from web sources Atlas doesn't treat as evidence (MOFCOM announcements 10 and 72, USGS indium, JX's and Sumitomo's capacity plans). Two are 10-K risk factors. The other two are AXT needing no permit within China, and Lumentum's remark that the Chinese government controls substrate supply.
- **Wrong, by kind** (33):
  - status (agreements or plans as in_effect or in_development; permits as hedged; AXT's own estimates as reported_by_third_party): about two-thirds;
  - context from the next sentence; a dropped hedge (Lumentum thinking, not saying, it had solved the shortage); a headline quote carrying a body's details.
- **New defects:**
  - Ticket `atlas-bottleneck-argument/07`: an optional role failing sinks the card. The analyst wrote `kind: "assertion"` where only sourced, estimated or missing is allowed, and its first attempt hit the 4,096-token output cap.
  - The review pack took company names from the card, so this run's Facts showed none. The tool is fixed (`argument_review_pack.py` now uses the Fact's subject), and no verdict turned on it.
- **Assessment:** fails the bar, because there is no card. Measured on the Facts, precision is 73% (0.4.6: 58%), baseline coverage 60% (0.4.6: 20%), and 22 of the researcher's 32 facts are there, in under 10 minutes. The reading works; the stop rule threw its output away.

### Question 3 on 0.5.3: transceiver module assembly

- **ID:** `a5a7402d-…`. **Seeds:** Fabrinet, Applied Optoelectronics, Coherent. **Stop:** `needs_review`; constraint, demand_vs_supply, relief and control are disputed. **Usage:** 1,511,323 tokens in, 80,598 out; 10 min 40 s.
- **Card:** six steps and 30 statements, from 157 Facts.
- **Review:** two blind reviewers per chunk (5 chunks). One reviewer's chunk 1 came back with 34 invented fact IDs (correct 8-character prefixes, made-up remainders), and that chunk was re-reviewed. Agreement 146 of 157, **kappa 0.82**. The lead adjudicated the 11 disagreements: 5 right, 3 wrong, 3 off-question.

| Measure | 0.4.6 | **0.5.3 argument** | Bar |
|---|---|---|---|
| Precision | 69% | **76%** (119 of 157) | ≥ 80% |
| Saved work | 0 | **19 of 30 statements** | ≥ 3 |
| Trust gate | fails (1) | **fails (6 of 30)** | holds |
| Baseline coverage | 30% | **60%** (6 of 10) | ≥ 50% |
| Researcher's facts on the card | 1 of 25 | **7** (5 more in Facts only; 13 absent) | reported |
| Latency | 25.0 min | **10.7 min** | ≤ 20 min |
| Cost | 0.98M | 1.59M | ≤ 2M |

- **Saved work:** the card's main answer is that module assembly is mostly not the constraint.
  - Coherent says assembly and test are not constrained, indium phosphide is.
  - Fabrinet is short of one or two components, not capacity.
  - AOI's capacity path: about 90k units a month at end-2025, about 200k now, over 650k by end-2026 and over 930k by end-2027.
  - AOI's Q2 capex was $565.5M, including $280M of prepayments.
  - Coherent's book-to-bill is above 4x.
  - AOI's Taiwan factory is approved for 800G.
  
  The card shows all of this but never states it as the conclusion.
- **Trust gate failures (6):**
  - a "c1" Fact reference left in a statement in place of Coherent (ticket `atlas-bottleneck-argument/08`);
  - a forecast ($1.1B 2026 revenue) written as a result;
  - customers' view presented as AOI's own;
  - two AOI facilities merged;
  - "on 1.6T pricing" added;
  - an unstated "it" read as the constraint.
- **Missed:**
  - customer concentration, one of the question's three parts, is on neither the card nor the Facts (Fabrinet's 10% customers and NVIDIA's falling share, Coherent's 20% customer, AOI's Digicomm and Microsoft shares). Only AOI's top ten at 99% is a Fact;
  - qualification cycle times (Fabrinet's 3 to 6 months; AOI's month-long trial in the data center);
  - Fabrinet's later quarters (shortages broadening, the second EML source);
  - the web sources (Cignal AI, ComSoc).
  
  The four baseline misses are Coherent's and AOI's 10-K qualification and contract-manufacturer risk paragraphs, and Coherent's 2025 investor deck.
- **Counterevidence:** all of it is Lumentum's, and none of it contradicts the statement it is attached to. Some of it confirms the constraint. This matches question 1 (next-session priority 3).
- **Assessment:** precision 76% (just under 80%). Saved work and coverage are well above the bar, latency and cost are within it, and **the trust gate fails**. Against 0.4.6 on the same question: 19 saved statements against none, coverage doubled, 7 of the researcher's facts on the card against 1, in less than half the time.

### Question 4 on 0.5.3: the DSP and driver layer

- **ID:** `fe7e5989-…`. **Seeds:** Marvell, MACOM.
- **Stop:** `needs_review`. Constraint, demand_vs_supply and capture are disputed. The Financial Analyst's first attempt was quarantined and its second succeeded.
- **Usage:** 1,515,953 tokens in, 72,749 out.
- **Time:** 44 minutes from the first task to the stop. About 25 of those were tasks queued rather than running: two Readers waited 16 minutes and the Editor 9. The run started at the end of the MiniMax window that questions 2 and 3 had filled, so the working time is about 20 minutes.
- **Card:** six steps and 34 statements, from 138 Facts.
- **Review:** two blind reviewers per chunk (4 chunks). They agreed on 132 of 138, **kappa 0.89**. The lead adjudicated the 6 disagreements: 1 right, 3 wrong, 2 off-question.

| Measure | 0.4.6 | **0.5.3 argument** | Bar |
|---|---|---|---|
| Precision | 39% | **75%** (103 of 138) | ≥ 80% |
| Saved work | 0 (no finding) | **19 of 34 statements** | ≥ 3 |
| Trust gate | holds (no finding) | **fails (2 of 34)** | holds |
| Baseline coverage | 10% | **70%** (7 of 10, 1 more in substance) | ≥ 50% |
| Researcher's facts on the card | 1 of 27 | **6** (7 more in Facts only; 14 absent) | reported |
| Latency | 20.8 min | 44 min wall (about 20 working; see above) | ≤ 20 min |
| Cost | 0.94M | 1.59M | ≤ 2M |

- **Saved work:**
  - Marvell's DSP generations: 5nm sampled February 2024, 3nm sampled February 2025, more than 20% lower module power, shipping in volume.
  - TSMC as the sole wafer source at 3nm, assembly and test partners possibly single-sourced, and the TSMC capacity reservation with $458.2M of commitments.
  - 3.2T on 2nm in calendar 2028.
  - The Celestial AI acquisition for CPO, and NPO before CPO.
  - Demand for drivers and TIAs above expectations, and MACOM's 200G-per-lane products for 1.6T.
- **Trust gate failures (2):**
  - The design-win momentum of an earlier product is attached to the 3nm DSP announced in the next sentence.
  - A revenue trajectory is named "data center interconnect", which the quote doesn't say.
- **Wrong, by kind (14):**
  - merged facts (plasmonics for 3.2T with being first to 14A DSPs; the 800G/1.6T scale-out modules read as the NPO modules);
  - a billion-dollar analog business read as NPO revenue;
  - added glosses ("including interconnects").
  
  The off-question Facts are mostly active electrical cables and switching.
- **Missed:** the question's "how many qualified sources" half. Broadcom's Sian3, Credo's Bluebird, MaxLinear's Rushmore and NVIDIA's own DSP are all absent: they appear in no seed's filing and the web sources aren't evidence. Also missing is MACOM's side: no R&D on DSPs, its LPO orders, and the contested driver sockets. The baseline's two misses are both of these, MACOM's DSP stance and Marvell's lead in 1.6T TIAs and its LPO sockets. Marvell's majority-share remark is a Fact but on no statement.
- **Counterevidence:** not real again. Two items are another company's hypothetical about a DSP shortage, and one is Ciena saying it will compete with Marvell. One step is marked disputed with no counterevidence shown.
- **Assessment:** precision 75% (just under 80%). Saved work and coverage are well above the bar, cost is within it, and **the trust gate fails** on two narrow overstatements. Latency is over the bar as measured, because of the queued time. Against 0.4.6, which had no finding at all: 19 saved statements, coverage from 10% to 70%, and 6 of the researcher's facts on the card against 1.

### Question 5 on 0.5.3: coherent-optics and systems demand

- **ID:** `25692663-…`. **Seeds:** Ciena, Lumentum, Coherent.
- **Stop:** `needs_review`. Relief, control, capture and invalidation are disputed.
- **Usage:** 1,491,428 tokens in, 82,962 out; **15.5 minutes**, starting in a fresh MiniMax window.
- **Card:** six steps and 32 statements, from 200 Facts.
- **Review:** two blind reviewers per chunk (6 chunks). Reviewer A's chunk 1 stopped halfway and padded with a placeholder ID, so it was re-reviewed. They agreed on 153 of 200, **kappa 0.52**. 36 of the 47 disagreements were about scope: whether a datacom-only Fact (1.6T transceivers, EMLs, CPO, OCS) bears on a coherent and DCI question. The lead applied question 5's rule from 0.4.6, under which those are off-question. The other 11 split 2 right, 4 wrong (AXT agreement statuses, as on question 2) and 5 off-question.

| Measure | 0.4.6 | **0.5.3 argument** | Bar |
|---|---|---|---|
| Precision | 66% | **59%** (117 of 200; 88% true to their quotes, 29% off-question) | ≥ 80% |
| Saved work | 1 | **21 of 32 statements** | ≥ 3 |
| Trust gate | fails (4) | **fails (5 of 32)** | holds |
| Baseline coverage | 10% | **33%** (3 of 9, 2 more in substance) | ≥ 50% |
| Researcher's facts on the card | 5 of 28 | **6** (4 more in Facts only; 18 absent) | reported |
| Latency | 21.7 min | **15.5 min** | ≤ 20 min |
| Cost | 0.99M | 1.57M | ≤ 2M |

- **The card answers a neighbouring question.** It argues the InP laser and substrate bind on datacom optics thoroughly: Coherent's 6-inch ramp, Lumentum sold out, AXT's share and agreements, ASPs at 1.6T. It barely reaches the coherent and DCI path the question asks about:
  - Ciena: external lasers and ITLAs, CDMs and gold boxes are where supply is tightest, and InP wafers are not its limit.
  - Lumentum: pump and narrow-linewidth lasers are tighter than EMLs.
  - Ciena's 800ZR doubling and its purchase commitments.
  
  The researcher had all of these. Most of the 58 off-question Facts are datacom, so the reading followed the theme's datacom story, not the question (pilot-fixes 36).
- **Saved work:** Ciena's orders against revenue, no balance before 2028, the backlog and supply secured to 2029. Coherent's InP as its primary constraint while assembly is not. Lumentum's pump lasers up more than 80% and narrow-linewidth lasers up more than 130% year on year, and its substrate no longer covered.
- **Trust gate failures (5):**
  - "on indium phosphide" added;
  - a mid-2025 tripling joined to the 2026 doubling plan, undated;
  - four Lumentum statements of different dates merged, one from a Nokia-titled source;
  - the qualifier dropped from Coherent's cost buffer;
  - a Coherent Fact folded into a Lumentum statement.
- **Wrong, by kind (25):** above all, fiscal against calendar years. On Coherent's fiscal Q2 and Q3 2026 calls, "this calendar year" was recorded as 2025 several times. Also agreement statuses, and two headwinds split where Ciena named one.
- **Counterevidence:** not real again. Coherent's own later statements confirm the ones they are filed against, and one step is marked disputed with nothing attached.
- **Assessment:** precision 59% fails. Saved work passes. Coverage of 33% fails. The trust gate fails. Latency and cost are within the bar.

### The argument plan on 0.5.3: pooled against the 0.4.6 verdict

| Measure (pooled over 5) | 0.4.6 (default plan) | **0.5.3 (argument plan)** | Bar |
|---|---|---|---|
| Precision | 63% (228 of 364 Claims) | **71%** (608 of 853 Facts) | ≥ 80% per question |
| Saved work | 3 findings | **82 statements** (23, 0, 19, 19, 21) | ≥ 3 per question |
| Trust gate | fails in 4 of 5 | **fails in 4 of 4 cards**: 17 of 130 statements | holds |
| Baseline coverage | 22% (11 of 50) | **63%** (31 of 49) | ≥ 50% |
| Researcher's facts on a card | 16 of 145 (11%) | **27 of 145 (19%)**; 72 of 145 (50%) in Facts or on a card | reported |
| Latency | 21–26 min | **10–16 min** (Q4: 44 min wall, about 25 of it queued) | ≤ 20 min |
| Cost | 0.94–0.99M each | 1.49–1.55M in, 73–91k out each | ≤ 2M |
| Reviewer kappa | 0.77–0.86 | 0.85, 0.69, 0.82, 0.89, 0.52 | reported |

**Verdict: still fails the bar.** No question reaches 80% precision, and the trust gate fails on every card. The argument plan is still clearly better than the default plan on every measure the verdict uses:

- **Reading is much better:** 27 times the saved work, coverage nearly three times higher, half the researcher's facts reached.
- **What fails, ranked:**
  1. The trust gate: narrow overstatements the judge misses, such as merged dates, added glosses and dropped qualifiers.
  2. Fact statuses and periods, notably fiscal against calendar years and agreements labelled in_effect.
  3. Counterevidence that confirms instead of contradicting.
  4. Reading that follows the theme's story instead of the question (question 5).
  5. Competitors outside the seeds and web-only facts (question 4's DSP vendors, question 2's MOFCOM and USGS facts).
  6. An optional role that sank a whole card (question 2; fixed on main as ticket 07, not yet released).

By the rule agreed with the owner, the argument plan replaces the default plan: it beats 0.4.6 on researcher facts held, archive hits covered and precision. The default plan's retirement is next-session priority 7.

**Label correction (2026-10-08).** The regression check (`.scratch/tools/argument_regression.py`) found two question 2 Facts, `8db4f309` and `d65b0dd3`, that both reviewers labelled right. They are twins of `f8fc66fa`, which the lead adjudicated wrong: AXT's own market-share estimate labelled `reported_by_third_party`. The lead corrected both to wrong for consistency. Question 2 goes to 72% and the pooled figure to 71% (608 of 853).
