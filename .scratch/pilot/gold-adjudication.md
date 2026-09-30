# Gold case adjudication (12 cases)

Each case is an agent draft (`adjudication.method: agent_draft`). For each one, read the question, the evidence and what Atlas is expected to do, then mark **Accept** or write what's wrong. Cases are immutable, so a change becomes a new superseding case (`docs/evaluation-methodology.md`). Every company here is fictional, except in RST, which reuses Nokia's real restatement.

Legend: *present* = the edge must exist (in the given review state); *absent* = no such edge in any state; *not_verified* = the edge must not be machine-reviewed or approved.

## EV-COM-001: Companies named together as exhibitors are not a supply relationship
**Question:** Does Aurora Photonics supply Cirrus Compute?
**Sources:**
- source `s1`: Aurora Photonics OFC 2025 recap ()
**Expected:**
- edge Aurora Photonics **supplies** Cirrus Compute: *absent*
- edge Cirrus Compute **supplies** Aurora Photonics: *absent*
- claims: `[{"subject": "aurora", "predicate": "supplies", "object": "cirrus", "accepted": false}]`

- [ ] Accept  - [ ] Change: ____________________

## EV-COM-002: A market ranking naming two wafer companies is not a purchase
**Question:** Does Dunmore Epitaxy buy substrates from Borealis Substrates?
**Sources:**
- source `s1`: Dunmore Epitaxy annual report 2025 ()
**Expected:**
- edge Dunmore Epitaxy **buys_from** Borealis Substrates: *absent*
- edge Borealis Substrates **supplies** Dunmore Epitaxy: *absent*
- claims: `[{"subject": "dunmore", "predicate": "buys_from", "object": "borealis", "accepted": false}]`

- [ ] Accept  - [ ] Change: ____________________

## EV-CON-001: The Skeptic finds a later filing contradicting the supply claim; the card shows it
**Question:** Is Cirrus Compute a durable customer of Aurora Photonics' 800G transceivers?
**Sources:**
- source `s1`: Aurora Photonics 10-K fiscal 2024 ()
- source `s2`: Aurora Photonics 10-Q Q1 fiscal 2026 ()
**Expected:**
- claims: `[{"subject": "aurora", "predicate": "supplies", "object": "cirrus", "source": "s1", "quote": "In fiscal 2024 we shipped 800G optical transceivers to Cirrus Compute under a multi-year supply agreement.", "accepted": true}]`
- investigation: `{"stop_reason": ["needs_review"], "min_contradictions": 1, "min_findings": 1}`

- [ ] Accept  - [ ] Change: ____________________

