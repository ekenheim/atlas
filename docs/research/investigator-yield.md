# Investigator yield on bottleneck evidence (pilot-fixes ticket 03)

Measured 2026-09-30 against live MiniMax-M3 (through the owner's LiteLLM, thinking disabled). 25 chat completions in total, under the 30-call cap.

## What was replayed

Pilot investigation 1 sent the Investigator 24 passages of Coherent's FY2026 10-K and got `{"claims": []}` from all 4 calls. `scripts/investigator_replay.py` reproduces that extraction offline:

- **Passages.** Coherent is ingested from the recorded EDGAR fixture of the same 10-K (`iivi-20260630.htm`, which covers the document through Item 7) into a throwaway database, and the production `ClaimExtractor` picks the passages. Recall is stubbed to the 10-K's Item 1 and Item 1A, the sections the pilot's recall resolved to. The pilot's budget applies: 24 passages, 6 per call. The extractor puts entity-tagged windows first, so the 24 are 1 Item 5 window (the stock-performance peer group names Lumentum), 17 Item 1 windows and the first 6 of Item 1A's 37.
- **Request and checks.** The run uses the pilot's question, the whole company universe, the whitelist and the layers. Every proposed Claim goes through the production checks: whitelist, layer, parties, quote location, span check and directional cue. Only the prompt changes between variants.
- **Offline.** `--rehearse` runs the same pipeline against the scripted LiteLLM fake, which checks the harness itself.

Raw results are in `investigator-yield/live-1-results.json` (whitelist of 9 predicates) and `live-2-results.json` (whitelist of 13). The variant prompts are in `investigator-yield/`.

## Round 1: prompt only, the 9-predicate whitelist

| variant | calls (repairs) | tokens in / out | proposed | accepted | rejections |
|---|---|---|---|---|---|
| `investigator.v2` (the pilot's prompt) | 4 (0) | 23,536 / 903 | 5 | **3** | party_not_in_quote 1, missing_object 1 |
| relaxed (v2 without "names both parties" and without the empty-list sentence) | 5 (1) | 31,383 / 3,112 | 9 | **0** | party_not_in_quote 7, quote_mismatch 1, missing_object 1 |
| self-statements (relaxed plus a section on the filer's own facts with product objects) | 6 (2; 1 batch quarantined) | 39,655 / 5,583 | 17 | **4** | party_not_in_quote 5, no_directional_language 5, quote_mismatch 1, quote_outside_passage 1, missing_object 1 |

v2's accepted Claims were all self-statements with product objects:

- `manufactures`: "We manufacture GaAs VCSELs and VCSEL arrays, InP edge-emitting lasers and photodiodes, and specialty glass wafers for the consumer electronics market."
- `uses_material` InP substrates: "These include InP substrates, ICs, DSPs, mechanical housings, and optical components, and we commonly refer to them as raw materials."
- `expands_capacity_for` 6-inch InP: "We continue to expand our global 6-inch InP manufacturing capacity in the United States and Europe to support increasing customer demand, …"

### Diagnosis

1. **The pilot's zero was partly chance.** On the same kind of passages, v2 proposed 5 and 7 Claims in two runs and got 3 and 4 accepted. It is cautious: about one Claim per five passages. The pilot's run hit the empty end of that range. The pilot also had one more obstacle: its Investigator task shared a document budget that the first seed company had used up (ticket 01).
2. **The "names both parties" rule is needed.** Removing it (relaxed) made the model quote list items and fragments: "indium phosphide (InP);", "edge-emitting laser (EEL);". 7 of 9 failed the party check, and nothing was accepted. v3 keeps the rule and adds that a fragment without the company is never a quote.
3. **The Claim model had no place for most bottleneck facts.** Each variant reached for statements that no predicate could express:
   - Sole or limited sourcing with no supplier named: "we currently purchase several key components and materials … from sole-source or limited-source suppliers", and "there is a limited number of high-quality suppliers of many of the components we manufacture". Both were proposed as `depends_on` and rejected `missing_object`, since `depends_on` needs a named company.
   - In-house supply of an input: "Our vertically integrated technology platform includes the in-house design and manufacture of transceivers and many of their critical components …" and "Leveraging our vertically integrated 6-inch GaAs platform …". Both were forced into `manufactures` or `uses_material` and rejected `no_directional_language` or `quote_mismatch`.
   - A named counterparty outside the universe: "a strategic multi-year supply agreement with NVIDIA" was rejected `missing_object`, because NVIDIA isn't one of the 12 companies. That is a universe gap for the Candidates flow, not a prompt defect.
4. **Other losses.**
   - Quote placement (1 per run): the 10-K's "in-house design and manufacture" sentence is split in the parsed text by a page break ("manufacture\n9\nTable of Contents\nof transceivers"), so no exact quote of the sentence as it reads can be located. This is a parser finding, not addressed here.
   - Schema drift in repairs: the model added `claim_id` or left out `object_company_id`. One repair fixes it, but it costs tokens, and one self-statements batch was quarantined.

The answer to the ticket's question is **both**: the prompt suppressed self-statements, and the Claim model had no predicates for company-level bottleneck facts. A prompt fix alone (self-statements, 4 accepted) barely moved acceptance, because the model's best bottleneck statements had nowhere to go.

## What was built (owner direction 2026-09-30: implement, don't under-express)

- **Four company-level bottleneck predicates** (`atlas/claims/predicates.py`; CONTEXT.md "Bottleneck Predicate"; `docs/decisions.md` 2026-09-30):
  - `capacity_constrained`
  - `sole_sources`
  - `vertically_integrates`
  - `qualified_for`

  Each has a product object and a direction from the company to the product, and forms an edge to a product node like `manufactures`. "Demand exceeds supply" folds into `capacity_constrained`. A named counterparty keeps the two-company predicates. Migration `0043` extends the `relationship.predicate` check.
- **`investigator.v3`**: "A company's own statements" (one line per product predicate, with examples and mapping rules), the no-fragments rule, and the words a quote must contain. The empty-list instruction now applies only when nothing is stated.
- **`reviewer.v2`**: how to judge a product-object fact, and what the new predicates don't cover.

## Round 2: the 13-predicate whitelist

| variant | calls (repairs) | tokens in / out | proposed | accepted | rejections |
|---|---|---|---|---|---|
| **`investigator.v3`** | 6 (2) | 42,501 / 4,025 | 14 | **8** | party_not_in_quote 3, no_directional_language 2, quote_mismatch 1 |
| `investigator.v2` (control, same whitelist) | 4 (0) | 24,348 / 1,348 | 7 | **4** | party_not_in_quote 2, quote_mismatch 1 |

v3's accepted Claims by predicate: `manufactures` 2, `vertically_integrates` 2, `expands_capacity_for` 2, `uses_material` 1, `sole_sources` 1. Examples:

- `sole_sources` (key components and materials): "in the Industrial segment, we currently purchase several key components and materials used in the manufacture of our products, including exotic materials, crystals, and optics, from sole-source or limited-source suppliers"
- `vertically_integrates` (strategic components, crystals, fibers, semiconductor lasers, and laser-based systems): "We rely on our own production and design capability to manufacture and specify certain strategic components, crystals, fibers, semiconductor lasers, and laser-based systems."
- `expands_capacity_for` 6-inch InP manufacturing capacity: "We continue to expand our global 6-inch InP manufacturing capacity in the United States and Europe to support increasing customer demand, …"
- `uses_material` InP substrates: "These include InP substrates, ICs, DSPs, mechanical housings, and optical components, and we commonly refer to them as raw materials."
- `manufactures` GaAs VCSELs … InP edge-emitting lasers: "We manufacture GaAs VCSELs and VCSEL arrays, InP edge-emitting lasers and photodiodes, …"

Even with the old prompt, the control found a `sole_sources` Claim once the predicate existed: the new whitelist raises yield on its own. v3 doubles it again: 8 accepted against 4, and 3 of the 8 are bottleneck predicates. Round 1's best was 4. The cost is about 1.75× the tokens (42.5k in against 24.3k) and two repairs.

**Precision still depends on review.** Two of v3's 8 accepted Claims are weak:

- `vertically_integrates` on "Coherent … is a vertically integrated manufacturing company that develops, manufactures, and markets lasers, transceivers, …": the object is what Coherent sells, so this is `manufactures`.
- `expands_capacity_for` "6-inch GaAs VCSEL manufacturing facilities": its quote says "operating", and it passed only on the same sentence's "expand" clause.

Both pass the cue check, which is a necessary condition only. `reviewer.v2` is told about exactly these cases ("making a product it sells is `manufactures`"), and the edge table's exceptions queue is where they belong. None of this was measured against the Reviewer live.

The 24 passages cover only the first 6 windows of Item 1A. Most of the risk factors, where "we may experience shortages" or "limited-source suppliers" statements concentrate, were never read. Their hedges ("may", "could") route those facts to human review anyway.

## Recommendation

1. **Ship v3 and the four predicates** (done on this branch). They are the change that moved yield, and they keep every check: exact located quote, span, parties and cue.
2. **Measure the Reviewer on these edges** before trusting `machine_reviewed` for the bottleneck predicates. That means a live `review_relationships` over v3's accepted Assertions (about 2 calls with 5 per call). Also consider a narrower `vertically_integrates` cue ("vertically integrated" alone describes the company, not an input) if the Reviewer doesn't catch the case above.
3. **Separate findings for other tickets:**
   - The parser leaves page-break furniture ("9\nTable of Contents") inside sentences, which makes true quotes unlocatable.
   - NVIDIA, a named customer in Coherent's 10-K, is outside the universe, so its supply agreement can't become an edge. A Candidate should come of it.
   - The passage budget of 24 stops at the start of Item 1A.
   - The model's schema drift costs a repair on about a third of v3's calls.