## EV-DIR-001: A supply stated one way never becomes a verified edge the other way
**Question:** Who supplies whom between Aurora Photonics and Cirrus Compute?
**Sources:**
- source `s1`: Aurora Photonics 10-Q Q1 fiscal 2026 ()
**Expected:**
- edge Aurora Photonics **supplies** Cirrus Compute [module]: *present* (machine_reviewed)
- edge Cirrus Compute **supplies** Aurora Photonics: *not_verified*
- citation from `s1`: “In fiscal 2025 we shipped 800G optical transceivers to Cirrus Compute under a multi-year supply agreement.” (resolved)
**Why (agent's note):** In fake mode the scripted Investigator proposes the reversed edge as well, so the case checks that the Reviewer's direction verdict keeps it out of the verified edges.

- [ ] Accept  - [ ] Change: ____________________

## EV-FUT-001: A contract disclosed after the cutoff must not leak into an investigation as of it
**Question:** Which customers had Aurora Photonics disclosed for its transceivers?
**Sources:**
- source `s1`: Aurora Photonics 10-K fiscal 2024 ()
- source `s2`: Aurora Photonics 8-K (supply agreement) ()
**Expected:**
- answer: `{"evidence_missing": true, "must_not_mention": ["cirrus"]}`
- forbidden_sources: `["s2"]`
- investigation: `{"stop_reason": ["no_new_independent_evidence"]}`
**Why (agent's note):** s2 describes an event before as_of (March 15) but became available after it (June 2), so it is also a LAT-style trap. In fake mode the scripted Investigator would quote s2 if it were ever sent.

- [ ] Accept  - [ ] Change: ____________________

## EV-HED-001: A planned, non-binding supply is an exception for a human, never a verified edge
**Question:** Does Aurora Photonics supply Cirrus Compute with 1.6T transceivers?
**Sources:**
- source `s1`: Aurora Photonics 10-Q Q2 fiscal 2026 ()
**Expected:**
- edge Aurora Photonics **supplies** Cirrus Compute: *present* (needs_human_review)
- edge Aurora Photonics **supplies** Cirrus Compute: *not_verified*

- [ ] Accept  - [ ] Change: ____________________

## EV-INF-001: A partner page and its later edit support no supply or purchase edge
**Question:** Is Borealis Substrates a supplier of Aurora Photonics, and did Aurora drop it?
**Sources:**
- source `s1`: Aurora Photonics partners page ()
- source `s2`: Aurora Photonics partners page ()
**Expected:**
- edge Borealis Substrates **supplies** Aurora Photonics: *absent*
- edge Aurora Photonics **buys_from** Borealis Substrates: *absent*
- edge Aurora Photonics **buys_from** Dunmore Epitaxy: *absent*
- claims: `[{"subject": "borealis", "predicate": "supplies", "object": "aurora", "accepted": false}, {"subject": "aurora", "predicate": "buys_from", "object": "borealis", "accepted": false}, {"subject": "aurora", "predicate": "buys_from", "object": "dunmore", "accepted": false}]`
**Why (agent's note):** "Works with" names no direction and maps to no predicate; Borealis vanishing from the page between s1 and s2 supports at most an agent inference, never an Assertion.

- [ ] Accept  - [ ] Change: ____________________

## EV-LAY-001: A substrate supplier isn't an epitaxy supplier: the layer the filing names wins
**Question:** What does Borealis Substrates supply to Aurora Photonics: substrates or epitaxial wafers?
**Sources:**
- source `s1`: Aurora Photonics 10-K fiscal 2024 ()
**Expected:**
- edge Borealis Substrates **supplies** Aurora Photonics [substrate]: *present* (machine_reviewed)
- edge Borealis Substrates **supplies** Aurora Photonics [epi]: *not_verified*
**Why (agent's note):** Methodology §5 LAY also foresees a news item misnaming the layer. Manual imports are recorded as Tier A, and news reaches Atlas only as Tier C leads (never Evidence), so this first case uses the primary source alone, with the misnamed layer proposed by the Investigator.

- [ ] Accept  - [ ] Change: ____________________

## EV-RST-001: Nokia's FY2023 revenue: the original value before the restating 20-F, the restated one after
**Question:** What was Nokia's FY2023 revenue as known just before and just after its FY2024 20-F?
**Sources:**
- source `submissions`: Nokia submissions index ()
- source `companyfacts`: Nokia companyfacts ()
**Expected:**
- financials: `[{"concept": "RevenueFromContractsWithCustomers", "period_start": "2023-01-01", "period_end": "2023-12-31", "unit": "EUR", "as_of": "2025-03-13T17:00:00+00:00", "value": "22258000000", "from_source": "companyfacts", "accession": "0000924613-24-000013", "linkage": "first"}, {"concept": "RevenueFromCo`
**Why (agent's note):** The values are the research note's worked example (spec 'Unit tests': the Nokia FY2023 restatement); the restating 20-F was accepted 2025-03-13 17:24:32Z.

- [ ] Accept  - [ ] Change: ____________________

## EV-SUP-001: A supplier relationship stated in the buyer's 10-K becomes a verified edge
**Question:** Who supplies Aurora Photonics with its indium phosphide substrates?
**Sources:**
- source `s1`: Aurora Photonics 10-K fiscal 2025 ()
**Expected:**
- edge Borealis Substrates **supplies** Aurora Photonics [substrate]: *present* (machine_reviewed)
- citation from `s1`: “Borealis Substrates supplies the bare indium phosphide substrates for our laser chips under a supply agreement that runs through 2027.” (resolved)
- claims: `[{"subject": "borealis", "predicate": "supplies", "object": "aurora", "source": "s1", "quote": "Borealis Substrates supplies the bare indium phosphide substrates for our laser chips under a supply agreement that runs through 2027.", "accepted": true}]`

- [ ] Accept  - [ ] Change: ____________________

## EV-SUP-002: A purchase the buyer states is a buys_from edge in the buyer's direction
**Question:** From whom does Cirrus Compute buy its 800G transceivers?
**Sources:**
- source `s1`: Cirrus Compute 10-K fiscal 2025 ()
**Expected:**
- edge Cirrus Compute **buys_from** Aurora Photonics [module]: *present* (machine_reviewed)
- edge Aurora Photonics **buys_from** Cirrus Compute: *absent*
- citation from `s1`: “We purchase 800G optical transceivers from Aurora Photonics, which provided more than 40% of the transceivers we deployed in fiscal 2025.” (resolved)
- claims: `[{"subject": "cirrus", "predicate": "buys_from", "object": "aurora", "source": "s1", "quote": "We purchase 800G optical transceivers from Aurora Photonics, which provided more than 40% of the transceivers we deployed in fiscal 2025.", "accepted": true}]`

- [ ] Accept  - [ ] Change: ____________________

## EV-SYN-001: One announcement mirrored by ten sites is one Evidence Family
**Question:** How many independent sources report Ember Lasers' second EML fab?
**Sources:**
- source `s0`: Ember Lasers press release: second EML fab ()
- source `s1`: Ember Lasers opens second EML laser fab in Tucson (wire) ()
- source `s2`: Ember Lasers opens second EML laser fab in Tucson (photonics-daily) ()
- source `s3`: Ember Lasers opens second EML laser fab in Tucson (optics-trade) ()
- source `s4`: Ember Lasers opens second EML laser fab in Tucson (markets-feed) ()
- source `s5`: Ember Lasers opens second EML laser fab in Tucson (chip-journal) ()
- source `s6`: Ember Lasers opens second EML laser fab in Tucson (ai-infra-news) ()
- source `s7`: Ember Lasers opens second EML laser fab in Tucson (az-business) ()
- source `s8`: Ember Lasers opens second EML laser fab in Tucson (lightwave-wire) ()
- source `s9`: Ember Lasers opens second EML laser fab in Tucson (semi-digest) ()
- source `s10`: Ember Lasers opens second EML laser fab in Tucson (investor-brief) ()
- source `s11`: Ember Lasers Q1 2025 results ()
**Expected:**
- evidence_families: `{"count": 2}`
**Why (agent's note):** s0 is the release and s1-s10 its mirrors (re-marked-up, some with a source line), one witness; s11 is an unrelated release, a second family, so the count also shows families aren't merged indiscriminately.

- [ ] Accept  - [ ] Change: ____________________
